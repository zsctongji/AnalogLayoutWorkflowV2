"""Read-only placement input audit owned by the dispatcher; no CAD operations."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from workflow_runtime import Invalid, digest, filehash, load

def check_logical_row_pattern(intent, group, pattern, axis):
    """Explicit ABBA/BAAB is a logical identity constraint on measured coordinates."""
    logicals = group.get('logical_devices', [])
    rows = group.get('rows', [])
    if pattern not in ('ABBA', 'BAAB') or len(logicals) != 2 or not rows:
        raise Invalid('Unsupported/missing explicit row pattern for group: ' + group['name'])
    items = {i['name']:i for i in intent.get('instances', [])}
    grid = intent.get('coordinate_contract', {}).get('manufacturing_grid', 0)
    if not isinstance(axis, (int, float)) or not grid or grid <= 0:
        raise Invalid('Explicit pattern requires measured grid and core axis')
    required = [logicals[0 if letter == 'A' else 1] for letter in pattern]
    tolerance = max(1e-9, grid * 1e-6)
    for row in rows:
        if any(n not in items for n in row):
            raise Invalid('Explicit row has unknown physical copy')
        active = [items[n] for n in row if items[n].get('logical_device') in logicals]
        if any('bbox' not in i for i in active):
            raise Invalid('Explicit pattern requires actual physical bboxes')
        active.sort(key=lambda i:(i['bbox'][0][0]+i['bbox'][1][0])/2)
        if [i['logical_device'] for i in active] != required:
            raise Invalid('Measured logical order violates '+pattern+' for group: '+group['name'])
        for logical in logicals:
            copies = [i for i in active if i['logical_device']==logical]
            centroid = sum((i['bbox'][0][0]+i['bbox'][1][0])/2 for i in copies)/len(copies)
            if abs(centroid-axis) > tolerance:
                raise Invalid('Logical copies do not share the declared axis: '+logical)
        for left, right in ((active[0],active[3]),(active[1],active[2])):
            if (abs(left['bbox'][0][0]+right['bbox'][1][0]-2*axis)>tolerance
                    or abs(left['bbox'][1][0]+right['bbox'][0][0]-2*axis)>tolerance):
                raise Invalid('Logical mirror extents mismatch: '+group['name'])

def matching_policy(state):
    overrides = state.get('constraints', {}).get('matching_overrides', {})
    if not isinstance(overrides, dict):
        raise Invalid('matching_overrides must be a per-group mapping')
    for group, choice in overrides.items():
        if not isinstance(choice, dict) or choice.get('source') != 'user' or not isinstance(choice.get('instruction'), str) or not choice['instruction'].strip():
            raise Invalid('Matching override requires actual explicit user instruction: ' + group)
        if choice.get('mode') not in ('common_axis', 'common_centroid', 'explicit_pattern'):
            raise Invalid('Unsupported matching override: ' + group)
    return {'default':'common_axis', 'overrides':overrides}

def check_matching_intent(state, intent):
    policy = matching_policy(state)
    groups = {g['name']:g for g in intent.get('groups', [])}
    for name, choice in policy['overrides'].items():
        if choice.get('mode') == 'explicit_pattern' and choice.get('pattern') in ('ABBA','BAAB') and name not in groups:
            raise Invalid('Requested explicit matching group is missing: '+name)
    for group in intent.get('groups', []):
        pattern = str(group.get('pattern_mode', '')).lower()
        requested = group.get('matching_mode', '')
        # A measured coincident centroid alone is not a requested topology.
        if 'common_centroid' in pattern or '共质心' in pattern or requested == 'common_centroid':
            choice = policy['overrides'].get(group['name'], {})
            if choice.get('mode') != 'common_centroid':
                raise Invalid('Common-centroid candidate requires explicit user request for group: ' + group['name'])
        choice = policy['overrides'].get(group['name'], {})
        row_pattern = choice.get('pattern') if choice.get('mode')=='explicit_pattern' else group.get('required_active_pattern')
        if row_pattern:
            axis = state.get('constraints', {}).get('axis', {}).get('x_um', intent.get('floorplan', {}).get('core_axis_x'))
            check_logical_row_pattern(intent, group, row_pattern, axis)
    return policy

def _read_input(record, base):
    if not isinstance(record, dict) or record.get('host', 'local') != 'local':
        raise Invalid('Dispatcher preflight requires a local hash-bound input')
    if not isinstance(record.get('path'), str) or not record['path']:
        raise Invalid('Dispatcher input path is missing')
    path = Path(record['path'])
    path = path if path.is_absolute() else Path(base) / path
    if not path.is_file() or filehash(path) != record.get('sha256'):
        raise Invalid('Dispatcher input missing/changed: ' + str(path))
    return load(path), {'path':str(path.resolve()), 'sha256':record['sha256'], 'host':'local'}

def _multiplicity(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number != number.to_integral_value():
            raise InvalidOperation
        return int(number)
    except (InvalidOperation, ValueError):
        raise Invalid('Source multiplicity must be an explicit positive integer')

def placement_preflight(state, base, mutating):
    """Audit source multiplicities before planning; audit explicit copies before writes.

    This does not certify geometry, PDK rules, contacts, or live readback.
    """
    request = state.get('dispatch_inputs', {}).get('place', {})
    if not request.get('schematic'):
        raise Invalid('Placement requires dispatch_inputs.place.schematic before execution')
    schematic, source_artifact = _read_input(request['schematic'], base)
    source = {k:schematic.get('source', {}).get(k) for k in ('lib','cell','view')}
    if source != state['source']:
        raise Invalid('Placement schematic identity differs from workflow source')
    devices = schematic.get('instances')
    if not isinstance(devices, list) or not devices:
        raise Invalid('Placement source inventory is empty')
    names = [d['name'] for d in devices]
    if len(set(names)) != len(names):
        raise Invalid('Duplicate logical source device')
    expected = {d['name']:_multiplicity(d.get('params', {}).get('m', 1)) for d in devices}
    policy = matching_policy(state)
    result = {'status':'INPUTS_CHECKED', 'expected_parallel_copies':expected,
              'expected_instance_count':sum(expected.values()),
              'constraints_sha256':digest(state['constraints']), 'artifacts':[source_artifact], 'matching_policy':policy,
              'scope':'Source identity/multiplicity and candidate inventory; not physical verification'}
    if not request.get('placement_intent'):
        if mutating:
            raise Invalid('Materialize only after dispatch_inputs.place.placement_intent is available')
        return result
    intent, candidate_artifact = _read_input(request['placement_intent'], base)
    check_matching_intent(state, intent)
    if intent.get('source_schematic') != state['source']:
        # Ignore nonidentity metadata such as positions_included.
        identity = {k:intent.get('source_schematic', {}).get(k) for k in ('lib','cell','view')}
        if identity != state['source']:
            raise Invalid('Placement candidate has another source identity')
    copies = intent.get('instances', [])
    actual = Counter(c.get('logical_device') for c in copies)
    if dict(actual) != expected:
        raise Invalid('Parallel-copy inventory mismatch (including passive m): expected '
                      + str(expected) + ', candidate ' + str(dict(actual)))
    copy_names = [c['name'] for c in copies]
    if len(set(copy_names)) != len(copy_names):
        raise Invalid('Duplicate physical copy identity')
    by_source = {d['name']:d for d in devices}
    dummy_map = state['constraints'].get('dummy_module_map', {})
    for name, count in expected.items():
        members = [c for c in copies if c['logical_device'] == name]
        if {c.get('copy_index') for c in members} != set(range(count)) or any(c.get('copy_count') != count for c in members):
            raise Invalid('Copy indices/count inconsistent with source m: ' + name)
    for c in copies:
        d = by_source[c['logical_device']]
        if isinstance(c.get('pcell_parameters', {}).get('m'), bool) or c.get('pcell_parameters', {}).get('m') not in (1, '1'):
            raise Invalid('Candidate is not an explicit m=1 copy: ' + c['name'])
        if c['logical_device'] in dummy_map and c.get('group') != dummy_map[c['logical_device']]:
            raise Invalid('Dummy ownership conflicts with frozen module map: ' + c['name'])
        if 'dummy' in c.get('placement_role', '') and c['logical_device'] not in dummy_map:
            raise Invalid('Resolve dummy ownership before materialization: ' + c['name'])
        if c.get('source_master') != {'lib':d['lib'],'cell':d['cell'],'view':d.get('view','schematic')}:
            raise Invalid('Candidate source master mismatch: ' + c['name'])
        wanted = {k.upper():v for k,v in d.get('terms', {}).items()}
        got = {k.upper():v for k,v in c.get('terminals', {}).items()}
        if wanted != got:
            raise Invalid('Candidate terminal net mismatch: ' + c['name'])
    result['artifacts'].append(candidate_artifact)
    result['status'] = 'CANDIDATE_INVENTORY_CHECKED'
    return result
