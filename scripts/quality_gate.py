"""Frozen application invariants plus mandatory, non-skipped regression tests."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def app_snapshot(root):
    result = {'banks': {}, 'storage': {}}
    names = ['index.html', 'rika-tango-v4.2.html', 'rika-tango-v4.7.html',
             'rika-tango-v5.6.html', 'rika-tango-v6.2.html']
    for name in names:
        path = root / name
        if path.is_symlink():
            raise ValueError('Application files must not be symlinks')
        text = path.read_text()
        start, end = text.index('const qs='), text.index('const KEY=')
        result['banks'][name] = digest(text[start:end])
        match = re.search(r"const KEY='([^']+)';const def=\{schemaVersion:(\d+)", text)
        if not match:
            raise ValueError('Storage declaration missing')
        result['storage'][name] = dict(key=match[1], schema=int(match[2]))
        if name == 'index.html':
            start, end = text.index('// Input grading rules'), text.index('const KISO300_TITLES=')
            result['answer_rules'] = digest(text[start:end])
    return result


def leaf_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaf_tests(item)
        else:
            yield item


class TrackedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.executed = set()

    def startTest(self, test):
        self.executed.add(test.id())
        super().startTest(test)


def result_is_ready(result, mandatory):
    return (result.wasSuccessful() and not result.skipped and not result.expectedFailures
            and not result.unexpectedSuccesses and set(mandatory) <= result.executed)


def main():
    baseline = json.loads((ROOT / 'quality/baseline.json').read_text())
    if app_snapshot(ROOT) != baseline['application']:
        print('STOP: application data, grading rules, or storage format differ from the reviewed baseline.', file=sys.stderr)
        return 1
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    mandatory = baseline['mandatory_tests']
    discovered = {test.id() for test in leaf_tests(suite)}
    if len(mandatory) < 82 or not set(mandatory) <= discovered:
        print('STOP: mandatory regression tests missing.', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2, resultclass=TrackedResult).run(suite)
    if not result_is_ready(result, mandatory):
        print('STOP: failures, skips, expected failures, or missing executions.', file=sys.stderr)
        return 1
    print(f'PASS: frozen data and {result.testsRun} tests; all {len(mandatory)} mandatory regressions executed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
