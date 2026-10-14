"""Optional performance decisions bind to validated simulation and layout evidence."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workflow_runtime import DEPS, Invalid, checkpoint, checked, filehash, init, next_action


class PerformanceDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / 'evidence').write_text('isolated test evidence')
        self.art = [{'path': 'evidence', 'sha256': filehash(self.base / 'evidence')}]
        cell = lambda name: {'lib': 'fixture', 'cell': name, 'view': 'layout'}
        self.config = dict(run_id='isolated', mode='execute', source=cell('source'),
                           reference=cell('reference'), destination=cell('work'),
                           constraints={'axis': 0}, bindings={'layout': 'revision-A'},
                           last_human_decision='Analyze post-simulation performance')
        self.state = init(dict(self.config, requested_stages=list(DEPS)))
        self.state['current_revision'] = 'revision-A'
        for sid in list(DEPS)[:-1]:
            verdict = {'drc': 'CLEAN', 'lvs': 'VERIFIED_MATCH', 'pex': 'EXTRACTED_VALIDATED',
                       'postsim': 'MEASURED'}.get(sid, 'LOCAL_PASS')
            self.state = checkpoint(self.state, sid, self.receipt(verdict), self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def receipt(self, verdict='DECISION_READY'):
        return dict(status='LOCALLY_VERIFIED', validation={'verdict': verdict},
                    artifacts=self.art, readback_verified=True,
                    output_revision='revision-A', checked_cellview=self.state['current'])

    def test_default_scope_still_ends_at_lvs(self):
        self.assertEqual(init(self.config)['scope'][-1], 'lvs')

    def test_optional_decision_selected_after_postsim(self):
        self.assertEqual(next_action(self.state, self.base)['stage'], 'performance-opt')
        self.state = checkpoint(self.state, 'performance-opt', self.receipt(), self.base)
        self.assertEqual(next_action(self.state, self.base)['status'], 'REQUESTED_STAGES_COMPLETE')

    def test_changed_simulation_invalidates_decision(self):
        self.state = checkpoint(self.state, 'performance-opt', self.receipt(), self.base)
        self.state = checkpoint(self.state, 'postsim', dict(self.receipt('MEASURED'),
                                limitations=['recomputed measurement']), self.base)
        self.assertEqual(checked(self.state, self.base)['performance-opt']['status'], 'STALE')

    def test_wrong_layout_or_revision_rejected(self):
        for field, value in [('output_revision', 'revision-B'),
                             ('checked_cellview', self.state['destination'])]:
            with self.subTest(field=field), self.assertRaises(Invalid):
                checkpoint(self.state, 'performance-opt', dict(self.receipt(), **{field: value}), self.base)

    def test_spec_pass_cannot_replace_decision(self):
        with self.assertRaises(Invalid):
            checkpoint(self.state, 'performance-opt', self.receipt('SPEC_PASS'), self.base)
        legacy = copy.deepcopy(self.state)
        legacy = checkpoint(legacy, 'performance-opt', self.receipt(), self.base)
        legacy['stages']['performance-opt']['validation']['verdict'] = 'SPEC_PASS'
        self.assertEqual(checked(legacy, self.base)['performance-opt']['status'], 'STALE')

    def test_decision_cannot_advance_physical_target(self):
        with self.assertRaises(Invalid):
            checkpoint(self.state, 'performance-opt', dict(self.receipt(),
                       output_cellview=self.state['destination']), self.base)


if __name__ == '__main__':
    unittest.main()
