"""Offline, translation-only macro search. Python standard library only."""
import argparse
import copy
import hashlib
import html
import itertools
import json
import math
from pathlib import Path

EPS = 1e-7


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def union(boxes):
    return [[min(b[0][k] for b in boxes) for k in (0,1)],
            [max(b[1][k] for b in boxes) for k in (0,1)]]


def box_ok(b):
    return (isinstance(b,list) and len(b)==2 and all(isinstance(p,list) and len(p)==2 for p in b)
            and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for p in b for v in p)
            and all(b[1][k]>b[0][k] for k in (0,1)))


def shifted(b,d):
    return [[round(p[k]+d[k],9) for k in (0,1)] for p in b]


def check_keys(obj, allowed):
    if set(obj)-set(allowed):
        raise ValueError('Unsupported keys: '+str(sorted(set(obj)-set(allowed))))


def prepare(snapshot, request):
    digest(snapshot); digest(request)  # Reject non-finite JSON numbers.
    check_keys(request, ['schema','snapshot_sha256','bounds_um','pair_gaps','align','mirror','order','locked','nets','search','objective_priority'])
    if snapshot.get('schema')!='analog-layout-macro-opt.snapshot/v1' or request.get('schema')!='analog-layout-macro-opt.request/v1':
        raise ValueError('Unsupported schema')
    if request['snapshot_sha256']!=digest(snapshot): raise ValueError('Stale snapshot hash')
    if not snapshot.get('source') or not snapshot.get('evidence'): raise ValueError('Missing source/evidence')
    if snapshot.get('cross_macro_connections') != []: raise ValueError('Cross-macro connections require adapter review')
    g=snapshot['grid_um']
    if not isinstance(g,(float,int)) or g<=0: raise ValueError('Invalid grid')
    macros={m['id']:m for m in snapshot['macros']}
    if not macros or len(macros)!=len(snapshot['macros']): raise ValueError('Duplicate/empty macros')
    objects={o['id']:o for o in snapshot['objects']}
    if not objects or len(objects)!=len(snapshot['objects']): raise ValueError('Duplicate/empty objects')
    if len(snapshot['source_object_ids'])!=len(set(snapshot['source_object_ids'])) or set(objects)!=set(snapshot['source_object_ids']):
        raise ValueError('Incomplete source object coverage')
    boxes={}
    for o in objects.values():
        if o.get('macro') not in macros or not box_ok(o.get('bbox_um')) or not o.get('payload_sha256'):
            raise ValueError('Invalid or unowned object '+o['id'])
    for name in macros:
        members=[o['bbox_um'] for o in objects.values() if o['macro']==name]
        if not members: raise ValueError('Empty macro '+name)
        boxes[name]=union(members)
    for relation in snapshot.get('protected_sets',[]):
        ids=relation['object_ids']
        if not ids or any(i not in objects for i in ids) or len({objects[i]['macro'] for i in ids})!=1:
            raise ValueError('Protected ring/shared structure split across macros')
    if not box_ok(request['bounds_um']): raise ValueError('Invalid search bounds')
    gaps={}
    for p in request['pair_gaps']:
        check_keys(p,['macros','x_um','y_um','basis'])
        key=frozenset(p['macros'])
        if len(p['macros'])!=2 or len(key)!=2 or not key<=set(macros) or key in gaps or not p.get('basis'):
            raise ValueError('Invalid clearance provenance/pair')
        if min(p['x_um'],p['y_um'])<0: raise ValueError('Negative clearance')
        gaps[key]=[p['x_um'],p['y_um']]
    if set(gaps)!={frozenset(p) for p in itertools.combinations(macros,2)}:
        raise ValueError('Missing pair clearance; never infer zero')
    for a in request.get('align',[]):
        check_keys(a,['axis','macros'])
        if a['axis'] not in ('x','y') or not a['macros'] or not set(a['macros'])<=set(macros): raise ValueError('Invalid alignment')
    for p in request.get('mirror',[]):
        check_keys(p,['axis','coordinate_um','pairs'])
        if p['axis'] not in ('x','y') or not math.isfinite(p['coordinate_um']): raise ValueError('Invalid mirror axis')
        for pair in p['pairs']:
            if len(pair)!=2 or pair[0]==pair[1] or not set(pair)<=set(macros): raise ValueError('Invalid mirror pair')
    for o in request.get('order',[]):
        check_keys(o,['axis','before','after','gap_um'])
        if o['axis'] not in ('x','y') or o['before']==o['after'] or not {o['before'],o['after']}<=set(macros) or o['gap_um']<0:
            raise ValueError('Invalid order')
    if not set(request.get('locked',[]))<=set(macros): raise ValueError('Unknown lock')
    netids=set()
    for net in request.get('nets',[]):
        check_keys(net,['id','pins','weight','max_hpwl_um'])
        if net['id'] in netids or net.get('weight',1)<0 or not net['pins']: raise ValueError('Invalid net')
        netids.add(net['id'])
        if 'max_hpwl_um' in net and net['max_hpwl_um']<0: raise ValueError('Invalid span bound')
        pinids=set()
        for pin in net['pins']:
            check_keys(pin,['island_id','macro','xy_um'])
            if pin['macro'] not in macros or pin['island_id'] in pinids or len(pin['xy_um'])!=2:
                raise ValueError('Invalid physical pin island')
            pinids.add(pin['island_id'])
    search=request['search']
    check_keys(search,['max_evaluations','max_iterations','beam_width','top_k','step_um'])
    for key in ('max_evaluations','max_iterations','beam_width','top_k'):
        if type(search[key]) is not int or search[key]<1: raise ValueError('Invalid budget')
    if search['step_um']<=0 or abs(search['step_um']/g-round(search['step_um']/g))>EPS:
        raise ValueError('Step must be positive grid multiple')
    return macros,objects,boxes,gaps


