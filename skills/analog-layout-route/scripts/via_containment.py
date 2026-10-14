"""Exact rectangle-union containment; never count a via's own metal as wire.

Callers must supply actual rectilinear wire polygons decomposed into rectangles,
including measured path end extensions. Unsupported geometry stays UNKNOWN.
"""
def subtract_rect(a,b,tol=1e-9):
    x0,y0,x1,y1=a;u0,v0,u1,v1=b
    l,r=max(x0,u0),min(x1,u1);d,t=max(y0,v0),min(y1,v1)
    if r-l<=tol or t-d<=tol:return [a]
    parts=[(x0,y0,l,y1),(r,y0,x1,y1),(l,y0,r,d),(l,t,r,y1)]
    return [p for p in parts if p[2]-p[0]>tol and p[3]-p[1]>tol]

def uncovered_rectangles(landing,wires,tol=1e-9):
    remaining=[tuple(landing)]
    for wire in wires:
        remaining=[p for old in remaining for p in subtract_rect(old,wire,tol)]
        if not remaining:break
    return remaining

def check(wires,vias,geometry_verified=True):
    if not geometry_verified:return dict(status='UNKNOWN',reason='Actual wire polygon decomposition or via landing geometry missing')
    if any(w.get('role')=='via-landing' for w in wires):raise ValueError('Via metal cannot be included in the wire union')
    records=[]
    for via in vias:
        for f in via['metal_figures']:
            region=[w['bbox_um'] for w in wires if w['net']==via['net'] and w['layer']==f['layer']]
            missing=uncovered_rectangles(f['bbox_um'],region)
            records.append(dict(via_id=via['id'],net=via['net'],layer=f['layer'],landing_bbox_um=f['bbox_um'],uncovered_rectangles_um=missing,pass_=not missing))
    return dict(status='PASS' if all(r['pass_'] for r in records) else 'FAIL',records=records,failed_layers=sum(not r['pass_'] for r in records))
