import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'analog-layout-workflow/scripts'))
loader = importlib.util.spec_from_file_location('fast_frontend_fixture', ROOT / 'analog-layout-symmetric-fast/tests/test_fast.py')
fixture_module = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture_module)
loader = importlib.util.spec_from_file_location('fast_frontend', ROOT / 'analog-layout-workflow/scripts/configured_flow.py')
flow = importlib.util.module_from_spec(loader)
loader.loader.exec_module(flow)


class FrontendTests(unittest.TestCase):
    def project(self, base):
        p, a, r = fixture_module.fixture()
        for name, data in [('profile.json', p), ('access.json', a)]:
            (base / name).write_text(json.dumps(data))
        return {'_base': str(base), '_project_sha256': 'fixture', '_bindings': {}, 'target': a['target'],
                'inputs': {'routing_profile': 'profile.json', 'terminal_access': 'access.json'},
                'routing': {'fast_templates': {k: copy.deepcopy(r[k]) for k in ('axis', 'seed_spec', 'pairs', 'self_nets', 'ordinary_nets')}},
                'pdk': {'layer_roles': r['routing_policy']['layer_roles'], 'routing_rules': {'metal_levels': {'m1': 1}}}}

    def test_unspecified_method_is_fast_and_missing_templates_do_not_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = self.project(root)
            result = flow.route(project, root / 'candidate')
            self.assertEqual(result['status'], 'PLANNED', result)
            out = Path(result['output'])
            self.assertEqual(out.name, 'symmetric-fast')
            self.assertEqual(json.loads((out / 'candidates.json').read_text())['backend'], 'symmetric_fast')
            self.assertEqual(json.loads((out / 'direction-audit.json').read_text())['status'], 'PASS')
            project['routing'] = {}
            result = flow.route(project, root / 'candidate')
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertIn('FAST_TEMPLATE_REQUIRED', result['failures'][0]['reason'])
            self.assertEqual(json.loads((out / 'spec.json').read_text())['routes'], [])
            self.assertEqual(json.loads((out / 'intent.json').read_text())['configuration_gate']['status'], 'BLOCKED')
            self.assertEqual(json.loads((out / 'direction-audit.json').read_text())['status'], 'BLOCKED')
            self.assertEqual(json.loads((out / 'template-result.json').read_text())['status'], 'BLOCKED')

    def test_existing_success_is_replaced_after_direction_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = self.project(root)
            result = flow.route(project, root / 'candidate')
            out = Path(result['output'])
            project['routing']['fast_templates']['seed_spec']['routes'][0]['points_um'] = [[-4, 0], [-5, 0], [-5, 4], [-4, 4]]
            result = flow.route(project, root / 'candidate')
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(json.loads((out / 'spec.json').read_text())['routes'], [])

    def test_explicit_general_backend_is_preserved(self):
        p, a, r = fixture_module.fixture()
        module = fixture_module.fast
        loader = importlib.util.spec_from_file_location('explicit_general', ROOT / 'analog-layout-route/scripts/configured_route.py')
        configured = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(configured)
        policy = {'backend': 'general', 'nets': {n: {'net_class': 'ordinary', 'layers': ['m1'], 'widths_um': {'m1': .2}} for n in ('P', 'N')}}
        obstacles = {'schema': configured.PLANNER.OBSTACLE_SCHEMA, 'target': a['target'],
                     'sources': {'profile_fingerprint': p['fingerprint']['value'], 'terminal_access_sha256': module.MIRROR.ri.digest(a)},
                     'bounds_um': [[-10, -10], [10, 10]], 'obstacles': [], 'coverage': {'live_snapshot': False}}
        result = configured.search(p, a, policy, {}, obstacles)
        self.assertEqual(result['status'], 'PLANNED', result['failures'])
        self.assertNotEqual(result['backend'], 'symmetric_fast')

    def test_bad_or_missing_input_never_leaves_previous_success_selected(self):
        for failure in ('malformed-profile', 'missing-access', 'malformed-access-shape', 'missing-obstacles'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                project = self.project(root)
                result = flow.route(project, root / 'candidate')
                out = Path(result['output'])
                self.assertEqual(result['status'], 'PLANNED')
                if failure == 'malformed-profile':
                    (root / 'profile.json').write_text('{')
                elif failure == 'missing-access':
                    project['inputs']['terminal_access'] = 'absent.json'
                elif failure == 'malformed-access-shape':
                    (root / 'access.json').write_text('[1,2,3]')
                else:
                    project['inputs']['obstacles'] = 'absent-obstacles.json'
                result = flow.route(project, root / 'candidate')
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(json.loads((out / 'candidates.json').read_text())['candidates'], [])
                self.assertEqual(json.loads((out / 'spec.json').read_text())['routes'], [])
                self.assertEqual(json.loads((out / 'intent.json').read_text())['configuration_gate']['status'], 'BLOCKED')

    def test_unreadable_routing_policy_invalidates_prior_cli_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = self.project(root)
            result = flow.route(project, root / 'candidate')
            out = Path(result['output'])
            external = {'schema': 'analog-layout-workflow.project/v1', 'source': {**project['target'], 'view': 'schematic'},
                        'target': project['target'], 'inputs': project['inputs'], 'pdk': 'pdk.json', 'circuit': 'circuit.json', 'routing': 'routing.json'}
            (root / 'project.json').write_text(json.dumps(external))
            (root / 'pdk.json').write_text(json.dumps({'schema': 'analog-layout-workflow.pdk-map/v1', 'devices': [{}], **project['pdk']}))
            (root / 'circuit.json').write_text(json.dumps({'schema': 'analog-layout-workflow.circuit/v1'}))
            (root / 'routing.json').write_text('{')
            with patch.object(sys, 'argv', ['configured_flow.py', 'route', '--project', str(root / 'project.json'), '--work', str(root / 'candidate')]):
                self.assertEqual(flow.main(), 2)
            self.assertEqual(json.loads((out / 'template-result.json').read_text())['status'], 'BLOCKED')
            self.assertEqual(json.loads((out / 'intent.json').read_text())['configuration_gate']['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
