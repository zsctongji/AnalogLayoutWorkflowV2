"""Run offline suites in separate processes to isolate legacy helper module names."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-suite', type=Path)
    args = parser.parse_args()
    if args.child_suite:
        suite = args.child_suite.resolve()
        if not suite.is_relative_to(ROOT):
            raise ValueError('Test suite outside repository')
        sys.path.insert(0, str(suite if suite.is_dir() else suite.parent))
        sys.path.insert(0, str(ROOT / 'src'))
        import pytest
        return pytest.main(['--import-mode=importlib', '-q', str(suite)])
    suites = [ROOT / 'tests']
    suites.extend(sorted((ROOT / 'examples').glob('*/tests')))
    standalone = []
    for skill in sorted((ROOT / 'skills').iterdir()):
        tests = skill / 'tests'
        if tests.is_dir() and list(tests.glob('test_*.py')):
            suites.append(tests)
        for p in sorted((skill / 'scripts').glob('test_*.py')):
            if p.name == 'test_all.py':
                standalone.append(p)
            else:
                suites.append(p)
    failed = []
    for suite in suites:
        print('Testing ' + suite.relative_to(ROOT).as_posix(), flush=True)
        result = subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--child-suite', str(suite)], cwd=ROOT)
        if result.returncode:
            failed.append(suite.relative_to(ROOT).as_posix())
    for suite in standalone:
        print('Testing ' + suite.relative_to(ROOT).as_posix(), flush=True)
        result = subprocess.run([sys.executable, '-X', 'utf8', str(suite)], cwd=suite.parent)
        if result.returncode:
            failed.append(suite.relative_to(ROOT).as_posix())
    print(json.dumps({'status': 'PASS' if not failed else 'BLOCKED', 'suites': len(suites) + len(standalone), 'failed': failed}))
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
