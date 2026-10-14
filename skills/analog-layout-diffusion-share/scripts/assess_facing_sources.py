"""Assess measured orientation variants; geometry candidates, never signoff.

Input probes use live-pcell-contact-probe/v1 records, in placed orientation at
origin (0,0). The caller must measure all PDK-legal requested orientations and
abutment settings. No terminal swapping or geometry synthesis occurs here.
"""
import argparse
import json
from pathlib import Path

EPS = 1e-8


def inside(a, b):
    return all(a[0][k] >= b[0][k]-EPS and a[1][k] <= b[1][k]+EPS for k in (0, 1))


def overlap(a, b):
    return all(min(a[1][k], b[1][k])-max(a[0][k], b[0][k]) > EPS for k in (0, 1))


def shift(box, dx):
    return [[round(p[0]+dx, 9), p[1]] for p in box]


def facing(probe, side):
    thin = [s[1] for s in probe['shapes_local'] if s[0] == ['thin', 'drawing']]
    if not thin:
        raise ValueError('missing_active_geometry')
    index = 1 if side == 'right' else 0
    extreme = (max if index else min)(b[index][0] for b in thin)
    # Do not choose the rightmost S island if it is actually on the left of
    # a single-finger dummy: the PHYSICAL facing edge must itself be S.
    regions = [b for b in probe['source_thin_local'] if abs(b[index][0]-extreme) < EPS]
    if len(regions) != 1:
        raise ValueError('facing_boundary_is_not_unique_source_try_other_orientation')
    region = regions[0]
    cuts = sorted((b for b in probe['source_contacts_local'] if inside(b, region)), key=str)
    metal = [b for b in probe['source_metal_local'] if cuts and all(inside(c, b) for c in cuts)]
    if not cuts or not metal:
        raise ValueError('missing_source_contacts_or_landing_metal')
    return region, cuts, metal[0]


def assess_pair(left, right):
    a, ac, am = facing(left, 'right')
    b, bc, bm = facing(right, 'left')
    dx = round(ac[0][0][0]-bc[0][0][0], 9)
    bc = sorted((shift(c, dx) for c in bc), key=str)
    if ac != bc:
        raise ValueError('source_contact_arrays_do_not_coincide_at_same_y')
    b, bm = shift(b, dx), shift(bm, dx)
    if not overlap(a, b) or not overlap(am, bm):
        raise ValueError('no_positive_source_active_or_metal_overlap')
    la = [s[1] for s in left['shapes_local'] if s[0] == ['thin','drawing']]
    ra = [shift(s[1], dx) for s in right['shapes_local'] if s[0] == ['thin','drawing']]
    lg = [s[1] for s in left['shapes_local'] if s[0] == ['poly1','drawing']]
    rg = [shift(s[1], dx) for s in right['shapes_local'] if s[0] == ['poly1','drawing']]
    if any(overlap(g,t) for gs,ts in ((lg,ra),(rg,la)) for g in gs for t in ts):
        raise ValueError('gate_intrudes_other_device_active')
    drains = left['drain_metal_local'] + [shift(d,dx) for d in right['drain_metal_local']]
    if any(overlap(m,d) for m in (am,bm) for d in drains):
        raise ValueError('source_landing_overlaps_drain_metal')
    return {'status':'GEOMETRY_CANDIDATE_NOT_SIGNOFF','origin_dx_um':dx,
            'source_contacts_um':ac,'contact_count':len(ac)}


def assess_variants(left, right, records):
    net = left.get('terminals',{}).get('S')
    if not net or net != right.get('terminals',{}).get('S'):
        return {'status':'BLOCKED_SOURCE_NET_CONFLICT','accepted':[], 'attempts':[],
                'source_nets':[net,right.get('terminals',{}).get('S')],
                'resolution':'No implicit dummy retie or S/D swap; request schematic-intent decision.'}
    if (left.get('kind') != right.get('kind') or not left.get('pcell_master')
            or left.get('pcell_master') != right.get('pcell_master')
            or not left.get('terminals',{}).get('B')
            or left['terminals']['B'] != right.get('terminals',{}).get('B')):
        return {'status':'BLOCKED_DEVICE_OR_BODY_COMPATIBILITY','accepted':[], 'attempts':[]}
    lp=[p for p in records if p['instance']==left['name']]
    rp=[p for p in records if p['instance']==right['name']]
    attempts=[]; accepted=[]
    for a in lp:
        for b in rp:
            trial={'left_orientation':a['orientation'],'right_orientation':b['orientation'],
                   'left_flags':a.get('flags'),'right_flags':b.get('flags')}
            try:
                result=assess_pair(a,b)
                accepted.append({**trial,**result})
                trial['status']=result['status']
            except ValueError as exc:
                trial.update(status='TRIAL_REJECTED',reason=str(exc))
            attempts.append(trial)
    return {'status':'GEOMETRY_CANDIDATES' if accepted else 'NO_VALID_SUPPLIED_VARIANT',
            'accepted':accepted,'attempts':attempts,
            'boundary':'Failed supplied trials are not proof that every PDK-legal orientation is infeasible. Full-array isolation, matching, well, contact readback and DRC/LVS remain required.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('intent','probes','left','right','out'):
        parser.add_argument('--'+arg,required=True)
    args=parser.parse_args()
    by_name={i['name']:i for i in json.loads(Path(args.intent).read_text(encoding='utf-8'))['instances']}
    records=json.loads(Path(args.probes).read_text(encoding='utf-8'))['records']
    result=assess_variants(by_name[args.left],by_name[args.right],records)
    Path(args.out).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(result['status'])
