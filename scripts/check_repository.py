"""Validate source layout, skill metadata, links, provenance and private-data exclusions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', 'local', 'runs', 'outputs', 'artifacts'}


def source_files():
    return [p for p in ROOT.rglob('*') if p.is_file() and p.name != '.env' and not p.name.endswith('.env') and not any(k in IGNORED or k.endswith('.egg-info') for k in p.relative_to(ROOT).parts)]


def check(strict_manifest=True):
    errors, links = [], 0
    examples = ROOT / 'examples'
    if examples.exists():
        for example in examples.iterdir():
            metadata = example / 'example.json'
            try:
                data = json.loads(metadata.read_text(encoding='utf-8'))
                if (data.get('schema') != 'analog-layout-flow.example/v1' or
                        data.get('synthetic') is not True or data.get('offline_only') is not True):
                    raise ValueError('Synthetic offline provenance required')
                for key in ('entrypoint', 'project'):
                    path = (example / data[key]).resolve()
                    if not path.is_relative_to(example.resolve()) or not path.is_file():
                        raise ValueError('Missing or escaping example ' + key)
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append('Unqualified bundled example: ' + example.name + ': ' + str(error))
    if (ROOT / '.git').exists():
        tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        if tracked.returncode:
            errors.append('Cannot inspect Git tracked-file exclusions')
        for name in tracked.stdout.split('\0'):
            path = Path(name)
            if name and (any(part in {'local','runs','outputs','artifacts'} for part in path.parts) or path.name == '.env' or path.name.endswith('.env') or path.suffix in {'.gds','.gdsii','.oa','.psf'}):
                errors.append('Private/generated file tracked by Git: ' + name)
    for p in source_files():
        relative = p.relative_to(ROOT)
        if any(k in {'local', 'runs', 'outputs', 'artifacts'} for k in relative.parts) or p.name == '.env':
            errors.append('Private/generated file bundled: ' + relative.as_posix())
        if p.name.endswith('.reference.json') or p.suffix.lower() in {'.gds', '.gdsii', '.oa', '.psf'}:
            errors.append('Native design/capture bundled: ' + relative.as_posix())
        if p.suffix == '.py':
            try:
                compile(p.read_text(encoding='utf-8-sig'), relative.as_posix(), 'exec')
            except (SyntaxError, UnicodeError) as error:
                errors.append(str(error))
        if p.suffix.lower() not in {'.md', '.py', '.json', '.yaml', '.yml', '.toml', '.il', '.template'}:
            continue
        text = p.read_text(encoding='utf-8-sig')
        # Only known local-state signatures and secret material; synthetic fixtures
        # remain allowed. This is not a claim to detect every possible secret.
        private_pattern = r'C:[/\\]+Users[/\\]+16034|192\.168\.220\.(?:129|141)|/home/' + r'eda(?:/|\b)|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9]{24,}'
        if re.search(private_pattern, text):
            errors.append('Known private signature: ' + relative.as_posix())
        if p.suffix == '.md' and 'vendor' not in relative.parts:
            if re.search(r'[\u3400-\u9fff]', text):
                errors.append('Non-English maintained Markdown: ' + relative.as_posix())
            for href in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
                if '://' in href or href.startswith('#') or '<' in href:
                    continue
                target = (p.parent / href.split('#')[0]).resolve()
                links += 1
                if not target.exists():
                    errors.append('Missing local link: ' + relative.as_posix() + ' -> ' + href)
    skills = sorted((ROOT / 'skills').glob('*/SKILL.md'))
    import yaml
    for p in skills:
        text = p.read_text(encoding='utf-8-sig')
        match = re.match(r'^---\s*\n(.*?)\n---', text, re.S)
        if not match:
            errors.append('Missing skill frontmatter: ' + str(p.parent.name))
            continue
        data = yaml.safe_load(match.group(1))
        if data.get('name') != p.parent.name or not data.get('description'):
            errors.append('Invalid skill metadata: ' + p.parent.name)
    manifest = json.loads((ROOT / 'docs/source-manifest.json').read_text(encoding='utf-8'))
    if strict_manifest:
        listed = {item['path'] for item in manifest['files']}
        actual = {p.relative_to(ROOT).as_posix() for p in source_files()} - {'docs/source-manifest.json'}
        if listed != actual:
            errors.append('Source manifest file set drift')
        for item in manifest['files']:
            p = ROOT / item['path']
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
                errors.append('Source manifest hash drift: ' + item['path'])
    return {'status': 'PASS' if not errors else 'BLOCKED', 'skills': len(skills), 'local_links': links, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-modified', action='store_true', help='Skip snapshot hash checking while developing; retain structural checks')
    args = parser.parse_args()
    result = check(not args.allow_modified)
    print(json.dumps(result, indent=2))
    return 0 if not result['errors'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
