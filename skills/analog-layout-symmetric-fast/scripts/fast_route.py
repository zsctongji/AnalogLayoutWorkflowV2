"""Bounded configurable templates; no A*, live CAD writes or signoff claims."""
from pathlib import Path
import argparse
import copy
import importlib.util
import json
import math

HERE = Path(__file__).resolve().parent
loader = importlib.util.spec_from_file_location('fast_mirror', HERE / 'mirror_spec.py')
MIRROR = importlib.util.module_from_spec(loader)
loader.loader.exec_module(MIRROR)
SCHEMA = 'analog-layout-symmetric-fast.templates/v1'


def positive(value, label):
    value = MIRROR.finite(value)
    if value <= 0:
        raise ValueError('Positive ' + label + ' required')
    return value


def metal_levels(profile, explicit):
    """Actual levels are independent of layer names and technology-rank parity."""
    layers = {r['layer'] for r in profile['routing_layers']}
    if not isinstance(explicit, dict) or not layers <= set(explicit):
        raise ValueError('Explicit actual metal levels required for every routing layer')
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in explicit.values()):
        raise ValueError('Metal levels must be positive integers')
    if len(set(explicit.values())) != len(explicit):
        raise ValueError('Duplicate actual metal levels')
    functions = [f for f in profile.get('layer_functions', []) if f.get('function') == 'metal']
    if functions:
        ranks = [f.get('rank') for f in functions]
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in ranks) or len(set(ranks)) != len(ranks):
            raise ValueError('Incomplete or ambiguous PDK metal stack')
        derived = {f['layer']: i + 1 for i, f in enumerate(sorted(functions, key=lambda f: f['rank']))}
        if any(layer in explicit and explicit[layer] != n for layer, n in derived.items()):
            raise ValueError('Actual metal levels disagree with PDK stack')
    for rule in profile['routing_layers']:
        expected = 'vertical' if explicit[rule['layer']] % 2 else 'horizontal'
        if rule.get('preferred_direction') not in (None, 'none', expected):
            raise ValueError('PDK direction conflicts with odd/even policy: ' + rule['layer'])
    return explicit


def generated_tracks(profile, obstacles, points, axis, layer, width, limit):
    """Finite grid tracks from measured pins, bounds and expanded obstacle edges.

    Candidate generation only; it does not certify a complete route or via.
    """
    if axis not in ('x', 'y') or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError('Coordinate axis and positive track limit required')
    grid = positive(profile['manufacturing_grid_um'], 'manufacturing grid')
    rule = next((r for r in profile['routing_layers'] if r['layer'] == layer), None)
    if rule is None:
        raise ValueError('Unknown PDK track layer')
    width = positive(width, 'track width')
    if width < MIRROR.ri.floor(rule['minimum_width_rules'], 'minimum width'):
        raise ValueError('Track width below PDK minimum')
    spacing = MIRROR.ri.floor(rule['minimum_spacing_rules'], 'minimum spacing')
    for conditional in rule.get('width_spacing_rules', []):
        if not conditional.get('source'):
            raise ValueError('Conditional track spacing lacks provenance')
        spacing = max(spacing, positive(conditional['spacing_um'], 'conditional spacing'))
    bounds = obstacles['bounds_um']
    if len(bounds) != 2 or any(len(p) != 2 for p in bounds) or any(MIRROR.finite(bounds[0][k]) >= MIRROR.finite(bounds[1][k]) for k in (0, 1)):
        raise ValueError('Invalid routing bounds')
    k = 'xy'.index(axis)
    snap_up = lambda x: round(math.ceil(x / grid - 1e-10) * grid, 12)
    snap_down = lambda x: round(math.floor(x / grid + 1e-10) * grid, 12)
    values = {snap_up(bounds[0][k] + width / 2), snap_down(bounds[1][k] - width / 2)}
    anchors = [MIRROR.xy(p)[k] for p in points]
    for x in anchors:
        values.update((snap_down(x), snap_up(x)))
    for obstacle in obstacles.get('obstacles', []):
        if obstacle.get('layer') != layer:
            continue
        box = obstacle['bbox_um']
        values.update((snap_down(box[0][k] - spacing - width / 2), snap_up(box[1][k] + spacing + width / 2)))
    values = [v for v in values if bounds[0][k] + width / 2 <= v <= bounds[1][k] - width / 2]
    return sorted(values, key=lambda v: (sum(abs(v - x) for x in anchors), v))[:limit]


