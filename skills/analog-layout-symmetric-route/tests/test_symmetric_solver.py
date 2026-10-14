import copy, importlib.util, json, sys
from pathlib import Path
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'scripts'))
import symmetric_solver as S
from symmetric_geometry import SolverError, Geometry, via_objects, reflected, wire

def refresh(p,a,o,r):
    p['fingerprint']={'value':S.PLANNER.ROUTE.fingerprint(p)}
    o['sources']={'profile_fingerprint':p['fingerprint']['value'],'terminal_access_sha256':S.PLANNER.ROUTE.digest(a)}
    r['sources']={**o['sources'],'obstacles_sha256':S.PLANNER.ROUTE.digest(o)}

def fixture(mode='pair',count=2):
    geom={'cut_layer':'v23','cut_size_um':[.2,.2],'cut_spacing_um':[.2,.2],'rows':1,'columns':1,
          'layer1_enclosure_um':[.1,.1],'layer2_enclosure_um':[.1,.1]}
    p={'schema':S.PLANNER.ROUTE.PROFILE_SCHEMA,'technology':{'library':'example'},'manufacturing_grid_um':.1,
       'layers':[{'name':'m'+str(i)} for i in range(1,4)],'layer_purposes':[{'layer':'m'+str(i),'purpose':'drawing'} for i in range(1,4)],
       'layer_functions':[{'layer':'m'+str(i),'function':'metal','rank':2*i+7} for i in range(1,4)],'constraints':{'rules':[]},
       'routing_layers':[{'layer':'m'+str(i),'preferred_direction':'horizontal' if i%2==0 else 'vertical',
                         'minimum_width_rules':[{'value':.2,'parameters':None}],
                         'minimum_spacing_rules':[{'value':.2,'parameters':None}]} for i in (2,3)],
       'vias':[{'name':'V23','layer1':'m2','layer2':'m3','standard_geometry':geom}],
       'coverage':{'basic_routing_ready':True,'unknown_signoff_categories':[]},
       'boundaries':{'may_drive_automatic_routing':True},'validation':{'structurally_valid':True}}
    a={'schema':S.PLANNER.ROUTE.ACCESS_SCHEMA,'target':{'lib':'example','cell':'mirror','view':'layout'},'instances':[]}
    nets={};orbits=[]
    for side in ('L','R'):
        net=side if mode=='pair' else 'BIAS'
        for i in range(count):
            name=side+str(i);ident=name+':G:0';xy=[(-1 if side=='L' else 1)*(5-i),0 if i<2 else 2]
            island={'id':ident,'candidate_centers':[xy],'selected_center':xy,'access_layers':['m2']}
            a['instances'].append({'name':name,'terminals':{'G':{'net':net,'pin_islands':[island]}}})
            nets.setdefault(net,[]).append({'instance':name,'terminal':'G','pin_island_id':ident})
    orbits=[['L'+str(i)+':G:0','R'+str(i)+':G:0'] for i in range(count)]
    group={'id':'signal','mode':mode,'pin_pairs':orbits}
    group.update({'first_net':'L','second_net':'R'} if mode=='pair' else {'net':'BIAS'})
    o={'schema':S.PLANNER.OBSTACLE_SCHEMA,'target':a['target'],'bounds_um':[[-8,-5],[8,5]],'obstacles':[],
       'coverage':{'live_snapshot':False}}
    r={'schema':S.REQUEST_SCHEMA,'target':a['target'],'axis':{'coordinate':'x','value_um':0},'groups':[group],
       'nets':[{'net':n,'net_class':'differential' if mode=='pair' else 'bias','layers':['m2','m3'],
                'widths_um':{'m2':.4,'m3':.4},'max_bbox_excursion_um':5,'terminals':t} for n,t in nets.items()],
       'cut_rules':{'v23':{'spacing_um':.2,'source':'synthetic spacing fixture'}},
       'via_mirror_evidence':{'V23':{'geometry_sha256':S.PLANNER.ROUTE.digest(geom),'source':'synthetic symmetric array','mirror_verified':True}},
       'search':{'group_candidates':1,'top_k':1,'max_expansions':10000}}
    refresh(p,a,o,r);return p,a,o,r

