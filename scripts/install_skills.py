"""Install the repository skill set locally, with preview and replacement backups."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'__pycache__', '.pytest_cache'}


def files(folder):
    return [p for p in folder.rglob('*') if p.is_file() and not any(k in IGNORED for k in p.relative_to(folder).parts) and p.suffix not in {'.pyc', '.pyo'}]


def install(destination, replace=False, dry_run=False):
    destination = Path(destination).expanduser().resolve()
    sources = sorted(p.parent for p in (ROOT / 'skills').glob('*/SKILL.md'))
    changes, conflicts = [], []
    for source in sources:
        target = destination / source.name
        if target.exists() and (target.is_symlink() or target.resolve().parent != destination):
            raise ValueError('Skill target escapes installation directory: ' + str(target))
        for item in files(source):
            out = target / item.relative_to(source)
            if not out.resolve().is_relative_to(destination):
                raise ValueError('Installation file escapes target directory')
            if out.exists() and (not out.is_file() or out.is_symlink()):
                raise ValueError('Nonregular installation target: ' + str(out))
            if out.exists() and hashlib.sha256(out.read_bytes()).digest() == hashlib.sha256(item.read_bytes()).digest():
                continue
            if out.exists() and not replace:
                conflicts.append(str(out))
            changes.append((item, out))
    plan = {'status': 'CONFLICT' if conflicts else ('PREVIEW' if dry_run else 'INSTALLED'), 'skills': len(sources), 'changed_files': len(changes), 'conflicts': conflicts, 'destination': str(destination)}
    if dry_run or conflicts:
        return plan
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = destination / '.analog-layout-flow-backups' / stamp
    completed = []
    try:
        for source, target in changes:
            previous = backup / target.relative_to(destination)
            existed = target.exists()
            if existed:
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, previous)
            target.parent.mkdir(parents=True, exist_ok=True)
            completed.append((target, previous, existed))
            shutil.copy2(source, target)
            if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
                raise ValueError('Installation readback mismatch: ' + str(target))
    except Exception:
        for target, previous, existed in reversed(completed):
            if existed:
                shutil.copy2(previous, target)
            elif target.exists():
                target.unlink()
        raise
    plan['backup'] = str(backup) if backup.exists() else None
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path.home() / '.codex/skills')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--replace', action='store_true', help='Back up and replace conflicting distributed files; preserve unrelated files')
    args = parser.parse_args()
    result = install(args.destination, args.replace, args.dry_run)
    print(json.dumps(result, indent=2))
    return 2 if result['status'] == 'CONFLICT' else 0


if __name__ == '__main__':
    raise SystemExit(main())