def anchor(m,b,k):
    return m.get('anchor_um',[(b[0][i]+b[1][i])/2 for i in (0,1)])[k]-b[0][k]


def components(macros,boxes,request,k):
    """Solve affine coordinate equalities p_j = sign*p_i + offset."""
    graph={n:[] for n in macros}
    def edge(a,b,s,c):
        graph[a].append((b,s,c)); graph[b].append((a,s,-s*c))
    for a in request.get('align',[]):
        if a['axis']=='xy'[k]:
            for n in a['macros'][1:]:
                root=a['macros'][0]
                edge(root,n,1,anchor(macros[root],boxes[root],k)-anchor(macros[n],boxes[n],k))
    for p in request.get('mirror',[]):
        for a,b in p['pairs']:
            aa,ab=anchor(macros[a],boxes[a],k),anchor(macros[b],boxes[b],k)
            if p['axis']=='xy'[k]: edge(a,b,-1,2*p['coordinate_um']-aa-ab)
            else: edge(a,b,1,aa-ab)  # equal orthogonal anchors
    seen=set(); result=[]
    for root in macros:
        if root in seen: continue
        relations={root:(1,0)}; queue=[root]; fixed=[]
        while queue:
            a=queue.pop(); s,c=relations[a]; seen.add(a)
            if a in request.get('locked',[]): fixed.append((boxes[a][0][k]-c)/s)
            for b,t,d in graph[a]:
                proposed=(t*s,t*c+d)
                if b not in relations: relations[b]=proposed; queue.append(b)
                else:
                    bs,bc=relations[b]
                    if bs==proposed[0]:
                        if abs(bc-proposed[1])>EPS: raise ValueError('Conflicting symmetry/alignment')
                    else: fixed.append((proposed[1]-bc)/(bs-proposed[0]))
        if fixed and max(fixed)-min(fixed)>EPS: raise ValueError('Conflicting locks/symmetry')
        result.append({'axis':k,'root':root,'relations':relations,'fixed':fixed[0] if fixed else None})
    return result


def positions(comps,values):
    result={n:[0,0] for c in comps for n in c['relations']}
    for c,value in zip(comps,values):
        for n,(s,o) in c['relations'].items(): result[n][c['axis']]=round(s*value+o,9)
    return result


