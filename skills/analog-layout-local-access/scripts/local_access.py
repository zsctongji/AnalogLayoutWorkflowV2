"""Rectangle local-access compiler. Physical signoff is deliberately separate."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def inside(a,b):return all(a[0][k]>=b[0][k]-1e-9 and a[1][k]<=b[1][k]+1e-9 for k in (0,1))
def positive(a,b):return all(min(a[1][k],b[1][k])-max(a[0][k],b[0][k])>1e-9 for k in (0,1))
def gap(a,b):return math.hypot(*[max(a[0][k]-b[1][k],b[0][k]-a[1][k],0) for k in (0,1)])
def expand(b,e):return [[b[0][k]-e[k] for k in (0,1)],[b[1][k]+e[k] for k in (0,1)]]
def rect(c,size):return [[c[k]-size[k]/2 for k in (0,1)],[c[k]+size[k]/2 for k in (0,1)]]
def mirror(b,a):return [[2*a-b[1][0],b[0][1]],[2*a-b[0][0],b[1][1]]]
def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def point(p):return isinstance(p,list) and len(p)==2 and all(finite(v) for v in p)
def validbox(b):return isinstance(b,list) and len(b)==2 and all(point(p) for p in b) and all(b[0][k]<b[1][k] for k in (0,1))
def compile_request(req,base):
    if req.get('schema')!='analog-layout-local-access.request/v1':raise ValueError('Unsupported schema')
    for k in ('snapshot_sha256','pdk_fingerprint'):
        if not req.get(k):raise ValueError('Missing '+k)
    hashes=set()
    for e in req.get('evidence',[]):
        p=Path(e['path']);p=p if p.is_absolute() else Path(base)/p
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=e['sha256']:raise ValueError('Stale evidence '+str(p))
        hashes.add(e['sha256'])
    if req['snapshot_sha256'] not in hashes or req['pdk_fingerprint'] not in hashes:raise ValueError('Snapshot/PDK files not bound')
    grid=req['grid_um'];limit=req['max_escape_um']
    if not math.isfinite(grid) or grid<=0 or not math.isfinite(limit) or limit<=0:raise ValueError('Grid/escape budget invalid')
    islands={i['id']:i for i in req['islands']}
    if len(islands)!=len(req['islands']):raise ValueError('Duplicate island')
    wants={r['island_id']:r for r in req['requests']}
    if len(wants)!=len(req['requests']) or set(wants)!=set(islands):raise ValueError('Every island requires exactly one request')
    obstacles=req.get('obstacles',[])
    if len({o['id'] for o in obstacles})!=len(obstacles) or any(not o.get('id') or not o.get('net') or not o.get('layer') or not validbox(o.get('bbox_um')) for o in obstacles):raise ValueError('Incomplete/duplicate obstacle geometry')
    records=[];objects=[];blockers=[]
    for ident,i in islands.items():
        if i['terminal'] not in ('G','S','D','B') or not i.get('net') or not validbox(i['bbox_um']):raise ValueError('Unresolved/unsupported terminal '+ident)
        r=wants[ident];recipe=req['recipes'][r['recipe']]
        if recipe['qualification_sha256'] not in hashes:raise ValueError('Recipe qualification not bound')
        if i['layer']!=recipe['lower_layer']:raise ValueError('Wrong contact lower layer')
        for key in ('cut_size_um','lower_enclosure_um','upper_enclosure_um'):
            if len(recipe[key])!=2 or any(not math.isfinite(v) or v<0 for v in recipe[key]) or (key=='cut_size_um' and min(recipe[key])<=0):raise ValueError('Invalid recipe geometry')
        width=recipe['width_um']
        if not math.isfinite(width) or width<=0:raise ValueError('Invalid width')
        for key in ('spacing_um','cut_spacing_um'):
            if not finite(recipe.get(key)) or recipe[key]<0:raise ValueError('Invalid spacing')
        xy=r['contact_xy_um'];end=r['escape_xy_um'];reuse=r.get('reuse')
        if not point(xy) or not point(end):raise ValueError('Invalid contact/escape coordinate')
        cut=rect(xy,recipe['cut_size_um']);landing=expand(cut,recipe['upper_enclosure_um'])
        if reuse:
            if not validbox(reuse.get('cut_bbox_um')) or not validbox(reuse.get('landing_bbox_um')) or not reuse.get('contact_id') or not reuse.get('landing_id'):raise ValueError('Invalid reused contact/landing')
            if reuse['continuity_evidence_sha256'] not in hashes or [reuse['lower_layer'],reuse['upper_layer'],reuse['cut_layer']]!=[recipe['lower_layer'],recipe['upper_layer'],recipe['cut_layer']]:raise ValueError('Unbound/wrong reused contact')
            cut=reuse['cut_bbox_um'];landing=reuse['landing_bbox_um']
            if not inside(rect(xy,[grid,grid]),landing):raise ValueError('Escape center outside existing landing')
        if not inside(expand(cut,recipe['lower_enclosure_um']),i['bbox_um']):blockers.append(ident+': lower enclosure')
        if not inside(expand(cut,recipe['upper_enclosure_um']),landing):blockers.append(ident+': upper enclosure')
        if xy[0]!=end[0] and xy[1]!=end[1]:blockers.append(ident+': non-Manhattan local escape')
        length=abs(xy[0]-end[0])+abs(xy[1]-end[1])
        if length>limit+1e-9:blockers.append(ident+': excessive local escape')
        escape=[[min(xy[k],end[k])-width/2 for k in (0,1)],[max(xy[k],end[k])+width/2 for k in (0,1)]]
        reused_escape=False
        if reuse and reuse.get('existing_escape'):
            old=reuse['existing_escape']
            if not old.get('id') or not validbox(old.get('bbox_um')) or old.get('layer')!=recipe['upper_layer'] or old.get('net')!=i['net']:raise ValueError('Invalid existing escape identity')
            if inside(escape,old['bbox_um']):reused_escape=True
            else:blockers.append(ident+': existing escape does not cover request')
        local=[] if reused_escape else [dict(id=ident+':escape',net=i['net'],layer=recipe['upper_layer'],bbox_um=escape,owner=i['module'],kind='metal')]
        if not reuse:local += [dict(id=ident+':contact',net=i['net'],layer=recipe['cut_layer'],bbox_um=cut,owner=i['module'],kind='cut'),dict(id=ident+':landing',net=i['net'],layer=recipe['upper_layer'],bbox_um=landing,owner=i['module'],kind='metal')]
        for obj in local:
            if any(abs(v/grid-round(v/grid))>1e-6 for p in obj['bbox_um'] for v in p):blockers.append(obj['id']+': off-grid')
        objects+=local
        records.append(dict(island_id=ident,instance=i['instance'],terminal=i['terminal'],net=i['net'],cut=cut,landing=landing,escape=escape,recipe=r['recipe'],reused=bool(reuse),reused_escape=reused_escape,length_um=length))
    by={r['island_id']:r for r in records};scope=set()
    for pair in req.get('pairs',[]):
        l,r=pair['left'],pair['right']
        if l not in by or r not in by or (l in scope or r in scope):raise ValueError('Invalid/duplicate symmetry scope')
        scope.update([l,r]);a=pair['axis_x_um']
        if pair['net_relation'] not in ('pair','self'):raise ValueError('Unknown net relation')
        if (by[l]['net']==by[r]['net'])!=(pair['net_relation']=='self'):raise ValueError('Wrong symmetry net mapping')
        for k in ('cut','landing','escape'):
            m=mirror(by[l][k],a)
            if any(abs(m[j][n]-by[r][k][j][n])>1e-9 for j in (0,1) for n in (0,1)):blockers.append(l+'/'+r+': '+k+' not mirrored')
        if by[l]['recipe']!=by[r]['recipe']:blockers.append(l+'/'+r+': different recipes')
    if set(islands)-scope-set(req.get('exceptions',{})):raise ValueError('Unclassified symmetry islands')
    if any(not v for v in req.get('exceptions',{}).values()):raise ValueError('Empty exception')
    if {o['id'] for o in objects}&{o['id'] for o in obstacles}:raise ValueError('Generated/obstacle ID alias')
    checks=objects+obstacles
    for n,obj in enumerate(objects):
        rule=req['recipes'][by[obj['id'].rsplit(':',1)[0]]['recipe']]
        spacing=rule['cut_spacing_um'] if obj['kind']=='cut' else rule['spacing_um']
        for other in checks:
            if obj['id']==other['id'] or obj['layer']!=other['layer']:continue
            if obj['kind']=='cut' or obj['net']!=other['net']:
                if gap(obj['bbox_um'],other['bbox_um'])<spacing-1e-9:blockers.append(obj['id']+': spacing to '+other['id'])
    if req.get('conditional_rules_status')!='PASS':blockers.append('Conditional/site rules UNKNOWN')
    return dict(schema='analog-layout-local-access.plan/v1',target=req['target'],request_sha256=digest(req),snapshot_sha256=req['snapshot_sha256'],pdk_fingerprint=req['pdk_fingerprint'],status='SELECTED_RULES_PASS' if not blockers else 'BLOCKED',records=records,objects=objects,evidence=req['evidence'],blockers=sorted(set(blockers)),signoff=False)
def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--out',required=True);a=p.parse_args();src=Path(a.request);out=Path(a.out)
    if out.exists():raise ValueError('Output exists')
    result=compile_request(json.loads(src.read_text(encoding='utf-8')),src.parent);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(result['status'])
if __name__=='__main__':main()
