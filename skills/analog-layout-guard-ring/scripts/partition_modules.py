"""Resolve functional module ownership before guard-ring geometry planning."""
import argparse
import json
from pathlib import Path


def partition(intent, modules=None):
    if intent.get('schema') != 'analog-layout-align.pcell-placement-intent/v2':
        raise ValueError('Requires ALIGN v2 intent')
    items = intent['instances']
    by_name = {x['name']: x for x in items}
    if len(by_name) != len(items):
        raise ValueError('Duplicate instance identity')
    ownership = {name: set() for name in by_name}
    roles = {}
    if modules is not None:
        if len({m['name'] for m in modules}) != len(modules):
            raise ValueError('Duplicate module identity')
        for module in modules:
            roles[module['name']] = module.get('role', 'explicit_module')
            for name in module['instance_names']:
                if name not in by_name:
                    raise ValueError('Unknown module member: ' + name)
                ownership[name].add(module['name'])
    else:
        for item in items:
            if item.get('group'):
                ownership[item['name']].add(item['group'])
        for group in intent.get('groups', []):
            roles[group['name']] = group.get('role', 'functional_group')
            members = [name for row in group.get('rows', []) for name in row]
            members += group.get('dummy_copies', [])
            for name in members:
                if name not in by_name:
                    raise ValueError('Unknown group member: ' + name)
                ownership[name].add(group['name'])
        for assoc in intent.get('dummy_associations', []):
            if assoc.get('status', '').startswith('associated') and assoc.get('target_group'):
                for name in assoc.get('dummy_copies', []):
                    if name not in by_name:
                        raise ValueError('Unknown dummy: ' + name)
                    ownership[name].add(assoc['target_group'])
    buckets, unresolved = {}, []
    for item in items:
        if item.get('kind') not in ('nmos', 'pmos'):
            continue
        owners = ownership[item['name']]
        body = item.get('terminals', {}).get('B')
        if len(owners) != 1 or not body:
            unresolved.append({'instance': item['name'], 'owners': sorted(owners),
                               'reason': 'ambiguous_or_missing_module' if len(owners) != 1 else 'missing_body_net'})
            continue
        module = next(iter(owners))
        key = (module, item['kind'], body)
        buckets.setdefault(key, []).append(item)
    domains = []
    for (module, kind, body), members in sorted(buckets.items()):
        domains.append({'module': module, 'role': roles.get(module, 'functional_group'),
                        'polarity': 'p_substrate' if kind == 'nmos' else 'n_well',
                        'tie_net': body, 'instance_names': sorted(x['name'] for x in members),
                        'bbox_um': [[min(x['bbox'][0][i] for x in members) for i in (0, 1)],
                                    [max(x['bbox'][1][i] for x in members) for i in (0, 1)]]})
    return {'schema': 'analog-layout-guard-ring.module-domains/v1',
            'status': 'BLOCKED_MODULE_OWNERSHIP' if unresolved else 'MODULES_RESOLVED',
            'domains': domains, 'unresolved': unresolved,
            'boundary': 'No geometry or DRC qualification; never merge different modules by common rail.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intent', type=Path, required=True)
    parser.add_argument('--modules', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = partition(json.loads(args.intent.read_text(encoding='utf-8-sig')),
                       json.loads(args.modules.read_text(encoding='utf-8-sig')) if args.modules else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'domains': len(result['domains']), 'unresolved': len(result['unresolved'])}))
