"""Cross-design configuration behavior, PDK aliases and search invariants."""
from pathlib import Path
import copy, importlib.util, json, sys, tempfile, unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'analog-layout-workflow/scripts'))
from project_config import normalize_schematic,configured_groups,position_macros,load_project,typed_params,digest,read
from configured_flow import place,prepare,macro_opt,write
spec=importlib.util.spec_from_file_location('test_configured_route',ROOT/'analog-layout-route/scripts/configured_route.py')
ROUTER=importlib.util.module_from_spec(spec);spec.loader.exec_module(ROUTER)
fixture_spec=importlib.util.spec_from_file_location('planner_fixture',ROOT/'analog-layout-route/tests/test_route_planner.py')
FIX=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(FIX)

def mapping():
    return {'schema':'analog-layout-workflow.pdk-map/v1','technology_library':'pdk','layer_roles':{'local':'m1'},
        'devices':[{'source_master':{'lib':'pdk','cell':'ZDEV'},'kind':'nmos',
            'target_master':{'lib':'pdk','cell':'ZCELL','view':'layout'},
            'terminals':{'D':'DP','G':'GP','S':'SP','B':'BP'},
            'parameters':{'w':{'source':'WIDTH','target':'width_um','type':'float','scale':1e6,'required':True},
                'l':{'source':'LENGTH','target':'length_um','type':'float','scale':1e6,'required':True},
                'm':{'source':'MULT','default':1}}}]}

def device(name='InputLeft'):
    return {'name':name,'lib':'pdk','cell':'ZDEV','params':{'WIDTH':'10u','LENGTH':'1u','MULT':2},
        'terms':{'DP':'D'+name,'GP':'G'+name,'SP':'TAIL','BP':'RETURN'}}

def project_fixture(path, mode='stack'):
    source={'lib':'newlib','cell':'matched_block','view':'schematic'}
    modules=[{'name':m,'rows':[[a,b,b,a]],'pattern':'ABBA','matching':'common_axis'}
        for m,a,b in [('Input','InputLeft','InputRight'),('Bias','BiasLeft','BiasRight')]]
    floorplan={'order':['Input','Bias'],'mode':mode,'device_gap_um':2,'macro_gap_um':6}
    if mode=='rows':floorplan['rows']=[['Input','Bias']]
    project={'schema':'analog-layout-workflow.project/v1','source':source,
        'target':{**source,'view':'layout'},'pdk':'pdk.json','circuit':'circuit.json','routing':'routing.json',
        'inputs':{'schematic':'schematic.json','pcell_geometry':'geometry.json'}}
    for name,data in [('project.json',project),('pdk.json',mapping()),
        ('circuit.json',{'schema':'analog-layout-workflow.circuit/v1','modules':modules,'floorplan':floorplan}),
        ('routing.json',{'schema':'analog-layout-workflow.routing-policy/v1'}),
        ('schematic.json',{'source':source,'instances':[device(n) for n in ('InputLeft','InputRight','BiasLeft','BiasRight')]})]:
        write(path/name,data)
    loaded=load_project(path/'project.json');prepare(loaded,path/'candidate')
    copies=read(path/'candidate/plan/device-copies.json')
    geometry={'manufacturing_grid':1,'basis':'SYNTHETIC TEST, not measured PDK geometry','devices':{}}
    for c in copies:
        geometry['devices'][c['logical_device']]={'bbox_at_r0_origin':[[0,0],[4,2]],'width':4,'height':2,
            'pcell_master':c['pcell_master'],'pcell_parameters':c['pcell_parameters'],
            'pcell_parameter_entries':c['pcell_parameter_entries'],'pdk_mapping_sha256':c['pdk_mapping_sha256']}
    write(path/'geometry.json',geometry)
    return loaded

