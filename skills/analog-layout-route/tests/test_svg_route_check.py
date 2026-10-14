import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


route = module("route_for_svg_test", ROOT / "scripts" / "route_intent.py")
check = module("svg_route_check", ROOT / "scripts" / "svg_route_check.py")
apply = module("apply_for_svg_test", ROOT / "scripts" / "apply_routing_intent.py")


def fixture(endpoint=1.0):
    return {
        "schema": route.INTENT_SCHEMA,
        "target": {"lib": "l", "cell": "c", "view": "layout"},
        "manufacturing_grid_um": 0.01,
        "routes": [{"id": "r", "net": "TAIL", "layer": "m1", "purpose": "drawing",
                    "width_um": 0.2, "points_um": [[-1.0, 0.0], [endpoint, 0.0]]}],
        "vias": [], "contact_landings": [], "matching": [],
        "symmetry_groups": [{"id": "tail_mirror", "mode": "self", "net": "TAIL",
                             "transform": "mirror_x", "axis_um": 0.0, "tolerance_um": 0.01}],
    }


class SvgCheckTests(unittest.TestCase):
    def run_check(self, intent):
        with tempfile.TemporaryDirectory() as tmp:
            svg_path = Path(tmp) / "preview.svg"
            intent_path = Path(tmp) / "intent.json"
            intent_path.write_text("{}", encoding="utf-8")
            svg_path.write_text(route.svg(intent), encoding="utf-8")
            return check.build_check_from_values(intent, svg_path) if hasattr(check, "build_check_from_values") else self._direct(intent, svg_path)

    @staticmethod
    def _direct(intent, svg_path):
        errors = []
        attrs, objects = check.parse_svg(svg_path, errors)
        tol = max(float(intent["manufacturing_grid_um"]), 0.001)
        check.compare_structure(intent, attrs, objects, tol, errors)
        warnings = []
        symmetry = check.check_symmetry(intent, objects, tol, errors, warnings)
        matching = check.check_matching(intent, errors)
        return {"status": "PASS" if not errors else "BLOCKED", "target": intent["target"],
                "intent_sha256": check.digest(intent), "svg_sha256": check.file_digest(svg_path),
                "errors": errors, "warnings": warnings, "symmetry": symmetry, "matching": matching}

    def test_annotated_svg_passes_structure_and_self_mirror(self):
        result = self.run_check(fixture())
        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertTrue(result["symmetry"][0]["pass"])

    def test_asymmetric_svg_geometry_is_blocked(self):
        result = self.run_check(fixture(0.5))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("symmetry group" in item for item in result["errors"]))

    def test_pair_mirror_geometry_passes(self):
        intent = fixture()
        intent["routes"] = [
            {"id": "p", "net": "P", "layer": "m1", "purpose": "drawing", "width_um": 0.2,
             "points_um": [[-1.0, 0.0], [-1.0, 1.0]]},
            {"id": "n", "net": "N", "layer": "m1", "purpose": "drawing", "width_um": 0.2,
             "points_um": [[1.0, 0.0], [1.0, 1.0]]},
        ]
        intent["symmetry_groups"] = [{"id": "pn", "mode": "pair", "first_net": "P",
            "second_net": "N", "transform": "mirror_x", "axis_um": 0.0, "tolerance_um": 0.01}]
        result = self.run_check(intent)
        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertTrue(result["symmetry"][0]["pass"])

    def test_tampered_rendered_geometry_is_blocked(self):
        intent = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            svg_path = Path(tmp) / "preview.svg"
            svg_path.write_text(route.svg(intent), encoding="utf-8")
            tree = ET.parse(svg_path)
            polyline = next(item for item in tree.getroot().iter() if item.attrib.get("data-kind") == "route")
            polyline.set("points", "20.00,80.00 35.00,80.00")
            tree.write(svg_path, encoding="unicode")
            result = self._direct(intent, svg_path)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("route geometry differs" in item for item in result["errors"]))

    def test_materializer_rejects_stale_svg_check(self):
        intent = fixture()
        artifact = {"schema": check.SCHEMA, "status": "PASS", "target": intent["target"],
                    "intent_sha256": check.digest(intent), "svg_sha256": "abc", "errors": []}
        apply.validate_svg_check(intent, artifact)
        artifact["intent_sha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "hash drift"):
            apply.validate_svg_check(intent, artifact)


if __name__ == "__main__":
    unittest.main()