def evaluate(snapshot,request,boxes,gaps,pos):
    g=snapshot['grid_um']; failures=[]
    delta={n:[round(pos[n][k]-b[0][k],9) for k in (0,1)] for n,b in boxes.items()}
    moved={n:shifted(b,delta[n]) for n,b in boxes.items()}
    bounds=request['bounds_um']
    for n,b in moved.items():
        if any(abs(v/g-round(v/g))>EPS for v in delta[n]): failures.append('OFF_GRID:'+n)
        if any(b[0][k]<bounds[0][k]-EPS or b[1][k]>bounds[1][k]+EPS for k in (0,1)): failures.append('BOUNDS:'+n)
        if n in request.get('locked',[]) and any(abs(v)>EPS for v in delta[n]): failures.append('LOCK:'+n)
    for a,b in itertools.combinations(moved,2):
        gap=gaps[frozenset((a,b))]; ab,bb=moved[a],moved[b]
        if not any(ab[1][k]+gap[k]<=bb[0][k]+EPS or bb[1][k]+gap[k]<=ab[0][k]+EPS for k in (0,1)):
            failures.append('CLEARANCE:'+a+':'+b)
    anchors={m['id']:[pos[m['id']][k]+anchor(m,boxes[m['id']],k) for k in (0,1)] for m in snapshot['macros']}
    for a in request.get('align',[]):
        vals=[anchors[n]['xy'.index(a['axis'])] for n in a['macros']]
        if max(vals)-min(vals)>EPS: failures.append('ALIGN:'+','.join(a['macros']))
    for p in request.get('mirror',[]):
        k='xy'.index(p['axis'])
        for a,b in p['pairs']:
            if abs(anchors[a][k]+anchors[b][k]-2*p['coordinate_um'])>EPS or abs(anchors[a][1-k]-anchors[b][1-k])>EPS:
                failures.append('MIRROR:'+a+':'+b)
    for o in request.get('order',[]):
        k='xy'.index(o['axis'])
        if moved[o['before']][1][k]+o['gap_um']>moved[o['after']][0][k]+EPS: failures.append('ORDER:'+o['before'])
    spans={}; hpwl=0
    for net in request.get('nets',[]):
        points=[[pin['xy_um'][k]+delta[pin['macro']][k] for k in (0,1)] for pin in net['pins']]
        span=sum(max(p[k] for p in points)-min(p[k] for p in points) for k in (0,1))
        spans[net['id']]=round(span,9); hpwl+=span*net.get('weight',1)
        if 'max_hpwl_um' in net and span>net['max_hpwl_um']+EPS: failures.append('PIN_SPAN:'+net['id'])
    b=union(list(moved.values())); w,h=[b[1][k]-b[0][k] for k in (0,1)]; area=w*h
    return {'valid':not failures,'failures':failures,'bbox_um':b,'width_um':w,'height_um':h,'area_um2':round(area,9),
            'aspect_ratio':w/h,'macro_envelope_occupancy_proxy':sum((v[1][0]-v[0][0])*(v[1][1]-v[0][1]) for v in boxes.values())/area,
            'weighted_hpwl_um':round(hpwl,9) if request.get('nets') else None,'net_hpwl_um':spans,'deltas_um':delta}


def ordered_compaction_seeds(snapshot,request,boxes,gaps,comps,seed):
    """Propose an entire ordered stack; validate later, never relax constraints."""
    proposals=[];grid=snapshot['grid_um']
    for k in (0,1):
        edges=[e for e in request.get('order',[]) if e['axis']=='xy'[k]]
        successors={n:set() for n in boxes};indegree={n:0 for n in boxes}
        for e in edges:
            if e['after'] not in successors[e['before']]:
                successors[e['before']].add(e['after']);indegree[e['after']]+=1
        order=[];ready=sorted(n for n in boxes if indegree[n]==0)
        while len(ready)==1:
            n=ready.pop();order.append(n)
            for other in sorted(successors[n]):
                indegree[other]-=1
                if indegree[other]==0:ready.append(other)
            ready.sort()
        axiscomps={c['root']:(j,c) for j,c in enumerate(comps) if c['axis']==k}
        if len(order)!=len(boxes) or len(axiscomps)!=len(boxes):continue
        if any(len(c['relations'])!=1 for _,c in axiscomps.values()):continue
        for reverse in (False,True):
            trial=list(seed);placed={};ok=True
            for n in reversed(order) if reverse else order:
                j,c=axiscomps[n];width=boxes[n][1][k]-boxes[n][0][k]
                limit=request['bounds_um'][1 if reverse else 0][k]-(width if reverse else 0)
                for other,value in placed.items():
                    sep=gaps[frozenset((n,other))][k]
                    before,after=(n,other) if reverse else (other,n)
                    sep=max([sep]+[e['gap_um'] for e in edges if e['before']==before and e['after']==after])
                    bound=value-width-sep if reverse else value+(boxes[other][1][k]-boxes[other][0][k])+sep
                    limit=min(limit,bound) if reverse else max(limit,bound)
                phase=boxes[n][0][k]
                value=round(phase+(math.floor((limit-phase)/grid+EPS) if reverse else math.ceil((limit-phase)/grid-EPS))*grid,9)
                if c['fixed'] is not None:
                    value=c['fixed']
                    if (reverse and value>limit+EPS) or (not reverse and value<limit-EPS):ok=False;break
                elif not placed:
                    value=min(value,phase) if reverse else max(value,phase)
                placed[n]=value;trial[j]=value
            if ok:proposals.append(tuple(trial))
    return sorted(set(proposals))