def planned(args):
    result=S.solve(*args)
    assert result['status']=='PLANNED',result['failures']
    assert result['candidates'][0]['audit']['status']=='PASS'
    assert result['materializable'] is False
    return result['candidates'][0]

def blocked(args,code=None):
    result=S.solve(*args);assert result['status']=='BLOCKED',result
    if code:assert any(f['code']==code for f in result['failures']),result['failures']
    return result

def test_straight_pair():
    c=planned(fixture());assert not c['route_spec']['vias']
    assert c['metrics']['L']['path_length_um']==c['metrics']['R']['path_length_um']

def test_asymmetric_obstacle_forces_common_detour():
    p,a,o,r=fixture();o['obstacles']=[{'id':'right-only','layer':'m2','bbox_um':[[4.4,-.6],[4.6,.6]],'net':None}]
    refresh(p,a,o,r);c=planned((p,a,o,r));assert len(c['route_spec']['vias'])>=4
    assert c['metrics']['L']['layer_lengths_um']==c['metrics']['R']['layer_lengths_um']

def test_multiple_terminal_tree():
    c=planned(fixture(count=3));assert c['audit']['metrics']['L']['physical_access_count']==3

def test_connected_self_net():
    c=planned(fixture('self'));assert len(c['route_spec']['required_nets'])==1

@pytest.mark.parametrize('change,code',[
    ('hash','SOURCE_DRIFT'),('axis','AXIS_GRID_CONFLICT'),('cut','RULES_UNKNOWN'),
    ('mirror','VIA_MIRROR_UNKNOWN'),('mapping','INVALID_MAPPING'),('width','INVALID_WIDTH')])
def test_fail_closed(change,code):
    p,a,o,r=fixture()
    if change=='hash':r['sources']['obstacles_sha256']='stale'
    elif change=='axis':r['axis']['value_um']=.03
    elif change=='cut':r['cut_rules']={}
    elif change=='mirror':r['via_mirror_evidence']={}
    elif change=='mapping':r['groups'][0]['pin_pairs'].pop()
    elif change=='width':r['nets'][0]['widths_um']['m2']=.1
    blocked((p,a,o,r),code)

def test_budget_is_not_unsat():
    p,a,o,r=fixture();r['search']['max_expansions']=1
    blocked((p,a,o,r),'BUDGET_EXHAUSTED')

def test_pair_axis_short_blocked():
    p,a,o,r=fixture()
    for inst in a['instances']:
        if inst['name'].endswith('1'):
            island=inst['terminals']['G']['pin_islands'][0];island['candidate_centers']=[[0,0]];island['selected_center']=[0,0]
    refresh(p,a,o,r);blocked((p,a,o,r),'PAIR_CROSSES_AXIS')

def test_hard_direction_no_same_layer_turn():
    p,a,o,r=fixture(count=3)
    for net in r['nets']:net['layers']=['m2'];net['widths_um']={'m2':.4}
    blocked((p,a,o,r),'NO_PATH_IN_GRAPH')

@pytest.mark.parametrize('mode',['pair','self'])
def test_half_grid_axis(mode):
    p,a,o,r=fixture(mode);r['axis']['value_um']=.05
    for inst in a['instances']:
        if inst['name'].startswith('R'):
            island=inst['terminals']['G']['pin_islands'][0]
            island['candidate_centers'][0][0]+=.1;island['selected_center']=island['candidate_centers'][0]
    refresh(p,a,o,r);planned((p,a,o,r))