class ConfigurationTests(unittest.TestCase):
    def test_alias_master_terminals_and_units(self):
        normalized,bindings=normalize_schematic({'instances':[device()]},mapping())
        self.assertEqual(normalized['instances'][0]['kind'],'nmos')
        self.assertEqual(normalized['instances'][0]['terms']['S'],'TAIL')
        self.assertEqual(bindings['InputLeft']['entries'][0]['value'],10)
        self.assertEqual(bindings['InputLeft']['master']['cell'],'ZCELL')

    def test_unknown_device_and_unresolved_expression_rejected(self):
        d=device();d['cell']='NOT_REGISTERED'
        with self.assertRaisesRegex(ValueError,'Unknown'): normalize_schematic({'instances':[d]},mapping())
        d=device();d['params']['WIDTH']='Wvar*2'
        with self.assertRaisesRegex(ValueError,'Unresolved'): normalize_schematic({'instances':[d]},mapping())

    def test_copy_rows_do_not_depend_on_instance_names(self):
        copies=[{'name':n+'__M'+str(i),'logical_device':n,'align_instance':'M'+n+str(i)} for n in ('Alpha','Beta') for i in range(2)]
        groups,_=configured_groups(copies,[{'name':'Input','rows':[['Alpha','Beta','Beta','Alpha']]}])
        self.assertEqual(groups[0]['rows'][0],['Alpha__M0','Beta__M0','Beta__M1','Alpha__M1'])
        with self.assertRaisesRegex(ValueError,'Incomplete'): configured_groups(copy.deepcopy(copies),[{'name':'Input','rows':[['Alpha']]}])
        with self.assertRaisesRegex(ValueError,'duplicate'): configured_groups(copy.deepcopy(copies),[{'name':'Input','rows':[['Alpha__M0','Alpha__M0']]}])

    def test_module_order_and_spacing_are_configuration(self):
        macros=[{'name':'Input','size':[4,2]},{'name':'Bias','size':[8,3]}]
        origins,axis=position_macros(macros,{'order':['Input','Bias'],'axis_x_um':20,'gap_after_um':{'Input':7}},lambda x,g:round(x/g)*g,.1,1)
        self.assertEqual(axis,20);self.assertEqual(origins,{'Input':[18,0],'Bias':[16,9]})
        with self.assertRaisesRegex(ValueError,'exactly once'): position_macros(macros,{'order':['Input']},lambda x,g:x,.1,1)

    def test_mapped_parameter_import_retains_explicit_type(self):
        out=typed_params({'pcell_parameter_entries':[{'name':'width_um','type':'float','value':10}]},json.dumps)
        self.assertIn('"width_um" "float" 10',out)
        with self.assertRaisesRegex(ValueError,'Nonintegral'):typed_params({'pcell_parameter_entries':[{'name':'f','type':'int','value':1.5}]},json.dumps)

    def test_new_pdk_mapping_places_without_name_prefix_assumptions(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);project=project_fixture(path)
            self.assertEqual(place(project,path/'candidate')['instances'],8)
            intent=read(path/'candidate/plan/placement-intent.json')
            self.assertTrue(intent['validation']['configured_matching_checks'])
            self.assertTrue(all(i['pcell_master']['cell']=='ZCELL' for i in intent['instances']))
            self.assertTrue(all(c['pass_check'] for c in intent['validation']['ABBA_matching_checks']))

    def test_side_by_side_modules_use_their_own_matching_axes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);project=project_fixture(path,'rows');place(project,path/'candidate')
            intent=read(path/'candidate/plan/placement-intent.json')
            axes={c['group']:c['axis_x_um'] for c in intent['validation']['ABBA_matching_checks']}
            self.assertNotEqual(axes['Input'],axes['Bias'])
            self.assertFalse(intent['validation']['core_center_aligned'])
            self.assertIsNone(intent['floorplan']['core_axis_x'])
            self.assertEqual(intent['floorplan']['axis_scope'],'module_local')
            self.assertTrue(intent['validation']['bbox_overlap_free'])

    def test_mapping_change_invalidates_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);project_fixture(path)
            pdk=read(path/'pdk.json');pdk['devices'][0]['parameters']['w']['target']='another_width'
            write(path/'pdk.json',pdk)
            with self.assertRaisesRegex(ValueError,'measure again'):place(load_project(path/'project.json'),path/'candidate')

    def test_measured_geometry_change_recomputes_module_positions(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);project=project_fixture(path);place(project,path/'candidate')
            before=read(path/'candidate/plan/placement-intent.json')
            geometry=read(path/'geometry.json')
            for n in ('InputLeft','InputRight'):
                geometry['devices'][n]['height']=4;geometry['devices'][n]['bbox_at_r0_origin'][1][1]=4
            write(path/'geometry.json',geometry);place(project,path/'candidate')
            after=read(path/'candidate/plan/placement-intent.json')
            self.assertEqual(after['macro_instances'][1]['origin'][1]-before['macro_instances'][1]['origin'][1],2)

    def test_negative_scale_and_split_module_ownership_rejected(self):
        pdk=mapping();pdk['devices'][0]['parameters']['w']['scale']=-1
        with self.assertRaisesRegex(ValueError,'Positive'):normalize_schematic({'instances':[device()]},pdk)
        copies=[{'name':'Alpha__M'+str(i),'logical_device':'Alpha','align_instance':'MA'+str(i)} for i in range(2)]
        with self.assertRaisesRegex(ValueError,'split across'):configured_groups(copies,[{'name':'A','rows':[['Alpha']]},{'name':'B','rows':[['Alpha']]}])

    def test_macro_constraints_and_objective_are_read_from_config(self):
        fixture_spec=importlib.util.spec_from_file_location('macro_config_fixture',ROOT/'analog-layout-macro-opt/tests/test_macro_opt.py')
        fixture=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);project=project_fixture(path);snapshot,request=fixture.fixture()
            snapshot['source']=project['target'];request.pop('schema');request.pop('snapshot_sha256')
            request.update(locked=['CAP'],objective_priority=['weighted_hpwl_um','area_um2'])
            project['circuit']['macro_optimization']=request;project['inputs']['macro_snapshot']='macro.json';write(path/'macro.json',snapshot)
            result=macro_opt(project,path/'candidate');self.assertGreater(result['candidates'],0)
            saved=read(path/'candidate/macro-opt/request.json');self.assertEqual(saved['snapshot_sha256'],digest(snapshot))
            self.assertEqual(saved['objective_priority'],request['objective_priority'])
            for c in read(path/'candidate/macro-opt/candidates.json')['candidates']:
                self.assertEqual(c['metrics']['deltas_um']['CAP'],[0,0])

    def test_search_routes_around_obstacles_and_rejects_missing_net_policy(self):
        profile,access,obstacles,request=FIX.fixtures()
        policy={'backend':'general','nets':{'N':{'net_class':'ordinary','layer_roles':['local']}},'search':{}}
        result=ROUTER.search(profile,access,policy,mapping(),obstacles)
        self.assertEqual(result['status'],'PLANNED');self.assertFalse(result['materializable'])
        self.assertEqual(result['candidates'][0]['authoritative_preflight']['status'],'READY_FOR_REVIEW')
        with self.assertRaisesRegex(ValueError,'exact access nets'):ROUTER.search(profile,access,{'backend':'general','nets':{}},mapping(),obstacles)
        policy['nets']['N']['net']='AccidentalOverride'
        with self.assertRaisesRegex(ValueError,'identity'):ROUTER.search(profile,access,policy,mapping(),obstacles)

    def test_renamed_network_uses_identical_search_geometry(self):
        profile,access,obstacles,_=FIX.fixtures()
        policy={'backend':'general','nets':{'N':{'net_class':'ordinary','layer_roles':['local']}}}
        before=ROUTER.search(profile,access,policy,mapping(),obstacles)
        access2=copy.deepcopy(access);obstacles2=copy.deepcopy(obstacles)
        for inst in access2['instances']:
            for term in inst['terminals'].values():term['net']='Renamed'
        for o in obstacles2['obstacles']:
            if o.get('net')=='N':o['net']='Renamed'
        obstacles2['sources']['terminal_access_sha256']=ROUTER.PLANNER.ROUTE.digest(access2)
        policy['nets']={'Renamed':policy['nets']['N']}
        after=ROUTER.search(profile,access2,policy,mapping(),obstacles2)
        self.assertEqual(after['status'],'PLANNED')
        routes=lambda result:[(r['layer'],r['width_um'],r['points_um']) for r in result['candidates'][0]['route_spec']['routes']]
        self.assertEqual(routes(before),routes(after))

    def test_critical_network_is_not_downgraded_to_ordinary(self):
        profile,access,obstacles,_=FIX.fixtures()
        policy={'backend':'general','nets':{'N':{'net_class':'differential','layer_roles':['local'],'max_detour_ratio':2}}}
        result=ROUTER.search(profile,access,policy,mapping(),obstacles)
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['candidates'],[])

    def test_configured_paired_search_passes_matching_under_obstacles(self):
        profile,access,obstacles,request=FIX.pair_fixture()
        policy={'backend':'general','nets':{n['net']:{k:v for k,v in n.items() if k not in ('net','terminals')} for n in request['nets']},
            'matching':request['matching']}
        result=ROUTER.search(profile,access,policy,mapping(),obstacles)
        self.assertEqual(result['status'],'PLANNED')
        intent=ROUTER.PLANNER.ROUTE.build(profile,access,result['candidates'][0]['route_spec'])
        self.assertTrue(intent['matching'][0]['pass'])

    def test_missing_waiver_authorization_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            project={'schema':'analog-layout-workflow.project/v1','source':{'lib':'L','cell':'C','view':'schematic'},'target':{'lib':'L','cell':'C','view':'layout'},
                'pdk':'pdk.json','circuit':'circuit.json','routing':'routing.json','verification':{'waivers':[{'scope':['density']}]}}
            for name,data in [('project.json',project),('pdk.json',mapping()),('circuit.json',{'schema':'analog-layout-workflow.circuit/v1'}),('routing.json',{'schema':'analog-layout-workflow.routing-policy/v1'})]:
                (path/name).write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'project-specific'):load_project(path/'project.json')

if __name__=='__main__':unittest.main()
