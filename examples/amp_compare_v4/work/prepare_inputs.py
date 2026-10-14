"""Build visibly synthetic geometry, placement and complete terminal-access inputs."""
from pathlib import Path

from common import flow, load_project, read, ri, snap, write


def profile_from_mapping(project):
    pdk = project['pdk']
    geometry, rules = pdk['synthetic_geometry'], pdk['synthetic_routing']
    levels = pdk['routing_rules']['metal_levels']
    layers = sorted(pdk['layer_roles'].values(), key=levels.__getitem__)
    vias = []
    for via in rules['adjacent_vias']:
        vias.append({'name': via['name'],
                     'layer1': pdk['layer_roles'][via['lower_role']],
                     'layer2': pdk['layer_roles'][via['upper_role']],
                     'standard_geometry': {
                         'cut_layer': via['cut_layer'], 'cut_size_um': rules['cut_size_um'],
                         'cut_spacing_um': rules['cut_spacing_um'], 'rows': 1, 'columns': 1,
                         'layer1_enclosure_um': rules['enclosure_um'],
                         'layer2_enclosure_um': rules['enclosure_um']}})
    profile = {
        'schema': ri.PROFILE_SCHEMA, 'provenance': 'SYNTHETIC_PDK',
        'source_target': project['target'], 'technology': {'library': pdk['technology_library']},
        'manufacturing_grid_um': geometry['manufacturing_grid_um'],
        'layers': [{'name': layer} for layer in layers],
        'layer_purposes': [{'layer': layer, 'purpose': 'drawing'} for layer in layers],
        # Technology rank is deliberately different from actual metal-level parity.
        'layer_functions': [{'layer': layer, 'function': 'metal', 'rank': 9 + i * 2}
                            for i, layer in enumerate(layers)],
        'constraints': {'rules': []},
        'routing_layers': [{'layer': layer, 'preferred_direction':
                            'vertical' if levels[layer] % 2 else 'horizontal',
                            'minimum_width_rules': [{'value': rules['minimum_width_um'],
                                                     'source': 'synthetic configuration'}],
                            'minimum_spacing_rules': [{'value': rules['minimum_spacing_um'],
                                                       'source': 'synthetic configuration'}]}
                           for layer in layers],
        'vias': vias, 'validation': {'structurally_valid': True},
        'coverage': {'basic_routing_ready': True, 'live_snapshot': False,
                     'basis': 'Synthetic offline contract inputs only'},
        'boundaries': {'may_drive_automatic_routing': True, 'offline_only': True,
                       'materializable': False, 'foundry_qualified': False}}
    profile['fingerprint'] = {'algorithm': 'sha256', 'value': ri.fingerprint(profile)}
    return profile


