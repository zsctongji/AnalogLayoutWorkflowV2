"""Locate sibling skill helpers without a site installation or CAD connection."""
import importlib.util
import json
from pathlib import Path
import sys

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]
SKILLS = ROOT / 'skills'
sys.path.insert(0, str(SKILLS / 'analog-layout-workflow/scripts'))
import configured_flow as flow
from project_config import load_project, read


def helper(skill, filename, name):
    path = SKILLS / skill / 'scripts' / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fast = helper('analog-layout-symmetric-fast', 'fast_route.py', 'example_fast')
ri = fast.MIRROR.ri


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')


def snap(value, grid):
    return ri.snap(value, grid)
