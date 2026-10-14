import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('legacy_fixture', ROOT / 'tests/test_templates.py')
old = importlib.util.module_from_spec(loader)
loader.loader.exec_module(old)
loader = importlib.util.spec_from_file_location('fast_test_module', ROOT / 'scripts/fast_route.py')
fast = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fast)


def fixture():
    profile, access, request = old.fixture()
    request['schema'] = fast.SCHEMA
    request['seed_spec']['routes'][0]['points_um'] = [[-4, 0], [-4, 4]]
    request['routing_policy'] = {'metal_levels': {'m1': 1}, 'layer_roles': {'local': 'm1'}}
    request['ordinary_nets'] = {}
    bind(profile, access, request)
    return profile, access, request


def bind(p, a, r):
    r['sources'] = {'profile_fingerprint': fast.MIRROR.ri.fingerprint(p),
                    'terminal_access_sha256': fast.MIRROR.ri.digest(a),
                    'seed_sha256': fast.MIRROR.ri.digest(r['seed_spec'])}


class FastTests(unittest.TestCase):
    def test_fast_preserves_pair_and_offline_boundary(self):
        p, a, r = fixture()
        result = fast.compile_fast(p, a, r)
        self.assertEqual(result['status'], 'TEMPLATE_PREFLIGHT_PASS')
        self.assertEqual(result['direction_audit']['status'], 'PASS')
        self.assertFalse(result['materializable'])
        self.assertEqual(result['route_spec']['routes'][1]['points_um'], [[4, 0], [4, 4]])

    def test_pdk_names_and_rank_parity_are_not_level_parity(self):
        p, a, r = fixture()
        p['layers'][0]['name'] = 'CUSTOM_47'
        p['routing_layers'][0]['layer'] = 'CUSTOM_47'
        p['layer_functions'] = [{'layer': 'CUSTOM_47', 'function': 'metal', 'rank': 10}]
        for inst in a['instances']:
            data = inst['terminals']['G']
            data['access_layers'] = ['CUSTOM_47']
            data['pin_islands'][0]['access_layers'] = ['CUSTOM_47']
        r['seed_spec']['routes'][0]['layer'] = 'CUSTOM_47'
        r['routing_policy'] = {'metal_levels': {'CUSTOM_47': 1}, 'layer_roles': {'local': 'CUSTOM_47'}}
        p['fingerprint']['value'] = fast.MIRROR.ri.fingerprint(p)
        bind(p, a, r)
        self.assertEqual(fast.compile_fast(p, a, r)['status'], 'TEMPLATE_PREFLIGHT_PASS')

    def test_rejects_wrong_actual_stack(self):
        p, a, r = fixture()
        p['layer_functions'] = [{'layer': 'm1', 'function': 'metal', 'rank': 9}]
        r['routing_policy']['metal_levels']['m1'] = 2
        with self.assertRaisesRegex(ValueError, 'disagree'):
            fast.compile_fast(p, a, r)

    def test_off_direction_is_blocked_even_if_template_connects(self):
        p, a, r = fixture()
        r['seed_spec']['routes'][0]['points_um'] = [[-4, 0], [-5, 0], [-5, 4], [-4, 4]]
        bind(p, a, r)
        self.assertEqual(fast.compile_fast(p, a, r)['status'], 'BLOCKED')

    def test_all_access_nets_are_required(self):
        p, a, r = fixture()
        a['instances'][0]['terminals']['B'] = {'net': 'BODY', 'candidate_centers': [[-4, -1]], 'access_layers': ['m1']}
        bind(p, a, r)
        with self.assertRaisesRegex(ValueError, 'exact terminal-access'):
            fast.compile_fast(p, a, r)

    def test_cannot_omit_symmetry_scope(self):
        p, a, r = fixture()
        r['pairs'] = []
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            fast.compile_fast(p, a, r)

    def test_ordinary_reasons_must_be_nonempty(self):
        p, a, r = fixture()
        r['ordinary_nets'] = {'P': ''}
        with self.assertRaisesRegex(ValueError, 'reasons'):
            fast.compile_fast(p, a, r)

    def test_stale_bindings_block(self):
        p, a, r = fixture()
        r['sources']['seed_sha256'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'Stale'):
            fast.compile_fast(p, a, r)

    def test_no_hidden_template_or_search_fallback(self):
        p, a, r = fixture()
        with self.assertRaisesRegex(ValueError, 'FAST_TEMPLATE_REQUIRED'):
            fast.configured_search(p, a, {}, {'layer_roles': {}})
        with self.assertRaisesRegex(ValueError, 'cannot silently'):
            fast.configured_search(p, a, {'symmetry_solver': {'axis': {}}}, {})

    def test_no_off_direction_bus_branch(self):
        with self.assertRaisesRegex(ValueError, 'share bus y'):
            fast.MIRROR.horizontal_bus('s', 'SUPPLY', 'custom1', 'custom2', .2, .6, 'via',
                [{'access': {'xy_um': [0, 0]}, 'landing_xy_um': [0, 1]}], 3, [-2, 2])

    def test_generated_tracks_change_with_measured_obstacle(self):
        p, a, r = fixture()
        obstacle = {'bounds_um': [[-10, -10], [10, 10]], 'obstacles': [{'layer': 'm1', 'bbox_um': [[1, -2], [2, 2]]}]}
        tracks = fast.generated_tracks(p, obstacle, [[0, 0]], 'x', 'm1', .2, 20)
        self.assertIn(.7, tracks)
        self.assertIn(2.3, tracks)
        obstacle['obstacles'][0]['bbox_um'] = [[3, -2], [4, 2]]
        moved = fast.generated_tracks(p, obstacle, [[0, 0]], 'x', 'm1', .2, 20)
        self.assertNotIn(.7, moved)
        self.assertIn(2.7, moved)
        self.assertEqual(len(fast.generated_tracks(p, obstacle, [[0, 0]], 'x', 'm1', .2, 2)), 2)

    def test_configured_fast_selection_compiles_the_same_geometry(self):
        p, a, r = fixture()
        policy = {'fast_templates': {k: copy.deepcopy(r[k]) for k in ('axis', 'seed_spec', 'pairs', 'self_nets', 'ordinary_nets')}}
        pdk = {'layer_roles': r['routing_policy']['layer_roles'], 'routing_rules': {'metal_levels': {'m1': 1}}}
        result = fast.configured_search(p, a, policy, pdk, target=a['target'])
        self.assertEqual(result['status'], 'PLANNED')
        self.assertFalse(result['materializable'])

    def test_layered_dogleg_uses_mapped_layers_and_a_real_named_via(self):
        p, _, _ = fixture()
        p['routing_layers'].append({**copy.deepcopy(p['routing_layers'][0]), 'layer': 'vendor_upper'})
        p['vias'] = [{'name': 'vendor_transition', 'layer1': 'm1', 'layer2': 'vendor_upper'}]
        policy = {'metal_levels': {'m1': 1, 'vendor_upper': 2}, 'layer_roles': {'local': 'm1', 'collection': 'vendor_upper'}}
        fragment = fast.layered_dogleg(p, policy, 'candidate', 'N', [[0, 0], [2, 0], [2, 2]], 'collection', 'local', {'collection': .4, 'local': .2}, 'vendor_transition')
        self.assertEqual([x['layer'] for x in fragment['routes']], ['vendor_upper', 'm1'])
        self.assertEqual(fragment['vias'][0]['via'], 'vendor_transition')
        with self.assertRaisesRegex(ValueError, 'Named PDK via'):
            fast.layered_dogleg(p, policy, 'candidate', 'N', [[0, 0], [2, 0], [2, 2]], 'collection', 'local', {'collection': .4, 'local': .2}, 'invented')
        policy['metal_levels']['vendor_upper'] = 4
        with self.assertRaisesRegex(ValueError, 'Nonadjacent'):
            fast.layered_dogleg(p, policy, 'candidate', 'N', [[0, 0], [2, 0], [2, 2]], 'collection', 'local', {'collection': .4, 'local': .2}, 'vendor_transition')

    def test_local_exception_covers_the_full_route_footprint(self):
        p, _, r = fixture()
        spec = {'routes': [{'id': 'exception', 'layer': 'm1', 'width_um': .2, 'points_um': [[0, 0], [1, 0], [1, 4]]}]}
        policy = {'metal_levels': {'m1': 1}, 'local_direction_exceptions': {'exception': {'source': 'measurement', 'reason': 'local pin escape', 'region_um': [[-.2, -.2], [1.2, .2]], 'max_length_um': 6}}}
        self.assertEqual(fast.direction_audit(p, spec, policy)['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