def test_access_fallback_is_joint():
    p,a,o,r=fixture()
    for inst in a['instances']:
        island=inst['terminals']['G']['pin_islands'][0];x=island['candidate_centers'][0][0]
        island['candidate_centers'].append([x,2])
    o['obstacles']=[{'layer':'m2','bbox_um':[[3.6,-.4],[4.4,.4]],'net':None}]
    refresh(p,a,o,r);c=planned((p,a,o,r))
    assert any(att['xy_um'][1]==2 for route in c['route_spec']['routes'] for att in route['access'])

def test_pin_map_does_not_relax_for_unmirrored_access():
    p,a,o,r=fixture();island=a['instances'][2]['terminals']['G']['pin_islands'][0]
    island['candidate_centers']=[[5,.1]];island['selected_center']=[5,.1];refresh(p,a,o,r)
    blocked((p,a,o,r),'NO_MIRRORED_ACCESS')

def test_level_ordinal_uses_real_stack_not_technology_rank():
    p,a,o,r=fixture();c=planned((p,a,o,r))
    assert all(route['points_um'][0][1]==route['points_um'][1][1] for route in c['route_spec']['routes'])
    r['metal_levels']={'m1':1,'m2':3,'m3':2};blocked((p,a,o,r),'METAL_LEVEL_CONFLICT')

def test_same_net_cut_spacing_is_not_waived():
    p,a,o,r=fixture();g=Geometry(S.PLANNER,p,o,r);via=g.vias['V23']
    one=via_objects(via,[0,0],'SAME','one');two=via_objects(via,[.3,0],'SAME','two')
    assert not g.clear(one+two)

def test_cross_cut_stacking_needs_sourced_rule_and_common_center():
    p,a,o,r=fixture();g=Geometry(S.PLANNER,p,o,r)
    one={'kind':'cut','layer':'v23','net':'N','bbox_um':[[0,0],[.2,.2]]}
    two={**one,'layer':'v12'}
    with pytest.raises(SolverError,match='Cross-cut'):g.compatible(one,two)
    r['cross_cut_rules']=[{'layers':['v12','v23'],'spacing_um':.2,'source':'fixture','stacking_allowed':True}]
    g=Geometry(S.PLANNER,p,o,r);assert g.compatible(one,two)
    two['bbox_um']=[[.01,0],[.21,.2]];assert not g.compatible(one,two)

def test_illegal_via_array_cut_pitch():
    p,a,o,r=fixture();geom=p['vias'][0]['standard_geometry'];geom.update(columns=2,cut_spacing_um=[.05,.2])
    for net in r['nets']:net['widths_um']={'m2':1,'m3':1}
    r['via_mirror_evidence']['V23']['geometry_sha256']=S.PLANNER.ROUTE.digest(geom);refresh(p,a,o,r)
    blocked((p,a,o,r),'ILLEGAL_VIA_ARRAY')

def test_legal_multicut_array_and_width_qualification():
    p,a,o,r=fixture();geom=p['vias'][0]['standard_geometry'];geom.update(columns=3)
    for net in r['nets']:net['widths_um']={'m2':1.2,'m3':1.2}
    r['via_mirror_evidence']['V23']['geometry_sha256']=S.PLANNER.ROUTE.digest(geom);refresh(p,a,o,r)
    g=Geometry(S.PLANNER,p,o,r);assert g.qualified_via('V23',r['nets'][0]['widths_um'],r['axis'])
    assert len([o for o in via_objects(g.vias['V23'],[0,0],'N') if o['kind']=='cut'])==3

def test_unknown_via_offsets_block():
    p,a,o,r=fixture();geom=p['vias'][0]['standard_geometry'];geom['offset_um']=[.1,0]
    r['via_mirror_evidence']['V23']['geometry_sha256']=S.PLANNER.ROUTE.digest(geom);refresh(p,a,o,r)
    blocked((p,a,o,r),'UNSUPPORTED_VIA')

