"""Pure rectangle/cut symmetry gate and transactional adapter protocol.
No built-in live writer: adapter must supply fresh full snapshot, clone rollback,
connectivity/PDK verification and same-policy DRC rerun. Never edits source.
"""
import copy,hashlib,json,math

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def boxes(obj):
    for k in ('metal','cuts'):
        rows=obj.get(k)
        if not isinstance(rows,list):raise ValueError('explicit metal and cuts inventories required')
        for r in rows:
            b=r.get('bbox_um')
            if not isinstance(b,list) or len(b)!=2 or any(not isinstance(p,list) or len(p)!=2 for p in b):raise ValueError('bad bbox')
            if not all(isinstance(x,(float,int)) and math.isfinite(x) for p in b for x in p):raise ValueError('nonfinite geometry')
            if b[0][0]>=b[1][0] or b[0][1]>=b[1][1]:raise ValueError('empty bbox')
            if not r.get('layer'):raise ValueError('missing layer')
    if not obj['metal']:raise ValueError('empty conductor')

def reflected(obj,axis):
    out=copy.deepcopy(obj)
    for k in ('metal','cuts'):
        for r in out[k]:
            b=r['bbox_um'];b[0][0],b[1][0]=2*axis-b[1][0],2*axis-b[0][0]
    return out

def signature(obj):
    # Array definitions/width etc must be represented in actual metal/cut
    # rectangles, not just nominal via names or centerline lengths.
    return {k:sorted((r['layer'],tuple(round(x,9) for p in r['bbox_um'] for x in p)) for r in obj[k]) for k in ('metal','cuts')}

def check(snapshot,plan):
    if plan.get('snapshot_sha256')!=digest(snapshot):raise ValueError('stale repair plan')
    if plan.get('source')!=snapshot.get('target'):raise ValueError('source identity mismatch')
    target=plan.get('target',{})
    if not all(isinstance(target.get(k),str) and target[k] for k in ('lib','cell','view')) or target==snapshot['target']:
        raise ValueError('a distinct explicit draft destination is required')
    if not plan.get('authorization'):raise ValueError('repair authorization required')
    objects={o['id']:o for o in snapshot['objects']}
    if len(objects)!=len(snapshot['objects']):raise ValueError('duplicate object ID')
    for o in objects.values():boxes(o)
    edits=plan.get('edits',[]);ids=[e['id'] for e in edits]
    if not ids or len(ids)!=len(set(ids)):raise ValueError('empty/duplicate edits')
    if any(x not in objects for x in ids):raise ValueError('unknown edited object')
    after=copy.deepcopy(objects)
    for e in edits:
        old=objects[e['id']];new=e['after'];boxes(new)
        if e.get('before_sha256')!=digest(old):raise ValueError('object drift')
        if e['id'] not in plan.get('authorized_object_ids',[]):raise ValueError('object not authorized')
        if old.get('owner')!='route-owned':raise ValueError('non-route geometry requires a separate workflow')
        for k in ('id','owner','net','kind'):
            if new.get(k)!=old.get(k):raise ValueError('identity/net/owner/kind change prohibited')
        after[e['id']]=new
    groups=snapshot.get('symmetry_groups');scope=snapshot.get('scope_by_object')
    if not isinstance(groups,list) or not isinstance(scope,dict) or set(scope)!=set(objects):raise ValueError('complete symmetry/exception inventory required')
    covered=set();group_ids=[g['id'] for g in groups]
    if len(group_ids)!=len(set(group_ids)):raise ValueError('duplicate group ID')
    for g in groups:
        axis=g.get('axis_x_um')
        if not isinstance(axis,(int,float)) or not math.isfinite(axis):raise ValueError('invalid fixed axis')
        pairs=g.get('object_pairs',[])
        seen=set()
        for left,right in pairs:
            if left not in objects or right not in objects:raise ValueError('unknown mate')
            if left in seen or (right!=left and right in seen):raise ValueError('mate map not one-to-one')
            seen.update((left,right));covered.update((left,right))
            if scope[left]!=g['id'] or scope[right]!=g['id']:raise ValueError('group/scope mismatch')
            if (left in ids)!=(right in ids):raise ValueError('one-sided repair rejected: '+g['id'])
            if g.get('mode')=='self' and after[left]['net']!=after[right]['net']:raise ValueError('self group mixes nets')
            if g.get('mode')=='pair':
                nets=g.get('net_pair',[])
                if len(nets)!=2 or nets[0]==nets[1] or [after[left]['net'],after[right]['net']]!=nets:raise ValueError('pair net map mismatch')
            elif g.get('mode')!='self':raise ValueError('unsupported group mode')
            if signature(reflected(after[left],axis))!=signature(after[right]):raise ValueError('post-repair metal/cut mirror mismatch: '+g['id'])
        if not pairs:raise ValueError('empty symmetry group')
    exceptions=snapshot.get('exceptions',{})
    for ident in objects:
        if ident in covered:continue
        e=exceptions.get(scope[ident],{})
        if not all(e.get(k) for k in ('reason','approval','boundary')):raise ValueError('unaccounted or unapproved asymmetric scope')
        if ident in ids and scope[ident] not in plan.get('authorized_exceptions',[]):raise ValueError('asymmetric exception edit not authorized')
    return dict(status='GEOMETRY_PLAN_PASS_NOT_DRC',after_objects=[after[o['id']] for o in snapshot['objects']],
                boundary='Rectangle/cut exact-partition reflection only; equivalent polygon repartition is conservatively rejected. Environment, connectivity and PDK remain adapter gates.')

