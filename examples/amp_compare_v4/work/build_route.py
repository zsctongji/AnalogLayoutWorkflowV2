"""Assemble a complete seed from geometry and policy, using shared fast helpers.

This is a deliberately spacious teaching topology, not a universal analog router.
It supports complete self-symmetric nets with M1 access, M2 fanouts/buses and M3
external columns. It rejects unsupported topology rather than changing backends.
"""
import copy
import sys

from common import SKILLS, fast, flow, helper, load_project, read, ri, snap, write


def pin_orbits(pins, axis, grid):
    by_point = {}
    for pin in pins:
        key = (pin['net'], *pin['xy_um'])
        if key in by_point:
            raise ValueError('Ambiguous coincident pin islands; use another recipe')
        by_point[key] = pin
    used, orbits = set(), []
    for pin in sorted(pins, key=lambda p: (p['net'], p['xy_um'][1], p['xy_um'][0])):
        if pin['pin_island_id'] in used:
            continue
        x, y = pin['xy_um']
        mate = by_point.get((pin['net'], snap(2 * axis - x, grid), y))
        if mate is None or mate['row_orbit_rank'] != pin['row_orbit_rank']:
            raise ValueError('Complete-net self-reflection is unavailable for ' + pin['pin_island_id'])
        used.update((pin['pin_island_id'], mate['pin_island_id']))
        orbits.append([pin] if pin is mate else [pin, mate])
    return orbits


