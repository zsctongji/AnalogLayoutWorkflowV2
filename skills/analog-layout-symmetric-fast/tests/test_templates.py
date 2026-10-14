import copy,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/'scripts/mirror_spec.py'
spec=importlib.util.spec_from_file_location('mirror_spec',PATH);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture():
    p={'schema':m.ri.PROFILE_SCHEMA,'technology':{'library':'synthetic'},'manufacturing_grid_um':.01,
       'layers':[{'name':'m1'}],'layer_purposes':[],'layer_functions':[],'constraints':{'rules':[]},
       'routing_layers':[{'layer':'m1','minimum_width_rules':[{'value':.2,'parameters':None}],
                          'minimum_spacing_rules':[{'value':.2,'parameters':None}]}],'vias':[],
       'coverage':{'basic_routing_ready':True,'unknown_signoff_categories':['DRC']},
       'boundaries':{'may_drive_automatic_routing':True},'validation':{'structurally_valid':True}}
    p['fingerprint']={'value':m.ri.fingerprint(p)}
    a={'schema':m.ri.ACCESS_SCHEMA,'target':{'lib':'synthetic','cell':'pair','view':'layout'},'instances':[]}
    for name,net,pos in [('L0','P',[-4,0]),('L1','P',[-4,4]),('R0','N',[4,0]),('R1','N',[4,4])]:
        island={'id':name+':G:p0','candidate_centers':[pos],'selected_center':pos,'access_layers':['m1']}
        a['instances'].append({'name':name,'terminals':{'G':{'net':net,'pin_islands':[island],
                                'candidate_centers':[pos],'selected_center':pos,'access_layers':['m1']}}})
    seed={'schema':m.ri.SPEC_SCHEMA,'target':a['target'],'required_nets':['P','N'],
          'routes':[{'id':'left','net':'P','layer':'m1','width_um':.2,'points_um':[[-4,0],[-5,0],[-5,4],[-4,4]],
                     'access':[{'instance':n,'terminal':'G','pin_island_id':n+':G:p0','xy_um':pos}
                               for n,pos in [('L0',[-4,0]),('L1',[-4,4])]]}],
          'vias':[],'contact_landings':[],
          'net_constraints':[{'net':n,'net_class':'differential','max_detour_ratio':2} for n in ['P','N']]}
    r={'schema':'analog-layout-symmetric-route.templates/v1','sources':{},'axis':{'coordinate':'x','value_um':0},
       'seed_spec':seed,'pairs':[{'first_net':'P','second_net':'N','pin_pairs':[['L0:G:p0','R0:G:p0'],['L1:G:p0','R1:G:p0']]}],
       'self_nets':[],'via_mirror_evidence':{}}
    return p,a,r


def bind(p,a,r):
    r['sources']={'profile_fingerprint':m.ri.fingerprint(p),'terminal_access_sha256':m.ri.digest(a),'seed_sha256':m.ri.digest(r['seed_spec'])}
    return m.compile_spec(p,a,r)


