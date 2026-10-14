"""Deterministic template compiler; no live writes, maze search or obstacle legality claim."""
import argparse
import copy
import importlib.util
import json
import math
from pathlib import Path

DEPENDENCY=Path(__file__).resolve().parents[2]/'analog-layout-route/scripts/route_intent.py'
if not DEPENDENCY.is_file():raise RuntimeError('Missing sibling analog-layout-route')
module=importlib.util.spec_from_file_location('symmetric_route_intent',DEPENDENCY)
ri=importlib.util.module_from_spec(module);module.loader.exec_module(ri)
_svg_module=importlib.util.spec_from_file_location('symmetric_route_geometry',DEPENDENCY.with_name('svg_route_check.py'))
geometry=importlib.util.module_from_spec(_svg_module);_svg_module.loader.exec_module(geometry)


def symmetry_preflight(intent,axis):
    """Check represented layer/width centerline unions and via/contact points.
    Not a polygon, live-via-array, branch-access or environment signoff check.
    """
    errors=[];warnings=[];objects={};tol=min(1e-9,intent['manufacturing_grid_um']*1e-6)
    checked=copy.deepcopy(intent)
    for group in checked.get('symmetry_groups',[]):
        if group.get('transform')!='mirror_'+axis['coordinate'] or group.get('axis_um')!=axis['value_um']:
            errors.append('Symmetry axis differs from fixed template axis: '+str(group.get('id')))
        requested=group.get('tolerance_um',tol)
        if not isinstance(requested,(int,float)) or isinstance(requested,bool) or not math.isfinite(requested) or requested<0 or requested>tol:
            errors.append('Symmetry tolerance exceeds numerical-only limit: '+str(group.get('id')))
        group['tolerance_um']=tol
        nets=[group.get('net')] if group.get('mode')=='self' else [group.get('first_net'),group.get('second_net')]
        if any(not any(r['net']==n for r in intent.get('routes',[])) for n in nets):
            errors.append('Empty symmetry scope: '+str(group.get('id')))
    for r in intent.get('routes',[]):
        objects[r['id']]={'kind':'route','data-net':r['net'],'data-layer':r['layer'],
            'data-purpose':r['purpose'],'data-width-um':r['width_um'],'points_um':r['points_um']}
    for key,kind in [('vias','via'),('contact_landings','contact')]:
        for v in intent.get(key,[]):
            objects[v['id']]={'kind':kind,'data-net':v['net'],'data-via':v['via'],
                'data-source-layer':v.get('source_layer',''),'xy_um':v['xy_um']}
    groups=geometry.check_symmetry(checked,objects,tol,errors,warnings)
    return {'status':'PASS' if not errors else 'BLOCKED','groups':groups,'errors':errors,'warnings':warnings,
            'scope':'Represented route unions and via/contact centers only; live polygons/arrays/ports and branch access still require independent review'}


def check_keys(obj,keys):
    if set(obj)-set(keys):raise ValueError('Unsupported fields: '+str(sorted(set(obj)-set(keys))))


def finite(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Non-finite number')
    return v


def xy(p):
    if not isinstance(p,list) or len(p)!=2:raise ValueError('Expected XY')
    return [finite(v) for v in p]


def clean(points):
    out=[]
    for p in points:
        xy(p)
        if not out or p!=out[-1]:out.append(list(p))
    if len(out)<2:raise ValueError('Zero-length route')
    for a,b in zip(out,out[1:]):
        if a[0]!=b[0] and a[1]!=b[1]:raise ValueError('Non-Manhattan route')
    for a,b,c in zip(out,out[1:],out[2:]):
        if (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1])<0:raise ValueError('Backtracking')
    return out


