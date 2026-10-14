import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

path = Path(__file__).resolve().parents[1]/'scripts/symmetry_plan.py'
spec = importlib.util.spec_from_file_location('symmetry_plan', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    s = {'schema':'analog-layout-macro-opt.snapshot/v1', 'source':{'lib':'test','cell':'synthetic','view':'layout'},
         'evidence':{'kind':'synthetic'}, 'grid_um':0.5, 'macros':[{'id':'A'}, {'id':'B'}],
         'objects':[{'id':'a','macro':'A','bbox_um':[[0,0],[2,2]],'payload_sha256':'synthetic-a'},
                    {'id':'b','macro':'B','bbox_um':[[6,0],[8,2]],'payload_sha256':'synthetic-b'}],
         'source_object_ids':['a','b'], 'protected_sets':[], 'cross_macro_connections':[]}
    base = {'schema':'analog-layout-macro-opt.request/v1','snapshot_sha256':m.opt.digest(s),
            'bounds_um':[[-20,-20],[20,20]], 'pair_gaps':[{'macros':['A','B'],'x_um':1,'y_um':1,'basis':'synthetic'}],
            'align':[], 'mirror':[], 'order':[], 'locked':[], 'nets':[],
            'search':{'max_evaluations':1,'max_iterations':1,'beam_width':1,'top_k':1,'step_um':0.5}}
    r = {'schema':'analog-layout-macro-symmetry.request/v1','base_request':base,
         'axis':{'coordinate':'x','value_um':0,'basis':'synthetic'}, 'start_um':0,
         'orders':[[['A'],['B']]], 'excluded_macros':{}}
    return s,r


def geometry(s):
    figs=[]
    for o in s['objects']:
        (x,y),(u,v)=o['bbox_um']
        figs.append({'id':o['id']+'flat','object_id':o['id'],'macro':o['macro'],'lpp':['M1','drawing'],
                     'points_um':[[x,y],[u,y],[u,v],[x,v]]})
    return {'snapshot_sha256':m.opt.digest(s),'evidence':{'kind':'synthetic'},
            'source_figure_ids':[f['id'] for f in figs],'figures':figs,'excluded_annotation_ids':[]}


class Tests(unittest.TestCase):
    def test_stack(self):
        s,r=fixture(); c=m.plan(s,r)['candidates'][0]
        self.assertEqual(c['positions_um'],{'A':[-1,0],'B':[-1,3]})
        self.assertEqual(c['geometry_audit']['status'],'COAXIAL_ONLY')
        self.assertEqual(len(c['object_moves']),2)

    def test_geometry_and_pair(self):
        s,r=fixture(); r['orders']=[[['A','B']]]; r['geometry']=geometry(s)
        c=m.plan(s,r)['candidates'][0]
        self.assertEqual(c['geometry_audit']['status'],'REPRESENTED_GEOMETRY_SYMMETRIC')
        self.assertNotEqual(c['routing_status'],'SYMMETRY_HANDOFF_READY')

    def test_horizontal(self):
        s,r=fixture(); r['axis']['coordinate']='y'
        c=m.plan(s,r)['candidates'][0]
        self.assertEqual(c['positions_um'],{'A':[0,-1],'B':[3,-1]})

    def test_asymmetry_detected(self):
        s,r=fixture(); r['geometry']=geometry(s)
        r['geometry']['figures'][0]['points_um'][1][0]=1.5
        self.assertEqual(m.plan(s,r)['candidates'][0]['geometry_audit']['status'],'GEOMETRY_ASYMMETRIC')

    def test_vertex_order(self):
        self.assertEqual(m.canonical([[0,0],[2,0],[2,2],[0,2]]),m.canonical([[2,2],[2,0],[0,0],[0,2]]))

    def test_grid_conflict(self):
        s,r=fixture(); r['axis']['value_um']=0.25
        result=m.plan(s,r)
        self.assertFalse(result['candidates'])
        self.assertIn('OFF_GRID:A',result['rejected'][0]['metrics']['failures'])

    def test_lock_conflict(self):
        s,r=fixture(); r['base_request']['locked']=['A']
        self.assertFalse(m.plan(s,r)['candidates'])

    def test_missing_clearance(self):
        s,r=fixture(); r['base_request']['pair_gaps']=[]
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_stale_snapshot(self):
        s,r=fixture(); s['grid_um']=0.1
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_incomplete_rows(self):
        s,r=fixture(); r['orders']=[[['A']]]
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_cross_macro_wire(self):
        s,r=fixture(); s['cross_macro_connections']=['wire']; r['base_request']['snapshot_sha256']=m.opt.digest(s)
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_missing_physical_object(self):
        s,r=fixture(); r['geometry']=geometry(s); r['geometry']['figures'].pop()
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_missing_geometry_inventory(self):
        s,r=fixture(); r['geometry']=geometry(s); r['geometry']['source_figure_ids'].pop()
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_net_span(self):
        s,r=fixture(); r['base_request']['nets']=[{'id':'sensitive','max_hpwl_um':0,
            'pins':[{'island_id':'a','macro':'A','xy_um':[1,1]},{'island_id':'b','macro':'B','xy_um':[7,1]}]}]
        self.assertFalse(m.plan(s,r)['candidates'])

    def test_rigid_readback(self):
        s,r=fixture(); c=m.plan(s,r)['candidates'][0]; target=copy.deepcopy(s)
        for o in target['objects']:
            o['bbox_um']=m.opt.shifted(o['bbox_um'],c['metrics']['deltas_um'][o['macro']])
        self.assertTrue(m.opt.verify_translation(s,target,c)['valid'])
        target['objects'][0]['payload_sha256']='changed'
        self.assertFalse(m.opt.verify_translation(s,target,c)['valid'])

    def test_unknown_option(self):
        s,r=fixture(); r['silently_relax_symmetry']=True
        with self.assertRaises(ValueError): m.plan(s,r)

    def test_cli_artifacts_and_no_overwrite(self):
        s,r=fixture(); r['geometry']=geometry(s)
        with tempfile.TemporaryDirectory(prefix='macro-symmetry-test-') as tmp:
            root=Path(tmp)
            (root/'s.json').write_text(json.dumps(s),encoding='utf-8')
            (root/'r.json').write_text(json.dumps(r),encoding='utf-8')
            command=[sys.executable,str(path),'--snapshot',str(root/'s.json'),
                     '--request',str(root/'r.json'),'--out',str(root/'result')]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads((root/'result/candidates.json').read_text(encoding='utf-8'))
            self.assertFalse(data['materialized'])
            self.assertIn('<line ',(root/'result/candidate-1.svg').read_text(encoding='utf-8'))
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)


if __name__=='__main__': unittest.main()
