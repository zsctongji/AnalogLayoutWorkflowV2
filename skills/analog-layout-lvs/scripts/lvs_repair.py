"""Bounded LVS repair gate/controller. Live execution requires a trusted CAD adapter."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path

# Reuse the installed DRC skill's geometry primitives, not its update-only controller.
_path = Path(__file__).resolve().parents[2] / 'analog-layout-drc/scripts/symmetric_repair.py'
_spec = importlib.util.spec_from_file_location('lvs_drc_geometry', _path)
_geo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_geo)
FINGERPRINTS = ('baseline_sha256', 'reference_sha256', 'lvs_policy_sha256', 'drc_policy_sha256')
IDENTITY = ('id', 'owner', 'kind', 'net')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hashes(plan):
    for k in FINGERPRINTS:
        h = plan.get(k)
        require(isinstance(h, str) and len(h) == 64 and all(x in '0123456789abcdef' for x in h), 'missing/invalid '+k)


def evidence(value):
    return isinstance(value, list) and bool(value) and all(isinstance(x, dict) and x.get('path') and
           isinstance(x.get('sha256'), str) and len(x['sha256']) == 64 for x in value)


def object_valid(o):
    require(all(isinstance(o.get(k), str) and o[k] for k in IDENTITY), 'object identity missing')
    require(o['owner'] in ('route-owned', 'pin-owned'), 'protected owner')
    require(o['kind'] in ('metal', 'via', 'pin'), 'unsupported geometry kind')
    require((o['kind'] == 'pin') == (o['owner'] == 'pin-owned'), 'pin ownership mismatch')
    _geo.boxes(o)
    require(o['kind'] != 'via' or bool(o['cuts']), 'via requires actual cuts')


def check(snapshot, plan):
    hashes(plan)
    require(plan.get('snapshot_sha256') == digest(snapshot), 'stale snapshot')
    require(plan.get('source') == snapshot.get('target'), 'source mismatch')
    target = plan.get('target', {})
    require(all(isinstance(target.get(k), str) and target[k] for k in ('lib', 'cell', 'view')) and
            target != plan['source'], 'distinct destination required')
    require(plan.get('authorization'), 'authorization missing')
    require(isinstance(snapshot.get('protected'), dict) and snapshot['protected'], 'protected invariants required')
    old = {o['id']: o for o in snapshot['objects']}
    require(len(old) == len(snapshot['objects']), 'duplicate object')
    slots = snapshot['slots']
    require(isinstance(slots, dict) and not (set(slots) & set(old)), 'invalid slots')
    inventory = {**old, **slots}
    for ident, o in inventory.items():
        require(o.get('id') == ident and all(o.get(k) for k in IDENTITY), 'invalid slot identity')
    for o in old.values():
        object_valid(o)
    scope = snapshot['scope']
    require(set(scope) == set(inventory), 'incomplete scope inventory')
    findings = {f['id']: f for f in plan['findings']}
    require(findings and len(findings) == len(plan['findings']), 'missing/duplicate finding')
    for f in findings.values():
        require(f.get('category') in ('open', 'short', 'port') and
                isinstance(f.get('expected_delta'), dict) and bool(f['expected_delta']) and
                isinstance(f.get('evidence'), dict) and bool(f['evidence']), 'unsupported/unproven finding')
    edits = plan['edits']
    ids = [e['id'] for e in edits]
    require(ids and len(ids) == len(set(ids)), 'empty/duplicate edits')
    require(set(ids) <= set(plan.get('authorized_ids', [])), 'unauthorized objects')
    after = copy.deepcopy(old)
    changed = False
    for e in edits:
        ident, op = e['id'], e['op']
        require(ident in inventory, 'unreserved object')
        require(e.get('finding_ids') and set(e['finding_ids']) <= set(findings), 'missing finding link')
        require(op in ('create', 'replace', 'delete', 'verify'), 'unsupported operation')
        require(e.get('before_sha256') == (digest(old[ident]) if ident in old else None), 'object drift')
        require((ident in slots) == (op == 'create'), 'operation/existence conflict')
        origin = inventory[ident]
        require(origin['owner'] in ('route-owned', 'pin-owned'), 'protected object')
        if origin['owner'] == 'pin-owned' and op != 'verify':
            require(plan.get('authorize_pin_edits') is True, 'pin edit authorization missing')
        new = e.get('after')
        if op == 'delete':
            require(new is None, 'delete must have null after')
            del after[ident]
        else:
            object_valid(new)
            require(all(new.get(k) == origin.get(k) for k in IDENTITY), 'identity/net change')
            # Geometry only for route replacements; pin metadata changes need pin authorization.
            if op == 'replace' and origin['owner'] == 'route-owned':
                require({k:v for k,v in new.items() if k not in ('metal','cuts')} ==
                        {k:v for k,v in origin.items() if k not in ('metal','cuts')}, 'route metadata change')
            if op == 'verify':
                require(new == old[ident], 'verify must be unchanged')
            after[ident] = copy.deepcopy(new)
        changed |= op != 'verify' and new != old.get(ident)
    require(changed, 'no effective repair')
    covered = set()
    groups = snapshot['groups']
    group_ids = [g['id'] for g in groups]
    require(len(group_ids) == len(set(group_ids)) and not set(group_ids) & set(snapshot['exceptions']), 'duplicate scope IDs')
    for g in groups:
        axis = g['axis_x_um']
        require(type(axis) in (int, float) and math.isfinite(axis), 'invalid axis')
        require(g.get('pairs') and len(g.get('net_pair', [])) == 2, 'invalid symmetry group')
        for left, right in g['pairs']:
            pair = {left, right}
            require(pair <= set(inventory) and not pair & covered, 'missing/duplicate mate')
            covered |= pair
            require(all(scope[x] == g['id'] for x in pair), 'scope mismatch')
            require([inventory[left]['net'], inventory[right]['net']] == g['net_pair'], 'mate net mapping')
            require((left in ids) == (right in ids), 'one-sided repair')
            require((left in after) == (right in after), 'missing final mate')
            if left in after:
                require(after[left]['kind'] == after[right]['kind'], 'mate kind mismatch')
                require(_geo.signature(_geo.reflected(after[left], axis)) == _geo.signature(after[right]), 'metal/cut mirror mismatch')
    for ident in set(inventory) - covered:
        exception = snapshot['exceptions'].get(scope[ident], {})
        require(all(exception.get(k) for k in ('reason', 'approval', 'boundary')), 'unaccounted symmetry scope')
        if ident in ids:
            require(scope[ident] in plan.get('authorized_exceptions', []), 'exception edit not authorized')
    result = copy.deepcopy(snapshot)
    result['target'] = copy.deepcopy(target)
    result['objects'] = [after[k] for k in sorted(after)]
    result['slots'] = {k:{field:v[field] for field in IDENTITY} for k,v in inventory.items() if k not in after}
    return result


def execute(plan, adapter):
    before = adapter.snapshot(plan['source'])
    expected = check(before, plan)
    baseline = adapter.validate_baseline(plan, before)
    require(baseline.get('status') == 'BOUND_MISMATCH' and evidence(baseline.get('evidence')), 'baseline not qualified')
    require(baseline.get('snapshot_sha256') == digest(before) and all(baseline.get(k) == plan[k] for k in FINGERPRINTS), 'baseline binding mismatch')
    require(not adapter.exists(plan['target']), 'destination exists or aliases source')
    tx = adapter.begin_clone(plan['source'], plan['target'])
    committed = False
    try:
        clone = copy.deepcopy(before)
        clone['target'] = plan['target']
        require(adapter.read(tx) == clone, 'clone drift')
        for edit in plan['edits']:
            adapter.apply(tx, edit)
        actual = adapter.read(tx)
        require(actual == expected, 'full readback drift')
        receipt = adapter.verify(tx, before, actual, plan)
        require(receipt.get('before_sha256') == digest(before) and receipt.get('after_sha256') == digest(actual) and evidence(receipt.get('evidence')), 'verification binding missing')
        for k in ('expected_delta', 'no_unintended_connectivity', 'pdk_geometry', 'pin_access', 'matched_metrics', 'environment'):
            require(receipt.get('checks', {}).get(k) == 'PASS', 'failed/unknown '+k)
        require(adapter.read(tx) == expected and adapter.snapshot(plan['source']) == before, 'precommit drift')
        adapter.commit(tx)
        committed = True
    finally:
        if not committed:
            adapter.rollback(tx)
    out = {'status': 'SAVED_NOT_CLOSED', 'target': plan['target'], 'issues': [], 'verification': receipt}
    try:
        require(adapter.snapshot(plan['target']) == expected and adapter.snapshot(plan['source']) == before, 'saved/source drift')
        for kind in ('lvs', 'drc'):
            r = getattr(adapter, 'rerun_'+kind)(plan['target'])
            out[kind] = r
            require(r.get('bound') is True and evidence(r.get('evidence')) and r.get('integrity_issues') == [], kind+' unbound/incomplete')
            require(r.get('saved_snapshot_sha256') == digest(expected) and r.get('policy_sha256') == plan[kind+'_policy_sha256'], kind+' revision/policy drift')
            if kind == 'lvs':
                require(r.get('reference_sha256') == plan['reference_sha256'], 'reference changed')
        require(adapter.snapshot(plan['target']) == expected and adapter.snapshot(plan['source']) == before, 'postrun drift')
        if out['lvs']['status'] == 'VERIFIED_MATCH' and out['drc']['status'] == 'CLEAN':
            out['status'] = 'REPAIR_CLOSED'
        else:
            out['issues'].append('Residual/unverified LVS or DRC findings; saved draft retained.')
    except Exception as exc:
        out['issues'].append(str(exc))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    after = check(json.loads(a.snapshot.read_text(encoding='utf-8')), json.loads(a.plan.read_text(encoding='utf-8')))
    with a.output.open('x', encoding='utf-8') as f:
        json.dump({'status':'PLAN_VALIDATED', 'not_live_verified':True, 'expected':after}, f, indent=2)


if __name__ == '__main__':
    main()
