import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "refine_placement_intent.py"
SPEC = importlib.util.spec_from_file_location("refine_placement_intent", SCRIPT)
REFINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REFINE)


def instance(name, logical, x):
    return {
        "name": name,
        "kind": "nmos",
        "logical_device": logical,
        "group": "MATCH",
        "placement_role": "active",
        "origin": [x, 0.0],
        "orientation": "R0",
        "bbox": [[x, 0.0], [x + 1.0, 1.0]],
        "pcell_parameters": {"m": "1", "w": "1u"},
    }


def parent_intent():
    return {
        "schema": "analog-layout-align.pcell-placement-intent/v2",
        "coordinate_contract": {"manufacturing_grid": 0.1},
        "instances": [instance("LEFT", "A", 0.0), instance("RIGHT", "B", 2.0)],
        "groups": [{"name": "MATCH", "role": "differential_pair", "logical_devices": ["A", "B"], "instances": ["LEFT", "RIGHT"]}],
        "macro_instances": [{"name": "CORE", "rows": [["LEFT", "RIGHT"]]}],
        "floorplan": {"bbox": [[0.0, 0.0], [3.0, 1.0]], "core_macros": ["CORE"]},
        "validation": {},
    }


class RefinementTests(unittest.TestCase):
    def test_generic_macro_translation_rebuilds_geometry_and_delta(self):
        spec = {
            "schema": "analog-layout-align.refinement-spec/v1",
            "metadata": {"reason": "synthetic regression"},
            "operations": [{"op": "translate", "selector": {"macro": "CORE"}, "dx": 1.0, "dy": 2.0}],
        }
        child, delta = REFINE.refine(parent_intent(), spec)
        self.assertEqual([item["origin"] for item in child["instances"]], [[1.0, 2.0], [3.0, 2.0]])
        self.assertEqual(child["floorplan"]["bbox"], [[1.0, 2.0], [4.0, 3.0]])
        self.assertTrue(child["validation"]["bbox_overlap_free"])
        self.assertEqual(delta["changed_instance_count"], 2)

    def test_parameter_change_requires_geometry_evidence(self):
        spec = {
            "schema": "analog-layout-align.refinement-spec/v1",
            "operations": [{"op": "set_parameters", "selector": {"names": ["LEFT"]}, "parameters": {"w": "2u"}}],
        }
        with self.assertRaisesRegex(ValueError, "evaluated bboxes"):
            REFINE.refine(parent_intent(), spec)

    def test_explicit_place_allows_parameter_change_and_snaps_to_grid(self):
        spec = {
            "schema": "analog-layout-align.refinement-spec/v1",
            "operations": [
                {"op": "set_parameters", "selector": {"names": ["LEFT"]}, "parameters": {"w": "2u"}},
                {"op": "place", "placements": [{"name": "LEFT", "origin": [0.04, 0.04], "orientation": "MY", "bbox": [[-1.04, 0.04], [0.04, 1.04]]}]},
            ],
        }
        child, _ = REFINE.refine(parent_intent(), spec)
        left = next(item for item in child["instances"] if item["name"] == "LEFT")
        self.assertEqual(left["origin"], [0.0, 0.0])
        self.assertEqual(left["bbox"], [[-1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(left["orientation"], "MY")
        self.assertEqual(left["pcell_parameters"]["w"], "2u")

    def test_parent_is_not_mutated(self):
        parent = parent_intent()
        original = copy.deepcopy(parent)
        spec = {"schema": "analog-layout-align.refinement-spec/v1", "operations": [{"op": "translate", "selector": {"kind": "nmos"}, "dx": 1, "dy": 0}]}
        REFINE.refine(parent, spec)
        self.assertEqual(parent, original)


if __name__ == "__main__":
    unittest.main()
