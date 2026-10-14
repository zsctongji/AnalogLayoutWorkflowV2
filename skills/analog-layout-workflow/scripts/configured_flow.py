"""Configuration-driven offline placement and routing. Never opens or writes OA."""
from pathlib import Path
import argparse, copy, importlib.util, json, math, sys
from project_config import load_project, normalize_schematic, configured_groups, read, digest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'analog-layout-align/scripts'))
import placement_flow as placement

def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def resolve(project,value):
    return (Path(project['_base'])/value).resolve()

def prepare(project,work):
    source=read(resolve(project,project['inputs']['schematic']))
    actual=source.get('source',{})
    if any(actual.get(k)!=v for k,v in project['source'].items()): raise ValueError('Schematic target differs from project')
    normalized,bindings=normalize_schematic(source,project['pdk'])
    copies,_=placement.expand_mos_copies(normalized)
    for item in copies:
        binding=bindings[item['logical_device']]
        item['pcell_master']=copy.deepcopy(binding['master'])
        item['pcell_parameter_entries']=copy.deepcopy(binding['entries'])
        item['source_parameters']=binding['source_parameters']
        item['pdk_mapping_sha256']=project['_bindings']['pdk']['sha256']
    circuit=project['circuit']
    if circuit.get('modules'):
        groups,associations=configured_groups(copies,circuit['modules'])
        intent=placement.infer_intent(normalized,circuit.get('module_map'))
    else:
        from functional_groups import prepare_groups
        intent,_,groups,associations=prepare_groups(normalized,circuit)
    plan=Path(work)/'plan'
    for name,data in [('schematic.json',normalized),('device-copies.json',copies),('copy-groups.json',groups),('dummy-associations.json',associations),('intent.json',intent),('floorplan-policy.json',circuit['floorplan'])]:
        write(plan/name,data)
    manifest={'schema':'analog-layout-workflow.configuration-binding/v1','project_sha256':project['_project_sha256'],
        'configurations':project['_bindings'],'source_schematic_sha256':digest(source),'target':project['target'],
        'copies_sha256':digest(copies),'groups_sha256':digest(groups),'materializable':False}
    write(plan/'configuration-binding.json',manifest)
    return manifest