class Tests(unittest.TestCase):
    def svg_check(self,intent):
        path=PATH.parents[2]/'analog-layout-route/scripts/svg_route_check.py'
        spec=importlib.util.spec_from_file_location('sym_svg_test',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory(prefix='sym-svg-test-') as td:
            p=Path(td);(p/'intent.json').write_text(json.dumps(intent),encoding='utf-8')
            (p/'preview.svg').write_text(m.ri.svg(intent),encoding='utf-8')
            return mod.build_check(p/'intent.json',p/'preview.svg')

    def test_end_to_end_svg(self):
        p,a,r=fixture();out=bind(p,a,r)
        result=self.svg_check(out['intent'])
        self.assertEqual(result['status'],'PASS',result['errors'])
        self.assertTrue(any('live-target reconciliation' in e for e in m.ri.validate(p,out['intent'])))

    def test_multilayer_mirror_vias(self):
        p,a,r=fixture()
        p['layers'].append({'name':'m2'})
        p['routing_layers'].append({'layer':'m2','minimum_width_rules':[{'value':.2,'parameters':None}],
                                   'minimum_spacing_rules':[{'value':.2,'parameters':None}]})
        p['vias']=[{'name':'v12','layer1':'m1','layer2':'m2','standard_geometry':{
            'cut_layer':'cut12','cut_size_um':[.1,.1],'layer1_enclosure_um':[.1,.1],'layer2_enclosure_um':[.1,.1]}}]
        p['fingerprint']={'value':m.ri.fingerprint(p)}
        route=r['seed_spec']['routes'][0];first,last=route['access']
        r['seed_spec']['routes']=[dict(route,id='local0',points_um=[[-4,0],[-5,0]],access=[first]),
           dict(route,id='trunk',layer='m2',points_um=[[-5,0],[-5,4]],access=[]),
           dict(route,id='local1',points_um=[[-5,4],[-4,4]],access=[last])]
        r['seed_spec']['vias']=[{'id':'v0','net':'P','via':'v12','xy_um':[-5,0]},
                               {'id':'v1','net':'P','via':'v12','xy_um':[-5,4]}]
        r['via_mirror_evidence']={'v12':'synthetic centered enclosure test; not a real PDK'}
        out=bind(p,a,r)
        self.assertEqual(out['status'],'TEMPLATE_PREFLIGHT_PASS',out['intent']['validation']['errors'])
        self.assertEqual(len(out['route_spec']['vias']),4)
        self.assertEqual(self.svg_check(out['intent'])['status'],'PASS')

    def test_asymmetric_self_blocked_by_svg(self):
        p,a,r=fixture();a['instances']=a['instances'][:2]
        r['pairs']=[];r['self_nets']=['P'];r['seed_spec']['required_nets']=['P']
        r['seed_spec']['net_constraints']=[{'net':'P','net_class':'ordinary'}]
        out=bind(p,a,r)
        self.assertEqual(out['status'],'BLOCKED')
        self.assertEqual(out['symmetry_preflight']['status'],'BLOCKED')
        self.assertEqual(self.svg_check(out['intent'])['status'],'BLOCKED')

    def test_equal_length_wrong_position_rejected(self):
        p,a,r=fixture();intent=bind(p,a,r)['intent']
        for point in intent['routes'][1]['points_um']:point[0]+=1
        self.assertEqual(m.symmetry_preflight(intent,r['axis'])['status'],'BLOCKED')

    def test_same_geometry_wrong_layer_rejected(self):
        p,a,r=fixture();intent=bind(p,a,r)['intent'];intent['routes'][1]['layer']='other'
        self.assertEqual(m.symmetry_preflight(intent,r['axis'])['status'],'BLOCKED')

    def test_wrong_width_rejected(self):
        p,a,r=fixture();intent=bind(p,a,r)['intent'];intent['routes'][1]['width_um']=.3
        self.assertEqual(m.symmetry_preflight(intent,r['axis'])['status'],'BLOCKED')

    def test_inflated_tolerance_rejected(self):
        p,a,r=fixture();r['seed_spec']['symmetry_groups']=[{'id':'loose','mode':'pair','first_net':'P','second_net':'N',
            'transform':'mirror_x','axis_um':0,'tolerance_um':1}]
        self.assertEqual(bind(p,a,r)['status'],'BLOCKED')

    def test_axis_drift_rejected(self):
        p,a,r=fixture();r['seed_spec']['symmetry_groups']=[{'id':'other-axis','mode':'self','net':'P',
            'transform':'mirror_x','axis_um':-4.5,'tolerance_um':1e-9}]
        self.assertEqual(bind(p,a,r)['status'],'BLOCKED')

    def test_asymmetric_via_positions_rejected(self):
        p,a,r=fixture();intent=bind(p,a,r)['intent']
        intent['vias']=[{'id':'a','net':'P','via':'v12','xy_um':[-5,0]},
                       {'id':'b','net':'N','via':'v12','xy_um':[5,1]}]
        self.assertEqual(m.symmetry_preflight(intent,r['axis'])['status'],'BLOCKED')

    def test_segmentation_does_not_change_symmetry(self):
        p,a,r=fixture();intent=bind(p,a,r)['intent']
        intent['routes'][1]['points_um'].insert(2,[5,2])
        self.assertEqual(m.symmetry_preflight(intent,r['axis'])['status'],'PASS')

    def test_mirror_connectivity_and_metrics(self):
        p,a,r=fixture();out=bind(p,a,r)
        self.assertEqual(out['status'],'TEMPLATE_PREFLIGHT_PASS',out['intent']['validation']['errors'])
        self.assertFalse(out['materializable'])
        self.assertTrue(out['intent']['physical_connectivity']['complete'])
        self.assertEqual(out['route_spec']['routes'][1]['points_um'],[[4,0],[5,0],[5,4],[4,4]])
        self.assertTrue(out['intent']['matching'][0]['pass'])

    def test_stale(self):
        p,a,r=fixture()
        with self.assertRaises(ValueError):m.compile_spec(p,a,r)

    def test_off_grid(self):
        p,a,r=fixture();r['axis']['value_um']=.003
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_nonmirrored_access(self):
        p,a,r=fixture();a['instances'][-1]['terminals']['G']['pin_islands'][0]['candidate_centers']=[[4,5]]
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_missing_island(self):
        p,a,r=fixture();r['pairs'][0]['pin_pairs'].pop()
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_wrong_net(self):
        p,a,r=fixture();a['instances'][-1]['terminals']['G']['net']='SOMETHING_ELSE'
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_wrong_terminal(self):
        p,a,r=fixture();r['seed_spec']['routes'][0]['access'][0]['terminal']='D'
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_mate_not_overwritten(self):
        p,a,r=fixture();route=copy.deepcopy(r['seed_spec']['routes'][0]);route['net']='N';r['seed_spec']['routes'].append(route)
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_unknown_via_evidence(self):
        p,a,r=fixture();r['seed_spec']['vias']=[{'id':'v','net':'P','via':'unqualified','xy_um':[-5,0]}]
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_disconnected(self):
        p,a,r=fixture();r['seed_spec']['routes'].append({'id':'floating','net':'P','layer':'m1','width_um':.2,'points_um':[[-9,9],[-8,9]],'access':[]})
        self.assertEqual(bind(p,a,r)['status'],'BLOCKED')

    def test_required_net_not_omitted(self):
        p,a,r=fixture();r['seed_spec']['required_nets'].append('TAIL');r['seed_spec']['net_constraints'].append({'net':'TAIL','net_class':'ordinary'})
        self.assertEqual(bind(p,a,r)['status'],'BLOCKED')

    def test_pair_short_is_blocked(self):
        p,a,r=fixture();r['seed_spec']['routes'][0]['points_um']=[[-4,0],[0,0],[0,4],[-4,4]]
        self.assertEqual(bind(p,a,r)['status'],'BLOCKED')

    def test_no_diagonal(self):
        with self.assertRaises(ValueError):m.clean([[0,0],[1,1]])

    def test_dogleg_U(self):
        paths=m.doglegs([-4,0],[-4,4],tracks_x=[-5])
        self.assertIn([[-4,0],[-5,0],[-5,4],[-4,4]],paths)
        self.assertEqual(paths[0],[[-4,0],[-4,4]])

    def test_continuous_bus(self):
        access={'instance':'M','terminal':'S','pin_island_id':'M:S:p0','xy_um':[-2,0]}
        bus=m.horizontal_bus('supply','VDD','m1','m2',.2,.6,'v12',[{'access':access,'landing_xy_um':[-2,3]}],3,[-4,4])
        self.assertEqual(bus['routes'][0]['points_um'],[[-4,3],[4,3]])
        self.assertEqual(len(bus['vias']),1)
        self.assertEqual(bus['routes'][-1]['points_um'],[[-2,0],[-2,3]])

    def test_bus_outside(self):
        with self.assertRaises(ValueError):m.horizontal_bus('s','V','m1','m2',.2,.6,'v',
          [{'access':{'xy_um':[0,0]},'landing_xy_um':[5,0]}],3,[-4,4])

    def test_reject_nonfinite(self):
        p,a,r=fixture();r['axis']['value_um']=float('nan')
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_no_implicit_min_width(self):
        p,a,r=fixture();r['seed_spec']['routes'][0]['width_um']=None
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_no_supply_without_width_basis(self):
        p,a,r=fixture();r['seed_spec']['net_constraints'][0]['net_class']='power'
        with self.assertRaises(ValueError):bind(p,a,r)

    def test_cli_no_overwrite(self):
        p,a,r=fixture();bind(p,a,r)
        with tempfile.TemporaryDirectory(prefix='symmetric-route-test-') as td:
            root=Path(td)
            for n,obj in [('profile',p),('access',a),('request',r)]: (root/(n+'.json')).write_text(json.dumps(obj),encoding='utf-8')
            cmd=[sys.executable,str(PATH),'--profile',str(root/'profile.json'),'--terminal-access',str(root/'access.json'),
                 '--request',str(root/'request.json'),'--out',str(root/'out')]
            run=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr)
            self.assertTrue((root/'out/route-spec.json').is_file())
            self.assertNotEqual(subprocess.run(cmd,capture_output=True).returncode,0)


if __name__=='__main__':unittest.main()
