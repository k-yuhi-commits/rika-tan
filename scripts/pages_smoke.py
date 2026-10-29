"""Exercise downloaded public HTML with a fresh, network-isolated browser."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import shutil
from playwright.sync_api import sync_playwright

if __package__:
    from .prepare_pages_smoke import SITE, SHA
else:
    from prepare_pages_smoke import SITE, SHA


def smoke(directory):
    info = json.loads((directory / 'metadata.json').read_text())
    html = (directory / 'index.html').read_bytes()
    if info.get('url') != SITE or not SHA.fullmatch(info.get('sha', '')):
        raise ValueError('Unverified site metadata')
    if hashlib.sha256(html).hexdigest() != info.get('sha256'):
        raise ValueError('Downloaded HTML changed')
    with sync_playwright() as p:
        executable = os.environ.get('CHROMIUM_PATH') or shutil.which('chromium')
        browser = p.chromium.launch(**({'executable_path': executable} if executable else {}),
                                    headless=True, args=['--no-sandbox'])
        try:
            context = browser.new_context()
            # Use the byte-verified public response; prohibit external requests,
            # telemetry, file access, imports, and access to personal profiles.
            context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html)
                          if route.request.url == SITE else route.abort())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            response = page.goto(SITE)
            if response.status != 200 or page.title() != '理科タン v9.2':
                raise ValueError('Home did not load')
            if page.evaluate('[qs.length,bosses.length]') != [740, 4]:
                raise ValueError('Question count mismatch')
            page.locator('button[onclick="start(\'input\')"]').click()
            page.locator('#txt').fill(page.evaluate('sess.list[sess.i].a'))
            page.get_by_role('button', name='答える', exact=True).click()
            if page.locator('#feedback').evaluate("e=>e.classList.contains('hidden')"):
                raise ValueError('Answer feedback missing')
            page.reload()
            if page.locator('#total').inner_text() != '1' or errors:
                raise ValueError('Persistence or runtime check failed')
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        smoke(Path(args.directory))
    except Exception as exc:
        print('STOP: Pages functional check failed: '+type(exc).__name__)
        return 1
    print('PASS: verified HTML home, question counts, quiz, feedback and isolated persistence.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
