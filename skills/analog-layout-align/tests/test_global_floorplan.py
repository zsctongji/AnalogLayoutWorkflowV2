import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from placement_candidates import generate_candidates
from analyze_placement import global_floorplan_metrics, closure_decision
from placement_optimizer import pareto


class GlobalFloorplanTests(unittest.TestCase):
    def fixture(self):
        records = [dict(name=n, group=g, bbox=b, terminals={'D': 'CRIT'}) for n, g, b in
                   [('CORE', 'CORE_GROUP', [[0, 0], [10, 10]]),
                    ('CAP_A', 'CAP', [[100, 0], [110, 10]]),
                    ('CAP_B', 'CAP', [[112, 0], [122, 10]])]]
        intent = {'instances': records, 'coordinate_contract': {'manufacturing_grid': .1},
                  'floorplan': {'core_macros': ['CORE_GROUP']},
                  'groups': [{'name': 'CAP', 'rows': [['CAP_A', 'CAP_B']]}]}
        request = {'search': {'macro_relocation_gap_um': 2},
                   'constraints': {'critical_net_weights': {'CRIT': 1}}}
        return intent, request

    def test_coarse_move_keeps_array_and_core(self):
        p, r = self.fixture()
        before = copy.deepcopy(p)
        moves = [m for m in generate_candidates(p, {}, r, []) if 'macro relocation' in m['reason']]
        self.assertEqual(len(moves), 4)
        self.assertTrue(all(m['affected_instances'] == ['CAP_A', 'CAP_B'] for m in moves))
        self.assertTrue(any(abs(m['spec']['operations'][0]['dx']) > 50 for m in moves))
        self.assertEqual(p, before)

    def test_locked_member_locks_entire_array(self):
        p, r = self.fixture()
        r['search']['locked_instances'] = ['CAP_B']
        self.assertFalse(any('macro relocation' in m['reason'] for m in generate_candidates(p, {}, r, [])))

    def test_no_critical_intent_no_implicit_supply_attraction(self):
        p, r = self.fixture()
        r['constraints'] = {}
        self.assertFalse(any('macro relocation' in m['reason'] for m in generate_candidates(p, {}, r, [])))

    def test_bad_gap_rejected(self):
        p, r = self.fixture()
        for gap in [0, -1, True, float('nan')]:
            r['search']['macro_relocation_gap_um'] = gap
            with self.assertRaises(ValueError): generate_candidates(p, {}, r, [])

    def test_global_metrics_include_passives(self):
        p, _ = self.fixture()
        p['instances'][1]['kind'] = 'capacitor'
        metrics = global_floorplan_metrics(p['instances'])
        self.assertEqual(metrics['width_um'], 122)
        self.assertAlmostEqual(metrics['bbox_occupancy'], 300/1220)

    def test_local_matching_cannot_close_long_nets(self):
        d = closure_decision(False, [{'name': 'CRIT'}], True)
        self.assertEqual(d['status'], 'GLOBAL FLOORPLAN REVIEW REQUIRED')
        self.assertIsNone(d['needs_refinement'])
        self.assertTrue(closure_decision(True, [], False)['needs_refinement'])

    def test_observed_channel_count_cannot_reward_worse_floorplan(self):
        p, _ = self.fixture()
        def candidate(name, cost, unknown):
            intent = copy.deepcopy(p)
            intent['instances'][0]['origin'] = [cost, 0]
            return {'candidate_id': name, 'intent': intent, 'evaluation': {'status': 'EVALUATED',
                    'metrics': {'critical_hpwl_um': cost, 'unknown_channels': unknown,
                                'unknown_declared_channels': 0, 'unknown_accesses': 10}}}
        result = pareto([candidate('worse', 200, 60), candidate('better', 100, 70)], ['critical_hpwl_um'], 5)
        self.assertEqual([c['candidate_id'] for c in result], ['better'])


if __name__ == '__main__': unittest.main()
