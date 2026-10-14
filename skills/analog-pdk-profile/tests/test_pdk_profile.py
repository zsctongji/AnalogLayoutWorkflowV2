import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "pdk_profile.py"
SPEC = importlib.util.spec_from_file_location("pdk_profile", SCRIPT)
PROFILE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROFILE)


def raw_profile(include_spacing=True):
    constraints = [
        {"name": "W1", "definition": "minWidth", "layers": ["M1"], "value": 0.5, "parameters": None, "hard": True},
        {"name": "W2", "definition": "minWidth", "layers": ["M2"], "value": 0.6, "parameters": None, "hard": True},
        {"name": "S2", "definition": "minSpacing", "layers": ["M2"], "value": 0.6, "parameters": None, "hard": True},
    ]
    if include_spacing:
        constraints.append({"name": "S1", "definition": "minSpacing", "layers": ["M1"], "value": 0.5, "parameters": None, "hard": True})
    return {
        "technology": {"library": "test_tech", "file": "tech.db", "timestamp": "revision-1"},
        "manufacturing_grid_um": 0.005,
        "layers": [
            {"name": "M1", "number": 1, "material": "metal", "valid": True},
            {"name": "V1", "number": 2, "material": "cut", "valid": True},
            {"name": "M2", "number": 3, "material": "metal", "valid": True},
        ],
        "layer_purposes": [{"layer": "M1", "purpose": "drawing", "valid": True, "selectable": True}],
        "layer_functions": [
            {"layer": "M1", "function": "metal", "rank": 1},
            {"layer": "V1", "function": "cut", "rank": 2},
            {"layer": "M2", "function": "metal", "rank": 3},
        ],
        "constraints": constraints,
        "vias": [
            {
                "name": "M1_M2",
                "layer1": "M1",
                "layer2": "M2",
                "resistance_per_cut": 0.0,
                "raw_parameters": ["V1", 0.5, 0.5, 1, 1, [0.5, 0.5], [0.2, 0.2], [0.25, 0.25]],
            }
        ],
    }


class PdkProfileTests(unittest.TestCase):
    def test_lisp_parser_handles_nested_standard_via_parameters(self):
        value = PROFILE.parse_lisp('(\"V1\" 0.5 0.5 1 1 (0.5 0.5) nil t)')
        self.assertEqual(value, ["V1", 0.5, 0.5, 1, 1, [0.5, 0.5], None, True])

    def test_complete_profile_is_basic_routing_ready(self):
        profile = PROFILE.build_profile(raw_profile(), {"lib": "work", "cell": "block", "view": "layout"}, "foundry")
        self.assertTrue(profile["coverage"]["basic_routing_ready"])
        self.assertTrue(profile["validation"]["structurally_valid"])
        self.assertEqual([item["layer"] for item in profile["routing_layers"]], ["M1", "M2"])

    def test_missing_spacing_blocks_basic_routing(self):
        profile = PROFILE.build_profile(raw_profile(False), {"lib": "work", "cell": "block", "view": "layout"}, "foundry")
        self.assertFalse(profile["coverage"]["basic_routing_ready"])
        self.assertEqual(profile["coverage"]["missing_basic_layer_rules"][0]["layer"], "M1")

    def test_standard_via_is_normalized(self):
        via = PROFILE.normalize_via(raw_profile()["vias"][0])
        self.assertEqual(via["standard_geometry"]["cut_layer"], "V1")
        self.assertEqual(via["standard_geometry"]["layer1_enclosure_um"], [0.2, 0.2])

    def test_fingerprint_detects_tampering(self):
        profile = PROFILE.build_profile(raw_profile(), {"lib": "work", "cell": "block", "view": "layout"}, "foundry")
        changed = copy.deepcopy(profile)
        changed["routing_layers"][0]["minimum_width_rules"][0]["value"] = 9.9
        validation = PROFILE.validate_profile(changed)
        self.assertIn("profile fingerprint mismatch", validation["errors"])

    def test_missing_required_payload_is_rejected_without_crashing(self):
        validation = PROFILE.validate_profile({"schema": "analog-pdk-profile/v1"})
        self.assertFalse(validation["structurally_valid"])
        self.assertTrue(any(error.startswith("missing required field") for error in validation["errors"]))


if __name__ == "__main__":
    unittest.main()
