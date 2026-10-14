import importlib.util,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('refine_simple',root/'analog-layout-place/scripts/refine_placement_intent.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class SharingPolicy(unittest.TestCase):
    def intent(self):
        items=[{'name':n,'kind':'pmos','pcell_master':{'lib':'p','cell':'pm'},'module_id':'MIRROR','terminals':{'S':'VDD'},'bbox':bb} for n,bb in [('A',[[0,0],[2,2]]),('B',[[1,0],[3,2]])]]
        cuts=[[[1.4,.4],[1.6,.6]]]
        return {'instances':items,'shared_diffusion_groups':[{'id':'central','instances':['A','B'],'terminal':'S','net':'VDD','axis':'x','evidence':{'eligibility_policy':'same_net_same_module','source':'measured native geometry','abutment_geometry_verified':True,'source_contact_overlap_verified':True,'contact_layer':'cont/drawing','source_contacts_um':{'A':cuts,'B':cuts},'expected_bbox_overlap_um':1}}]}
    def test_same_net_module_builds_with_pending_electrical_checks(self):
        checks=r.validate_shared_diffusion_groups(self.intent(),.001)
        self.assertEqual(checks[0]['electrical_verification'],'PENDING')
        self.assertEqual(checks[0]['coincident_source_contact_count'],1)
    def test_same_net_cross_module_rejected(self):
        intent=self.intent();intent['instances'][1]['module_id']='INPUT'
        with self.assertRaises(ValueError):r.validate_shared_diffusion_groups(intent,.001)
    def test_same_module_different_net_rejected(self):
        intent=self.intent();intent['instances'][1]['terminals']['S']='OUT'
        with self.assertRaises(ValueError):r.validate_shared_diffusion_groups(intent,.001)
    def test_split_contacts_still_invalid_geometry(self):
        intent=self.intent();intent['shared_diffusion_groups'][0]['evidence']['source_contacts_um']['B']=[[[1.5,.4],[1.7,.6]]]
        with self.assertRaises(ValueError):r.validate_shared_diffusion_groups(intent,.001)

if __name__=='__main__':unittest.main()