def doglegs(start,end,tracks_x=(),tracks_y=()):
    """Finite straight/L/U skeletons. Caller checks both halves, widths and obstacles."""
    xy(start);xy(end)
    trials=[[start,[start[0],end[1]],end],[start,[end[0],start[1]],end]]
    trials += [[start,[finite(x),start[1]],[x,end[1]],end] for x in tracks_x]
    trials += [[start,[start[0],finite(y)],[end[0],y],end] for y in tracks_y]
    result=[]
    for trial in trials:
        try:p=clean(trial)
        except ValueError:continue
        if p not in result:result.append(p)
    return sorted(result,key=lambda p:(sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(p,p[1:])),len(p)))


def horizontal_bus(prefix,net,m1,trunk_layer,width_m1,width_trunk,via,taps,y,x_range):
    """Explicit short-M1 taps, one named transition, continuous horizontal trunk.
    Returns route-spec fragments. Does not size power wires or select/qualify vias.
    """
    if finite(width_m1)<=0 or finite(width_trunk)<=0:raise ValueError('Non-positive width')
    finite(y)
    if len(x_range)!=2 or finite(x_range[0])>=finite(x_range[1]):raise ValueError('Invalid bus extent')
    if not taps or (m1!=trunk_layer and not via):raise ValueError('Missing taps/via')
    if any(xy(tap['landing_xy_um'])[1] != y for tap in taps):
        raise ValueError('Horizontal bus landings must share bus y; use layered_dogleg for vertical branches')
    routes=[{'id':prefix+':bus','net':net,'layer':trunk_layer,'width_um':width_trunk,
             'points_um':[[x_range[0],y],[x_range[1],y]],'access':[]}];vias=[]
    for i,tap in enumerate(taps):
        a=tap['access'];p=xy(a['xy_um']);q=xy(tap['landing_xy_um'])
        if not x_range[0]<=q[0]<=x_range[1]:raise ValueError('Tap outside bus extent')
        if p == q:
            raise ValueError('Zero-length tap needs an explicit existing conductor landing; do not fabricate a wire')
        points=clean([p,q])
        routes.append({'id':f'{prefix}:tap:{i}','net':net,'layer':m1,'width_um':width_m1,'points_um':points,'access':[copy.deepcopy(a)]})
        if m1!=trunk_layer:vias.append({'id':f'{prefix}:via:{i}','net':net,'via':via,'xy_um':q})
        if q[1]!=y:routes.append({'id':f'{prefix}:branch:{i}','net':net,'layer':trunk_layer,'width_um':width_trunk,'points_um':[q,[q[0],y]],'access':[]})
    # Multiple taps may share a landing; do not inflate via count by duplicate creation.
    unique={ (v['net'],v['via'],tuple(v['xy_um'])):v for v in vias }
    return {'routes':routes,'vias':list(unique.values())}