def test_independent_audit_rejects_removed_via_landing_and_island():
    p,a,o,r=fixture();o['obstacles']=[{'layer':'m2','bbox_um':[[4.4,-.6],[4.6,.6]],'net':None}];refresh(p,a,o,r)
    spec=planned((p,a,o,r))['route_spec'];spec['routes']=[route for route in spec['routes'] if not route['access']]
    from symmetric_audit import audit
    result=audit(p,a,o,r,spec,S.PLANNER,S.MIRROR);assert result['status']=='BLOCKED'

def test_single_island_requires_real_sourced_escape():
    args=fixture(count=1);blocked(args,'PIN_WITHOUT_CONDUCTOR')
    for net in args[3]['nets']:
        x=-6 if net['net']=='L' else 6
        net['terminal_escape']={'pin_island_id':net['terminals'][0]['pin_island_id'],'layer':'m2','end_xy_um':[x,0],'source':'explicit external pin escape'}
    planned(args)

def test_m1_union_length_and_local_region():
    p,a,o,r=fixture();p['routing_layers'].append({'layer':'m1','preferred_direction':'vertical',
        'minimum_width_rules':[{'value':.2}],'minimum_spacing_rules':[{'value':.2}]})
    r['local_access']={}
    for inst in a['instances']:
        island=inst['terminals']['G']['pin_islands'][0];x=-5 if inst['name'].startswith('L') else 5;y=0 if inst['name'].endswith('0') else 2
        island.update(candidate_centers=[[x,y]],selected_center=[x,y],access_layers=['m1'])
        r['local_access'][island['id']]={'source':'measured local region','region_um':[[x-.5,-.5],[x+.5,2.5]],'max_length_um':3}
    for net in r['nets']:net.update(layers=['m1'],widths_um={'m1':.4})
    refresh(p,a,o,r);c=planned((p,a,o,r));assert c['audit']['local_access'][0]['union_length_um']==2
    for rule in r['local_access'].values():rule['max_length_um']=1
    from symmetric_audit import audit
    assert audit(p,a,o,r,c['route_spec'],S.PLANNER,S.MIRROR)['status']=='BLOCKED'

def test_ordinary_exception_must_be_explicit():
    p,a,o,r=fixture('self');r['groups']=[{'id':'ordinary','mode':'ordinary','net':'BIAS'}]
    blocked((p,a,o,r),'UNSCOPED_ASYMMETRY')

def test_soft_regions_have_effect_on_search_cost():
    p,a,o,r=fixture();o['obstacles']=[{'layer':'m2','bbox_um':[[4.2,-.5],[4.8,.5]],'hard':False,'cost_per_um':100,'source':'sensitivity cost'}]
    refresh(p,a,o,r);c=planned((p,a,o,r));assert c['route_spec']['vias']

def test_more_than_one_candidate_and_determinism():
    p,a,o,r=fixture();r['search'].update(group_candidates=3,top_k=2)
    result=S.solve(p,a,o,r);assert len(result['candidates'])>=2,result['failures']
    assert [c['route_spec'] for c in result['candidates']]==[c['route_spec'] for c in S.solve(p,a,o,r)['candidates']]

def test_renaming_nets_changes_no_geometry():
    p,a,o,r=fixture();old=planned((p,a,o,r))['route_spec']
    names={'L':'INPUT_A','R':'INPUT_B'}
    for inst in a['instances']:inst['terminals']['G']['net']=names[inst['terminals']['G']['net']]
    for net in r['nets']:net['net']=names[net['net']]
    r['groups'][0].update(first_net='INPUT_A',second_net='INPUT_B');refresh(p,a,o,r)
    new=planned((p,a,o,r))['route_spec']
    assert [v['points_um'] for v in old['routes']]==[v['points_um'] for v in new['routes']]