def place(project,work):
    prepare(project,work);plan=Path(work)/'plan'
    geometry=read(resolve(project,project['inputs']['pcell_geometry']))
    copies=read(plan/'device-copies.json');grid=geometry['manufacturing_grid']
    for item in copies:
        measured=geometry['devices'].get(item['logical_device'])
        if measured is None or measured['pcell_master']!=item['pcell_master']: raise ValueError('Missing/stale PCell master measurement')
        if measured.get('pcell_parameter_entries') is not None:
            if measured['pcell_parameter_entries']!=item['pcell_parameter_entries'] or measured.get('pdk_mapping_sha256')!=item['pdk_mapping_sha256']:
                raise ValueError('Measured PDK mapping changed; measure again')
        else:
            # Legacy evidence may be reused only for the exact old importer mapping.
            from apply_placement_intent import pcell_params
            legacy={k:v for k,v in item.items() if k!='pcell_parameter_entries'}
            sys.path.insert(0,str(ROOT/'analog-layout-guard-ring/scripts'))
            from inspect_reference import parse_lisp
            old=parse_lisp(pcell_params(legacy).replace('list(', '('));new=parse_lisp(pcell_params(item).replace('list(', '('))
            if sorted(old)!=sorted(new):
                raise ValueError('Legacy measurement does not cover mapped PCell parameters; measure again')
        # Compare the measured geometry inputs, not schematic-only derived fields.
        from project_config import numeric
        for key,value in measured.get('pcell_parameters',{}).items():
            expected=item['pcell_parameters'].get(key)
            if expected is None: raise ValueError('Measured parameter absent from current mapping: '+key)
            try: equal=abs(numeric(value)-numeric(expected))<=max(1e-15,abs(numeric(value))*1e-9)
            except ValueError: equal=str(value)==str(expected)
            if not equal: raise ValueError('Stale geometry parameter: '+item['name']+':'+key)
    write(plan/'pcell-geometry.json',geometry)
    policy=project['circuit']['floorplan']
    if any(not math.isfinite(policy[k]) or policy[k]<0 for k in ('device_gap_um','macro_gap_um')):
        raise ValueError('Finite nonnegative placement gaps required')
    placement.cmd_legalize_pcells(argparse.Namespace(work=Path(work),device_gap=policy['device_gap_um'],macro_gap=policy['macro_gap_um'],floorplan_policy=policy))
    output=read(plan/'placement-intent.json')
    for group in output['groups']:
        if group.get('matching_mode') not in ('common_axis','common_centroid'): raise ValueError('Unsupported matching mode')
        members=[i for i in output['instances'] if i['group']==group['name'] and i['placement_role']=='active']
        centers={}
        for logical in group['logical_devices']:
            devices=[i for i in members if i['logical_device']==logical]
            centers[logical]=[sum(i['bbox_center'][d] for i in devices)/len(devices) for d in (0,1)]
        if len(centers)>1:
            dimensions=(0,1) if group['matching_mode']=='common_centroid' else (0,)
            if any(max(v[d] for v in centers.values())-min(v[d] for v in centers.values())>grid*1e-6 for d in dimensions):
                raise ValueError('Configured matching centers fail: '+group['name'])
    output['configuration_binding']=read(plan/'configuration-binding.json')
    output['configuration_binding']['geometry_sha256']=digest(geometry)
    output['validation']['configured_matching_checks']=True
    output['coordinate_contract']['space']='supplied PCell bbox evidence (offline replay)'
    evidence=geometry.get('basis',geometry.get('source','hash-bound supplied measurement'))
    output['coordinate_contract']['geometry_evidence']=evidence
    output['floorplan']['module_axes_x_um']=output['validation']['core_center_x']
    output['floorplan']['axis_scope']='common_core' if output['validation']['core_center_aligned'] else 'module_local'
    if not output['validation']['core_center_aligned']: output['floorplan']['core_axis_x']=None
    write(plan/'placement-intent.json',output)
    summary=(plan/'summary.md').read_text(encoding='utf-8')
    summary=summary.replace('Evaluated PCell variants','Supplied PCell geometry variants')
    summary=summary.replace('The coordinates use live evaluated PCell bounding boxes','The coordinates replay the supplied PCell bounding box evidence offline')
    if not output['validation']['core_center_aligned']:
        summary=summary.replace('Core macro center aligned at x =','Common core axis unavailable; reference x =')
    (plan/'summary.md').write_text('Offline candidate; geometry evidence: '+str(evidence)+'\n\n'+summary,encoding='utf-8')
    return {'status':'OFFLINE_PLACEMENT_CANDIDATE','instances':len(output['instances']),'materializable':False}

