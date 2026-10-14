import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from dispatch_preflight import placement_preflight, check_matching_intent
from workflow_runtime import Invalid, filehash, init, write

class PlacementPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.source={'lib':'test','cell':'AMP','view':'schematic'}
        self.schematic={'source':dict(self.source,positions_included=False),'instances':[
            {'name':'N','lib':'pdk','cell':'mos','params':{'m':'2'},'terms':{'G':'IN','S':'VSS'}},
            {'name':'C','lib':'pdk','cell':'cap','params':{'m':'2'},'terms':{'N1':'IN','N2':'VSS'}}]}
        self.intent={'source_schematic':dict(self.source,positions_included=False),'instances':[]}
        for device in self.schematic['instances']:
            for index in range(2):
                self.intent['instances'].append({'name':f'{device["name"]}__M{index}',
                    'logical_device':device['name'],'copy_index':index,'copy_count':2,
                    'source_master':{'lib':'pdk','cell':device['cell'],'view':'schematic'},
                    'pcell_parameters':{'m':'1'},'terminals':device['terms'],
                    'group':'G','placement_role':'active'})
        self.state={'source':self.source,'constraints':{'matching':'common-axis','dummy_module_map':{}},
                    'dispatch_inputs':{'place':{}}}
        self.refresh()
    def tearDown(self):self.tmp.cleanup()
    def refresh(self):
        for key,data in (('schematic',self.schematic),('placement_intent',self.intent)):
            path=self.base/(key+'.json');write(path,data)
            self.state['dispatch_inputs']['place'][key]={'path':path.name,'sha256':filehash(path)}
    def test_capacitor_m_is_counted(self):
        result=placement_preflight(self.state,self.base,True)
        self.assertEqual(result['expected_parallel_copies'],{'N':2,'C':2})
        self.assertEqual(result['expected_instance_count'],4)
    def test_missing_second_capacitor_blocks(self):
        self.intent['instances'].pop();self.refresh()
        with self.assertRaisesRegex(Invalid,'Parallel-copy'):placement_preflight(self.state,self.base,True)
    def test_planning_without_candidate(self):
        del self.state['dispatch_inputs']['place']['placement_intent']
        self.assertEqual(placement_preflight(self.state,self.base,False)['status'],'INPUTS_CHECKED')
        with self.assertRaisesRegex(Invalid,'Materialize'):placement_preflight(self.state,self.base,True)
    def test_changed_candidate_blocks(self):
        (self.base/'placement_intent.json').write_text('{}')
        with self.assertRaisesRegex(Invalid,'missing/changed'):placement_preflight(self.state,self.base,True)
    def test_another_source_blocks(self):
        self.schematic['source']['cell']='OTHER';self.refresh()
        with self.assertRaisesRegex(Invalid,'identity'):placement_preflight(self.state,self.base,True)
    def test_wrong_net_blocks(self):
        self.intent['instances'][0]['terminals']=dict(G='OUT',S='VSS');self.refresh()
        with self.assertRaisesRegex(Invalid,'net mismatch'):placement_preflight(self.state,self.base,True)
    def test_dummy_ownership_blocks(self):
        self.state['constraints']['dummy_module_map']={'N':'OTHER'}
        with self.assertRaisesRegex(Invalid,'Dummy ownership'):placement_preflight(self.state,self.base,True)
    def test_unresolved_dummy_blocks(self):
        self.intent['instances'][0]['placement_role']='dummy';self.refresh()
        with self.assertRaisesRegex(Invalid,'dummy ownership'):placement_preflight(self.state,self.base,True)
    def test_duplicate_copy_index_blocks(self):
        self.intent['instances'][1]['copy_index']=0;self.refresh()
        with self.assertRaisesRegex(Invalid,'indices'):placement_preflight(self.state,self.base,True)
    def test_unspecified_matching_defaults_to_common_axis(self):
        self.state['constraints'].pop('matching')
        self.assertEqual(placement_preflight(self.state,self.base,True)['matching_policy']['default'],'common_axis')
    def test_implicit_common_centroid_blocks(self):
        self.intent['groups']=[{'name':'PAIR','pattern_mode':'rotational_2x2_diagonal_common_centroid'}];self.refresh()
        with self.assertRaisesRegex(Invalid,'explicit user request'):placement_preflight(self.state,self.base,True)
    def test_explicit_common_centroid_allowed_for_named_group(self):
        self.intent['groups']=[{'name':'PAIR','pattern_mode':'rotational_2x2_diagonal_common_centroid'}];self.refresh()
        self.state['constraints']['matching_overrides']={'PAIR':{'mode':'common_centroid','source':'user','instruction':'Use common centroid for PAIR.'}}
        placement_preflight(self.state,self.base,True)
        self.intent['groups'].append({'name':'OTHER','pattern_mode':'common_centroid'});self.refresh()
        with self.assertRaisesRegex(Invalid,'OTHER'):placement_preflight(self.state,self.base,True)
    def test_agent_cannot_authorize_centroid(self):
        self.state['constraints']['matching_overrides']={'PAIR':{'mode':'common_centroid','source':'agent','instruction':'Use common centroid.'}}
        with self.assertRaisesRegex(Invalid,'user instruction'):placement_preflight(self.state,self.base,True)
    def test_noninteger_source_m_blocks(self):
        self.schematic['instances'][1]['params']['m']='1.5';self.refresh()
        with self.assertRaisesRegex(Invalid,'positive integer'):placement_preflight(self.state,self.base,True)
    def test_init_preserves_dispatch_inputs(self):
        config=dict(run_id='test',source=self.source,reference=self.source,
                    destination={'lib':'test','cell':'LAYOUT','view':'layout'},
                    constraints=self.state['constraints'],bindings={'source':'hash'},
                    last_human_decision='Use frozen placement decisions',
                    dispatch_inputs=self.state['dispatch_inputs'])
        result=init(config)
        self.assertEqual(result['dispatch_inputs'],self.state['dispatch_inputs'])

