#!/usr/bin/env python3
"""Read-only, group-aware source-sharing candidate inspection for ALIGN v2 intents."""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import combinations
from pathlib import Path

SCHEMA = "analog-layout-align.pcell-placement-intent/v2"


def digest(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def inspect_declared_rows(intent: dict) -> dict:
    if intent.get("schema") != SCHEMA:
        raise ValueError("Expected an analog-layout-align v2 PCell placement intent")
    instances = intent.get("instances", [])
    by_name = {item.get("name"): item for item in instances}
    if not instances or len(by_name) != len(instances) or None in by_name:
        raise ValueError("Instance identities must be complete and unique")
    candidates = []
    rejected = []
    reflected_sets = []
    seen_edges = set()
    rows = [(group.get("name"), group.get("role"), row_number, row)
            for group in intent.get("groups", [])
            for row_number, row in enumerate(group.get("rows", []))]
    rows += [(macro.get("name"), macro.get("role", "macro"), row_number, row)
             for macro in intent.get("macro_instances", [])
             for row_number, row in enumerate(macro.get("rows", []))]
    for group_name, role, row_number, row in rows:
        if not group_name:
            raise ValueError("Group or macro row needs a name")
        if len(row) != len(set(row)) or any(name not in by_name for name in row):
            raise ValueError(f"Invalid row: {group_name} row {row_number}")
        edge_ids = {}
        for column in range(len(row)-1):
                names = row[column:column+2]
                edge_key = frozenset(names)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                left, right = (by_name[name] for name in names)
                reasons = []
                if any(item.get("kind") not in {"nmos", "pmos"} for item in (left, right)):
                    reasons.append("non_mos")
                if any(item.get("placement_role") not in {"active", "dummy"} for item in (left, right)):
                    reasons.append("non_device_placement_role")
                if left.get("kind") != right.get("kind"):
                    reasons.append("different_kind")
                if left.get("pcell_master") != right.get("pcell_master"):
                    reasons.append("different_master")
                nets = [item.get("terminals", {}).get("S") for item in (left, right)]
                if not nets[0] or nets[0] != nets[1]:
                    reasons.append("different_or_missing_source_net")
                boxes = [item.get("bbox") for item in (left,right)]
                if any(not box or len(box)!=2 for box in boxes):
                    reasons.append("missing_bbox")
                    gap = None
                else:
                    if boxes[0][0][0] > boxes[1][0][0]:
                        reasons.append("row_order_disagrees_with_x")
                    gap = round(boxes[1][0][0]-boxes[0][1][0], 9)
                    if gap < 0:
                        reasons.append("existing_bbox_overlap")
                    if min(boxes[0][1][1], boxes[1][1][1]) <= max(boxes[0][0][1], boxes[1][0][1]):
                        reasons.append("no_vertical_overlap")
                record = {"id":f"{group_name}:r{row_number}:e{column}",
                          "group":group_name,"role":role,"row":row_number,
                          "columns":[column,column+1],"instances":names,
                          "logical_devices":[left.get('logical_device'),right.get('logical_device')],
                          "source_net":nets[0] if nets[0]==nets[1] else None,
                          "current_bbox_gap_um":gap}
                if reasons:
                    rejected.append({**record,"reasons":reasons})
                else:
                    edge_ids[column]=record['id']
                    candidates.append({**record,"status":"REQUIRES_PDK_PAIR_PROBE"})
        for column,edge_id in edge_ids.items():
                reflected = len(row)-2-column
                if reflected < column or reflected not in edge_ids:
                    continue
                partner = edge_ids[reflected]
                if column != reflected and set(row[column:column+2]) & set(row[reflected:reflected+2]):
                    continue
                reflected_sets.append({"group":group_name,"row":row_number,
                                       "candidate_ids":[edge_id] if edge_id==partner else [edge_id,partner],
                                       "status":"SYMMETRIC_PROBE_SET_ONLY"})
    return {"schema":"analog-layout-diffusion-share.candidates/v1",
            "source_intent_sha256":digest(intent),"candidates":candidates,
            "rejected_edges":rejected,"symmetric_probe_sets":reflected_sets,
            "boundary":"Candidate discovery only. No shared active geometry, continuity, DRC or LVS has been verified."}


def dummy_boundary_review(intent: dict) -> list[dict]:
    """Explain active/dummy row boundaries without authorizing net changes."""
    items = {i['name']: i for i in intent['instances']}
    result, seen = [], set()
    for group in intent.get('groups', []) + intent.get('macro_instances', []):
        for row in group.get('rows', []):
            for names in zip(row, row[1:]):
                key = frozenset(names)
                if key in seen:
                    continue
                seen.add(key)
                pair = [items[n] for n in names]
                if sum(i.get('placement_role') == 'dummy' for i in pair) != 1:
                    continue
                nets = {i['name']: i.get('terminals', {}).get('S') for i in pair}
                missing = any(not net for net in nets.values())
                same = not missing and len(set(nets.values())) == 1
                result.append({'instances': list(names), 'module': group.get('name'),
                               'source_nets': nets, 'same_source': same,
                               'status': 'MISSING_SOURCE_NET' if missing else
                                         'SAME_SOURCE_CANDIDATE' if same else 'SOURCE_NET_CONFLICT',
                               'next_step': 'Check facing source, contacts, module and PDK compatibility' if same else
                                            'Resolve exact schematic S nets; never retie or share automatically',
                               'schematic_change_authorized': False})
    return result


def inspect(intent: dict) -> dict:
    legacy = inspect_declared_rows(intent)
    items = intent['instances']
    owners = {x['name']: ({x.get('module_id') or x.get('group')} if x.get('module_id') or x.get('group') else set()) for x in items}
    for group in intent.get('groups', []):
        for name in [n for row in group.get('rows', []) for n in row] + group.get('dummy_copies', []):
            if name not in owners:
                raise ValueError('Unknown group member: ' + name)
            owners[name].add(group['name'])
    for assoc in intent.get('dummy_associations', []):
        if assoc.get('status', '').startswith('associated') and assoc.get('target_group'):
            for name in assoc.get('dummy_copies', []):
                if name not in owners:
                    raise ValueError('Unknown dummy: ' + name)
                owners[name].add(assoc['target_group'])
    local = {frozenset(e['instances']): e for e in legacy['candidates']}
    pairs = []
    mos = sorted((x for x in items if x.get('kind') in {'nmos', 'pmos'}), key=lambda x: x['name'])
    for a, b in combinations(mos, 2):
        net = a.get('terminals', {}).get('S')
        if not net or net != b.get('terminals', {}).get('S'):
            continue
        checks = []
        if a.get('kind') != b.get('kind') or not a.get('pcell_master') or a.get('pcell_master') != b.get('pcell_master'):
            checks.append('pdk_device_compatibility_required')
        if not a.get('terminals', {}).get('B') or a.get('terminals', {}).get('B') != b.get('terminals', {}).get('B'):
            checks.append('body_well_compatibility_required')
        ao, bo = owners[a['name']], owners[b['name']]
        eligible = len(ao) == len(bo) == 1 and ao == bo
        if not ao or not bo:
            checks.append('module_ownership_required')
        if len(ao) > 1 or len(bo) > 1:
            checks.append('ambiguous_module_ownership')
        if ao and bo and ao != bo:
            checks.append('cross_module_guard_ring_conflict')
        if not a.get('bbox') or not b.get('bbox'):
            checks.append('missing_measured_bbox')
        else:
            left, right = sorted((a, b), key=lambda x: (x['bbox'][0][0], x['name']))
            lb, rb = left['bbox'], right['bbox']
            y0, y1 = max(lb[0][1], rb[0][1]), min(lb[1][1], rb[1][1])
            if y1 <= y0:
                checks.append('re_placement_required')
            elif any(x['name'] not in {a['name'], b['name']} and x.get('bbox')
                     and x['bbox'][0][0] < rb[0][0] and x['bbox'][1][0] > lb[1][0]
                     and x['bbox'][0][1] < y1 and x['bbox'][1][1] > y0 for x in items):
                checks.append('intervening_geometry_requires_re_placement')
            if rb[0][0] < lb[1][0]:
                checks.append('existing_overlap_readback_required')
        edge = local.get(frozenset((a['name'], b['name'])), {})
        pairs.append({**edge, 'id': edge.get('id', 'same-source:' + a['name'] + ':' + b['name']),
                      'instances': edge.get('instances', [a['name'], b['name']]), 'source_net': net,
                      'includes_dummy': any(x.get('placement_role') == 'dummy' for x in (a, b)),
                      'sharing_eligible': eligible, 'module': next(iter(ao)) if eligible else None,
                      'eligibility_policy': 'same_net_same_module',
                      'requirements': checks,
                      'status': 'SHARE_ELIGIBLE' if eligible else 'REQUIRES_MODULE_RESOLUTION'})
    return {**legacy, 'schema': 'analog-layout-diffusion-share.candidates/v2',
            'candidates': pairs, 'declared_row_candidates': legacy['candidates'],
            'dummy_boundary_review': dummy_boundary_review(intent),
            'boundary': 'Same-net, same-module pairs are eligible, including dummy/central edges and chains. Check geometry and connectivity after implementation; exclude cross-module sharing.'}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intent',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=inspect(json.loads(args.intent.read_text(encoding='utf-8-sig')))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({"candidates":len(result['candidates']),"symmetric_probe_sets":len(result['symmetric_probe_sets']),"out":str(args.out)}))


if __name__=='__main__':
    main()
