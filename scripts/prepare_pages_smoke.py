"""Read-only Pages preflight. No redirects, deployment, or repository writes."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import urllib.request
from urllib.error import HTTPError

REPO = 'k-yuhi-commits/rika-tan'
SITE = 'https://k-yuhi-commits.github.io/rika-tan/'
SHA = re.compile(r'^[0-9a-f]{40}$')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Redirect refused')


def request(url, token=None, json_data=False):
    if token is not None and not url.startswith('https://api.github.com/repos/'+REPO+'/'):
        raise ValueError('Credential destination refused')
    headers = {'User-Agent': 'rika-tan-readiness', 'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(urllib.request.Request(url, headers=headers), timeout=25) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Unexpected HTTP response')
        data = response.read(2*1024*1024+1)
        if len(data) > 2*1024*1024:
            raise ValueError('Oversized response')
        return json.loads(data) if json_data else data


def deployment_sha(event_name, event, manual_sha):
    if event.get('repository', {}).get('full_name') != REPO or event['repository'].get('private') is not False:
        raise ValueError('Only the public selected repository is supported')
    if event_name == 'workflow_dispatch':
        sha = manual_sha
    elif event_name == 'page_build':
        build = event.get('build', {})
        if build.get('status') != 'built':
            raise ValueError('Pages build did not complete')
        sha = build.get('commit')
    elif event_name == 'deployment_status':
        status, deploy = event.get('deployment_status', {}), event.get('deployment', {})
        if status.get('state') != 'success' or deploy.get('environment') != 'github-pages':
            raise ValueError('Successful GitHub Pages deployment required')
        if deploy.get('creator', {}).get('login') not in ['github-actions[bot]', 'github-pages[bot]']:
            raise ValueError('Untrusted deployment creator')
        sha = deploy.get('sha')
    else:
        raise ValueError('Unsupported trigger')
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError('Exact deployed commit SHA required')
    return sha


def validate_site(site):
    if site.get('html_url') != SITE or site.get('cname') or site.get('public') is not True:
        raise ValueError('Only the verified default public Pages URL is supported')
    if site.get('source') != {'branch': 'main', 'path': '/'}:
        raise ValueError('Pages source must be verified as main/root')
    if site.get('status') != 'built':
        raise ValueError('Pages is not built')


def prepare(event_name, event, manual_sha, api, download):
    sha = deployment_sha(event_name, event, manual_sha)
    site = api('pages')
    validate_site(site)
    if api('commits/main').get('sha') != sha:
        raise ValueError('Stale deployment: main differs from deployed commit')
    if site.get('build_type') == 'legacy':
        latest = api('pages/builds/latest')
        if latest.get('commit') != sha or latest.get('status') != 'built':
            raise ValueError('Latest Pages build does not match commit')
    elif site.get('build_type') != 'workflow' or event_name != 'deployment_status':
        raise ValueError('Deployment provenance could not be verified')
    content = api('contents/index.html?ref='+sha)
    if content.get('encoding') != 'base64' or content.get('type') != 'file':
        raise ValueError('Unexpected source content')
    expected = base64.b64decode(content['content'].replace('\n', ''), validate=True)
    html = download(SITE)
    if html != expected:
        raise ValueError('Public HTML differs from the deployed source commit')
    return {'url': SITE, 'sha': sha, 'sha256': hashlib.sha256(html).hexdigest()}, html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        token = os.environ['GITHUB_TOKEN']
        def api(path):
            return request('https://api.github.com/repos/'+REPO+'/'+path, token=token, json_data=True)
        info, html = prepare(os.environ['GITHUB_EVENT_NAME'], event, os.environ.get('EXPECTED_SHA'), api, request)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        (output / 'index.html').write_bytes(html)
        (output / 'metadata.json').write_text(json.dumps(info))
        print('PASS: public Pages URL, source, commit, and HTML verified.')
        return 0
    except Exception as exc:
        # Never print credentials, HTTP headers, or event payloads.
        print('STOP: Pages preflight failed: '+type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
