import copy
import unittest

from plan_guard_ring import plan as raw_plan, ring_points
from partition_modules import partition
from check_gate_access import check_gate_access, content_hash


def gate_fixture(intent, source):
    """Synthetic qualified evidence for planner regression tests, never PDK data."""
    access = {'schema': 'analog-layout-align.terminal-access/v1', 'target': source, 'instances': []}
    records = []
    for item in intent['instances']:
        item.setdefault('terminals', {}).setdefault('G', 'G_'+item['name'])
        ident = item['name']+':G:p0'
        access['instances'].append({'name': item['name'], 'bbox': item['bbox'], 'terminals': {'G': {
            'net': item['terminals']['G'], 'pin_islands': [{'id': ident, 'figures': [{'layer': 'poly', 'bbox': item['bbox']}]}]}}})
        records.append({'instance': item['name'], 'net': item['terminals']['G'], 'covered_island_ids': [ident],
                        'contact_object_ids': [item['name']+':cut'], 'metal_landing_object_ids': [item['name']+':landing'],
                        'metal_layer': 'testM1', 'access_bbox_um': copy.deepcopy(item['bbox']), 'verification_source': 'synthetic-test',
                        'continuity_verified': True, 'pdk_legality_verified': True, 'local_escape_verified': True})
    review = {'schema': 'analog-layout-guard-ring.gate-contact-review/v1', 'target': source,
              'intent_sha256': content_hash(intent), 'terminal_access_sha256': content_hash(access),
              'layout_snapshot_sha256': 'synthetic-layout', 'pdk_fingerprint': 'synthetic-pdk', 'records': records}
    return access, review


def plan(intent, profile, request, hashes):
    intent = copy.deepcopy(intent)
    access, review = gate_fixture(intent, request['source'])
    return raw_plan(intent, profile, request, hashes, access, review)


