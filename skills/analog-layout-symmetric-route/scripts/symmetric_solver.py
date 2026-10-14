#!/usr/bin/env python3
"""Bounded joint mirror routing. Offline candidates only; no OA or signoff calls."""
from pathlib import Path
import argparse, copy, importlib.util, itertools, json, math, sys

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
from symmetric_geometry import SolverError, Geometry, EPS, number, reflected, wire, via_objects
from symmetric_search import Budget, JointGraph, grow_tree, nodes_on_tree

def sibling(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

PLANNER=sibling('joint_route_planner',HERE.parents[1]/'analog-layout-route/scripts/route_planner.py')
MIRROR=sibling('joint_mirror_check',HERE/'mirror_spec.py')
COMPACT=sibling('joint_route_compact',HERE.parents[1]/'analog-layout-route/scripts/compact_route_spec.py')
REQUEST_SCHEMA='analog-layout-symmetric-route.solve-request/v1'
BACKEND='joint-mirror-manhattan/v1'

def finite(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise SolverError('INVALID_INPUT',label+' must be finite')
    return float(value)

def prepare(profile,access,obstacles,request):
    if request.get('schema')!=REQUEST_SCHEMA:raise SolverError('INVALID_INPUT','Unsupported joint solve-request schema')
    allowed={'schema','target','sources','axis','nets','groups','metal_levels','cut_rules','cross_cut_rules','via_mirror_evidence','local_access','search','costs','matching'}
    if set(request)-allowed:raise SolverError('INVALID_INPUT','Unsupported solve-request fields: '+str(sorted(set(request)-allowed)))
    expected={'profile_fingerprint':profile.get('fingerprint',{}).get('value'),
              'terminal_access_sha256':PLANNER.ROUTE.digest(access),'obstacles_sha256':PLANNER.ROUTE.digest(obstacles)}
    if request.get('sources')!=expected:raise SolverError('SOURCE_DRIFT','Exact profile/access/obstacle binding required')
    PLANNER.validate_sources(profile,access,obstacles,{**request,'schema':PLANNER.REQUEST_SCHEMA})
    if access.get('schema')!=PLANNER.ROUTE.ACCESS_SCHEMA or not profile.get('validation',{}).get('structurally_valid'):
        raise SolverError('INVALID_INPUT','Validated profile and terminal-access schemas required')
    axis=request.get('axis',{})
    if set(axis)!={'coordinate','value_um'} or axis['coordinate'] not in ('x','y'):
        raise SolverError('INVALID_AXIS','One fixed x or y mirror axis required')
    value=finite(axis['value_um'],'axis');grid=profile['manufacturing_grid_um']
    if abs(2*value/grid-round(2*value/grid))>1e-6:raise SolverError('AXIS_GRID_CONFLICT','Reflection must preserve manufacturing grid')
    g=Geometry(PLANNER,profile,obstacles,request);pins={};by_net={}
    for instance in access.get('instances',[]):
        for terminal,data in instance.get('terminals',{}).items():
            net=data.get('net')
            if not isinstance(net,str) or not net:raise SolverError('INVALID_INPUT','Every terminal needs its electrical net')
            for island in PLANNER.terminal_islands(instance['name'],terminal,data):
                ident=island['id']
                if ident in pins:raise SolverError('INVALID_MAPPING','Duplicate physical island '+ident)
                pin={'instance':instance['name'],'terminal':terminal,'pin_island_id':ident,'net':net,'island':island}
                pins[ident]=pin;by_net.setdefault(net,set()).add(ident)
    nets={}
    for raw in request.get('nets',[]):
        if set(raw)-{'net','net_class','layers','widths_um','terminals','max_detour_ratio','max_bends','max_bbox_excursion_um','width_basis','terminal_escape'}:
            raise SolverError('INVALID_INPUT','Unsupported strict network policy field')
        net=raw['net']
        if net in nets:raise SolverError('INVALID_MAPPING','Duplicate network policy '+net)
        layers=raw.get('layers',[])
        if not layers or len(set(layers))!=len(layers) or not set(layers)<=set(g.minimum):
            raise SolverError('INVALID_INPUT','Explicit valid allowed layer stack required for '+net)
        if raw.get('net_class') not in PLANNER.NET_CLASSES:raise SolverError('INVALID_INPUT','Explicit valid net_class required')
        if raw['net_class'] in ('power','ground','high_current') and not str(raw.get('width_basis','')).strip():
            raise SolverError('WIDTH_BASIS_REQUIRED','Power width requires current/IR/EM analysis basis')
        if raw['net_class'] in ('sensitive','high_impedance','differential','matched','feedback') and not any(raw.get(k) is not None for k in ('max_detour_ratio','max_bbox_excursion_um')):
            raise SolverError('DIRECTNESS_REQUIRED','Analog critical net requires an explicit directness limit')
        for key in ('max_detour_ratio','max_bends','max_bbox_excursion_um'):
            if key in raw:number(raw[key],key)
        if 'max_bends' in raw and (isinstance(raw['max_bends'],bool) or not isinstance(raw['max_bends'],int)):
            raise SolverError('INVALID_INPUT','max_bends must be a nonnegative integer')
        widths=raw.get('widths_um',{})
        if set(widths)!=set(layers):raise SolverError('INVALID_INPUT','Explicit width required on each allowed layer')
        for layer,width in widths.items():
            number(width,'width',True)
            if width+EPS<g.minimum[layer] or abs(width/grid-round(width/grid))>1e-6:
                raise SolverError('INVALID_WIDTH','Width must meet minimum and manufacturing grid')
        ids=[t.get('pin_island_id') for t in raw.get('terminals',[])]
        if set(ids)!=by_net.get(net) or len(ids)!=len(set(ids)):
            raise SolverError('INVALID_MAPPING','Network request must cover every physical island exactly: '+net)
        for t in raw['terminals']:
            pin=pins[t['pin_island_id']]
            if (t.get('instance'),t.get('terminal'))!=(pin['instance'],pin['terminal']):
                raise SolverError('INVALID_MAPPING','Island identity differs from access evidence')
        nets[net]=copy.deepcopy(raw)
        for ident in ids:
            island=pins[ident]['island'];options=[]
            for xy in island.get('candidate_centers',[]):
                if not isinstance(xy,list) or len(xy)!=2:raise SolverError('INVALID_INPUT','Invalid physical access point')
                for v in xy:finite(v,'pin coordinate')
                if any(abs(v/grid-round(v/grid))>1e-6 for v in xy):continue
                for layer in layers:
                    if layer in island.get('access_layers',[]):options.append((xy[0],xy[1],layer))
            if not options:raise SolverError('LOCAL_CONTACT_REQUIRED','No qualified metal access on allowed layers: '+ident)
            selected=island.get('selected_center')
            pins[ident]['options']=sorted(set(options),key=lambda p:(list(p[:2])!=selected,g.levels[p[2]],p))
    if set(nets)!=set(by_net):raise SolverError('INVALID_MAPPING','Policies must classify all electrical nets')
    groups=[];classified=set();group_ids=set()
    for raw in request.get('groups',[]):
        mode=raw.get('mode');ident=raw.get('id')
        if set(raw)-{'id','mode','net','first_net','second_net','pin_pairs','reason'}:
            raise SolverError('INVALID_MAPPING','Unsupported group scope/transform; solver uses complete whole nets and fixed axis')
        if not isinstance(ident,str) or not ident or ident in group_ids:raise SolverError('INVALID_MAPPING','Unique group id required')
        group_ids.add(ident);group=copy.deepcopy(raw)
        members=[raw.get('first_net'),raw.get('second_net')] if mode=='pair' else [raw.get('net')]
        if mode not in ('pair','self','ordinary') or any(n not in nets or n in classified for n in members) or len(set(members))!=len(members):
            raise SolverError('INVALID_MAPPING','Exactly one pair/self/ordinary group per net required')
        classified.update(members);group['members']=members
        if mode=='ordinary':
            if not str(raw.get('reason','')).strip():raise SolverError('UNSCOPED_ASYMMETRY','Ordinary whole-net exception needs a reason')
            group['orbits']=[(i,None) for i in sorted(by_net[members[0]])]
        else:
            pairs=raw.get('pin_pairs',[])
            if not pairs or any(not isinstance(p,list) or len(p)!=2 for p in pairs):raise SolverError('INVALID_MAPPING','Complete physical pin orbit mapping required')
            first=[p[0] for p in pairs];second=[p[1] for p in pairs]
            if mode=='pair':
                if set(first)!=by_net[members[0]] or set(second)!=by_net[members[1]] or len(set(first))!=len(first) or len(set(second))!=len(second):
                    raise SolverError('INVALID_MAPPING','Pair map must bijectively cover both whole nets')
                group['orbits']=[tuple(p) for p in pairs]
            else:
                flattened=[i for p in pairs for i in (p if p[0]!=p[1] else p[:1])]
                if set(flattened)!=by_net[members[0]] or len(flattened)!=len(set(flattened)):
                    raise SolverError('INVALID_MAPPING','Self map must partition all islands into fixed points or pairs')
                group['orbits']=[tuple(p) for p in pairs]
            for a,b in group['orbits']:
                if a not in pins or b not in pins:raise SolverError('INVALID_MAPPING','Unknown pin in orbit')
        groups.append(group)
    if classified!=set(nets):raise SolverError('INVALID_MAPPING','Symmetry policy must cover the complete circuit')
    paired={n for group in groups if group['mode']=='pair' for n in group['members']}
    electrical={m.get(k) for m in request.get('matching',[]) for k in ('first_net','second_net')}
    if any(n['net_class'] in ('matched','differential') and name not in paired|electrical for name,n in nets.items()):
        raise SolverError('MATCHING_REQUIRED','Matched/differential classes need a strict pair or explicit electrical matching contract')
    if not groups:raise SolverError('INVALID_MAPPING','Empty circuit/groups')
    for ident,rule in g.local.items():
        from symmetric_geometry import box_ok
        if ident not in pins or not rule.get('source') or not box_ok(rule.get('region_um')):
            raise SolverError('LOCAL_ACCESS_UNKNOWN','Invalid sourced local access region '+ident)
        number(rule.get('max_length_um'),'local budget',True)
    return g,pins,nets,groups

def orbit_options(group,pins,axis):
    result=[];k=0 if axis['coordinate']=='x' else 1
    for a,b in group['orbits']:
        if b is None:choices=[(a,p,None,None) for p in pins[a]['options']]
        else:
            choices=[]
            for p in pins[a]['options']:
                q=tuple(reflected(p,axis))
                if q not in pins[b]['options']:continue
                if a==b and q!=p:continue
                if group['mode']=='self' and p[k]>axis['value_um']+EPS:choices.append((b,q,a,p))
                else:choices.append((a,p,b,q))
        if not choices:raise SolverError('NO_MIRRORED_ACCESS','No common mirrored access for '+a+'/'+str(b))
        result.append(choices)
    return result

def to_geometry(graph,actions):
    objects=[]
    for action in actions:
        objects.extend(graph.wire_actions(action['a'],action['b']) if action['kind']=='wire' else graph.via_actions(action['a'],action['via']))
    return objects

def build_fragment(graph,actions,selections):
    routes=[];vias=[];seen=set()
    def add_route(net,a,b):
        key=(net,a[2],tuple(sorted((tuple(a[:2]),tuple(b[:2])))))
        if key in seen:return
        seen.add(key);routes.append({'net':net,'layer':a[2],'width_um':graph.widths[a[2]],'points_um':[list(a[:2]),list(b[:2])],'access':[]})
    for action in actions:
        placements=[(graph.first['net'],action['a'],action['b'])]
        if graph.second:placements.append((graph.second['net'],graph.transform(action['a']),graph.transform(action['b'])))
        for net,a,b in placements:
            if action['kind']=='wire':add_route(net,a,b);continue
            key=('via',net,action['via'],tuple(a[:2]))
            if key in seen:continue
            seen.add(key);vias.append({'net':net,'via':action['via'],'xy_um':list(a[:2])})
            # Same stubs as the searched geometry, with exact physical landing coverage.
            for obj in graph.via_actions(action['a'],action['via']):
                if obj['net']!=net or '/landing-wire/' not in obj.get('id',''):continue
                layer=obj['layer'];d=1 if graph.g.directions[layer]=='vertical' else 0
                lo=list(a[:2]);hi=list(lo);lo[d]=obj['bbox_um'][0][d]+graph.widths[layer]/2;hi[d]=obj['bbox_um'][1][d]-graph.widths[layer]/2
                add_route(net,lo+[layer],hi+[layer])
    for ident,node in selections.items():
        pin=graph.pin_lookup[ident];net=pin['net']
        match=next((r for r in routes if r['net']==net and r['layer']==node[2] and
                    PLANNER.ROUTE.on_segment(node[:2],*r['points_um'],EPS)),None)
        if match is None:raise SolverError('PIN_WITHOUT_CONDUCTOR','A physical island needs a real connected conductor: '+ident)
        match['access'].append({k:pin[k] for k in ('instance','terminal','pin_island_id')}|{'xy_um':list(node[:2])})
    return {'routes':routes,'vias':vias,'objects':to_geometry(graph,actions)}

def self_bridge(graph,paths,nodes):
    axis=graph.axis;k=0 if axis['coordinate']=='x' else 1;d=k
    layer_candidates=[l for l in graph.layers if graph.g.directions[l]==('horizontal' if k==0 else 'vertical')]
    if not layer_candidates:raise SolverError('SELF_AXIS_UNREACHABLE','No allowed layer can cross the symmetry axis')
    # Half-grid axes use a complete one-grid bridge; never invent an off-grid via/node.
    near=graph.g.p.snap_down(axis['value_um'],graph.g.grid)
    xs,ys=graph.coordinates(nodes[0],nodes,nodes);parallel=ys if k==0 else xs;goals=[];bridges={}
    for layer in layer_candidates:
        for value in parallel:
            p=[near,value,layer] if k==0 else [value,near,layer];q=list(graph.transform(p))
            if p[:2]==q[:2]:
                # A real direction-correct conductor across the axis supplies the fixed point.
                p[d]-=graph.g.grid;q[d]+=graph.g.grid
            objects=graph.wire_actions(p,q)
            if graph.g.clear(objects,graph.reserved):goals.append(tuple(p));bridges[tuple(p)]={'a':tuple(p),'b':tuple(q),'kind':'wire','via':None}
    starts=sorted(nodes_on_tree(paths,nodes[0],nodes))
    answer=graph.search(starts[0],goals,nodes,starts=starts)
    if answer:
        actions,_=answer
        goal=actions[-1]['b'] if actions else next((p for p in starts if p in bridges),None)
        bridge=bridges[goal];objects=to_geometry(graph,actions+[bridge])
        if graph.g.clear(objects,graph.reserved):return actions+[bridge]
    raise SolverError('SELF_AXIS_UNREACHABLE','No legal connected mirror bridge in the finite graph')

def group_candidates(g,group,pins,nets,axis,reserved,budget,costs):
    options=orbit_options(group,pins,axis);products=itertools.product(*options);results=[];failures=[];k=0 if axis['coordinate']=='x' else 1
    for ci,combo in enumerate(products):
        if ci>=budget.limits['access_combinations']:budget.truncated=True;break
        selections={};nodes=[]
        for a,p,b,q in combo:
            selections[a]=p;nodes.append(p)
            if b:selections[b]=q
        side=None
        if group['mode']=='pair':
            signs={-1 if p[k]<axis['value_um']-EPS else 1 if p[k]>axis['value_um']+EPS else 0 for p in nodes}
            if len(signs)!=1 or 0 in signs:failures.append({'code':'PAIR_CROSSES_AXIS','reason':'Distinct strict mirrored nets require separate half-planes'});continue
            side=next(iter(signs))
        elif group['mode']=='self':side=-1
        first=nets[group['members'][0]];second=nets[group['members'][-1]] if group['mode']!='ordinary' else None
        previous_paths=[]
        for variant in range(budget.limits['group_candidates']):
            try:
                graph=JointGraph(g,first,second,axis if second else None,reserved,
                    ([i for i in selections if pins[i]['net']==first['net']],
                     [i for i in selections if second and pins[i]['net']==second['net']]),budget,costs,side)
                graph.pin_lookup=pins;ordered=list(dict.fromkeys(nodes));ordered=ordered[variant%len(ordered):]+ordered[:variant%len(ordered)]
                if previous_paths:
                    edges=[a for a in previous_paths if a['kind']=='wire'] or previous_paths
                    edge=edges[(variant-1)%len(edges)];graph.forbidden.add(frozenset((edge['a'],edge['b'])))
                # Explicit sourced terminal escapes support single-island nets without cosmetic loops.
                if len(ordered)==1 and (group['mode']!='self' or abs(ordered[0][k]-axis['value_um'])<EPS):
                    escape=first.get('terminal_escape',{})
                    if not escape.get('source') or escape.get('pin_island_id') not in selections:
                        raise SolverError('PIN_WITHOUT_CONDUCTOR','Single-island net needs a sourced terminal_escape')
                    xy=escape.get('end_xy_um',[]);layer=escape.get('layer')
                    if len(xy)!=2 or layer not in graph.layers or any(abs(finite(v,'escape')/g.grid-round(v/g.grid))>1e-6 for v in xy):
                        raise SolverError('INVALID_INPUT','Terminal escape must use an allowed layer and on-grid endpoint')
                    end=(xy[0],xy[1],layer)
                    if group['mode']=='self' and end[k]>axis['value_um']:end=graph.transform(end)
                    if group['mode']=='pair':
                        mate=second.get('terminal_escape',{})
                        if not mate.get('source') or mate.get('pin_island_id') not in selections or tuple(mate.get('end_xy_um',[]))!=tuple(graph.transform(end)[:2]) or mate.get('layer')!=layer:
                            raise SolverError('PAIR_POLICY_MISMATCH','Terminal escapes need complete mirrored endpoints')
                    ordered.append(end)
                paths,cost=grow_tree(graph,ordered,variant)
                previous_paths=paths
                if group['mode']=='self' and not (paths and any(abs(p[k]-axis['value_um'])<EPS for p in ordered)):
                    paths+=self_bridge(graph,paths,ordered)
                if not paths:raise SolverError('PIN_WITHOUT_CONDUCTOR','Single-access net requires an explicit connected terminal escape upstream')
                fragment=build_fragment(graph,paths,selections)
                from symmetric_audit import union_length
                cost=sum(union_length([r for r in fragment['routes'] if r['net']==net and r['layer']==layer])*(1+(costs or {}).get('metal_area_weight',0)*graph.widths[layer])
                         for net in group['members'] for layer in graph.layers)+len(fragment['vias'])*(costs or {}).get('via_cost_um',2)
                cost+=sum(g.soft_cost(route['points_um'][0],route['points_um'][1],route['layer']) for route in fragment['routes'])
                signature=PLANNER.ROUTE.digest({'routes':fragment['routes'],'vias':fragment['vias']})
                if any(r['signature']==signature for r in results):continue
                results.append({**fragment,'cost':cost,'signature':signature,'group':group['id']})
            except SolverError as error:
                if error.code=='BUDGET_EXHAUSTED':raise
                failures.append({'code':error.code,'reason':str(error)})
            if len(results)>=budget.limits['group_candidates']:break
        if len(results)>=budget.limits['group_candidates']:break
    if not results:
        if failures:raise SolverError(failures[-1]['code'],failures[-1]['reason'])
        raise SolverError('NO_PATH_IN_GRAPH','No complete group candidate in bounded access search')
    return sorted(results,key=lambda f:(f['cost'],f['signature']))

def route_spec(request,groups,fragments,obstacles):
    routes=[];vias=[];symmetry=[];matching=copy.deepcopy(request.get('matching',[]))
    for fragment in fragments:
        for raw in fragment['routes']:routes.append({**raw,'id':'joint_wire_'+str(len(routes))})
        for raw in fragment['vias']:vias.append({**raw,'id':'joint_via_'+str(len(vias))})
    axis=request['axis']
    for group in groups:
        if group['mode']=='ordinary':continue
        symmetry.append({k:v for k,v in group.items() if k in ('id','mode','net','first_net','second_net')}|
                        {'transform':'mirror_'+axis['coordinate'],'axis_um':axis['value_um'],'tolerance_um':0})
        if group['mode']=='pair' and not any({m.get('first_net'),m.get('second_net')}==set(group['members']) for m in matching):
            matching.append({'first_net':group['first_net'],'second_net':group['second_net'],'max_length_delta_um':0,'max_via_delta':0,
                'max_per_layer_length_delta_um':0,'max_bend_delta':0,'max_via_type_delta':0,'max_route_count_delta':0,
                'max_access_count_delta':0,'max_bbox_span_delta_um':0})
    result={'schema':PLANNER.ROUTE.SPEC_SCHEMA,'target':request['target'],'routes':routes,'vias':vias,
        'required_nets':sorted(n['net'] for n in request['nets']),'matching':matching,'symmetry_groups':symmetry,
        'preferred_directions':{},'planning_evidence':{'backend':BACKEND,'request_sha256':PLANNER.ROUTE.digest(request),
            'obstacles_sha256':PLANNER.ROUTE.digest(obstacles),'obstacle_coverage':obstacles.get('coverage',{'live_snapshot':False}),
            'sources':copy.deepcopy(request['sources']),
            'materializable':False},'net_constraints':[{k:v for k,v in n.items() if k in ('net','net_class','max_detour_ratio','max_bends','max_bbox_excursion_um','width_basis')} for n in request['nets']]}
    # Union redundant collinear landing/visibility segments before reporting metrics.
    # Restore each access to its original physical layer; generic compaction is layer-agnostic.
    attachments=[(route['net'],route['layer'],att) for route in routes for att in route['access']]
    result,_=COMPACT.compact(result,EPS)
    for route in result['routes']:route['access']=[]
    for net,layer,att in attachments:
        destination=next((route for route in result['routes'] if route['net']==net and route['layer']==layer and
                          PLANNER.ROUTE.on_segment(att['xy_um'],*route['points_um'],EPS)),None)
        if destination is None:raise SolverError('ACCESS_MAPPING','Compaction lost an original physical-layer access')
        destination['access'].append(att)
    return result

def verified_intent(profile,access,candidate):
    bound=candidate['route_spec']['planning_evidence']['sources']
    audit=candidate['audit'];spec=candidate['route_spec']
    if (bound['profile_fingerprint']!=profile['fingerprint']['value'] or bound['terminal_access_sha256']!=PLANNER.ROUTE.digest(access)
        or audit['sources']['spec_sha256']!=PLANNER.ROUTE.digest(spec)
        or audit['sources']['request_sha256']!=spec['planning_evidence']['request_sha256']):
        raise SolverError('SOURCE_DRIFT','Cannot export an intent from stale candidate/audit inputs')
    intent=PLANNER.ROUTE.build(profile,access,candidate['route_spec'])
    intent['net_metrics']=copy.deepcopy(candidate['audit']['metrics'])
    intent['joint_audit']={'status':candidate['audit']['status'],'sources':candidate['audit']['sources'],
                           'materializable':False,'bend_basis':'primitive plus adjacent-layer direction transitions'}
    if candidate['audit']['status']!='PASS':
        intent['validation']['valid']=False;intent['decision']['status']='BLOCKED'
    return intent

def solve(profile,access,obstacles,request):
    result={'schema':PLANNER.CANDIDATE_SCHEMA,'backend':BACKEND,'status':'BLOCKED','candidates':[],
            'failures':[],'materializable':False,'search_completeness':'Bounded graph/access/tree/ordering search; no global UNSAT or optimality claim'}
    budget=None;g=None
    try:
        g,pins,nets,groups=prepare(profile,access,obstacles,request);budget=Budget(request.get('search',{}));seen=set()
        rotations=[groups[i:]+groups[:i] for i in range(len(groups))]
        orders=itertools.chain(rotations,[list(reversed(groups))],itertools.permutations(groups));order_seen=set();oi=-1
        for order in orders:
            order_key=tuple(group['id'] for group in order)
            if order_key in order_seen:continue
            order_seen.add(order_key);oi+=1
            if oi>=budget.limits['max_orderings']:budget.truncated=True;break
            result.setdefault('orderings',[]).append([group['id'] for group in order])
            # Each ordering begins with an empty reservation: bounded atomic rip-up/re-route.
            beam=[([],[],0.0)]
            for group in order:
                following=[]
                for fragments,reserved,cost in beam:
                    try:
                        choices=group_candidates(g,group,pins,nets,request['axis'],reserved,budget,request.get('costs',{}))
                        for choice in choices:following.append((fragments+[choice],reserved+choice['objects'],cost+choice['cost']))
                    except SolverError as error:
                        if error.code=='BUDGET_EXHAUSTED':raise
                        result['failures'].append({'code':error.code,'reason':str(error),'group':group['id'],'ordering':oi})
                beam=sorted(following,key=lambda b:(b[2],tuple(f['signature'] for f in b[0])))[:budget.limits['beam_width']]
                if not beam:break
            for fragments,_,cost in beam:
                if len(fragments)!=len(groups):continue
                spec=route_spec(request,groups,fragments,obstacles);signature=PLANNER.ROUTE.digest(spec)
                if signature in seen:continue
                seen.add(signature)
                from symmetric_audit import audit
                checked=audit(profile,access,obstacles,request,spec,PLANNER,MIRROR)
                if checked['status']!='PASS':
                    result['failures'].append({'code':'INDEPENDENT_AUDIT_FAILED','reason':checked,'ordering':oi});continue
                result['candidates'].append({'id':'joint_candidate_'+str(len(result['candidates'])),'route_spec':spec,
                    'cost':cost,'audit':checked,'metrics':checked['metrics'],'materializable':False})
            if len(result['candidates'])>=budget.limits['top_k']:break
        result['candidates']=sorted(result['candidates'],key=lambda c:(c['cost'],PLANNER.ROUTE.digest(c['route_spec'])))[:budget.limits['top_k']]
    except (SolverError,ValueError,KeyError,TypeError,AttributeError) as error:
        result['failures'].append({'code':getattr(error,'code','INVALID_INPUT'),'reason':str(error)})
    if result['candidates']:result['status']='PLANNED'
    result['search_statistics']={'expansions':budget.expansions if budget else 0,'searches':budget.searches if budget else 0,
        'bounded_alternatives_truncated':budget.truncated if budget else False,'geometry_checks':g.checked if g else 0,'rejected_actions':g.rejected if g else {}}
    result['execution_scope']='Offline joint search; live polygon rules, DRC/LVS, IR/EM, PEX and saved geometry remain separate gates'
    return result

def dump(path,data):Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('profile','access','obstacles','request','out'):p.add_argument('--'+key,required=True,type=Path)
    args=p.parse_args()
    if args.out.exists():p.error('--out must be a new directory to avoid stale candidate reuse')
    profile,access,obstacles,request=[PLANNER.load(getattr(args,k)) for k in ('profile','access','obstacles','request')]
    result=solve(profile,access,obstacles,request);args.out.mkdir(parents=True);dump(args.out/'candidates.json',result)
    from symmetric_artifacts import context,selected
    context(args.out,profile,access,obstacles,request,result,PLANNER)
    for i,candidate in enumerate(result['candidates']):
        out=args.out/('candidate-'+str(i));out.mkdir();dump(out/'spec.json',candidate['route_spec']);dump(out/'audit.json',candidate['audit'])
        intent=verified_intent(profile,access,candidate);dump(out/'intent.json',intent)
        selected(out,candidate,intent,request)
        (out/'preview.svg').write_text(PLANNER.ROUTE.svg(intent),encoding='utf-8')
        dump(out/'svg-check.json',MIRROR.geometry.build_check(out/'intent.json',out/'preview.svg'))
    print(json.dumps({'status':result['status'],'candidates':len(result['candidates']),'failures':result['failures'],'search_statistics':result['search_statistics']},ensure_ascii=False))
    return 0 if result['status']=='PLANNED' else 2

if __name__=='__main__':raise SystemExit(main())
