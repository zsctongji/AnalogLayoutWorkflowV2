import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repository_installer', ROOT / 'scripts/install_skills.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_cli_discovers_the_checkout_without_eda():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/alflow.py'), 'doctor'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['status'] == 'OFFLINE_READY'
    assert Path(data['repository']) == ROOT


def test_installer_preview_idempotence_and_backed_up_replace(tmp_path):
    destination = tmp_path / 'skills'
    preview = installer.install(destination, dry_run=True)
    assert preview['status'] == 'PREVIEW' and not destination.exists()
    result = installer.install(destination)
    assert result['status'] == 'INSTALLED'
    assert installer.install(destination)['changed_files'] == 0
    target = destination / 'analog-layout-workflow/SKILL.md'
    target.write_text('local customization')
    (target.parent / 'custom.txt').write_text('preserve user file')
    assert installer.install(destination)['status'] == 'CONFLICT'
    assert target.read_text() == 'local customization'
    replaced = installer.install(destination, replace=True)
    assert replaced['status'] == 'INSTALLED'
    assert (Path(replaced['backup']) / 'analog-layout-workflow/SKILL.md').read_text() == 'local customization'
    assert (target.parent / 'custom.txt').read_text() == 'preserve user file'


def test_installer_rejects_file_target_escape(tmp_path):
    destination = tmp_path / 'skills'
    skill = destination / 'analog-layout-workflow'
    skill.mkdir(parents=True)
    outside = tmp_path / 'elsewhere'
    outside.mkdir()
    try:
        (skill / 'scripts').symlink_to(outside, target_is_directory=True)
    except OSError:
        import pytest
        pytest.skip('Symlink creation unavailable on this host')
    import pytest
    with pytest.raises(ValueError, match='escapes'):
        installer.install(destination, replace=True)
