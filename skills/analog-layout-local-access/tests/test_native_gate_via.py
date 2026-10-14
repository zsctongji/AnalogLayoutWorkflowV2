import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from native_gate_via import NativeGateBackend,make_plan,verifier,Invalid,digest,S

class NativeGateTests(unittest.TestCase):
    def setUp(self):
        self.figures=[['rect',[layer,'drawing'],[[-size,-size],[size,size]],None] for layer,size in [('cont',.225),('poly1',.475),('mt1',.405)]]
        self.objects=[dict(id='A/G0/'+layer,owner='INPUT',net='gateA',kind='rect',lpp=lpp,bbox_um=[[round(-4.575+x,9),round(6.425+y,9)] for x,y in bb]) for _,lpp,bb,_ in self.figures for layer in [lpp[0]]]
        self.before=dict(objects=sorted(self.objects,key=lambda o:o['id']),native_vias=[],protected=dict(instances=['immutable-device'],shapes=[],vias=[],terminals=[],grid_um=.001))
        self.record=dict(instance='A',net='gateA',contact_object_ids=['A/G0/cont'],metal_landing_object_ids=['A/G0/mt1'],poly_id='A/G0/poly1')
        self.source=dict(lib='L',cell='source',view='layout');self.target=dict(lib='L',cell='new',view='layout')
    def plan(self,records=None,before=None):
        return make_plan(self.source,self.target,before or self.before,records or [self.record],dict(local_figures=self.figures))
    def test_physical_equivalence_and_round_trip_center(self):
        plan,after,_=self.plan()
        self.assertEqual(after['native_vias'][0]['origin_um'],[-4.575,6.425])
        self.assertEqual(verifier(self.before,after,plan)['checks']['connectivity'],'PASS')
        self.assertEqual(after['protected'],self.before['protected'])
    def test_mismatched_cut_blocks_plan(self):
        before=copy.deepcopy(self.before);before['objects'][0]['bbox_um'][1][0]+=.001
        with self.assertRaises(Invalid):self.plan(before=before)
    def test_duplicate_contact_blocks_plan(self):
        with self.assertRaises(Invalid):self.plan(records=[self.record,self.record])
    def test_changed_native_net_blocks_verification(self):
        plan,after,_=self.plan();after['native_vias'][0]['net']='wrong'
        with self.assertRaises(Invalid):verifier(self.before,after,plan)
    def test_changed_device_blocks_verification(self):
        plan,after,_=self.plan();after['protected']['instances']=['modified-device']
        with self.assertRaises(Invalid):verifier(self.before,after,plan)
    def test_changed_native_cut_blocks_verification(self):
        plan,after,_=self.plan();after['native_vias'][0]['figures'][0]['bbox_um'][0][0]+=.001
        with self.assertRaises(Invalid):verifier(self.before,after,plan)
    def test_stale_replacement_rejected_before_cad_call(self):
        plan,_,_=self.plan();backend=NativeGateBackend(None,S)
        tx=dict(before=copy.deepcopy(self.before),written=set());backend.tx=tx
        tx['before']['objects'][0]['net']='foreign'
        with self.assertRaises(Invalid):backend.apply_batch(tx,plan['edits'])
    def test_qualification_drift_blocks_before_cad_call(self):
        backend=NativeGateBackend(None,S,{})
        with self.assertRaises(Invalid):backend.require('native-gate-via')

if __name__=='__main__':unittest.main()