class GuardRingPlanTests(unittest.TestCase):
    def setUp(self):
        self.intent = {
            "schema": "analog-layout-align.pcell-placement-intent/v2",
            "coordinate_contract": {"manufacturing_grid": 0.005},
            "validation": {"bbox_overlap_free": True, "missing_instances": []},
            "instances": [
                {"name": "A", "bbox": [[0, 0], [2, 2]]},
                {"name": "B", "bbox": [[3, 0], [5, 2]]},
                {"name": "C", "bbox": [[15, 0], [17, 2]]},
            ],
        }
        cuts = [[[x - 0.225, -0.225], [x + 0.225, 0.225]] for x in (2, 3, 4, 5)]
        self.profile = {"source": {"lib": "mylib", "cell": "ref", "view": "layout"},
                        "rings": [{"id": "r0", "polarity": "p_substrate",
                                   "centerline_bbox_um": [[0, 0], [10, 6]],
                                   "path_layers": [{"lpp": [name, "drawing"], "width_um": width}
                                                   for name, width in (("thin", 0.9), ("pplus", 1.4), ("mt1", 0.81))],
                                   "contact_sizes_um": [[0.45, 0.45]],
                                   "contact_boxes_um": cuts, "contact_lpp": ["cont", "drawing"]}]}
        self.request = {"schema": "analog-layout-guard-ring.request/v1",
                        "source": {"lib": "mylib", "cell": "src", "view": "layout"},
                        "target": {"lib": "mylib", "cell": "dst", "view": "layout"},
                        "instance_names": ["A", "B"], "polarity": "p_substrate", "tie_net": "AVSS",
                        "reference_ring_id": "r0", "reference_qualified_for_pdk": True,
                        "active_to_inner_edge_um": 1, "foreign_keepout_um": 0,
                        "qualified_recipe": {"pdk_id": "test", "rule_source": "test-deck",
                                             "contact_pitch_um": 1, "corner_contact_inset_um": 1.2}}

    def test_valid_plan_is_closed_and_has_four_contact_sides(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', group='M' if item['name'] in ('A', 'B') else 'OTHER', terminals={'B': 'AVSS'})
        result = plan(self.intent, self.profile, self.request, {"intent": "hash"})
        self.assertEqual(result["status"], "PREFLIGHT_ONLY")
        self.assertEqual(result["points_um"][0], result["points_um"][-1])
        self.assertGreater(result["checks"]["contact_count"], 8)
        box = result["centerline_bbox_um"]
        centers = [[(cut[0][i] + cut[1][i]) / 2 for i in (0, 1)]
                   for cut in result["contact_boxes_um"]]
        for axis in (0, 1):
            for edge in (box[0][axis], box[1][axis]):
                self.assertTrue(any(abs(center[axis] - edge) < 1e-7 for center in centers))

    def test_configured_layer_roles_and_contact_size(self):
        for item in self.intent['instances']:
            item.update(kind='nmos',group='M' if item['name'] in ('A','B') else 'OTHER',terminals={'B':'AVSS'})
        roles={'active':'OD','implant':'PIMP','metal':'M1'}
        rename={'thin':'OD','pplus':'PIMP','mt1':'M1'}
        ring=self.profile['rings'][0]
        for layer in ring['path_layers']:layer['lpp'][0]=rename[layer['lpp'][0]]
        ring['contact_sizes_um']=[[.5,.5]];ring['contact_lpp']=['CUT','drawing']
        self.request['qualified_recipe'].update(layer_roles=roles,contact_size_um=[.5,.5])
        result=plan(self.intent,self.profile,self.request,{"intent":"hash"})
        self.assertEqual({x['lpp'][0] for x in result['path_layers']},set(roles.values()))
        self.assertEqual(result['contact_lpp'],['CUT','drawing'])
        for box in result['contact_boxes_um']:
            self.assertAlmostEqual(box[1][0]-box[0][0],.5)
            self.assertAlmostEqual(box[1][1]-box[0][1],.5)

    def test_recipe_contact_size_must_match_qualified_reference(self):
        self.request['qualified_recipe']['contact_size_um']=[.5,.5]
        with self.assertRaisesRegex(ValueError,'cross-section'):plan(self.intent,self.profile,self.request,{"intent":"hash"})

    def test_foreign_instance_in_ring_is_rejected(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', group='M' if item['name'] in ('A', 'B') else 'OTHER', terminals={'B': 'AVSS'})
        self.intent["instances"][2]["bbox"] = [[2.3, 0.2], [2.6, 1.8]]
        with self.assertRaisesRegex(ValueError, "Unselected PCell"):
            plan(self.intent, self.profile, self.request, {})

    def test_unsupported_well_ring_rejected(self):
        request = copy.deepcopy(self.request)
        request["polarity"] = "n_well"
        with self.assertRaisesRegex(ValueError, "P\\+ substrate"):
            plan(self.intent, self.profile, request, {})

    def test_unqualified_reference_rejected(self):
        request = copy.deepcopy(self.request)
        request["reference_qualified_for_pdk"] = False
        with self.assertRaisesRegex(ValueError, "qualification"):
            plan(self.intent, self.profile, request, {})

    def test_source_target_must_differ(self):
        request = copy.deepcopy(self.request)
        request["target"] = request["source"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            plan(self.intent, self.profile, request, {})

    def test_same_rail_different_modules_stay_separate(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', group=item['name'], terminals={'B': 'AVSS'})
        result = partition(self.intent)
        self.assertEqual(len(result['domains']), 3)
        with self.assertRaisesRegex(ValueError, 'cross-module'):
            plan(self.intent, self.profile, self.request, {})

    def test_dummy_follows_associated_module(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', terminals={'B': 'AVSS'}, group='M')
        self.intent['instances'][2].pop('group')
        self.intent['instances'][2]['placement_role'] = 'dummy'
        self.intent['dummy_associations'] = [{'status': 'associated_test', 'target_group': 'M', 'dummy_copies': ['C']}]
        self.assertEqual(partition(self.intent)['domains'][0]['instance_names'], ['A', 'B', 'C'])

    def test_ambiguous_membership_blocks(self):
        self.intent['instances'][0].update(kind='nmos', group='M', terminals={'B': 'AVSS'})
        self.intent['groups'] = [{'name': 'DIFFERENT', 'rows': [['A']]}]
        self.assertEqual(partition(self.intent)['status'], 'BLOCKED_MODULE_OWNERSHIP')

    def test_missing_module_is_not_guessed_from_rail(self):
        self.intent['instances'][0].update(kind='nmos', terminals={'B': 'AVSS'})
        self.assertEqual(partition(self.intent)['unresolved'][0]['instance'], 'A')


    def sharing_fixture(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', group='M' if item['name'] in ('A','B') else 'OTHER', terminals={'B':'AVSS'})
        self.intent['instances'][1]['bbox'] = [[1.5,0],[3.5,2]]
        self.intent['validation'].update(bbox_overlap_free=False, shared_diffusion_complete=True, shared_diffusion_only_bbox_overlaps=True)
        self.intent['shared_diffusion_groups'] = [{'instances':['A','B'], 'terminal':'S', 'axis':'x',
            'evidence':{'source_contact_overlap_verified':True,'overlap_isolation_verified':True,
                        'pair_probe_sha256':'test-proof','expected_bbox_overlap_um':.5}}]

    def test_declared_shared_overlap_is_accepted(self):
        self.sharing_fixture()
        self.assertEqual(plan(self.intent,self.profile,self.request,{})['status'],'PREFLIGHT_ONLY')

    def test_shared_overlap_depth_change_rejected(self):
        self.sharing_fixture()
        self.intent['instances'][1]['bbox'][0][0]=1.4
        with self.assertRaisesRegex(ValueError,'depth changed'):
            plan(self.intent,self.profile,self.request,{})

    def test_shared_edge_is_subset_of_whole_module(self):
        self.sharing_fixture()
        self.intent['instances'][2]['group']='M'
        self.request['instance_names']=['A','B','C']
        result=plan(self.intent,self.profile,self.request,{})
        self.assertEqual(result['selected_instances'],['A','B','C'])

    def test_unlisted_overlap_rejected_despite_flags(self):
        self.sharing_fixture()
        self.intent['instances'][2]['bbox']=[[.5,0],[1,1]]
        with self.assertRaisesRegex(ValueError,'unresolved bbox'):
            plan(self.intent,self.profile,self.request,{})

    def test_cross_domain_shared_overlap_rejected(self):
        self.sharing_fixture()
        self.intent['instances'][1]['group']='OTHER'
        with self.assertRaisesRegex(ValueError,'crosses module'):
            plan(self.intent,self.profile,self.request,{})

    def test_no_gate_evidence_blocks_planner(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', group='M' if item['name'] in ('A','B') else 'OTHER', terminals={'B':'AVSS'})
        with self.assertRaisesRegex(ValueError, 'BLOCKED_GATE_ACCESS'):
            raw_plan(self.intent,self.profile,self.request,{})

    def test_contact_escape_envelope_expands_ring(self):
        for item in self.intent['instances']:
            item.update(kind='nmos', group='M' if item['name'] in ('A','B') else 'OTHER', terminals={'B':'AVSS'})
        access, review = gate_fixture(self.intent, self.request['source'])
        baseline = raw_plan(self.intent,self.profile,self.request,{},access,review)
        review['records'][0]['access_bbox_um'] = [[-2,-1],[2,3]]
        expanded = raw_plan(self.intent,self.profile,self.request,{},access,review)
        self.assertLess(expanded['centerline_bbox_um'][0][0], baseline['centerline_bbox_um'][0][0])
        self.assertGreater(expanded['centerline_bbox_um'][1][1], baseline['centerline_bbox_um'][1][1])


class GateAccessTests(unittest.TestCase):
    def setUp(self):
        self.source={'lib':'lib','cell':'source','view':'layout'}
        self.intent={'instances':[{'name':'A','kind':'nmos','bbox':[[0,0],[2,2]],'terminals':{'G':'IN'}}]}
        self.access,self.review=gate_fixture(self.intent,self.source)

    def check(self):
        return check_gate_access(self.intent,self.access,self.review,self.source,['A'])

    def test_poly_pin_with_proven_real_contact_can_pass(self):
        self.assertEqual(self.check()['status'],'GATE_ACCESS_EVIDENCE_COMPLETE')

    def test_poly_only_without_contact_blocks(self):
        self.review['records']=[]
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')

    def test_metal_label_alone_is_not_proof(self):
        self.access['instances'][0]['terminals']['G']['pin_islands'][0]['figures'][0]['layer']='testM1'
        self.review['terminal_access_sha256']=content_hash(self.access)
        self.review['records'][0]['contact_object_ids']=[]
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')

    def test_missing_or_string_legality_does_not_pass(self):
        self.review['records'][0]['pdk_legality_verified']='true'
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')

    def test_stale_hash_and_wrong_target_block(self):
        self.review['intent_sha256']='old'
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')
        self.review['intent_sha256']=content_hash(self.intent)
        self.review['target']={'lib':'lib','cell':'other','view':'layout'}
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')

    def test_wrong_net_blocks(self):
        self.review['records'][0]['net']='VSS'
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')

    def test_every_island_required_but_one_contact_may_cover_continuous_gate(self):
        islands=self.access['instances'][0]['terminals']['G']['pin_islands']
        other=copy.deepcopy(islands[0]);other['id']='A:G:p1';islands.append(other)
        self.review['terminal_access_sha256']=content_hash(self.access)
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')
        self.review['records'][0]['covered_island_ids'].append('A:G:p1')
        self.assertEqual(self.check()['status'],'GATE_ACCESS_EVIDENCE_COMPLETE')

    def test_dummy_cannot_be_omitted(self):
        self.intent['instances'].append({'name':'DUMMY','kind':'nmos','placement_role':'dummy','bbox':[[3,0],[4,2]],'terminals':{'G':'VSS'}})
        self.review['intent_sha256']=content_hash(self.intent)
        result=check_gate_access(self.intent,self.access,self.review,self.source,['A','DUMMY'])
        self.assertEqual(result['status'],'BLOCKED_GATE_ACCESS')

    def test_invalid_envelope_blocks(self):
        self.review['records'][0]['access_bbox_um']=[[0,0],[float('nan'),2]]
        self.assertEqual(self.check()['status'],'BLOCKED_GATE_ACCESS')

if __name__ == "__main__":
    unittest.main()
