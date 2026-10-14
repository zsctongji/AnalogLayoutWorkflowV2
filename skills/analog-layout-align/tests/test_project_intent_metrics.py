import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "project_intent_metrics.py"
SPEC = importlib.util.spec_from_file_location("project_intent_metrics", SCRIPT)
PROJECT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROJECT)


class ProjectionTests(unittest.TestCase):
    def test_orientation_round_trip(self):
        for orientation in ("R0", "MX", "MY", "R180"):
            local = [1.25, -2.5]
            origin = [10.0, 20.0]
            placed = PROJECT.place(local, origin, orientation)
            self.assertEqual(PROJECT.inverse_placed(placed, origin, orientation), local)

    def test_hpwl(self):
        self.assertEqual(PROJECT.hpwl([[0.0, 1.0], [3.0, -1.0], [2.0, 4.0]]), 8.0)

    def test_candidate_choice_converges_toward_shared_access(self):
        terminals = [
            {"candidate_centers": [[0.0, 0.0], [5.0, 0.0]]},
            {"candidate_centers": [[5.0, 0.0], [10.0, 0.0]]},
        ]
        self.assertEqual(PROJECT.choose(terminals), [[5.0, 0.0], [5.0, 0.0]])


if __name__ == "__main__":
    unittest.main()