def layered_dogleg(profile, policy, prefix, net, points, horizontal_role, vertical_role, widths_by_role, via_name):
    """Assign a finite Manhattan skeleton to mapped roles, with adjacent vias.

    Endpoint access/landing geometry and complete obstacle review remain callers'
    responsibility. This helper never invents a direct nonadjacent transition.
    """
    levels = metal_levels(profile, policy['metal_levels'])
    roles = policy['layer_roles']
    h, v = roles[horizontal_role], roles[vertical_role]
    if levels[h] % 2 or not levels[v] % 2:
        raise ValueError('Horizontal/vertical roles violate actual-level directions')
    widths = {h: positive(widths_by_role[horizontal_role], 'horizontal width'), v: positive(widths_by_role[vertical_role], 'vertical width')}
    points = MIRROR.clean(points)
    routes, vias = [], []
    previous = None
    for i, (a, b) in enumerate(zip(points, points[1:])):
        layer = h if a[1] == b[1] else v
        if previous is not None and layer != previous:
            if abs(levels[layer] - levels[previous]) != 1:
                raise ValueError('Nonadjacent transition needs an explicit qualified via stack')
            definitions = [x for x in profile.get('vias', []) if x.get('name') == via_name]
            if len(definitions) != 1 or {definitions[0].get('layer1'), definitions[0].get('layer2')} != {layer, previous}:
                raise ValueError('Named PDK via does not connect mapped roles')
            vias.append({'id': prefix + ':via:' + str(i), 'net': net, 'via': via_name, 'xy_um': a})
        routes.append({'id': prefix + ':segment:' + str(i), 'net': net, 'layer': layer, 'width_um': widths[layer], 'points_um': [a, b], 'access': []})
        previous = layer
    return {'routes': routes, 'vias': vias}


def direction_audit(profile, spec, policy):
    levels = metal_levels(profile, policy['metal_levels'])
    exceptions = policy.get('local_direction_exceptions', {})
    errors, used = [], set()
    for route in spec['routes']:
        if route['layer'] not in levels:
            errors.append('Unmapped route layer: ' + route['id'])
            continue
        for a, b in zip(route['points_um'], route['points_um'][1:]):
            actual = 'vertical' if a[0] == b[0] else 'horizontal'
            expected = 'vertical' if levels[route['layer']] % 2 else 'horizontal'
            if actual == expected:
                continue
            rule = exceptions.get(route['id'], {})
            region = rule.get('region_um')
            length = sum(abs(c[0] - d[0]) + abs(c[1] - d[1]) for c, d in zip(route['points_um'], route['points_um'][1:]))
            boxes = [MIRROR.ri.segrect(c, d, route['width_um']) for c, d in zip(route['points_um'], route['points_um'][1:])]
            valid = (levels[route['layer']] == 1 and rule.get('source') and rule.get('reason') and
                     region and len(region) == 2 and all(len(p) == 2 for p in region) and
                     rule.get('max_length_um') is not None and length <= positive(rule['max_length_um'], 'exception length') and
                     all(region[0][0] <= box[0] and region[0][1] <= box[1] and region[1][0] >= box[2] and region[1][1] >= box[3] for box in boxes))
            if not valid:
                errors.append('Unqualified off-direction route: ' + route['id'])
            else:
                used.add(route['id'])
    if set(exceptions) - used:
        errors.append('Unused/stale local direction exceptions: ' + str(sorted(set(exceptions) - used)))
    return {'status': 'PASS' if not errors else 'BLOCKED', 'errors': errors, 'metal_levels': levels, 'exceptions': sorted(used)}