def macro_opt(project,work):
    """Search a complete measured macro snapshot under external circuit constraints."""
    snapshot=read(resolve(project,project['inputs']['macro_snapshot']))
    if snapshot.get('source')!=project['target']: raise ValueError('Macro snapshot target differs from project')
    settings=copy.deepcopy(project['circuit']['macro_optimization'])
    if set(settings)&{'schema','snapshot_sha256'}: raise ValueError('Macro identity is generated from measured inputs')
    request={'schema':'analog-layout-macro-opt.request/v1','snapshot_sha256':digest(snapshot),**settings}
    spec=importlib.util.spec_from_file_location('configured_macro_opt',ROOT/'analog-layout-macro-opt/scripts/macro_opt.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.optimize(snapshot,request)
    result['materializable']=False
    result['configuration_binding']={'project_sha256':project['_project_sha256'],'configurations':project['_bindings']}
    write(Path(work)/'macro-opt/request.json',request);write(Path(work)/'macro-opt/candidates.json',result)
    return {'status':result['status'],'candidates':len(result['candidates']),'materializable':False}

def route(project, work, strict=False, fast=False):
    module_spec = importlib.util.spec_from_file_location('configured_route', ROOT / 'analog-layout-route/scripts/configured_route.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    policy = copy.deepcopy(project['routing'])
    if strict:
        policy['backend'] = 'strict_symmetric'
    elif fast:
        policy['backend'] = 'symmetric_fast'
    policy.setdefault('backend', 'symmetric_fast')
    backend = policy['backend']
    profile = access = obstacles = None
    try:
        profile = read(resolve(project, project['inputs']['routing_profile']))
        access = read(resolve(project, project['inputs']['terminal_access']))
        obstacles = read(resolve(project, project['inputs']['obstacles'])) if project['inputs'].get('obstacles') else None
        result = module.search(profile, access, policy, project['pdk'], obstacles, target=project['target'])
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
        observed_nets = set()
        for inst in access.get('instances', []) if isinstance(access, dict) and isinstance(access.get('instances', []), list) else []:
            if not isinstance(inst, dict) or not isinstance(inst.get('terminals'), dict):
                continue
            for data in inst['terminals'].values():
                if isinstance(data, dict) and isinstance(data.get('net'), str):
                    observed_nets.add(data['net'])
        required = sorted(observed_nets)
        request = {'schema': 'analog-layout-routing.configuration-error/v1', 'target': project['target'],
                   'backend': backend, 'policy_sha256': digest(policy), 'pdk_sha256': digest(project['pdk']),
                   'nets': [{'net': net} for net in required]}
        unavailable = {'schema': module.PLANNER.OBSTACLE_SCHEMA, 'target': project['target'],
                       'coverage': {'live_snapshot': False}, 'status': 'UNAVAILABLE',
                       'reason': 'Configuration/input preflight failed; no obstacle evidence invented'}
        result = {'schema': module.PLANNER.CANDIDATE_SCHEMA, 'backend': backend, 'status': 'BLOCKED',
                  'candidates': [], 'failures': [{'code': 'INVALID_CONFIGURATION', 'reason': str(error)}],
                  'configured_request': request, 'configured_obstacles': obstacles if obstacles is not None else unavailable,
                  'materializable': False, 'search_statistics': {'expansions': 0, 'searches': 0}}
    result['configuration_binding'] = {'project_sha256': project['_project_sha256'], 'configurations': project['_bindings']}
    routing = Path(work) / 'routing'
    if backend == 'strict_symmetric':
        routing /= 'strict-symmetric'
    elif backend == 'symmetric_fast':
        routing /= 'symmetric-fast'
    write(routing / 'request.json', result['configured_request'])
    write(routing / 'obstacles.json', result['configured_obstacles'])
    if result['candidates']:
        candidate = result['candidates'][0]
        write(routing / 'spec.json', candidate['route_spec'])
        if candidate.get('template_preflight'):
            write(routing / 'template-result.json', candidate['template_preflight'])
            write(routing / 'direction-audit.json', candidate['template_preflight']['direction_audit'])
        if candidate.get('audit'):
            write(routing / 'symmetric-audit.json', candidate['audit'])
        intent = module.candidate_intent(profile, access, candidate)
        intent['configuration_gate'] = {'status': result['status'], 'materializable': False, 'request_sha256': digest(result['configured_request'])}
        write(routing / 'intent.json', intent)
        preview = routing / 'preview.svg'
        preview.write_text(module.PLANNER.ROUTE.svg(intent), encoding='utf-8')
        check_spec = importlib.util.spec_from_file_location('configured_svg_check', ROOT / 'analog-layout-route/scripts/svg_route_check.py')
        checker = importlib.util.module_from_spec(check_spec)
        check_spec.loader.exec_module(checker)
        audit = checker.build_check(routing / 'intent.json', preview)
        write(routing / 'svg-check.json', audit)
        if audit['status'] != 'PASS':
            result['status'] = 'BLOCKED'
            result['failures'].append({'code': 'SVG_CHECK_FAILED', 'reason': audit})
            result['candidates'] = []
    if not result['candidates']:
        # Clear every selected artifact even after unreadable/missing evidence or SVG failure.
        request = result['configured_request']
        required = request.get('seed_spec', {}).get('required_nets', [n['net'] for n in request.get('nets', [])])
        blocked_spec = {'schema': module.PLANNER.ROUTE.SPEC_SCHEMA, 'target': project['target'],
                        'routes': [], 'vias': [], 'required_nets': required,
                        'planning_evidence': {'request_sha256': digest(request), 'materializable': False}}
        write(routing / 'spec.json', blocked_spec)
        intent = {'schema': module.PLANNER.ROUTE.INTENT_SCHEMA, 'target': project['target'],
                  'routes': [], 'vias': [], 'required_nets': required,
                  'decision': {'status': 'BLOCKED', 'materializable': False},
                  'validation': {'valid': False, 'errors': result['failures']},
                  'configuration_gate': {'status': 'BLOCKED', 'materializable': False, 'request_sha256': digest(request)}}
        write(routing / 'intent.json', intent)
        (routing / 'preview.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="60"><text x="10" y="35">BLOCKED: no current routing candidate</text></svg>', encoding='utf-8')
        for name in ('symmetric-audit', 'svg-check', 'direction-audit', 'drc-preflight', 'symmetry-audit'):
            write(routing / (name + '.json'), {'status': 'BLOCKED', 'errors': result['failures'], 'materializable': False})
        if backend == 'symmetric_fast':
            write(routing / 'template-result.json', {'status': 'BLOCKED', 'errors': result['failures'], 'materializable': False})
    elif backend == 'strict_symmetric':
        module.symmetric_evidence(routing, profile, access, result)
    write(routing / 'candidates.json', result)
    return {'status': result['status'], 'candidates': len(result['candidates']), 'materializable': False,
            'failures': result['failures'], 'output': str(routing)}


def symmetric_route(project,work):return route(project,work,strict=True)
def symmetric_fast(project,work):return route(project,work,fast=True)

def invalidate_routing_outputs(work, reason):
    """Invalidate only known offline frontend outputs when config cannot be read."""
    routing = Path(work) / 'routing'
    blocked = {'schema': 'analog-layout-route.blocked-output/v1', 'status': 'BLOCKED',
               'reason': reason, 'routes': [], 'vias': [], 'candidates': [], 'materializable': False,
               'decision': {'status': 'BLOCKED', 'materializable': False},
               'configuration_gate': {'status': 'BLOCKED', 'materializable': False, 'reason': reason}}
    write(routing / 'configuration-error.json', blocked)
    for out in (routing, routing / 'symmetric-fast', routing / 'strict-symmetric'):
        if not out.is_dir():
            continue
        for name in ('candidates', 'request', 'spec', 'intent', 'template-result', 'direction-audit',
                     'symmetric-audit', 'svg-check', 'drc-preflight', 'symmetry-audit'):
            if (out / (name + '.json')).exists():
                write(out / (name + '.json'), blocked)
        if (out / 'preview.svg').exists():
            (out / 'preview.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="60"><text x="10" y="35">BLOCKED: unreadable routing configuration</text></svg>', encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','prepare','place','macro-opt','route','symmetric-route','symmetric-fast'])
    parser.add_argument('--project',required=True,type=Path);parser.add_argument('--work',type=Path)
    args=parser.parse_args()
    try:project=load_project(args.project)
    except (ValueError,OSError,KeyError,TypeError) as error:
        if args.work and args.command in ('route','symmetric-route','symmetric-fast'):
            invalidate_routing_outputs(args.work,str(error))
        print(json.dumps({'status':'BLOCKED','materializable':False,'reason':str(error)}))
        return 2
    if args.command=='validate': result={'status':'CONFIG_VALID','bindings':project['_bindings']}
    else:
        if not args.work: parser.error('--work required for generated artifacts')
        result=globals()[args.command.replace('-','_')](project,args.work)
    print(json.dumps(result,ensure_ascii=False))
    return 2 if result.get('status')=='BLOCKED' else 0

if __name__=='__main__': raise SystemExit(main())
