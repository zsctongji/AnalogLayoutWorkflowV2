import importlib.util
import unittest
from pathlib import Path

path=Path(__file__).parents[1]/'scripts'/'inspect_pairs.py'
spec=importlib.util.spec_from_file_location('inspect_pairs',path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def item(name, logical, source, x, *, master='nmos', role='active', kind='nmos'):
    return {'name':name,'logical_device':logical,'kind':kind,'placement_role':role,
            'pcell_master':{'lib':'pdk','cell':master,'view':'layout'},
            'terminals':{'S':source},'bbox':[[x,0],[x+1,2]]}


class InspectPairsTests(unittest.TestCase):
    def test_input_dummy_same_tail_does_not_require_all_terminal_ties(self):
        a,d=item('INPUT','INPUT','TAIL',2),item('DUMMY','DUMMY','TAIL',0,role='dummy')
        a['terminals'].update(G='INP',D='OUT',B='VSS')
        d['terminals'].update(G='VSS',D='VSS',B='VSS')
        a['pcell_parameters']={'fingers':2};d['pcell_parameters']={'fingers':1}
        intent={'schema':mod.SCHEMA,'instances':[d,a],
                'groups':[{'name':'INPUT_PAIR','role':'differential_pair','rows':[['DUMMY','INPUT']]}]}
        result=mod.inspect(intent)
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['dummy_boundary_review'][0]['status'],'SAME_SOURCE_CANDIDATE')
        self.assertFalse(result['dummy_boundary_review'][0]['schematic_change_authorized'])

    def test_input_dummy_net_conflict_is_explicit_and_never_reties(self):
        a,d=item('A','A','TAIL',2),item('D','D','VSS',0,role='dummy')
        intent={'schema':mod.SCHEMA,'instances':[d,a],
                'groups':[{'name':'PAIR','rows':[['D','A']]}],
                'macro_instances':[{'name':'PAIR','rows':[['D','A']]}]}
        original=mod.digest(intent);result=mod.inspect(intent)
        self.assertEqual(result['candidates'],[])
        self.assertEqual(len(result['dummy_boundary_review']),1)
        edge=result['dummy_boundary_review'][0]
        self.assertEqual(edge['status'],'SOURCE_NET_CONFLICT')
        self.assertEqual(edge['source_nets'],{'D':'VSS','A':'TAIL'})
        self.assertEqual(mod.digest(intent),original)

    def test_missing_dummy_source_is_not_a_conflict_or_candidate(self):
        intent={'schema':mod.SCHEMA,'instances':[item('D','D',None,0,role='dummy'),item('A','A','TAIL',2)],
                'groups':[{'name':'PAIR','rows':[['D','A']]}]}
        result=mod.inspect(intent)
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['dummy_boundary_review'][0]['status'],'MISSING_SOURCE_NET')

    def test_abba_outer_edges_are_a_symmetric_probe_set(self):
        names=['A0','B0','B1','A1']
        intent={'schema':mod.SCHEMA,'instances':[item(n,n[0],'tail',2*i) for i,n in enumerate(names)],
                'groups':[{'name':'PAIR','role':'differential_pair','rows':[names]}]}
        result=mod.inspect_declared_rows(intent)
        self.assertEqual(len(result['candidates']),3)
        self.assertEqual(result['symmetric_probe_sets'][0]['candidate_ids'],['PAIR:r0:e0','PAIR:r0:e2'])
        self.assertEqual(result['candidates'][0]['current_bbox_gap_um'],1)

    def test_different_source_nets_or_pcell_masters_are_rejected(self):
        intent={'schema':mod.SCHEMA,
                'instances':[item('A','A','tail',0),item('B','B','other',2),item('C','C','other',4,master='lvt')],
                'groups':[{'name':'M','role':'current_mirror','rows':[['A','B','C']]}]}
        result=mod.inspect_declared_rows(intent)
        self.assertFalse(result['candidates'])
        self.assertEqual(result['rejected_edges'][0]['reasons'],['different_or_missing_source_net'])
        self.assertEqual(result['rejected_edges'][1]['reasons'],['different_master'])

    def test_same_net_dummy_is_eligible_but_overlapping_boxes_are_not(self):
        intent={'schema':mod.SCHEMA,
                'instances':[item('D','D','VDD',0,role='dummy'),item('A','A','VDD',0.5),item('B','B','VDD',2)],
                'groups':[{'name':'M','role':'current_mirror','rows':[['D','A','B']]}]}
        result=mod.inspect_declared_rows(intent)
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(result['candidates'][0]['instances'],['A','B'])
        self.assertIn('existing_bbox_overlap',result['rejected_edges'][0]['reasons'])

    def test_macro_row_covers_same_net_mos_outside_matching_roles(self):
        names=['A','B','C']
        intent={'schema':mod.SCHEMA,
                'instances':[item(n,n,'VSS',i*2,role='dummy' if n=='C' else 'active')
                             for i,n in enumerate(names)],
                'groups':[{'name':'GENERAL','role':'bias','rows':[names]}],
                'macro_instances':[{'name':'CORE','rows':[names]}]}
        result=mod.inspect_declared_rows(intent)
        self.assertEqual([row['instances'] for row in result['candidates']],
                         [['A','B'],['B','C']])

    def test_all_same_source_pairs_including_standalone_and_dummy(self):
        intent={'schema':mod.SCHEMA, 'instances':[item('A','A','VSS',0,role='standalone'),
                item('D','D','VSS',4,role='dummy'), item('Z','Z','VSS',20,role='dummy')]}
        result=mod.inspect(intent)
        self.assertEqual(len(result['candidates']),3)
        self.assertTrue(all(x['includes_dummy'] for x in result['candidates']))
        distant=next(x for x in result['candidates'] if x['instances']==['A','Z'])
        self.assertIn('intervening_geometry_requires_re_placement', distant['requirements'])

    def test_different_source_or_missing_source_never_qualifies(self):
        intent={'schema':mod.SCHEMA, 'instances':[item('A','A','VSS',0),item('B','B','VDD',3),item('C','C',None,5)]}
        self.assertEqual(mod.inspect(intent)['candidates'],[])

    def test_same_source_different_master_kept_but_not_approved(self):
        intent={'schema':mod.SCHEMA, 'instances':[item('A','A','VSS',0), item('B','B','VSS',3,master='other')]}
        pair=mod.inspect(intent)['candidates'][0]
        self.assertIn('pdk_device_compatibility_required',pair['requirements'])
        self.assertEqual(pair['status'],'REQUIRES_MODULE_RESOLUTION')

    def test_cross_module_pair_is_visible_but_conflicts_with_separate_rings(self):
        a,b=item('A','A','VSS',0),item('B','B','VSS',3,role='dummy')
        a['group']='DIFF'; b['group']='MIRROR'
        pair=mod.inspect({'schema':mod.SCHEMA,'instances':[a,b]})['candidates'][0]
        self.assertIn('cross_module_guard_ring_conflict',pair['requirements'])

    def test_existing_overlap_requires_measurement_not_silent_skip(self):
        a,b=item('A','A','VSS',0),item('B','B','VSS',.5)
        pair=mod.inspect({'schema':mod.SCHEMA,'instances':[a,b]})['candidates'][0]
        self.assertIn('existing_overlap_readback_required',pair['requirements'])

    def test_module_ownership_also_resolved_from_rows(self):
        a,b=item('A','A','VSS',0),item('B','B','VSS',3)
        intent={'schema':mod.SCHEMA,'instances':[a,b],
                'groups':[{'name':'PAIR','rows':[['A']]},{'name':'MIRROR','rows':[['B']]}]}
        self.assertIn('cross_module_guard_ring_conflict',mod.inspect(intent)['candidates'][0]['requirements'])
