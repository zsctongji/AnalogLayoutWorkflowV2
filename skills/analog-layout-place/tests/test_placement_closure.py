import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_placement.py"
SPEC = importlib.util.spec_from_file_location("analyze_placement", SCRIPT)
CLOSURE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CLOSURE)


def access_instance(name, logical, x):
    terminals = {
        terminal: {"candidate_centers": [[x, offset]], "preferred_figures": [{"center": [x, offset], "layer": "mt1"}], "net": terminal}
        for terminal, offset in (("D", 0.2), ("G", 0.5), ("S", 0.8))
    }
    return {"name": name, "kind": "nmos", "logical_device": logical, "bbox": [[x - 0.5, 0.0], [x + 0.5, 1.0]], "terminals": terminals}


class PlacementClosureTests(unittest.TestCase):
    def test_lowest_metal_figures_are_preferred(self):
        figures = [
            {"layer": "poly1", "center": [0, 0]},
            {"layer": "mt2", "center": [1, 0]},
            {"layer": "mt1", "center": [2, 0]},
            {"layer": "metal1", "center": [3, 0]},
        ]
        self.assertEqual([item["center"] for item in CLOSURE.preferred_figures(figures)], [[2, 0], [3, 0]])

    def test_physical_pin_islands_preserve_each_cadence_pin(self):
        figures = [
            {"pin_index": 0, "layer": "mt1", "center": [1, 0], "bbox": [[0.8, -0.2], [1.2, 0.2]]},
            {"pin_index": 1, "layer": "poly1", "center": [3, 0], "bbox": [[2.9, -0.2], [3.1, 0.2]]},
            {"pin_index": 1, "layer": "mt1", "center": [4, 0], "bbox": [[3.8, -0.2], [4.2, 0.2]]},
        ]
        islands = CLOSURE.physical_pin_islands("M0", "D", figures)
        self.assertEqual([item["id"] for item in islands], ["M0:D:p0", "M0:D:p1"])
        self.assertEqual(islands[0]["candidate_centers"], [[1, 0]])
        self.assertEqual(islands[1]["candidate_centers"], [[4, 0]])

    def test_pair_symmetry_uses_group_metadata_not_device_names(self):
        instances = {
            "A_L": access_instance("A_L", "ALPHA", -2.0),
            "A_R": access_instance("A_R", "ALPHA", 2.0),
            "B_L": access_instance("B_L", "BETA", -1.0),
            "B_R": access_instance("B_R", "BETA", 1.0),
        }
        group = {"name": "PAIR", "instances": list(instances), "logical_devices": ["ALPHA", "BETA"], "pattern_mode": "explicit_abba"}
        result = CLOSURE.mirror_symmetry(instances, group)
        self.assertEqual(result["symmetry_transform"], "MY")
        self.assertEqual(result["status"], "pass")

    def test_rotational_pattern_checks_both_axes(self):
        instances = {
            "A0": access_instance("A0", "ALPHA", -1.0),
            "A1": access_instance("A1", "ALPHA", 1.0),
            "B0": access_instance("B0", "BETA", -2.0),
            "B1": access_instance("B1", "BETA", 2.0),
        }
        for item in instances.values():
            if item["name"].endswith("0"):
                for terminal in item["terminals"].values():
                    terminal["candidate_centers"][0][1] -= 0.5
        group = {"name": "ROT", "instances": list(instances), "logical_devices": ["ALPHA", "BETA"], "pattern_mode": "rotational_common_centroid"}
        result = CLOSURE.mirror_symmetry(instances, group)
        self.assertEqual(result["symmetry_transform"], "R180")
        self.assertEqual(result["status"], "issue")


if __name__ == "__main__":
    unittest.main()