@pytest.mark.parametrize('mode',['pair','self'])
def test_horizontal_axis_keeps_metal_directions(mode):
    p,a,o,r=fixture(mode);r['axis']['coordinate']='y';o['bounds_um']=[[-5,-8],[5,8]]
    for inst in a['instances']:
        island=inst['terminals']['G']['pin_islands'][0];xy=island['candidate_centers'][0];xy[:]=[xy[1],xy[0]]
        island['selected_center']=xy;island['access_layers']=['m3']
    refresh(p,a,o,r);planned((p,a,o,r))

def test_atomic_ripup_reorder_resolves_multinet_conflict():
    p,a,o,r=fixture();positions={'L0':[-6,0],'L1':[6,0],'R0':[-1,0],'R1':[1,0]}
    for inst in a['instances']:
        island=inst['terminals']['G']['pin_islands'][0];island.update(candidate_centers=[positions[inst['name']]],selected_center=positions[inst['name']])
    for net in r['nets']:net['net_class']='ordinary'
    r['nets'][1].update(layers=['m2'],widths_um={'m2':.4})
    r['groups']=[{'id':n,'mode':'ordinary','net':n,'reason':'explicit single-ended test'} for n in ('L','R')]
    r['search']['max_orderings']=2;refresh(p,a,o,r)
    result=S.solve(p,a,o,r);assert result['status']=='PLANNED',result['failures']
    assert result['orderings']==[['L','R'],['R','L']]
    assert result['failures'][0]['group']=='R'
    assert result['candidates'][0]['route_spec']['vias']

def test_configured_dispatch_and_legacy_backend():
    p,a,o,r=fixture();module=S.sibling('test_configured_route',HERE.parent/'analog-layout-route/scripts/configured_route.py')
    policy={'backend':'strict_symmetric','nets':{n['net']:{k:v for k,v in n.items() if k not in ('net','terminals')} for n in r['nets']},
            'symmetry_solver':{k:r[k] for k in ('axis','groups','search')}}
    pdk={'technology_library':'example','routing_rules':{k:r[k] for k in ('cut_rules','via_mirror_evidence')}}
    result=module.search(p,a,policy,pdk,o,a['target']);assert result['status']=='PLANNED',result['failures']
    assert result['backend']==S.BACKEND
    # Existing ordinary general planning remains selectable without the new contract.
    policy={'backend':'general','nets':{n['net']:{'net_class':'ordinary','layers':['m2','m3'],'widths_um':n['widths_um']} for n in r['nets']}}
    general=module.search(p,a,policy,{'technology_library':'example'},o,a['target'])
    assert general['status']=='PLANNED',general['failures']

def test_configured_flow_invalidates_stale_selected_candidate(tmp_path):
    sys.path.insert(0,str(HERE.parent/'analog-layout-workflow/scripts'))
    p,a,o,r=fixture();flow=S.sibling('test_joint_configured_flow',HERE.parent/'analog-layout-workflow/scripts/configured_flow.py')
    for name,value in [('profile',p),('access',a),('obstacles',o)]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
    project={'_base':str(tmp_path),'target':a['target'],'_project_sha256':'fixture','_bindings':{},
             'inputs':{'routing_profile':'profile.json','terminal_access':'access.json','obstacles':'obstacles.json'},
             'routing':{'backend':'strict_symmetric','nets':{n['net']:{k:v for k,v in n.items() if k not in ('net','terminals')} for n in r['nets']},
                        'symmetry_solver':{k:r[k] for k in ('axis','groups','search')}},
             'pdk':{'technology_library':'example','routing_rules':{k:r[k] for k in ('cut_rules','via_mirror_evidence')}}}
    first=flow.route(project,tmp_path/'out');assert first['status']=='PLANNED',first
    project['routing']['symmetry_solver']['groups'][0]['pin_pairs'].pop()
    second=flow.route(project,tmp_path/'out');assert second['status']=='BLOCKED'
    intent=json.loads((tmp_path/'out/routing/strict-symmetric/intent.json').read_text(encoding='utf-8'))
    assert intent['decision']['status']=='BLOCKED' and not intent['routes']
    assert intent['configuration_gate']['request_sha256']!=r['sources']['obstacles_sha256']
    project['routing']['symmetry_solver']['unrecognized']='invalid'
    third=flow.route(project,tmp_path/'out');assert third['status']=='BLOCKED'
    assert third['failures'][0]['code']=='INVALID_CONFIGURATION'