def gap_audit(request,boxes,gaps,pos):
    """Conservative ordered-axis envelope slack, not routing capacity."""
    records=[]
    for e in request.get('order',[]):
        k='xy'.index(e['axis']);a=e['before'];b=e['after']
        actual=pos[b][k]-pos[a][k]-(boxes[a][1][k]-boxes[a][0][k])
        required=max(e['gap_um'],gaps[frozenset((a,b))][k])
        records.append({'before':a,'after':b,'axis':e['axis'],'actual_gap_um':round(actual,9),
                        'required_axis_gap_um':required,'axis_slack_um':round(actual-required,9)})
    return records


def optimize(snapshot,request):
    macros,objects,boxes,gaps=prepare(snapshot,request)
    comps=components(macros,boxes,request,0)+components(macros,boxes,request,1)
    g=snapshot['grid_um']; search=request['search']; bounds=request['bounds_um']
    seed=tuple(c['fixed'] if c['fixed'] is not None else boxes[c['root']][0][c['axis']] for c in comps)
    basepos={n:b[0] for n,b in boxes.items()}
    baseline=evaluate(snapshot,request,boxes,gaps,basepos)
    candidates={}; seen=set(); evaluations=1; rejects={}
    def remember(pos,ev):
        if ev['valid']:
            key=digest(pos)
            candidates[key]={'id':key[:16],'positions_um':pos,'metrics':ev}
        else:
            for f in ev['failures']: rejects[f.split(':')[0]]=rejects.get(f.split(':')[0],0)+1
    remember(basepos,baseline)
    objective=request.get('objective_priority',['area_um2','weighted_hpwl_um'])
    if not objective or len(set(objective))!=len(objective) or set(objective)-{'area_um2','weighted_hpwl_um','aspect_ratio'}:
        raise ValueError('Unsupported objective priority')
    def rank(ev): return (len(ev['failures']),)+tuple(ev[k] or 0 for k in objective)
    def score(v):
        nonlocal evaluations
        seen.add(v); evaluations+=1
        pos=positions(comps,v); ev=evaluate(snapshot,request,boxes,gaps,pos); remember(pos,ev)
        return rank(ev)
    beam=[seed]; stop='ITERATION_BUDGET'
    if evaluations<search['max_evaluations']: score(seed)
    compact_scores={}
    for trial in ordered_compaction_seeds(snapshot,request,boxes,gaps,comps,seed):
        if trial not in seen and evaluations<search['max_evaluations']:compact_scores[trial]=score(trial)
    beam=sorted(set(beam)|set(compact_scores),key=lambda v:(rank(evaluate(snapshot,request,boxes,gaps,positions(comps,v))),v))[:search['beam_width']]
    for iteration in range(search['max_iterations']):
        pool={}
        for state in beam:
            pos=positions(comps,state)
            pool[state]=rank(evaluate(snapshot,request,boxes,gaps,pos))
            for j,c in enumerate(comps):
                if c['fixed'] is not None: continue
                k=c['axis']; phase=boxes[c['root']][0][k]
                targets={state[j]-search['step_um'],state[j]+search['step_um']}
                for n,(s,o) in c['relations'].items():
                    width=boxes[n][1][k]-boxes[n][0][k]
                    targets.update((v-o)/s for v in (bounds[0][k],bounds[1][k]-width))
                    for other in boxes:
                        if other in c['relations']: continue
                        ow=boxes[other][1][k]-boxes[other][0][k]; gap=gaps[frozenset((n,other))][k]
                        targets.update((v-o)/s for v in (pos[other][k]-gap-width,pos[other][k]+ow+gap,pos[other][k]))
                for target in sorted(targets):
                    trial=list(state); trial[j]=round(phase+round((target-phase)/g)*g,9); trial=tuple(trial)
                    if trial in seen: continue
                    if evaluations>=search['max_evaluations']: break
                    pool[trial]=score(trial)
                if evaluations>=search['max_evaluations']: break
            if evaluations>=search['max_evaluations']: break
        newbeam=sorted(pool,key=lambda v:(pool[v],v))[:search['beam_width']]
        if evaluations>=search['max_evaluations']: stop='EVALUATION_BUDGET'; break
        if newbeam==beam: stop='NO_NEW_BETTER_BEAM'; break
        beam=newbeam
    selected=sorted(candidates.values(),key=lambda c:(rank(c['metrics']),c['id']))[:search['top_k']]
    for c in selected:
        c['object_moves']=[{'object_id':o['id'],'macro':o['macro'],'delta_um':c['metrics']['deltas_um'][o['macro']],
                            'payload_sha256':o['payload_sha256']} for o in snapshot['objects']]
        c['area_delta_um2']=round(c['metrics']['area_um2']-baseline['area_um2'],9)
        c['ordered_gap_audit']=gap_audit(request,boxes,gaps,c['positions_um'])
    return {'schema':'analog-layout-macro-opt.candidates/v1','status':'CANDIDATES_FOR_REVIEW' if selected else 'NO_FEASIBLE_CANDIDATE_IN_BUDGET',
            'snapshot_sha256':digest(snapshot),'request_sha256':digest(request),'baseline':baseline,'candidates':selected,
            'evaluations':evaluations,'stop_reason':stop,'rejection_counts':rejects,'materialized':False,
            'ordered_compaction_seeds_evaluated':len(compact_scores),'baseline_ordered_gap_audit':gap_audit(request,boxes,gaps,basepos),
            'symmetry_scope':'Declared macro anchors only; internal geometry frozen, not proven mirrored or electrically matched',
            'limits':['Bounded heuristic, not global optimum','Rectangular envelope/HPWL proxies, not routing feasibility','No DRC/LVS/PEX or database operations']}


