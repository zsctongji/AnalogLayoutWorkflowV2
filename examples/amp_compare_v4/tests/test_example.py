"""Exercise the public example as a new checkout would, including portability."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

EXAMPLE = Path(__file__).resolve().parents[1]
ROOT = EXAMPLE.parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def run(out, example=EXAMPLE):
    return subprocess.run([sys.executable, '-X', 'utf8', str(EXAMPLE / 'work/run_example.py'),
                           '--example', str(example), '--out', str(out)],
                          cwd=ROOT, capture_output=True, text=True, encoding='utf-8')


def test_complete_offline_example_and_deterministic_rebuild(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    result = run(first)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = read(first / 'reports/result.json')
    expected = read(EXAMPLE / 'reports/expected.json')
    assert summary['status'] == 'OFFLINE_EXAMPLE_PASS'
    for key in ('physical_copies', 'functional_mos_modules', 'required_nets', 'materializable'):
        assert summary[key] == expected[key]
    assert summary['physical_pin_islands'] == 120
    for key in ('drc', 'lvs', 'pex', 'postsim'):
        assert summary['stages'][key] == expected[key] == 'NOT_RUN'
    intent = read(first / 'work/routing/symmetric-fast/intent.json')
    assert intent['physical_access_coverage']['complete']
    assert intent['physical_connectivity']['complete']
    assert read(first / 'reports/independent-geometry-audit.json')['status'] == 'PASS'
    assert read(first / 'work/routing/symmetric-fast/svg-check.json')['status'] == 'PASS'
    result = run(second)
    assert result.returncode == 0, result.stdout + result.stderr
    assert summary['inputs_sha256'] == read(second / 'reports/result.json')['inputs_sha256']
    for name in ('seed-spec.json', 'generated-tracks.json'):
        assert (first / 'inputs' / name).read_bytes() == (second / 'inputs' / name).read_bytes()
    result = run(first)
    assert result.returncode == 2 and 'Output exists' in result.stdout
    assert read(first / 'reports/result.json') == summary


def test_generated_configuration_replays_with_the_shared_frontend(tmp_path):
    out = tmp_path / 'run'
    result = run(out)
    assert result.returncode == 0, result.stdout + result.stderr
    work = tmp_path / 'replay'
    result = subprocess.run([sys.executable, '-X', 'utf8',
                             str(ROOT / 'skills/analog-layout-workflow/scripts/configured_flow.py'),
                             'route', '--project', str(out / 'config/project.json'), '--work', str(work)],
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    assert read(work / 'routing/symmetric-fast/candidates.json')['status'] == 'PLANNED'
    assert read(work / 'routing/symmetric-fast/spec.json') == read(out / 'work/routing/symmetric-fast/spec.json')


def test_renamed_devices_nets_layers_and_shifted_axis(tmp_path):
    changed = tmp_path / 'changed'
    shutil.copytree(EXAMPLE, changed, ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    schematic = read(changed / 'inputs/schematic.json')
    names = {i['name']: 'X_' + i['name'] for i in schematic['instances']}
    nets = {n: 'N_' + n for i in schematic['instances'] for n in i['terms'].values()}
    names.update(nets)
    names.update({'demo_l1': 'alpha', 'demo_l2': 'beta', 'demo_l3': 'gamma',
                  'demo_cut12': 'cut_a', 'demo_cut23': 'cut_b', 'toy_technology': 'renamed_tech',
                  'toy_devices': 'renamed_devices', 'DP': 'drain_pin', 'GP': 'gate_pin',
                  'SP': 'source_pin', 'BP': 'body_pin', 'WIDTH': 'TOTAL_WIDTH',
                  'finger_width_um': 'unit_width_um'})

    def rename(data):
        if isinstance(data, dict):
            return {rename(k): rename(v) for k, v in data.items()}
        if isinstance(data, list):
            return [rename(v) for v in data]
        if isinstance(data, str):
            if data in names:
                return names[data]
            for old, new in names.items():
                if data.startswith(old + '__M'):
                    return new + data[len(old):]
        return data

    for path in [changed / 'inputs/schematic.json', *sorted((changed / 'config').glob('*.json'))]:
        original = read(path)
        renamed = rename(original)
        if path.name == 'pdk-map.json':
            # Canonical terminal N1/N2 identities are not the circuit's net names.
            for device, before in zip(renamed['devices'], original['devices']):
                device['terminals'] = {key: rename(value) for key, value in before['terminals'].items()}
            renamed['synthetic_geometry']['capacitor_pin_offsets_um'] = original['synthetic_geometry']['capacitor_pin_offsets_um']
        write(path, renamed)
    path = changed / 'config/circuit.json'
    circuit = read(path)
    circuit['floorplan']['axis_x_um'] = 17.6
    write(path, circuit)
    out = tmp_path / 'renamed-run'
    result = run(out, changed)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = read(out / 'reports/result.json')
    assert summary['required_nets'] == sorted(nets.values())
    assert summary['physical_copies'] == 29
    intent = read(out / 'work/routing/symmetric-fast/intent.json')
    assert {r['layer'] for r in intent['routes']} == {'alpha', 'beta', 'gamma'}
    assert all(g['axis_um'] == 17.6 for g in intent['symmetry_groups'])
    assert read(out / 'reports/independent-geometry-audit.json')['status'] == 'PASS'


@pytest.mark.parametrize('defect', ['missing_master', 'missing_net_class', 'broken_reflection', 'illegal_pitch'])
def test_invalid_inputs_preserve_blocked_evidence(tmp_path, defect):
    changed = tmp_path / 'changed'
    shutil.copytree(EXAMPLE, changed, ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    if defect == 'missing_master':
        path = changed / 'config/pdk-map.json'
        data = read(path)
        data['devices'] = data['devices'][1:]
    elif defect == 'missing_net_class':
        path = changed / 'config/routing-policy.json'
        data = read(path)
        data['example_recipe']['net_classes'].pop('N1')
    elif defect == 'broken_reflection':
        path = changed / 'config/circuit.json'
        data = read(path)
        data['modules'][0]['orientations']['NREF__M1'] = 'R0'
    else:
        path = changed / 'config/routing-policy.json'
        data = read(path)
        data['example_recipe']['external_trunk_pitch_um'] = 0.4
    write(path, data)
    out = tmp_path / 'blocked-run'
    result = run(out, changed)
    assert result.returncode == 2, result.stdout + result.stderr
    summary = read(out / 'reports/result.json')
    assert summary['status'] == 'BLOCKED' and summary['materializable'] is False
    assert summary['reason']
    assert not (out / 'reports/summary.md').exists()