def execute(plan,adapter):
    """Adapter is trusted site code, not model-provided booleans in plan JSON."""
    before=adapter.snapshot(plan['source']);expected=check(before,plan)
    if adapter.exists(plan['target']):raise ValueError('destination exists')
    transaction=adapter.begin_clone(plan['source'],plan['target'])
    committed=False
    try:
        # Clone must be exactly the validated source before editing.
        clone=adapter.read(transaction)
        if clone.get('target')!=plan['target']:raise ValueError('clone target mismatch')
        if clone['objects']!=before['objects'] or clone['symmetry_groups']!=before['symmetry_groups'] or clone['scope_by_object']!=before['scope_by_object']:
            raise ValueError('clone drift')
        for edit in plan['edits']:adapter.apply(transaction,edit)
        actual=adapter.read(transaction)
        if actual.get('target')!=plan['target']:raise ValueError('transaction target drift')
        if actual['objects']!=expected['after_objects']:raise ValueError('unexpected/missing changes in readback')
        for k in ('symmetry_groups','scope_by_object','exceptions'):
            if actual.get(k)!=before.get(k):raise ValueError('symmetry scope drift')
        attest=adapter.verify(transaction,before,actual)
        for k in ('connectivity','pin_access','pdk_geometry','matched_metrics','environment'):
            if attest.get(k)!='PASS':raise ValueError('repair gate failed/unknown: '+k)
        if attest.get('before_sha256')!=digest(before) or attest.get('after_sha256')!=digest(actual):raise ValueError('verification evidence drift')
        if digest(adapter.snapshot(plan['source']))!=digest(before):raise ValueError('source changed before commit')
        adapter.commit(transaction);committed=True
    finally:
        if not committed:adapter.rollback(transaction)
    saved=adapter.snapshot(plan['target'])
    if saved.get('target')!=plan['target']:raise ValueError('saved target mismatch')
    for k in ('symmetry_groups','scope_by_object','exceptions'):
        if saved.get(k)!=before.get(k):raise ValueError('saved symmetry scope drift')
    if saved['objects']!=expected['after_objects']:raise ValueError('saved readback drift; retain destination for diagnosis')
    if digest(adapter.snapshot(plan['source']))!=digest(before):raise ValueError('source changed during repair')
    drc=adapter.rerun_drc(plan['target'])
    if drc.get('policy_sha256')!=plan.get('drc_policy_sha256') or not plan.get('drc_policy_sha256'):
        raise ValueError('DRC policy changed; no closure comparison')
    if drc.get('saved_snapshot_sha256')!=digest(saved):raise ValueError('DRC revision drift')
    closed=drc.get('status')=='CLEAN' and drc.get('provenance_status')=='BOUND_ADAPTER_ATTESTED' and not drc.get('integrity_issues')
    return dict(status='CLEAN' if closed else 'SAVED_NOT_CLOSED',drc=drc,saved_snapshot_sha256=digest(saved),verification=attest)