def verify_translation(source,target,candidate):
    """Stable normalized IDs required; source and target identities may differ."""
    src={o['id']:o for o in source['objects']}; dst={o['id']:o for o in target['objects']}
    failures=[]
    if len(src)!=len(source['objects']) or len(dst)!=len(target['objects']) or set(src)!=set(dst):
        return {'valid':False,'failures':['OBJECT_IDENTITY_OR_COUNT']}
    moves=candidate['object_moves']; byid={m['object_id']:m for m in moves}
    if len(byid)!=len(moves) or set(byid)!=set(src): return {'valid':False,'failures':['MOVE_COVERAGE']}
    macro_delta={}
    for name,a in src.items():
        b=dst[name]; move=byid[name]; d=move['delta_um']
        if move['macro']!=a['macro'] or (a['macro'] in macro_delta and macro_delta[a['macro']]!=d): failures.append('NONRIGID:'+name)
        macro_delta[a['macro']]=d
        if b['macro']!=a['macro'] or b['payload_sha256']!=a['payload_sha256'] or move['payload_sha256']!=a['payload_sha256']:
            failures.append('CONTENT:'+name)
        expected=shifted(a['bbox_um'],d)
        if any(abs(expected[i][k]-b['bbox_um'][i][k])>EPS for i in (0,1) for k in (0,1)): failures.append('GEOMETRY:'+name)
    return {'valid':not failures,'failures':failures,'scope':'Normalized geometry/payload checks only; independently extracted hashes required'}


def preview(snapshot,candidate):
    objects=snapshot['objects']; parts=[]
    for m in snapshot['macros']:
        b=union([o['bbox_um'] for o in objects if o['macro']==m['id']]); b=shifted(b,candidate['metrics']['deltas_um'][m['id']])
        x,y=b[0]; w,h=[b[1][k]-b[0][k] for k in (0,1)]
        parts.append(f'<rect x="{x}" y="{-y-h}" width="{w}" height="{h}" fill="#deebf7" stroke="#245" stroke-width="0.15"/><text x="{x+w/2}" y="{-y-h/2}" font-size="1.5" text-anchor="middle">{html.escape(m["id"])}</text>')
    b=candidate['metrics']['bbox_um']; w,h=[b[1][k]-b[0][k] for k in (0,1)]
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{b[0][0]-2} {-b[1][1]-2} {w+4} {h+4}">'+''.join(parts)+'</svg>'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','request','out'): parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists(): raise ValueError('Output directory exists; choose a new run')
    s=json.loads(args.snapshot.read_text(encoding='utf-8')); r=json.loads(args.request.read_text(encoding='utf-8'))
    result=optimize(s,r)
    args.out.mkdir(parents=True)
    (args.out/'candidates.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for i,c in enumerate(result['candidates']):
        (args.out/f'candidate-{i+1}.svg').write_text(preview(s,c),encoding='utf-8')
    print(json.dumps({'status':result['status'],'evaluations':result['evaluations'],'candidates':len(result['candidates'])}))


if __name__=='__main__': main()
