import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "apply_placement_intent.py"
SPEC = importlib.util.spec_from_file_location("apply_placement_intent", SCRIPT)
APPLY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(APPLY)


def instance(name="M0", kind="nmos"):
    params = {
        "w": "20u",
        "fw": "5u",
        "l": "1.5u",
        "fingers": "4",
        "m": "1",
        "connectGates": "None",
        "connectSD": "None",
        "tap": "None",
    }
    if kind == "capacitor":
        params = {"w": "30u", "l": "30u", "m": "1"}
    return {
        "name": name,
        "kind": kind,
        "origin": [1.0, 2.0],
        "orientation": "R0",
        "bbox": [[0.0, 0.0], [3.0, 4.0]],
        "terminals": {"D": "VOUT", "G": "VIN", "S": "VSS", "B": "VSS"} if kind != "capacitor" else {"N1": "A", "N2": "B"},
        "pcell_master": {"lib": "pdk", "cell": "cap" if kind == "capacitor" else "nmos", "view": "layout"},
        "pcell_parameters": params,
    }


def intent(instances):
    return {
        "schema": "analog-layout-align.pcell-placement-intent/v2",
        "instances": instances,
        "validation": {
            "expected_instances": len(instances),
            "placed_instances": len(instances),
            "all_mos_copies_have_m_1": True,
            "all_origins_on_manufacturing_grid": True,
            "bbox_overlap_free": True,
            "dummy_families_associated": True,
        },
    }


class ApplyPlacementIntentTests(unittest.TestCase):
    def test_drain_annotations_are_enabled_by_default_and_can_be_disabled(self):
        base = [
            "intent.json",
            "--env",
            "bridge.env",
            "--lib",
            "target_lib",
            "--cell",
            "target_cell",
            "--report",
            "report.json",
        ]
        self.assertTrue(APPLY.parser().parse_args(base).annotate_drains)
        self.assertFalse(APPLY.parser().parse_args(base + ["--no-annotate-drains"]).annotate_drains)

    def test_validation_accepts_arbitrary_complete_instance_count(self):
        records = [instance("M0"), instance("M1")]
        self.assertEqual(APPLY.validate_intent(intent(records)), records)

    def test_validation_rejects_incomplete_intent(self):
        value = intent([instance()])
        value["validation"]["placed_instances"] = 0
        with self.assertRaisesRegex(ValueError, "incomplete"):
            APPLY.validate_intent(value)

    def test_mos_parameters_preserve_types_and_do_not_pass_multiplier(self):
        rendered = APPLY.pcell_params(instance())
        self.assertIn('list("w" "string" "20u")', rendered)
        self.assertIn('list("l" "float" 1.5e-06)', rendered)
        self.assertIn('list("fingers" "float" 4)', rendered)
        self.assertNotIn('list("m"', rendered)

    def test_shared_diffusion_parameters_use_explicit_types(self):
        item = instance()
        item["pcell_parameters"]["rightAbut"] = "source"
        item["pcell_parameter_types"] = {"rightAbut": "string"}
        rendered = APPLY.pcell_params(item)
        self.assertIn('list("rightAbut" "string" "source")', rendered)

    def test_legacy_untyped_optional_parameters_remain_ignored(self):
        item = instance()
        item["pcell_parameters"]["leftTap"] = "legacy-value"
        rendered = APPLY.pcell_params(item)
        self.assertNotIn("leftTap", rendered)

    def test_shared_diffusion_requires_passing_validation(self):
        value = intent([instance()])
        value["shared_diffusion_groups"] = [{"id": "pair"}]
        with self.assertRaisesRegex(ValueError, "Shared-diffusion"):
            APPLY.validate_intent(value)

    def test_cnl5_width_and_length_are_numeric(self):
        rendered = APPLY.pcell_params(instance("C1", "capacitor"))
        self.assertIn('list("w" "float" 3e-05)', rendered)
        self.assertIn('list("l" "float" 3e-05)', rendered)

    def test_apply_skill_refuses_overwrite_and_purges_failed_transaction(self):
        rendered = APPLY.build_apply_skill([instance()], "lib", "new_cell", "layout")
        self.assertIn("ERROR|target-exists", rendered)
        self.assertIn("dbPurge(cv)", rendered)
        self.assertIn("dbSave(cv)", rendered)

    def test_quoted_bridge_output_is_normalized(self):
        self.assertEqual(APPLY.output_text('"OK|instances=2"'), "OK|instances=2")

    def test_drain_annotations_include_only_mos_devices(self):
        records = APPLY.drain_annotation_records(
            [instance("NM0"), instance("PM0", "pmos"), instance("C1", "capacitor")]
        )
        self.assertEqual([item["text"] for item in records], ["D/VOUT", "D/VOUT"])
        self.assertEqual([item["instance"] for item in records], ["NM0", "PM0"])

    def test_annotation_skill_uses_transformed_drain_pin_and_non_electrical_label(self):
        records = APPLY.drain_annotation_records([instance("NM0")])
        rendered = APPLY.build_annotate_skill(
            records, "lib", "cell", "layout", "annotate", "drawing", 0.5
        )
        self.assertIn('masterTerm~>name=="D"', rendered)
        self.assertNotIn("setof(t ", rendered)
        self.assertIn('car(candidate~>lpp)=="mt1"', rendered)
        self.assertIn("dbTransformBBox(fig~>bBox i~>transform)", rendered)
        self.assertIn('dbCreateLabel(cv list("annotate" "drawing")', rendered)
        self.assertIn('dbCreateProp(label "alaKind" "string"', rendered)
        self.assertNotIn("dbMakeNet", rendered)
        self.assertNotIn("dbCreateTerm", rendered)
        self.assertNotIn("dbCreatePin", rendered)


if __name__ == "__main__":
    unittest.main()
