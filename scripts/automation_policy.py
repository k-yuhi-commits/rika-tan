"""Read-only, fail-closed classification. This module NEVER authorizes a merge."""
import argparse
import json
from pathlib import Path
import re
import subprocess

LOW_RISK_FILES = frozenset({'docs/maintenance/editorial-notes.txt'})
SHA = re.compile(r'^[0-9a-f]{40}$')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def classify(changes):
    reasons = []
    for change in changes:
        path, status = change['path'], change['status']
        if path not in LOW_RISK_FILES:
            reasons.append(f'{path!r}: outside exact allowlist')
        if status != 'M':
            reasons.append(f'{path!r}: only edits to an existing file are eligible')
        if change.get('mode') != '100644':
            reasons.append(f'{path!r}: regular, non-executable file required')
        content = change.get('content', b'')
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            reasons.append(f'{path!r}: non-UTF-8 data')
            continue
        if len(content) > 8192 or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            reasons.append(f'{path!r}: oversized or control characters')
        if re.search(r'https?:|javascript:|data:|[<>`$]', text, re.I):
            reasons.append(f'{path!r}: active content, links or command markup')
    if not changes:
        reasons.append('No inspectable changes')
    return {
        'low_risk_candidate': not reasons,
        'human_approval_required': True,
        'auto_merge_authorized': False,
        'merge_state': 'STOPPED',
        'reasons': reasons,
        'blockers': ['Automatic merging is disabled; remote protections and required checks are not verified.'],
        'files': [dict(path=c['path'], status=c['status'], mode=c.get('mode')) for c in changes],
    }


def inspect_changes(repo, base, head):
    if not SHA.fullmatch(base or '') or not SHA.fullmatch(head or ''):
        raise ValueError('Exact base and head commit SHAs are required')
    for sha in (base, head):
        if git(repo, 'rev-parse', '--verify', sha+'^{commit}').decode().strip() != sha:
            raise ValueError('Commit unavailable')
    names = git(repo, 'diff', '--name-status', '-z', '--no-renames', base, head, '--').split(b'\0')
    if names[-1] != b'' or (len(names)-1) % 2:
        raise ValueError('Incomplete diff')
    changes = []
    for i in range(0, len(names)-1, 2):
        status, path = names[i].decode('ascii'), names[i+1].decode('utf-8', errors='strict')
        tree = git(repo, 'ls-tree', '-z', head, '--', path)
        if tree:
            metadata, found = tree[:-1].split(b'\t', 1)
            mode, kind, oid = metadata.decode().split()
            if found.decode() != path:
                raise ValueError('Ambiguous path')
            size = int(git(repo, 'cat-file', '-s', oid))
            content = (git(repo, 'cat-file', 'blob', oid) if kind == 'blob' and path in LOW_RISK_FILES and size <= 8192
                       else b'x' * 8193 if path in LOW_RISK_FILES and size > 8192 else b'')
        else:
            mode, content = None, b''
        changes.append(dict(path=path, status=status, mode=mode, content=content))
    return classify(changes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--repo', default='.')
    args = parser.parse_args()
    try:
        report = inspect_changes(Path(args.repo), args.base, args.head)
        print(json.dumps(report, ensure_ascii=True, indent=2))
    except (ValueError, subprocess.CalledProcessError, UnicodeError) as exc:
        print(json.dumps({'merge_state': 'STOPPED', 'auto_merge_authorized': False,
                          'human_approval_required': True, 'error': type(exc).__name__}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
