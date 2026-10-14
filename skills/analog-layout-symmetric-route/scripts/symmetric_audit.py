"""Reconstruct candidate geometry and validate it independently of A* state."""
from pathlib import Path
import tempfile, json
from symmetric_geometry import Geometry, SolverError, EPS, wire, via_objects, reflected_box, gap, contains, union_contains

def union_length(routes):
    buckets={}
    for r in routes:
        for a,b in zip(r['points_um'],r['points_um'][1:]):
            d=1 if a[0]==b[0] else 0
            buckets.setdefault((r['layer'],d,a[1-d]),[]).append(sorted((a[d],b[d])))
    length=0
    for intervals in buckets.values():
        end=None
        for low,high in sorted(intervals):
            if end is None or low>end: length+=high-low;end=high
            elif high>end:length+=high-end;end=high
    return length

def components(objects):
    """Exact metal contact, plus qualified vias joining their two landing layers."""
    metals=[o for o in objects if o['kind']=='metal'];parents=list(range(len(metals)))
    def root(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,a in enumerate(metals):
        for j,b in enumerate(metals[:i]):
            if a['net']!=b['net']:continue
            via=(a.get('via_instance') and a.get('via_instance')==b.get('via_instance'))
            if via or (a['layer']==b['layer'] and gap(a['bbox_um'],b['bbox_um'])<=EPS):parents[root(i)]=root(j)
    result={}
    for i,obj in enumerate(metals):result.setdefault(obj['net'],{}).setdefault(root(i),[]).append(obj)
    return result

def audit(profile,access,obstacles,request,spec,planner,mirror):
    errors=[];g=Geometry(planner,profile,obstacles,request);objects=[];grid=g.grid;cuts=[]
    try:
        policies={n['net']:n for n in request['nets']};access_map={}
        if spec.get('target')!=request['target'] or set(spec.get('required_nets',[]))!=set(policies):
            raise SolverError('POLICY_DRIFT','Candidate target/whole-net scope differs from request')
        strict_nets={group.get(k) for group in request['groups'] if group['mode']!='ordinary' for k in ('net','first_net','second_net')}
        for route in spec['routes']:
            layer=route['layer'];net=route['net'];width=route['width_um']
            if net not in policies or layer not in policies[net]['layers'] or width!=policies[net]['widths_um'].get(layer):
                raise SolverError('POLICY_DRIFT','Candidate layer/width differs from network policy')
            if layer not in g.minimum or width+EPS<g.minimum[layer]:raise SolverError('INVALID_WIDTH','Candidate width below PDK minimum')
            for att in route.get('access',[]):
                ident=att['pin_island_id']
                if ident in access_map:raise SolverError('ACCESS_MAPPING','A physical island is annotated more than once')
                access_map[ident]=(*att['xy_um'],layer)
            for a,b in zip(route['points_um'],route['points_um'][1:]):
                if any(abs(v/grid-round(v/grid))>1e-6 for p in (a,b) for v in p):raise SolverError('OFF_GRID','Candidate centreline is off grid')
                direction='vertical' if a[0]==b[0] else 'horizontal' if a[1]==b[1] else 'diagonal'
                if direction!=g.directions[layer]:raise SolverError('HARD_DIRECTION','Candidate violates actual-level odd/even direction')
                objects.append(wire(a+[layer],b+[layer],width,net,route['id']))
        widths={n['net']:n['widths_um'] for n in request['nets']}
        for via in spec['vias']:
            if any(abs(v/grid-round(v/grid))>1e-6 for v in via['xy_um']):raise SolverError('OFF_GRID','Via centre is off grid')
            if not g.qualified_via(via['via'],widths[via['net']],request['axis'] if via['net'] in strict_nets else None):raise SolverError('VIA_LANDING','Width cannot cover via enclosure')
            actual=via_objects(g.vias[via['via']],via['xy_um'],via['net'],via['id'])
            for obj in actual:
                obj['via_instance']=via['id']
                if obj['kind']=='cut':cuts.append(obj)
                else:
                    boxes=[o['bbox_um'] for o in objects if o['net']==obj['net'] and o['layer']==obj['layer']]
                    if not union_contains(obj['bbox_um'],boxes):raise SolverError('VIA_LANDING','Full lower/upper via landing not covered by route metal')
            objects.extend(actual)
        if not g.clear(objects):raise SolverError('GEOMETRY_CONFLICT','Independent candidate edge/cut spacing or bounds check failed')
        connected=components(objects)
        for net in spec['required_nets']:
            if len(connected.get(net,{}))!=1:raise SolverError('DISCONNECTED','Exact conductor geometry is disconnected on '+net)
        # Cut array reflection is checked explicitly; the legacy verifier covers wire unions.
        for group in request['groups']:
            if group['mode']=='ordinary':continue
            from symmetric_geometry import reflected
            for first_pin,second_pin in group['pin_pairs']:
                if first_pin not in access_map or second_pin not in access_map or tuple(reflected(access_map[first_pin],request['axis']))!=access_map[second_pin]:
                    raise SolverError('ACCESS_MAPPING','Candidate physical island selections do not reflect under the declared map')
            first=group.get('first_net',group.get('net'));second=group.get('second_net',group.get('net'))
            signature=lambda o:(o['layer'],tuple(tuple(round(v,12) for v in p) for p in o['bbox_um']))
            right={signature(o) for o in cuts if o['net']==second}
            left={signature({**o,'bbox_um':reflected_box(o['bbox_um'],request['axis'])}) for o in cuts if o['net']==first}
            if left!=right:raise SolverError('CUT_SYMMETRY','Actual normalized cut arrays are not exact mirrors')
        # M1 locality is measured as a union per complete local conductor component.
        m1=[r for r in spec['routes'] if g.levels[r['layer']]==1]
        local_objects=[o for o in objects if o['kind']=='metal' and g.levels[o['layer']]==1]
        local_components=components(local_objects)
        local_audit=[]
        pins={}
        for inst in access['instances']:
            for terminal,data in inst['terminals'].items():
                for island in planner.terminal_islands(inst['name'],terminal,data):pins[island['id']]=(data['net'],island)
        for net,comps in local_components.items():
            for items in comps.values():
                anchors=[]
                for ident,(pin_net,island) in pins.items():
                    if pin_net==net and any(g.levels.get(l)==1 for l in island.get('access_layers',[])) and any(
                        any(contains(o['bbox_um'],[p,p]) for o in items) for p in island.get('candidate_centers',[])):
                        anchors.append(ident)
                if not anchors or any(i not in g.local for i in anchors):raise SolverError('LOCAL_ACCESS_UNKNOWN','Every M1 component needs sourced physical access budgets')
                rules=[g.local[i] for i in anchors]
                if any(not any(contains(r['region_um'],o['bbox_um']) for r in rules) for o in items):raise SolverError('M1_REGION','M1 geometry leaves qualified local regions')
                ids={o['id'] for o in items};length=union_length([r for r in m1 if r['id'] in ids]);limit=min(r['max_length_um'] for r in rules)
                if length>limit+EPS:raise SolverError('M1_LENGTH','Cumulative local M1 union length exceeds access budget')
                local_audit.append({'net':net,'islands':anchors,'union_length_um':length,'limit_um':limit})
    except (SolverError,KeyError,TypeError,ValueError) as error:errors.append({'code':getattr(error,'code','INVALID_INPUT'),'reason':str(error)})
    intent=planner.ROUTE.build(profile,access,spec)
    if not intent['validation']['valid']:errors.append({'code':'INTENT_FAILED','reason':intent['validation']['errors']})
    # Primitive splitting cannot erase direction changes made at qualified vias.
    for net,metric in intent['net_metrics'].items():
        transitions=sum(g.directions[g.vias[v['via']]['lower']]!=g.directions[g.vias[v['via']]['upper']]
                        for v in spec['vias'] if v['net']==net)
        metric['primitive_bend_count']=metric['bend_count'];metric['layer_transition_bend_count']=transitions
        metric['bend_count']+=transitions
        limit=next((n.get('max_bends') for n in request['nets'] if n['net']==net),None)
        if limit is not None and metric['bend_count']>limit:
            errors.append({'code':'BEND_LIMIT','reason':net+' exceeds total primitive plus layer-transition bend budget'})
    for pair in spec.get('matching',[]):
        a,b=pair['first_net'],pair['second_net'];metrics=intent['net_metrics']
        if a in metrics and b in metrics and abs(metrics[a]['bend_count']-metrics[b]['bend_count'])>pair.get('max_bend_delta',0):
            errors.append({'code':'MATCHING_BENDS','reason':'Cross-layer bend difference exceeds matching budget: '+a+'/'+b})
    symmetry=mirror.symmetry_preflight(intent,request['axis'])
    if symmetry['status']!='PASS':errors.append({'code':'SYMMETRY_FAILED','reason':symmetry['errors']})
    with tempfile.TemporaryDirectory(prefix='joint-route-audit-') as temporary:
        path=Path(temporary);(path/'intent.json').write_text(json.dumps(intent,ensure_ascii=False),encoding='utf-8')
        (path/'preview.svg').write_text(planner.ROUTE.svg(intent),encoding='utf-8')
        svg=mirror.geometry.build_check(path/'intent.json',path/'preview.svg')
    if svg['status']!='PASS':errors.append({'code':'SVG_FAILED','reason':svg})
    return {'schema':'analog-layout-symmetric-route.audit/v1','status':'PASS' if not errors else 'BLOCKED','errors':errors,
        'sources':{'request_sha256':planner.ROUTE.digest(request),'spec_sha256':planner.ROUTE.digest(spec)},
        'checked':['hard layer direction','grid centreline','both-side edge spacing','individual cuts and cross-cut stacking',
            'complete via landing union coverage','exact conductor connectivity','whole-net physical island coverage',
            'wire-union and actual cut reflection','cumulative M1 region/budget','matching','independent SVG consistency'],
        'local_access':locals().get('local_audit',[]),'metrics':intent['net_metrics'],'symmetry':symmetry,'svg_status':svg['status'],
        'materializable':False,'not_checked':['native polygon caps/notches/EOL/conditional rules not represented in profile',
            'live layout revision/readback','foundry DRC/LVS','IR/EM capacity','parasitic/environmental symmetry','PEX']}