def compile_fast(profile, access, request):
    MIRROR.check_keys(request, ['schema', 'sources', 'axis', 'seed_spec', 'pairs', 'self_nets', 'ordinary_nets', 'via_mirror_evidence', 'routing_policy'])
    if request.get('schema') != SCHEMA:
        raise ValueError('Unsupported fast request schema')
    json.dumps([profile, access, request], allow_nan=False)
    policy = request['routing_policy']
    MIRROR.check_keys(policy, ['metal_levels', 'layer_roles', 'local_direction_exceptions'])
    levels = metal_levels(profile, policy['metal_levels'])
    roles = policy.get('layer_roles', {})
    if any(layer not in levels for layer in roles.values()):
        raise ValueError('Unknown mapped layer role')
    required = set(request['seed_spec']['required_nets'])
    actual = {data['net'] for inst in access['instances'] for data in inst['terminals'].values()}
    if required != actual:
        raise ValueError('Required nets must cover exact terminal-access nets')
    covered = [n for p in request.get('pairs', []) for n in (p['first_net'], p['second_net'])] + request.get('self_nets', [])
    ordinary = request.get('ordinary_nets', {})
    if any(not isinstance(reason, str) or not reason.strip() for reason in ordinary.values()):
        raise ValueError('Ordinary/matched-only nets require scoped reasons')
    covered += list(ordinary)
    if len(covered) != len(set(covered)) or set(covered) != required:
        raise ValueError('Every required net needs exactly one symmetry classification')
    template = {k: copy.deepcopy(v) for k, v in request.items() if k not in ('ordinary_nets', 'routing_policy')}
    template['schema'] = 'analog-layout-symmetric-route.templates/v1'
    result = MIRROR.compile_spec(profile, access, template)
    audit = direction_audit(profile, result['route_spec'], policy)
    result['direction_audit'] = audit
    result['configuration_sha256'] = MIRROR.ri.digest(request)
    result['intent']['validation']['warnings'].append('Fast template candidate: complete local-access, live obstacle/cut/conditional-rule and saved-readback checks remain required')
    if audit['status'] != 'PASS':
        result['status'] = 'BLOCKED'
    result['backend'] = 'symmetric_fast'
    result['materializable'] = False
    return result


def configured_search(profile, access, policy, pdk, obstacles=None, target=None):
    """Workflow backend using external seed/axis/net policies, never a solver fallback."""
    if target and target != access['target']:
        raise ValueError('Project/access target drift')
    if pdk.get('technology_library') and pdk['technology_library'] != profile['technology']['library']:
        raise ValueError('PDK technology mapping drift')
    if policy.get('search') or policy.get('symmetry_solver') or policy.get('symmetry_groups'):
        raise ValueError('Fast templates cannot silently consume general/joint search options; select the intended backend')
    config = copy.deepcopy(policy.get('fast_templates', {}))
    MIRROR.check_keys(config, ['axis', 'seed_spec', 'pairs', 'self_nets', 'ordinary_nets', 'via_mirror_evidence', 'local_direction_exceptions'])
    if 'seed_spec' not in config:
        raise ValueError('FAST_TEMPLATE_REQUIRED: provide a complete measured seed_spec; no implicit solver fallback')
    request = {'schema': SCHEMA, **config, 'sources': {
        'profile_fingerprint': MIRROR.ri.fingerprint(profile), 'terminal_access_sha256': MIRROR.ri.digest(access),
        'seed_sha256': MIRROR.ri.digest(config['seed_spec'])}, 'routing_policy': {
        'metal_levels': copy.deepcopy(pdk.get('routing_rules', {}).get('metal_levels', {})),
        'layer_roles': copy.deepcopy(pdk.get('layer_roles', {})),
        'local_direction_exceptions': config.pop('local_direction_exceptions', {})}}
    request.pop('local_direction_exceptions', None)
    if 'via_mirror_evidence' not in request:
        request['via_mirror_evidence'] = copy.deepcopy(pdk.get('routing_rules', {}).get('via_mirror_evidence', {}))
    result = compile_fast(profile, access, request)
    candidates = [{'route_spec': result['route_spec'], 'template_preflight': result}] if result['status'] == 'TEMPLATE_PREFLIGHT_PASS' else []
    return {'schema': 'analog-layout-route.plan-candidates/v1', 'backend': 'symmetric_fast',
            'status': 'PLANNED' if candidates else 'BLOCKED', 'candidates': candidates,
            'failures': [] if candidates else [{'code': 'FAST_TEMPLATE_PREFLIGHT_FAILED', 'reason': result}],
            'configured_request': request, 'configured_obstacles': obstacles or {'coverage': {'live_snapshot': False}},
            'configuration_sha256': MIRROR.ri.digest({'policy': policy, 'pdk': pdk}), 'materializable': False,
            'execution_scope': 'Offline template candidate only; no obstacle-routing/signoff claim'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'terminal-access', 'request', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Output exists; choose a new run directory')
    read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    result = compile_fast(read(args.profile), read(args.terminal_access), read(args.request))
    args.out.mkdir(parents=True)
    for name, data in [('template-result.json', result), ('route-spec.json', result['route_spec']), ('preflight-intent.json', result['intent']), ('direction-audit.json', result['direction_audit'])]:
        (args.out / name).write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    (args.out / 'preview.svg').write_text(MIRROR.ri.svg(result['intent']), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'materializable': False}))
    return 2 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
