"""Run the complete offline teaching example; no EDA session, writes or simulation."""
import argparse
from pathlib import Path

from common import EXAMPLE, ROOT, read, ri, write
from prepare_inputs import prepare
from build_route import build


def run(example, out):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError('Output exists; choose a new --out directory to preserve evidence')
    out.mkdir(parents=True)
    try:
        project, raw, placement_result = prepare(example, out)
        route_result, checked = build(project, raw, out)
        access = read(out / 'inputs/terminal-access.json')
        copies = read(out / 'work/plan/device-copies.json')
        nets = sorted({t['net'] for i in access['instances'] for t in i['terminals'].values()})
        pins = sum(len(t['pin_islands']) for i in access['instances'] for t in i['terminals'].values())
        stages = {'configuration': 'PASS', 'placement': 'OFFLINE_CANDIDATE',
                  'synthetic_terminal_access': 'PASS', 'fast_template': 'TEMPLATE_PREFLIGHT_PASS',
                  'independent_geometry_audit': checked['status'],
                  **{s: 'NOT_RUN' for s in ('diffusion_share', 'native_contacts', 'guard_rings',
                                           'complete_macro_optimization', 'live_import', 'drc', 'lvs', 'pex', 'postsim')}}
        summary = {'schema': 'analog-layout-flow.example-result/v1', 'status': 'OFFLINE_EXAMPLE_PASS',
                   'synthetic': True, 'materializable': False, 'backend': 'symmetric_fast',
                   'physical_copies': placement_result['instances'], 'physical_pin_islands': pins,
                   'functional_mos_modules': len({c['group'] for c in copies if c['kind'] in ('nmos', 'pmos')}),
                   'required_nets': nets, 'stages': stages,
                   'inputs_sha256': {name: ri.digest(read(out / 'inputs' / name))
                                     for name in ('schematic.json', 'pcell-geometry.json', 'routing-profile.json',
                                                  'terminal-access.json', 'seed-spec.json')},
                   'pending': ['Site-qualified physical stage adapters and saved live readback',
                               'Foundry DRC and independent LVS on the same revision',
                               'Qualified PEX and identical-condition pre/post simulation']}
        write(out / 'reports/result.json', summary)
        rows = '\n'.join('| ' + s + ' | ' + status + ' |' for s, status in stages.items())
        (out / 'reports/summary.md').write_text(
            '# Synthetic offline example\n\n'
            f'{summary["physical_copies"]} PCell copies, {pins} physical access islands and {len(nets)} complete nets. '
            'Placement, template, SVG and independent represented-geometry checks passed.\n\n'
            '| Stage | Status |\n|---|---|\n' + rows + '\n\n'
            'No native layout, contact, guard ring, signoff or parasitic result was produced. '
            'The external fanout is intentionally spacious and has no analog-performance qualification.\n', encoding='utf-8', newline='\n')
        return summary
    except (ValueError, KeyError, TypeError, OSError) as error:
        write(out / 'reports/result.json', {'status': 'BLOCKED', 'synthetic': True,
                                           'materializable': False, 'reason': str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--example', type=Path, default=EXAMPLE, help='Alternative synthetic input directory')
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/amp_compare_v4')
    args = parser.parse_args()
    try:
        summary = run(args.example, args.out)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('BLOCKED: ' + str(error))
        return 2
    print(summary['status'] + ': ' + str(args.out.resolve() / 'reports/result.json'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