def test_layer_changes_count_toward_bend_limit():
    p,a,o,r=fixture();o['obstacles']=[{'layer':'m2','bbox_um':[[4.4,-.6],[4.6,.6]],'net':None}];refresh(p,a,o,r)
    for net in r['nets']:net['max_bends']=0
    result=blocked((p,a,o,r),'INDEPENDENT_AUDIT_FAILED')
    assert any(e['code']=='BEND_LIMIT' for f in result['failures'] if isinstance(f['reason'],dict) for e in f['reason']['errors'])
    for net in r['nets']:net['max_bends']=20
    c=planned((p,a,o,r));intent=S.verified_intent(p,a,c)
    assert intent['net_metrics']['L']['bend_count']>0
    assert intent['net_metrics']['L']['bend_count']==intent['net_metrics']['L']['layer_transition_bend_count']

def test_overlapping_landings_do_not_inflate_length():
    from symmetric_audit import union_length
    p,a,o,r=fixture(count=3);o['obstacles']=[{'layer':'m2','bbox_um':[[4.4,-.6],[4.6,.6]],'net':None}];refresh(p,a,o,r)
    c=planned((p,a,o,r));routes=[route for route in c['route_spec']['routes'] if route['net']=='L']
    assert abs(c['metrics']['L']['path_length_um']-union_length(routes))<1e-9

def test_fixed_point_singleton_requires_sourced_escape():
    p,a,o,r=fixture('self',count=1);a['instances']=a['instances'][:1]
    island=a['instances'][0]['terminals']['G']['pin_islands'][0];island.update(candidate_centers=[[0,0]],selected_center=[0,0])
    r['nets'][0]['terminals']=r['nets'][0]['terminals'][:1];r['groups'][0]['pin_pairs']=[[island['id'],island['id']]]
    refresh(p,a,o,r);blocked((p,a,o,r),'PIN_WITHOUT_CONDUCTOR')
    r['nets'][0]['terminal_escape']={'pin_island_id':island['id'],'layer':'m3','end_xy_um':[0,2],'source':'intended top-level escape'}
    planned((p,a,o,r))

def test_export_cannot_reuse_stale_audit():
    p,a,o,r=fixture();c=planned((p,a,o,r));c['route_spec']['routes'][0]['width_um']=.6
    with pytest.raises(SolverError,match='stale'):S.verified_intent(p,a,c)

def test_ordinary_vias_do_not_need_mirror_evidence():
    p,a,o,r=fixture('self',count=3);r['groups']=[{'id':'single','mode':'ordinary','net':'BIAS','reason':'single-ended test'}]
    r['via_mirror_evidence']={};planned((p,a,o,r))

def test_standalone_cli_emits_bound_review_sidecars(tmp_path):
    import subprocess
    p,a,o,r=fixture()
    for name,value in [('profile',p),('access',a),('obstacles',o),('request',r)]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
    command=[sys.executable,str(HERE/'scripts/symmetric_solver.py')]
    for name in ('profile','access','obstacles','request'):command+=['--'+name,str(tmp_path/(name+'.json'))]
    command+=['--out',str(tmp_path/'out')]
    run=subprocess.run(command,capture_output=True,text=True);assert run.returncode==0,run.stderr+run.stdout
    assert (tmp_path/'out/input-audit.json').is_file() and (tmp_path/'out/routing-review.md').is_file()
    assert (tmp_path/'out/candidate-0/drc-preflight.json').is_file()
    second=subprocess.run(command,capture_output=True,text=True);assert second.returncode==2
