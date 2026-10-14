import sys, copy, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from functional_groups import prepare_groups, check_abba_geometry
from placement_flow import build_local_macro, translate_macro

def device(name):
    return dict(name=name,lib='test_pdk',cell='nmos',params=dict(w='20u',fw='5u',l='1u',fingers='4',m='2'),
                terms=dict(D='drain_'+name,G='gate_'+name,S='TAIL',B='VSS'))

class FunctionalGroupTests(unittest.TestCase):
    def setUp(self):
        self.schematic={'instances':[device('B'),device('A')]}
        self.policy=dict(matching='common_axis',module_map={'A':'INPUT','B':'INPUT'})
        self.geometry=dict(devices={name:dict(bbox_at_r0_origin=[[0,0],[5,7]]) for name in ('A','B')})
    def build(self,policy=None):
        _,copies,groups,_=prepare_groups(self.schematic,policy or self.policy)
        macro=build_local_macro(groups[0],{c['name']:c for c in copies},self.geometry,2,.001)
        translate_macro(macro,[-macro['size'][0]/2,0],.001)
        return groups,macro
    def test_axis_abba_checks_actual_geometry(self):
        groups,macro=self.build()
        self.assertEqual(check_abba_geometry(groups,macro['instances'],0,.001)[0]['pattern'],'ABBA')
        by_name={i['name']:i for i in macro['instances']};a,b=groups[0]['rows'][0][1],groups[0]['rows'][0][3]
        by_name[a]['bbox'],by_name[b]['bbox']=by_name[b]['bbox'],by_name[a]['bbox']
        with self.assertRaisesRegex(ValueError,'Actual logical'):
            check_abba_geometry(groups,macro['instances'],0,.001)
    def test_user_baab_override_updates_both_intent_and_floorplan_constraints(self):
        policy=copy.deepcopy(self.policy)
        policy['matching_overrides']={'INPUT':dict(mode='explicit_pattern',pattern='BAAB',source='user',instruction='Use BAAB for INPUT')}
        groups,macro=self.build(policy)
        self.assertEqual(groups[0]['rows'],[['B__M0','A__M0','A__M1','B__M1']])
        self.assertEqual(check_abba_geometry(groups,macro['instances'],0,.001)[0]['pattern'],'BAAB')
        self.assertEqual(groups[0]['constraints'][0]['regions'],groups[0]['align_rows'])
    def test_centroid_override_removes_default_abba_requirement(self):
        policy=copy.deepcopy(self.policy)
        policy['matching_overrides']={'INPUT':dict(mode='common_centroid',source='user',instruction='Use common centroid for INPUT')}
        groups,macro=self.build(policy)
        self.assertEqual([len(row) for row in groups[0]['rows']],[2,2])
        self.assertNotIn('required_active_pattern',groups[0])
        self.assertEqual(groups[0]['matching_mode'],'common_centroid')
    def test_module_map_disambiguates_common_source_devices(self):
        self.schematic['instances'].append(device('OTHER'))
        self.policy['module_map']['OTHER']='OUTPUT'
        _,copies,groups,_=prepare_groups(self.schematic,self.policy)
        self.assertEqual(len(copies),6)
        self.assertEqual(next(g for g in groups if g['name']=='INPUT')['logical_devices'],['A','B'])
    def test_missing_user_override_group_is_not_ignored(self):
        policy=copy.deepcopy(self.policy)
        policy['matching_overrides']={'MISSING':dict(mode='explicit_pattern',pattern='ABBA',source='user',instruction='Use ABBA')}
        with self.assertRaisesRegex(ValueError,'missing'):
            self.build(policy)
    def test_logical_centers_must_be_on_axis(self):
        groups,macro=self.build()
        with self.assertRaisesRegex(ValueError,'off axis'):
            check_abba_geometry(groups,macro['instances'],1,.001)

if __name__=='__main__':unittest.main()
