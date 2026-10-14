"""Explicit hierarchy placement mapping, never guessed from opaque Calibre CN fields."""
import json,math,hashlib,argparse

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def finite(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def transform_point(p,t):
    if len(t)!=6 or not all(finite(x) for x in t):raise ValueError('invalid affine transform')
    a,b,c,d,x,y=t
    if (a*a+c*c,b*b+d*d,a*b+c*d,abs(a*d-b*c))!=(1,1,0,1):
        raise ValueError('only explicit orthogonal unit transforms supported')
    return [a*p[0]+b*p[1]+x,c*p[0]+d*p[1]+y]

def overlap(a,b):return a[0][0]<=b[1][0] and b[0][0]<=a[1][0] and a[0][1]<=b[1][1] and b[0][1]<=a[1][1]

def locate(report,placements,snapshot):
    if placements.get('report_sha256')!=digest(report) or placements.get('snapshot_sha256')!=digest(snapshot):
        raise ValueError('marker/geometry binding mismatch')
    if placements.get('target')!=snapshot.get('target'):raise ValueError('target mismatch')
    if snapshot['target'].get('cell')!=report.get('primary_cell'):raise ValueError('primary cell mismatch')
    dbu=placements.get('dbu_per_um')
    if not finite(dbu) or dbu<=0:raise ValueError('missing/invalid DBU scale')
    if (report.get('header') or {}).get('dbu_per_um')!=dbu:raise ValueError('result header units mismatch')
    ids=[o['id'] for o in snapshot['objects']]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate live object IDs')
    for obj in snapshot['objects']:
        b=obj.get('bbox_um')
        if not isinstance(b,list) or len(b)!=2 or any(not isinstance(p,list) or len(p)!=2 for p in b):raise ValueError('invalid live bbox')
        if not all(finite(x) for p in b for x in p) or any(b[0][k]>b[1][k] for k in (0,1)):raise ValueError('invalid live bbox coordinates')
    if not placements.get('transform_evidence'):raise ValueError('adapter transform evidence required')
    output=[];used=set()
    for m in report['markers']:
        key=digest(m)
        entries=[p for p in placements.get('placements',[]) if p.get('marker_sha256')==key]
        if not entries:
            output.append(dict(marker_sha256=key,status='UNRESOLVED',reason='no verified occurrence mapping'));continue
        for p in entries:
            path=p.get('instance_path');chain=p.get('leaf_to_top_db_units')
            if not isinstance(path,list) or not isinstance(chain,list) or len(path)!=len(chain):
                raise ValueError('full instance path and one transform per level required')
            if not all(isinstance(x,str) and x for x in path):raise ValueError('invalid instance path')
            if not path and m.get('cell') not in (None,report['primary_cell']):raise ValueError('child marker needs hierarchy mapping')
            identity=(key,tuple(path))
            if identity in used:raise ValueError('duplicate marker occurrence')
            used.add(identity)
            points=[]
            for v in m['polygon_db_units']:
                for t in chain:v=transform_point(v,t)
                points.append([x/dbu for x in v])
            bbox=[[min(v[k] for v in points) for k in (0,1)],[max(v[k] for v in points) for k in (0,1)]]
            candidates=[]
            for obj in snapshot['objects']:
                # Bbox overlap identifies candidates, not causal ownership.
                if overlap(bbox,obj['bbox_um']):
                    candidates.append(dict(id=obj['id'],owner=obj.get('owner','unknown'),net=obj.get('net'),layer=obj.get('layer'),kind=obj.get('kind'),provenance=obj.get('provenance')))
            output.append(dict(marker_sha256=key,instance_path=path,status='LOCATED_CAUSE_UNCLASSIFIED',polygon_top_um=points,bbox_top_um=bbox,candidates=candidates))
    known={digest(m) for m in report['markers']}
    if any(p.get('marker_sha256') not in known for p in placements.get('placements',[])):raise ValueError('placement for unknown marker')
    return dict(schema='analog-layout-drc.marker-map/v1',report_sha256=digest(report),snapshot_sha256=digest(snapshot),occurrences=output,
                boundary='Exact explicit orthogonal transforms; bbox candidate query only. No automatic cause assignment or authorization.')

def main():
    a=argparse.ArgumentParser();a.add_argument('--report',required=True);a.add_argument('--placements',required=True);a.add_argument('--snapshot',required=True);a.add_argument('--out',required=True);x=a.parse_args()
    from pathlib import Path
    paths=[Path(getattr(x,k)).resolve() for k in ('report','placements','snapshot')];out=Path(x.out).resolve()
    if out in paths or out.exists():raise ValueError('output collision')
    result=locate(*(json.loads(p.read_text(encoding='utf-8')) for p in paths))
    with out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
if __name__=='__main__':main()
