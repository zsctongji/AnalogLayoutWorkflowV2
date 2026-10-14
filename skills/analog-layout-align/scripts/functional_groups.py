"""Functional topology discovery and explicit module/dummy ownership; offline only."""
from placement_flow import infer_intent, expand_mos_copies, build_copy_groups, associate_dummies, group_constraints

def check_abba_geometry(groups, instances, axis, grid):
    """Check logical identity, realized row order and individual centers/extents."""
    by_name = {i['name']: i for i in instances}
    records = []
    for group in groups:
        pattern = group.get('required_active_pattern')
        if pattern not in ('ABBA','BAAB'):
            continue
        a, b = group['logical_devices']
        for names in group['rows']:
            row = sorted((by_name[n] for n in names if by_name[n]['logical_device'] in (a,b)),
                         key=lambda i: sum(p[0] for p in i['bbox'])/2)
            expected = [a,b,b,a] if pattern == 'ABBA' else [b,a,a,b]
            if [i['logical_device'] for i in row] != expected:
                raise ValueError('Actual logical order is not '+pattern+': ' + group['name'])
            centers = {n:sum(sum(p[0] for p in i['bbox'])/2 for i in row if i['logical_device']==n)/2 for n in (a,b)}
            if any(abs(x-axis) > grid*1e-6 for x in centers.values()):
                raise ValueError('Logical centroid off axis: ' + group['name'])
            if max(sum(p[1] for p in i['bbox'])/2 for i in row)-min(sum(p[1] for p in i['bbox'])/2 for i in row) > grid*1e-6:
                raise ValueError('ABBA devices are not on the same row: ' + group['name'])
            for left, right in ((row[0],row[3]),(row[1],row[2])):
                if any(abs(left['bbox'][k][0]+right['bbox'][1-k][0]-2*axis)>grid*1e-6 for k in (0,1)):
                    raise ValueError('Logical mirrored extent mismatch: ' + group['name'])
            records.append(dict(group=group['name'],pattern=pattern,axis_x_um=axis,logical_x_centroids_um=centers,pass_check=True))
    return records

def prepare_groups(schematic, constraints=None):
    constraints = constraints or {}
    intent = infer_intent(schematic, constraints.get('module_map'))
    copies, by_logical = expand_mos_copies(schematic)
    groups = build_copy_groups(intent, by_logical, constraints.get('matching', 'common_axis'))
    module_map = constraints.get('module_map', {})
    capacitor_groups = [g for g in groups if all(by_logical[n][0]['kind']=='capacitor' for n in g['logical_devices'])]
    for group in groups:
        modules = {module_map[n] for n in group['logical_devices'] if n in module_map}
        if len(modules) > 1:
            raise ValueError('Matching group crosses declared modules: ' + str(group['logical_devices']))
        old = group['name']
        group['name'] = next(iter(modules)) if modules else ('CAP' if len(capacitor_groups)==1 and group in capacitor_groups else old)
        for item in copies:
            if item.get('group') == old:
                item['group'] = group['name']
    if len({g['name'] for g in groups}) != len(groups):
        raise ValueError('Multiple independent groups share a module name; supply an explicit combined plan')
    overrides = constraints.get('matching_overrides',{})
    unknown = set(overrides)-{g['name'] for g in groups}
    if unknown:
        raise ValueError('Matching override group missing from schematic: '+str(sorted(unknown)))
    for group in groups:
        override = overrides.get(group['name'])
        if not override:
            continue
        if override.get('source')!='user' or not isinstance(override.get('instruction'),str) or not override['instruction'].strip():
            raise ValueError('Matching override needs the actual user instruction')
        mode = override.get('mode')
        if mode not in ('common_axis','common_centroid','explicit_pattern'):
            raise ValueError('Unsupported matching override')
        pattern = override.get('pattern')
        if mode=='explicit_pattern' and (pattern not in ('ABBA','BAAB') or group['kind']!='matching_group'):
            raise ValueError('Unsupported explicit group pattern')
        target_mode = 'common_axis' if mode=='explicit_pattern' else mode
        if group['kind']=='matching_group':
            key = 'differential_pairs' if group['role']=='differential_pair' else 'mirror_pairs'
            selected = {'differential_pairs':[], 'mirror_pairs':[], 'dummies':[], 'roles':intent['roles']}
            selected[key] = [group['logical_devices']]
            replacement = build_copy_groups(selected,{n:by_logical[n] for n in group['logical_devices']},target_mode)[0]
            name=group['name'];group.pop('required_active_pattern',None);group.update(replacement);group['name']=name
            if mode=='explicit_pattern' and pattern=='BAAB':
                group['rows'] = [[row[1],row[0],row[3],row[2]] for row in group['rows']]
                mapping={c['name']:c['align_instance'] for c in copies}
                group['align_rows']=[[mapping[n] for n in row] for row in group['rows']]
                group['pattern_mode']='explicit_m_copy_baab_common_axis'
                group['required_active_pattern']='BAAB'
                by_name={c['name']:c for c in copies}
                group['constraints']=group_constraints([[by_name[n] for n in row] for row in group['rows']],symmetrize=True)
        else:
            group['matching_mode']=target_mode
            if group['kind']=='ratioed_matching_group':
                group['pattern_mode']='rotational_unit_copy_common_centroid' if target_mode=='common_centroid' else 'ratioed_common_axis_rows'
        for row_index,row in enumerate(group['rows']):
            for column_index,name in enumerate(row):
                item=next(c for c in copies if c['name']==name)
                item.update(group=group['name'],row=row_index,column=column_index)
    associations = associate_dummies(groups, intent, by_logical)
    dummy_map = constraints.get('dummy_module_map', {})
    for dummy, module in dummy_map.items():
        if dummy not in intent['dummies']:
            raise ValueError('Declared dummy is not a rail-tied MOS dummy: ' + dummy)
        targets = [g for g in groups if g['name'] == module]
        if len(targets) != 1:
            raise ValueError('Nonunique or missing dummy target module: ' + module)
        # Explicit prior user ownership supersedes dimension-only inference.
        names = {c['name'] for c in by_logical[dummy]}
        for group in groups:
            group['dummy_logical_devices'] = [n for n in group.get('dummy_logical_devices', []) if n != dummy]
            group['dummy_copies'] = [n for n in group.get('dummy_copies', []) if n not in names]
        target = targets[0]
        target['dummy_logical_devices'].append(dummy)
        target['dummy_copies'].extend(c['name'] for c in by_logical[dummy])
        associations = [a for a in associations if a['dummy_logical_device'] != dummy]
        associations.append(dict(dummy_logical_device=dummy, target_group=module,
                                 status='associated_explicit_module_map', dummy_copies=sorted(names)))
    if any(not a['status'].startswith('associated') for a in associations):
        raise ValueError('Resolve dummy ownership before writing: ' + str(associations))
    return intent, copies, groups, associations