def build(project, raw_project, out):
    recipe = project['routing']['example_recipe']
    if recipe['topology'] != 'self_symmetric_external_fanout':
        raise ValueError('Unsupported teaching topology; select and implement another recipe explicitly')
    profile = read(out / 'inputs/routing-profile.json')
    access = read(out / 'inputs/terminal-access.json')
    anchors = read(out / 'inputs/route-anchors.json')
    axis, grid = anchors['axis_x_um'], profile['manufacturing_grid_um']
    orbits = pin_orbits(anchors['pins'], axis, grid)
    roles = project['pdk']['layer_roles']
    rules = project['pdk']['synthetic_routing']
    routing_policy = {'layer_roles': roles, 'metal_levels': project['pdk']['routing_rules']['metal_levels']}
    fast.metal_levels(profile, routing_policy['metal_levels'])
    if routing_policy['metal_levels'][roles['local']] != 1:
        raise ValueError('This recipe requires local access on actual M1')

    def via_for(first, second):
        choices = [v for v in profile['vias'] if {v['layer1'], v['layer2']} == {roles[first], roles[second]}]
        if len(choices) != 1:
            raise ValueError('One named adjacent via required for ' + first + '/' + second)
        return choices[0]['name']

    v12, v23 = via_for('local', 'collection'), via_for('collection', 'trunk')
    widths = {net: copy.deepcopy(recipe['supply_widths_by_role_um'] if cls in ('power', 'ground')
                                else recipe['widths_by_role_um']) for net, cls in recipe['net_classes'].items()}
    max_width = max(w['trunk'] for w in widths.values())
    pitch = recipe['external_trunk_pitch_um']
    spacing = rules['minimum_spacing_um']
    if pitch < max_width + spacing:
        raise ValueError('External track pitch cannot satisfy worst-case wire spacing')
    core = anchors['core_bbox_um']
    margin = recipe['channel_margin_um']
    first_radius = max(abs(core[k][0] - axis) for k in (0, 1)) + margin
    radius_limit = first_radius + (len(orbits) + 3) * pitch
    low_y = core[0][1] - margin
    high_y = max(p['xy_um'][1] for p in anchors['pins']) + recipe['max_local_m1_um'] + margin
    bounds = [[snap(axis - radius_limit, grid), snap(low_y, grid)],
              [snap(axis + radius_limit, grid), snap(high_y, grid)]]
    # A conservative central keepout reserves all previously allocated M3 tracks.
    # Its boundary evolves with geometry; no circuit-specific coordinates occur.
    outer_edge = first_radius
    tracks, routes, vias, local, pairs = [], [], [], {}, {}
    bus_columns = {net: [] for net in anchors['bus_y_um']}
    for index, orbit in enumerate(orbits):
        keepout = {'bounds_um': bounds, 'obstacles': [{'layer': roles['trunk'],
                    'bbox_um': [[snap(axis - outer_edge, grid), bounds[0][1]],
                                [snap(axis + outer_edge, grid), bounds[1][1]]]}]}
        candidates = fast.generated_tracks(profile, keepout, [[axis, orbit[0]['xy_um'][1]]],
                                           'x', roles['trunk'], max_width, recipe['track_candidate_limit'])
        accepted = None
        for attempt, candidate in enumerate(candidates, 1):
            if attempt > recipe['track_attempt_budget']:
                break
            radius = snap(candidate - axis, grid)
            mate_x = snap(axis - radius, grid)
            if radius <= outer_edge or mate_x - max_width / 2 < bounds[0][0]:
                continue
            if tracks and radius - tracks[-1]['radius_um'] + 1e-10 < pitch:
                continue
            accepted = radius
            break
        if accepted is None:
            raise ValueError('Bounded common external-track search exhausted')
        radius = accepted
        tracks.append({'orbit': index, 'radius_um': radius, 'candidates_x_um': candidates,
                       'selected_x_um': [snap(axis - radius, grid), snap(axis + radius, grid)],
                       'islands': [p['pin_island_id'] for p in orbit]})
        outer_edge = snap(radius + pitch - spacing - max_width / 2, grid)
        net = orbit[0]['net']
        pair = [orbit[0]['pin_island_id'], orbit[-1]['pin_island_id']]
        pairs.setdefault(net, []).append(pair)
        for pin in orbit:
            p = pin['xy_um']
            stub_length = recipe['local_stub_base_um'] + pin['row_orbit_rank'] * recipe['local_stub_pitch_um']
            if stub_length > recipe['max_local_m1_um']:
                raise ValueError('Configured row exceeds local M1 budget')
            q = [p[0], snap(p[1] + stub_length, grid)]
            prefix = 'pin:' + pin['pin_island_id']
            w = widths[net]
            routes.append({'id': prefix + ':local', 'net': net, 'layer': roles['local'],
                           'width_um': w['local'], 'points_um': [p, q],
                           'access': [{k: pin[k] for k in ('instance', 'terminal', 'pin_island_id', 'xy_um')}]})
            vias.append({'id': prefix + ':v12', 'net': net, 'via': v12, 'xy_um': q})
            region = [[snap(p[0] - w['local'] / 2, grid), snap(p[1] - w['local'] / 2, grid)],
                      [snap(p[0] + w['local'] / 2, grid), snap(q[1] + w['local'] / 2, grid)]]
            local[pin['pin_island_id']] = {'region_um': region, 'max_length_um': recipe['max_local_m1_um'],
                                          'source': 'SYNTHETIC bounded metal-access recipe; not native qualification'}
            signs = (-1, 1) if p[0] == axis else (-1,) if p[0] < axis else (1,)
            for sign in signs:
                x = snap(axis + sign * radius, grid)
                end = [x, anchors['bus_y_um'][net]]
                fragment = fast.layered_dogleg(profile, routing_policy, prefix + ':' + str(sign), net,
                                              [q, [x, q[1]], end], 'collection', 'trunk', w, v23)
                routes.extend(fragment['routes'])
                vias.extend(fragment['vias'])
                vias.append({'id': prefix + ':' + str(sign) + ':bus-v23', 'net': net, 'via': v23, 'xy_um': end})
                bus_columns[net].append(x)
    for net, columns in bus_columns.items():
        y = anchors['bus_y_um'][net]
        routes.append({'id': 'bus:' + net, 'net': net, 'layer': roles['collection'],
                       'width_um': widths[net]['collection'], 'points_um': [[min(columns), y], [max(columns), y]],
                       'access': []})
    constraints = []
    for net, cls in recipe['net_classes'].items():
        policy = {'net': net, 'net_class': cls}
        if cls in ('power', 'ground'):
            policy['width_basis'] = recipe['supply_width_basis']
        if cls in ('sensitive', 'high_impedance'):
            policy['max_bbox_excursion_um'] = recipe['directness_excursion_um']
        constraints.append(policy)
    seed = {'schema': ri.SPEC_SCHEMA, 'target': project['target'], 'required_nets': sorted(bus_columns),
            'routes': routes, 'vias': vias, 'contact_landings': [], 'net_constraints': constraints}
    via_evidence = {v['name']: {'geometry_sha256': ri.digest(v['standard_geometry']),
                               'mirror_verified': True, 'source': 'SYNTHETIC centered cut array definition only'}
                    for v in profile['vias']}
    obstacles = {'schema': 'analog-layout-route.obstacles/v1', 'target': project['target'],
                 'bounds_um': bounds, 'obstacles': [], 'coverage': {'live_snapshot': False,
                 'basis': 'Synthetic empty scene; candidate metals/cuts checked independently'}, 'materializable': False}
    audit_request = {'target': project['target'], 'axis': {'coordinate': 'x', 'value_um': axis},
                     'metal_levels': routing_policy['metal_levels'], 'local_access': local,
                     'via_mirror_evidence': via_evidence,
                     'cut_rules': {v['standard_geometry']['cut_layer']: {'spacing_um': spacing,
                                   'source': 'SYNTHETIC cut spacing'} for v in profile['vias']},
                     'cross_cut_rules': [{'layers': [profile['vias'][0]['standard_geometry']['cut_layer'],
                                                    profile['vias'][1]['standard_geometry']['cut_layer']],
                                          'spacing_um': spacing, 'stacking_allowed': False,
                                          'source': 'SYNTHETIC no-stacked-cut rule'}],
                     'nets': [{'net': net, 'layers': list(roles.values()),
                               'widths_um': {roles[role]: width for role, width in widths[net].items()}}
                              for net in sorted(bus_columns)],
                     'groups': [{'id': 'self:' + net, 'mode': 'self', 'net': net, 'pin_pairs': pairs[net]}
                                for net in sorted(bus_columns)]}
    routing = copy.deepcopy(project['routing'])
    routing['fast_templates'] = {'axis': audit_request['axis'], 'seed_spec': seed,
                                 'pairs': [], 'self_nets': seed['required_nets'], 'ordinary_nets': {},
                                 'via_mirror_evidence': via_evidence}
    write(out / 'config' / raw_project['routing'], routing)
    for name, data in [('seed-spec.json', seed), ('obstacles.json', obstacles),
                       ('independent-audit-request.json', audit_request),
                       ('generated-tracks.json', {'source': 'geometry-derived common external tracks', 'tracks': tracks})]:
        write(out / 'inputs' / name, data)
    raw_project['inputs'].update({'routing_profile': '../inputs/routing-profile.json',
                                  'terminal_access': '../inputs/terminal-access.json', 'obstacles': '../inputs/obstacles.json'})
    write(out / 'config/project.json', raw_project)
    result = flow.route(load_project(out / 'config/project.json'), out / 'work', fast=True)
    if result['status'] != 'PLANNED':
        reasons = []
        for failure in result['failures']:
            detail = failure.get('reason')
            if isinstance(detail, dict):
                reasons.extend(detail.get('intent', {}).get('validation', {}).get('errors', []))
                reasons.extend(detail.get('direction_audit', {}).get('errors', []))
                reasons.extend(detail.get('symmetry_preflight', {}).get('errors', []))
            else:
                reasons.append(str(detail))
        raise ValueError('Fast template failed: ' + str(reasons or [f['code'] for f in result['failures']]))
    # Use the independent reconstruction validator without invoking the joint solver.
    sys.path.insert(0, str(SKILLS / 'analog-layout-symmetric-route/scripts'))
    audit = helper('analog-layout-symmetric-route', 'symmetric_audit.py', 'example_audit')
    planner = helper('analog-layout-route', 'route_planner.py', 'example_planner')
    spec = read(out / 'work/routing/symmetric-fast/spec.json')
    checked = audit.audit(profile, access, obstacles, audit_request, spec, planner, fast.MIRROR)
    write(out / 'reports/independent-geometry-audit.json', checked)
    if checked['status'] != 'PASS':
        raise ValueError('Independent synthetic geometry audit failed: ' + str(checked['errors']))
    return result, checked
