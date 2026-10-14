import copy
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).parents[1]/'scripts/assess_facing_sources.py'
spec=importlib.util.spec_from_file_location('facing',path)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def probe(name, source_right):
    s=[[2,0],[3,2]] if source_right else [[0,0],[1,2]]
    d=[[0,0],[1,2]] if source_right else [[2,0],[3,2]]
    x=s[0][0]
    return {'instance':name,'orientation':'MY' if source_right else 'R0',
            'source_thin_local':[s],'source_metal_local':[s],
            'source_contacts_local':[[[x+.3,.5],[x+.7,.9]]],
            'drain_metal_local':[d],
            'shapes_local':[[['thin','drawing'],[[0,0],[3,2]]],
                            [['poly1','drawing'],[[1,-.5],[2,2.5]]]]}

class FacingTests(unittest.TestCase):
    def items(self):
        a={'name':'D','kind':'pmos','pcell_master':{'cell':'p'},'terminals':{'S':'VDD','B':'VDD'}}
        b=copy.deepcopy(a); b['name']='A'
        return a,b

    def test_flipped_dummy_succeeds_after_current_orientation_fails(self):
        a,b=self.items()
        result=mod.assess_variants(a,b,[probe('D',False),probe('D',True),probe('A',False)])
        self.assertEqual(len(result['accepted']),1)
        self.assertEqual(result['accepted'][0]['left_orientation'],'MY')
        self.assertEqual(result['attempts'][0]['status'],'TRIAL_REJECTED')

    def test_missing_flip_is_not_permanent_rejection(self):
        a,b=self.items()
        self.assertEqual(mod.assess_variants(a,b,[probe('D',False),probe('A',False)])['status'],'NO_VALID_SUPPLIED_VARIANT')

    def test_diff_dummy_network_conflict_blocks(self):
        a,b=self.items(); a['terminals']['S']='VSS'; b['terminals']['S']='tail'
        self.assertEqual(mod.assess_variants(a,b,[])['status'],'BLOCKED_SOURCE_NET_CONFLICT')

    def test_same_tail_diff_dummy_is_eligible(self):
        a,b=self.items()
        for i in (a,b): i.update(kind='nmos',terminals={'S':'tail','B':'VSS'})
        self.assertEqual(mod.assess_variants(a,b,[probe('D',True),probe('A',False)])['status'],'GEOMETRY_CANDIDATES')

    def test_split_contacts_rejected(self):
        a,b=self.items(); p=probe('A',False); p['source_contacts_local'][0][0][1]+=.1
        self.assertFalse(mod.assess_variants(a,b,[probe('D',True),p])['accepted'])

    def test_body_mismatch_blocks(self):
        a,b=self.items(); b['terminals']['B']='other'
        self.assertEqual(mod.assess_variants(a,b,[])['status'],'BLOCKED_DEVICE_OR_BODY_COMPATIBILITY')

if __name__=='__main__': unittest.main()