def prepare(example, out):
    """Copy editable inputs; derive geometry from the mapped parameters, then place."""
    example, out = Path(example), Path(out)
    raw = read(example / 'config/project.json')
    if raw.get('example') != {'synthetic': True, 'mode': 'offline'}:
        raise ValueError('This runner accepts the synthetic offline example only')
    for ref in ('pdk', 'circuit', 'routing'):
        name = Path(raw[ref])
        if name.is_absolute() or name.parent != Path('.') or name.suffix != '.json':
            raise ValueError('Example configuration references must be JSON filenames inside config/')
        write(out / 'config' / raw[ref], read(example / 'config' / raw[ref]))
    write(out / 'inputs/schematic.json', read(example / 'inputs/schematic.json'))
    raw['inputs'] = {'schematic': '../inputs/schematic.json'}
    write(out / 'config/project.json', raw)
    project = load_project(out / 'config/project.json')
    flow.prepare(project, out / 'work')
    copies = read(out / 'work/plan/device-copies.json')
    blueprint = project['pdk']['synthetic_geometry']
    grid = blueprint['manufacturing_grid_um']
    devices = {}
    for item in copies:
        entries = {p['name']: p['value'] for p in item['pcell_parameter_entries']}
        mapping = next(d for d in project['pdk']['devices'] if d['target_master'] == item['pcell_master'])
        params = {key: entries[rule['target']] for key, rule in mapping['parameters'].items()}
        if item['kind'] in ('nmos', 'pmos'):
            width = blueprint['mos_finger_pitch_um'] * params['fingers'] + blueprint['mos_frame_width_um']
            height = blueprint['mos_frame_height_um'] + params['fw']
        elif item['kind'] == 'capacitor':
            width, height = blueprint['capacitor_size_um']
        else:
            raise ValueError('Synthetic geometry recipe does not support ' + item['kind'])
        width, height = snap(width, grid), snap(height, grid)
        devices[item['logical_device']] = {
            'pcell_master': item['pcell_master'], 'pcell_parameters': item['pcell_parameters'],
            'pcell_parameter_entries': item['pcell_parameter_entries'],
            'pdk_mapping_sha256': item['pdk_mapping_sha256'],
            'bbox_at_r0_origin': [[0, 0], [width, height]], 'width': width, 'height': height}
    geometry = {'schema': 'analog-layout-align.pcell-geometry/v1',
                'source': 'SYNTHETIC_GEOMETRY', 'basis': 'Synthetic parameter-derived rectangles; no PCell probe',
                'manufacturing_grid': grid, 'units': 'micron', 'devices': devices,
                'probe_saved': False, 'materializable': False}
    write(out / 'inputs/pcell-geometry.json', geometry)
    raw['inputs']['pcell_geometry'] = '../inputs/pcell-geometry.json'
    write(out / 'config/project.json', raw)
    project = load_project(out / 'config/project.json')
    placement_result = flow.place(project, out / 'work')
    placement = read(out / 'work/plan/placement-intent.json')
    if not placement['validation']['bbox_overlap_free']:
        raise ValueError('Synthetic placement overlaps')
    axis = placement['floorplan']['core_axis_x']
    if axis is None:
        raise ValueError('Common core axis required by this teaching topology')
    access_instances, pins = [], []
    rows = {}
    for item in placement['instances']:
        key = (item['group'], item['grid_position']['row'])
        rows.setdefault(key, set()).add(round(abs(item['bbox_center'][0] - axis), 9))
    for item in placement['instances']:
        if item['orientation'] not in ('R0', 'MY'):
            raise ValueError('Synthetic pin recipe requires R0/MY orientation')
        offsets = blueprint['mos_pin_offsets_um'] if item['kind'] in ('nmos', 'pmos') else blueprint['capacitor_pin_offsets_um']
        key = (item['group'], item['grid_position']['row'])
        rank = sorted(rows[key]).index(round(abs(item['bbox_center'][0] - axis), 9))
        terminals = {}
        for term, net in item['terminals'].items():
            dx, dy = offsets[term]
            point = [snap(item['bbox_center'][0] + dx * (-1 if item['orientation'] == 'MY' else 1), grid),
                     snap(item['bbox'][0][1] + dy, grid)]
            island = {'id': item['name'] + ':' + term, 'candidate_centers': [point],
                      'selected_center': point, 'access_layers': [project['pdk']['layer_roles']['local']]}
            terminals[term] = {'net': net, 'pin_islands': [island]}
            pins.append({'instance': item['name'], 'terminal': term, 'net': net,
                         'pin_island_id': island['id'], 'xy_um': point, 'row_orbit_rank': rank})
        access_instances.append({'name': item['name'], 'terminals': terminals})
    recipe = project['routing']['example_recipe']
    nets = sorted({p['net'] for p in pins})
    if set(nets) != set(recipe['net_classes']):
        raise ValueError('Every observed net needs exactly one configured net class')
    if len(set(recipe['ports'])) != len(recipe['ports']) or not set(recipe['ports']) <= set(nets):
        raise ValueError('External ports must be unique observed nets')
    top = placement['floorplan']['bbox'][1][1]
    bus_y = {net: snap(top + recipe['channel_margin_um'] + i * recipe['bus_pitch_um'], grid)
             for i, net in enumerate(nets)}
    port_base = max(bus_y.values()) + recipe['channel_margin_um']
    for i, net in enumerate(recipe['ports']):
        point = [axis, snap(port_base + i * recipe['port_pitch_um'], grid)]
        name = 'PORT:' + net
        island = {'id': name + ':P', 'candidate_centers': [point], 'selected_center': point,
                  'access_layers': [project['pdk']['layer_roles']['local']]}
        access_instances.append({'name': name, 'virtual_external_port': True,
                                 'terminals': {'P': {'net': net, 'pin_islands': [island]}}})
        pins.append({'instance': name, 'terminal': 'P', 'net': net,
                     'pin_island_id': island['id'], 'xy_um': point, 'row_orbit_rank': 0})
    access = {'schema': ri.ACCESS_SCHEMA, 'target': project['target'],
              'source': 'SYNTHETIC_METAL_PIN_ISLANDS', 'live_snapshot': False,
              'instances': access_instances, 'materializable': False}
    profile = profile_from_mapping(project)
    for name, value in [('terminal-access.json', access), ('routing-profile.json', profile),
                        ('route-anchors.json', {'axis_x_um': axis, 'pins': pins, 'bus_y_um': bus_y,
                                                'core_bbox_um': placement['floorplan']['bbox']})]:
        write(out / 'inputs' / name, value)
    return project, raw, placement_result
