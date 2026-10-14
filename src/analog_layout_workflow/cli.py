"""Repository frontend; read-only commands are usable without EDA software."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


def repository_root():
    configured = os.environ.get('ALFLOW_ROOT')
    if configured:
        return Path(configured).expanduser().resolve()
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / 'skills/analog-layout-workflow/SKILL.md').is_file():
        return candidate
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / 'skills/analog-layout-workflow/SKILL.md').is_file() and (directory / 'pyproject.toml').is_file():
            return directory
    return candidate


def main(argv=None):
    parser = argparse.ArgumentParser(prog='alflow')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    sub.add_parser('skills')
    state_parser = sub.add_parser('state')
    state_parser.add_argument('path', type=Path)
    next_parser = sub.add_parser('next')
    next_parser.add_argument('--state', required=True, type=Path)
    dispatch_parser = sub.add_parser('dispatch')
    dispatch_parser.add_argument('--state', required=True, type=Path)
    dispatch_parser.add_argument('--registry', required=True, type=Path)
    dispatch_parser.add_argument('--runs', required=True, type=Path)
    dispatch_parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    root = repository_root()
    skills = root / 'skills'
    try:
        if args.command == 'doctor':
            ready = (skills / 'analog-layout-workflow/SKILL.md').is_file()
            result = {'status': 'OFFLINE_READY' if ready else 'REPOSITORY_NOT_FOUND', 'python': sys.version.split()[0],
                      'repository': str(root), 'skills_present': ready,
                      'bridge_importable': importlib.util.find_spec('virtuoso_bridge') is not None,
                      'bridge_env_configured': bool(os.environ.get('ALFLOW_BRIDGE_ENV')),
                      'scope': 'Local configuration inspection; no CAD or network probe'}
        elif args.command == 'skills':
            if not (skills / 'analog-layout-workflow/SKILL.md').is_file():
                raise ValueError('Repository skills unavailable; use an editable checkout or set ALFLOW_ROOT')
            result = {'skills': sorted(p.parent.name for p in skills.glob('*/SKILL.md'))}
        elif args.command == 'state':
            data = json.loads(args.path.read_text(encoding='utf-8-sig'))
            result = {k: data[k] for k in ('schema', 'target', 'current', 'status', 'completion_status', 'physical_closure', 'verification') if k in data}
        else:
            runtime = skills / 'analog-layout-workflow/scripts'
            if not (runtime / 'workflow_runtime.py').is_file():
                raise ValueError('Workflow runtime unavailable; set ALFLOW_ROOT to the source checkout')
            sys.path.insert(0, str(runtime))
            from workflow_runtime import load, next_action
            if args.command == 'next':
                result = next_action(load(args.state), args.state.parent)
            else:
                from run_stage import run_stage
                result = run_stage(args.state, args.registry, args.runs, args.execute)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(error)}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get('status') in ('BLOCKED', 'REPOSITORY_NOT_FOUND') else 0
