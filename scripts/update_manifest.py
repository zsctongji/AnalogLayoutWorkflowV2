"""Refresh the source snapshot after reviewing deliberate source changes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', 'local', 'outputs', 'runs', 'artifacts'}
manifest_path = ROOT / 'docs/source-manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
origins = {item['path']: item['origin'] for item in manifest['files']}
files = []
for path in sorted(ROOT.rglob('*')):
    relative = path.relative_to(ROOT)
    if not path.is_file() or path == manifest_path or any(p in EXCLUDED or p.endswith('.egg-info') for p in relative.parts):
        continue
    if path.is_symlink():
        raise ValueError('Source symlink cannot be fingerprinted as an ordinary file')
    name = relative.as_posix()
    default_origin = 'synthetic-offline-example' if relative.parts[0] == 'examples' else 'repository-maintenance'
    files.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'origin': origins.get(name, default_origin)})
manifest['files'] = files
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
print(json.dumps({'status': 'MANIFEST_UPDATED', 'files': len(files)}))