class LogicalPatternTests(unittest.TestCase):
    def setUp(self):
        self.state={'constraints':{'axis':{'x_um':0},'matching_overrides':{'PAIR':{'mode':'explicit_pattern','pattern':'ABBA','source':'user','instruction':'Use ABBA on the common axis.'}}}}
        self.intent={'coordinate_contract':{'manufacturing_grid':.001},'groups':[{'name':'PAIR','logical_devices':['A','B'],'rows':[['A0','B0','B1','A1']]}],
                     'instances':[{'name':n,'logical_device':n[0],'bbox':[[x-.4,y],[x+.4,y+1]]} for n,x,y in [('A0',-3,0),('B0',-1,-.5),('B1',1,-.5),('A1',3,0)]]}
    def test_abba_common_axis_does_not_require_equal_y_centroid(self):
        check_matching_intent(self.state,self.intent)
    def test_centered_aabb_rejected_even_with_abba_written_rows(self):
        for item,x in zip(self.intent['instances'],[-3,1,3,-1]):item['bbox']=[[x-.4,0],[x+.4,1]]
        with self.assertRaisesRegex(Invalid,'order violates'):check_matching_intent(self.state,self.intent)
    def test_order_alone_cannot_mask_off_axis(self):
        for i in self.intent['instances']:
            if i['logical_device']=='A':
                for p in i['bbox']:p[0]+=.01
        with self.assertRaisesRegex(Invalid,'declared axis'):check_matching_intent(self.state,self.intent)
    def test_missing_requested_group_rejected(self):
        self.intent['groups']=[]
        with self.assertRaisesRegex(Invalid,'group is missing'):check_matching_intent(self.state,self.intent)
    def test_missing_bbox_rejected(self):
        self.intent['instances'][0].pop('bbox')
        with self.assertRaisesRegex(Invalid,'physical bboxes'):check_matching_intent(self.state,self.intent)

if __name__=='__main__':unittest.main()
