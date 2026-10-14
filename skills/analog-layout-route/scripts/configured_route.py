"""Build a complete planner request from network policy and actual pin islands."""
from pathlib import Path
import copy, importlib.util

spec=importlib.util.spec_from_file_location('configured_planner',Path(__file__).with_name('route_planner.py'))
PLANNER=importlib.util.module_from_spec(spec);spec.loader.exec_module(PLANNER)
helper_spec=importlib.util.spec_from_file_location('configured_obstacles',Path(__file__).with_name('prepare_planner_inputs.py'))
HELPER=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(HELPER)

def candidate_intent(profile,access,candidate):
    if not candidate.get('audit'):return PLANNER.ROUTE.build(profile,access,candidate['route_spec'])
    solver_spec=importlib.util.spec_from_file_location('configured_verified_intent',Path(__file__).resolve().parents[2]/'analog-layout-symmetric-route/scripts/symmetric_solver.py')
    solver=importlib.util.module_from_spec(solver_spec);solver_spec.loader.exec_module(solver)
    return solver.verified_intent(profile,access,candidate)

def symmetric_evidence(out,profile,access,result):
    import sys
    scripts=Path(__file__).resolve().parents[2]/'analog-layout-symmetric-route/scripts'
    if str(scripts) not in sys.path:sys.path.insert(0,str(scripts))
    from symmetric_artifacts import context,selected
    context(out,profile,access,result['configured_obstacles'],result['configured_request'],result,PLANNER)
    if result['candidates']:
        candidate=result['candidates'][0]
        selected(out,candidate,candidate_intent(profile,access,candidate),result['configured_request'])
    else:
        for name in ('symmetry-audit','drc-preflight','direction-audit'):
            (Path(out)/(name+'.json')).write_text(__import__('json').dumps({'status':'BLOCKED','reason':'NO_CURRENT_CANDIDATE','materializable':False}),encoding='utf-8')

def search(profile,access,policy,pdk,obstacles=None,target=None):
    backend=policy.get('backend','symmetric_fast')
    if backend=='symmetric_fast':
        fast_spec=importlib.util.spec_from_file_location('configured_fast_templates',Path(__file__).resolve().parents[2]/'analog-layout-symmetric-fast/scripts/fast_route.py')
        fast=importlib.util.module_from_spec(fast_spec);fast_spec.loader.exec_module(fast)
        return fast.configured_search(profile,access,policy,pdk,obstacles,target)
    if target and access['target']!=target: raise ValueError('Terminal-access target differs from project')
    if profile.get('source_target') and profile['source_target']!=access['target']: raise ValueError('PDK profile target drift')
    if pdk.get('technology_library') and profile['technology']['library']!=pdk['technology_library']:
        raise ValueError('PDK mapping and routing technology differ')
    if obstacles is None:
        obstacles,_=HELPER.build(profile,access,policy.get('bounds_margin_um',5))
    obstacles=copy.deepcopy(obstacles)
    nets={}
    for inst in access['instances']:
        for terminal,data in inst['terminals'].items():
            net=data.get('net')
            if not net: raise ValueError('Missing terminal network')
            for island in PLANNER.terminal_islands(inst['name'],terminal,data):
                nets.setdefault(net,[]).append({'instance':inst['name'],'terminal':terminal,'pin_island_id':island['id']})
    if set(policy.get('nets',{}))!=set(nets):
        raise ValueError('Network policies must cover exact access nets; missing='+str(sorted(set(nets)-set(policy.get('nets',{}))))+' extra='+str(sorted(set(policy.get('nets',{}))-set(nets))))
    order=policy.get('order',sorted(nets))
    if set(order)!=set(nets) or len(order)!=len(nets): raise ValueError('Invalid network order')
    layer_roles=pdk.get('layer_roles',{});requests=[]
    for net in order:
        settings=copy.deepcopy(policy['nets'][net])
        if set(settings)&{'net','terminals'}: raise ValueError('Network identity and terminals are generated from access evidence')
        if not settings.get('net_class'): raise ValueError('Explicit network class required')
        layers=settings.pop('layer_roles',None)
        if layers is not None:
            if any(role not in layer_roles for role in layers): raise ValueError('Unknown routing layer role')
            settings['layers']=[layer_roles[role] for role in layers]
        widths=settings.pop('widths_by_role_um',None)
        if widths is not None: settings['widths_um']={layer_roles[k]:v for k,v in widths.items()}
        requests.append({'net':net,**settings,'terminals':nets[net]})
    sources={'profile_fingerprint':profile['fingerprint']['value'],'terminal_access_sha256':PLANNER.ROUTE.digest(access),'obstacles_sha256':PLANNER.ROUTE.digest(obstacles)}
    request={'schema':PLANNER.REQUEST_SCHEMA,'target':access['target'],'sources':sources,'nets':requests,
        'matching':copy.deepcopy(policy.get('matching',[])),'symmetry_groups':copy.deepcopy(policy.get('symmetry_groups',[])),
        'reserve_matched_pairs_first':True,**copy.deepcopy(policy.get('search',{}))}
    # Search costs are configurable, but cannot overwrite connectivity or identity.
    allowed={'bend_cost_um','via_cost_um','off_direction_penalty','access_candidate_limit','access_beam_width','topology_frontier_limit','shared_tree','metal_area_weight'}
    if set(policy.get('search',{}))-allowed: raise ValueError('Unsupported search option')
    directions=policy.get('preferred_directions_by_role')
    if directions: request['preferred_directions']={layer_roles[k]:v for k,v in directions.items()}
    backend=policy.get('backend','symmetric_fast')
    if backend=='strict_symmetric':
        solver_spec=importlib.util.spec_from_file_location('configured_joint_solver',Path(__file__).resolve().parents[2]/'analog-layout-symmetric-route/scripts/symmetric_solver.py')
        solver=importlib.util.module_from_spec(solver_spec);solver_spec.loader.exec_module(solver)
        settings=copy.deepcopy(policy.get('symmetry_solver',{}));rules=copy.deepcopy(pdk.get('routing_rules',{}))
        allowed_settings={'axis','groups','search','costs','local_access'}
        allowed_rules={'metal_levels','cut_rules','cross_cut_rules','via_mirror_evidence'}
        if set(settings)-allowed_settings or set(rules)-allowed_rules:raise ValueError('Unsupported strict solver/PDK rule fields')
        if policy.get('search') or policy.get('symmetry_groups') or policy.get('preferred_directions_by_role'):
            raise ValueError('Strict backend uses symmetry_solver.search/groups and hard odd/even directions; migrate general options explicitly')
        request={'schema':solver.REQUEST_SCHEMA,'target':access['target'],'sources':sources,'nets':requests,
                 'matching':copy.deepcopy(policy.get('matching',[])),**rules,**settings}
        result=solver.solve(profile,access,obstacles,request)
    elif backend=='general':result=PLANNER.plan(profile,access,obstacles,request)
    else:raise ValueError('Unknown routing backend: '+str(backend))
    result['configured_request']=request;result['configured_obstacles']=obstacles
    result['configuration_sha256']=PLANNER.ROUTE.digest({'policy':policy,'pdk':pdk})
    # Offline search never grants live materialization, even if the data declares live coverage.
    result['materializable']=False
    result['execution_scope']='Offline candidate search; unchanged OA, DRC/LVS/PEX and existing routed evidence'
    return result