def compile_spec(profile,access,request):
    check_keys(request,['schema','sources','axis','seed_spec','pairs','self_nets','via_mirror_evidence'])
    if request['schema']!='analog-layout-symmetric-route.templates/v1':raise ValueError('Unsupported schema')
    # Reject NaN throughout input, including unused nested fields.
    json.dumps([profile,access,request],allow_nan=False)
    seed=request['seed_spec'];sources=request['sources']
    if sources!={'profile_fingerprint':ri.fingerprint(profile),'terminal_access_sha256':ri.digest(access),'seed_sha256':ri.digest(seed)}:
        raise ValueError('Stale inputs')
    if profile.get('fingerprint',{}).get('value')!=ri.fingerprint(profile):raise ValueError('Profile fingerprint mismatch')
    if not profile.get('validation',{}).get('structurally_valid') or not profile.get('coverage',{}).get('basic_routing_ready') or not profile.get('boundaries',{}).get('may_drive_automatic_routing'):
        raise ValueError('PDK not routing-ready')
    if seed.get('target')!=access.get('target') or (profile.get('source_target') and profile['source_target']!=access['target']):raise ValueError('Target mismatch')
    axis=request['axis'];check_keys(axis,['coordinate','value_um'])
    if axis['coordinate'] not in ('x','y'):raise ValueError('Unknown axis')
    k='xy'.index(axis['coordinate']);value=finite(axis['value_um']);grid=finite(profile['manufacturing_grid_um'])
    if grid<=0:raise ValueError('Invalid grid')
    def grid_point(p):
        xy(p)
        if any(abs(v/grid-round(v/grid))>1e-7 for v in p):raise ValueError('Off-grid coordinate; never silently snap mirrored access')
        return p
    def reflect(p):
        q=list(xy(p));q[k]=round(2*value-q[k],12)
        return grid_point(q)
    islands={}
    for inst in access['instances']:
        for term,data in inst['terminals'].items():
            for island in ri.terminal_islands(inst['name'],term,data):
                if island['id'] in islands:raise ValueError('Duplicate physical island identity')
                islands[island['id']]={'instance':inst['name'],'terminal':term,'net':data['net'],'island':island}
    output=copy.deepcopy(seed)
    if not seed.get('required_nets') or len(set(seed['required_nets']))!=len(seed['required_nets']):raise ValueError('Missing/duplicate required nets')
    if any(v['net'] not in seed['required_nets'] for kind in ('routes','vias','contact_landings') for v in seed.get(kind,[])):
        raise ValueError('Geometry outside declared routing scope')
    for kind in ('routes','vias','contact_landings'):output.setdefault(kind,[])
    for route in seed.get('routes',[]):
        clean(route['points_um'])
        if route.get('width_um') is None or finite(route['width_um'])<=0:raise ValueError('Explicit sized widths required')
        for p in route['points_um']:grid_point(p)
        for a in route.get('access',[]):grid_point(a['xy_um'])
    for kind in ('vias','contact_landings'):
        for item in seed.get(kind,[]):
            grid_point(item['xy_um'])
            if kind=='contact_landings':grid_point(item['pin_xy_um'])
    seen=set();sym=output.setdefault('symmetry_groups',[]);matching=output.setdefault('matching',[])
    for index,pair in enumerate(request.get('pairs',[])):
        check_keys(pair,['first_net','second_net','pin_pairs'])
        first,second=pair['first_net'],pair['second_net']
        if first==second or {first,second}&seen or not {first,second}<=set(seed['required_nets']):raise ValueError('Invalid/reused pair net')
        seen.update((first,second))
        if any(item['net']==second for kind in ('routes','vias','contact_landings') for item in seed.get(kind,[])):raise ValueError('Mate already has geometry; no overwrite')
        pairs=pair['pin_pairs'];mapping=dict(pairs)
        if len(mapping)!=len(pairs) or len(set(mapping.values()))!=len(mapping):raise ValueError('Non-bijective pin map')
        needed_first={i for i,v in islands.items() if v['net']==first};needed_second={i for i,v in islands.items() if v['net']==second}
        if not needed_first or set(mapping)!=needed_first or set(mapping.values())!=needed_second:raise ValueError('Incomplete electrical pin pairing')
        def mate_access(a,point_key='xy_um'):
            src=islands[a['pin_island_id']]
            if a['instance']!=src['instance'] or a['terminal']!=src['terminal']:raise ValueError('Wrong source terminal identity')
            q=reflect(a[point_key]);dst=islands[mapping[a['pin_island_id']]]
            if a[point_key] not in src['island'].get('candidate_centers',[]) or not any(all(abs(q[j]-p[j])<1e-9 for j in (0,1)) for p in dst['island'].get('candidate_centers',[])):
                raise ValueError('Non-mirrored physical access')
            return {'instance':dst['instance'],'terminal':dst['terminal'],'pin_island_id':mapping[a['pin_island_id']],point_key:q}
        for kind in ('routes','vias','contact_landings'):
            for item in seed.get(kind,[]):
                if item['net']!=first:continue
                new=copy.deepcopy(item);new['id']=f'mirror:{index}:'+item['id'];new['net']=second
                if kind=='routes':
                    new['points_um']=[reflect(p) for p in item['points_um']]
                    new['access']=[mate_access(a) for a in item.get('access',[])]
                else:
                    evidence=request.get('via_mirror_evidence',{}).get(item['via'])
                    if not evidence:raise ValueError('Via/contact reflection not PDK-qualified')
                    new['xy_um']=reflect(item['xy_um'])
                    if kind=='contact_landings':
                        new.update(mate_access(item,'pin_xy_um'))
                        if 'extension_bbox_um' in item:
                            pts=[reflect(p) for p in item['extension_bbox_um']]
                            new['extension_bbox_um']=[[min(p[j] for p in pts) for j in (0,1)],[max(p[j] for p in pts) for j in (0,1)]]
                output[kind].append(new)
        # Exact construction cannot be used to loosen existing circuit budgets.
        if not any({v['first_net'],v['second_net']}=={first,second} for v in matching):
            matching.append({'first_net':first,'second_net':second,'max_length_delta_um':0,'max_via_delta':0,
              'max_per_layer_length_delta_um':0,'max_bend_delta':0,'max_via_type_delta':0,'max_bbox_span_delta_um':0})
        sym.append({'id':f'compiled-pair-{index}','mode':'pair','first_net':first,'second_net':second,
                    'transform':'mirror_'+axis['coordinate'],'axis_um':value,'tolerance_um':min(1e-9,grid*1e-6)})
    for net in request.get('self_nets',[]):
        if net in seen or net not in seed['required_nets']:raise ValueError('Invalid self net')
        seen.add(net);sym.append({'id':'compiled-self-'+net,'mode':'self','net':net,
                                  'transform':'mirror_'+axis['coordinate'],'axis_um':value,'tolerance_um':min(1e-9,grid*1e-6)})
    constraints={v['net']:v for v in seed.get('net_constraints',[])}
    for net in seed['required_nets']:
        rule=constraints.get(net,{})
        if not rule.get('net_class'):raise ValueError('Missing explicit net class')
        if rule['net_class'] in ('power','ground','high_current') and not rule.get('width_basis'):raise ValueError('Missing supply width basis')
        if rule['net_class'] in ('differential','matched') and not any(net in (v['first_net'],v['second_net']) for v in matching):raise ValueError('Missing matching rule')
        if rule['net_class'] in ('differential','matched','sensitive','high_impedance','feedback') and not any(x in rule for x in ('max_detour_ratio','max_bbox_excursion_um')):raise ValueError('Missing sensitive-net directness budget')
    ids=[v['id'] for kind in ('routes','vias','contact_landings') for v in output[kind]]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate geometry ID')
    output['planning_evidence']={'obstacle_coverage':{'live_snapshot':False},'offline_obstacle_review':None,
                               'generator':'analog-layout-symmetric-fast: template-only; no obstacle solve'}
    intent=ri.build(profile,access,output)
    symmetry=symmetry_preflight(intent,axis)
    return {'status':'TEMPLATE_PREFLIGHT_PASS' if intent['validation']['valid'] and symmetry['status']=='PASS' else 'BLOCKED',
            'symmetry_preflight':symmetry,
            'materializable':False,'route_spec':output,'intent':intent,
            'pending':['Annotated SVG symmetry gate','Full live metal/via obstacle and environment review',
                       'DRC preflight per references/drc-constraints.md: actual edge spacing, same-net cut spacing, cross-cut stacking and enclosure; rule-table and fresh geometry evidence required',
                       'Foundry DRC/LVS/PEX']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('profile','terminal-access','request','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise ValueError('Output exists; choose a new run directory')
    def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
    result=compile_spec(read(args.profile),read(args.terminal_access),read(args.request))
    args.out.mkdir(parents=True)
    for name,data in [('template-result.json',result),('route-spec.json',result['route_spec']),('preflight-intent.json',result['intent'])]:
        (args.out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':result['status'],'materializable':False}))


if __name__=='__main__':main()
