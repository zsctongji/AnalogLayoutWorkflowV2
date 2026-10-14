import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "calibre_drc.py"
SPEC = importlib.util.spec_from_file_location("calibre_drc", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


SUMMARY = """\
Layout Primary Cell:       OTA
--- RUNTIME WARNINGS
Non-simple boundary at location (1,2).
--- ORIGINAL LAYER STATISTICS
--- RULECHECK RESULTS STATISTICS
RULECHECK cont.1 ........... TOTAL Result Count = 31 (153)
RULECHECK mt1.s.1 .......... TOTAL Result Count = 2  (2)
RULECHECK tm.1 ............. TOTAL Result Count = 1  (1)
--- RULECHECK RESULTS STATISTICS (BY CELL)
CELL generated_nmos ........ TOTAL Result Count = 31 (153)
    RULECHECK cont.1 ....... TOTAL Result Count = 31 (153)
CELL OTA ................... TOTAL Result Count = 3 (3)
    RULECHECK mt1.s.1 ...... TOTAL Result Count = 2 (2)
    RULECHECK tm.1 ......... TOTAL Result Count = 1 (1)
--- SUMMARY
"""

RESULTS = """\
mt1.s.1
2 2 2 Sep 10 00:00:00 2026
Rule File Pathname: /pdk/drc.cal
MT1.S.1 minimum spacing
p 1 4
CN OTA c 1 0 0 1 0 0 0
0 0
100 0
100 50
0 50
p 2 4
CN OTA c 1 0 0 1 0 0 0
200 0
300 0
300 50
200 50
"""


class CalibreDrcTests(unittest.TestCase):
    def test_summary_separates_global_and_hierarchy(self):
        parsed = MODULE.parse_summary(SUMMARY)
        self.assertEqual(parsed["primary_cell"], "OTA")
        self.assertEqual(parsed["global_rules"]["cont.1"]["flattened_count"], 153)
        self.assertEqual(parsed["cells"]["OTA"]["rules"]["mt1.s.1"]["count"], 2)
        self.assertEqual(len(parsed["runtime_warnings"]), 1)

    def test_results_extract_marker_polygons_and_bbox(self):
        parsed = MODULE.parse_results(RESULTS)
        self.assertEqual(len(parsed["markers"]), 2)
        self.assertEqual(parsed["markers"][0]["bbox_db_units"], [0, 0, 100, 50])
        self.assertEqual(parsed["markers"][0]["owner"], "unknown")

    def test_waivers_are_explicit_and_partial(self):
        parsed = MODULE.parse_summary(SUMMARY)
        result = MODULE.evaluate(parsed["global_rules"], [r"^cont\.1$", r"^tm\.1$"])
        self.assertEqual(result["status"], "VIOLATIONS")
        self.assertEqual(set(result["actionable_rules"]), {"mt1.s.1"})

    def test_markdown_handles_nonempty_actionable_and_ignored_rules(self):
        parsed = MODULE.parse_summary(SUMMARY)
        result = {
            "status": "FAIL",
            "primary_cell": parsed["primary_cell"],
            "markers": [],
            "runtime_warnings": parsed["runtime_warnings"],
            **MODULE.evaluate(parsed["global_rules"], [r"^cont\.1$"]),
        }
        report = MODULE.render_report(result)
        self.assertIn("`mt1.s.1`: 2 group(s)", report)
        self.assertIn("`cont.1`: 31 group(s)", report)

    def test_legacy_run_without_binding_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deck = root / "drc.cal"
            layer_map = root / "layer.map"
            deck.write_text("deck", encoding="utf-8")
            layer_map.write_text("map", encoding="utf-8")
            config = {
                "schema": MODULE.SCHEMA,
                "target": {"lib": "mylib", "cell": "OTA", "view": "layout"},
                "working_directory": str(root),
                "inputs": {"rule_deck": str(deck), "layer_map": str(layer_map)},
                "streamout": {
                    "argv": [sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('gds')", "{stream}"]
                },
                "drc": {
                    "argv": [
                        sys.executable, "-c",
                        "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text(sys.argv[3]);pathlib.Path(sys.argv[2]).write_text(sys.argv[4])",
                        "{summary}", "{results}", SUMMARY, RESULTS,
                    ]
                },
                "artifacts": {"stream": "OTA.gds", "summary": "OTA.drc.summary", "results": "OTA.drc.results"},
            }
            config_path = root / "run.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            plan = MODULE.prepare_run(config_path)
            # Legacy execution without OA/stream/deck receipts must fail closed.
            with self.assertRaises(ValueError):MODULE.execute_plan(plan)
            self.assertFalse((root/'OTA.gds').exists())
            (root/'OTA.drc.summary').write_text(SUMMARY,encoding='utf-8')
            (root/'OTA.drc.results').write_text(RESULTS,encoding='utf-8')
            parsed = MODULE.parse_artifacts(root / "OTA.drc.summary", root / "OTA.drc.results", [r"^cont\.1$", r"^tm\.1$", r"^mt1\.s\.1$"])
            self.assertEqual(parsed["status"], "INCOMPLETE")
            self.assertEqual(len(parsed["markers"]), 2)

    def test_unknown_placeholder_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.format_argv(["tool", "{unsafe}"], {})

    def test_density_inventory_is_not_a_rulecheck(self):
        parsed=MODULE.parse_results('OTA 1000\nDENSITY_RDBS\n0 0 2 Sep 28\nmt1_density_rep.db 1\nmt2_density_rep.db 0\n')
        self.assertNotIn('DENSITY_RDBS',parsed['declared_counts'])
        self.assertEqual(len(parsed['density_databases']),2)
        self.assertEqual(parsed['parse_issues'],[])

    def test_truncated_density_inventory_is_incomplete(self):
        parsed=MODULE.parse_results('OTA 1000\nDENSITY_RDBS\n0 0 2 Sep 28\nmt1_density_rep.db 1\n')
        self.assertTrue(parsed['parse_issues'])

    def test_density_inventory_cannot_grant_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'summary').write_text('Layout Primary Cell: OTA\nRULECHECK mt1.1 ... TOTAL Result Count = 0 (0)\n')
            (root/'results').write_text('OTA 1000\nDENSITY_RDBS\n0 0 1 Sep 28\nmt1_density_rep.db 1\n')
            (root/'mt1_density_rep.db').write_text('unqualified density dialect')
            result=MODULE.parse_artifacts(root/'summary',root/'results',[])
            self.assertEqual(result['status'],'INCOMPLETE')
            self.assertTrue(result['density_databases'][0]['sha256'])


if __name__ == "__main__":
    unittest.main()
