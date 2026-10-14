import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from placement_geometry import digest, project_islands
from placement_metrics import evaluate_placement, evaluate_channels
from placement_candidates import generate_candidates, movement_units
from placement_optimizer import optimize, pareto
from refine_placement_intent import refine


def fixture():
    items = []
    access = []
    for name, x in (("LEFT", 0.), ("RIGHT", 3.)):
        item = {"name": name, "logical_device": name, "kind": "nmos", "placement_role": "standalone",
                "group": None, "origin": [x, 0.], "orientation": "R0", "bbox": [[x, 0.], [x+2, 4.]],
                "pcell_master": {"lib": "synthetic", "cell": "nmos", "view": "layout"},
                "pcell_parameters": {"m": "1", "w": "1u", "l": "1u", "nf": 1}, "terminals": {"G": "SIGNAL"}}
        items.append(item)
        access.append({"name": name, "master": item["pcell_master"], "origin": item["origin"],
                       "orientation": "R0", "bbox": item["bbox"], "terminals": {"G": {"net": "SIGNAL", "pin_islands": [
                           {"id": name+":G:p0", "candidate_centers": [[x+1, 1], [x+1, 3]], "access_layers": ["m1"]}]}}})
    parent = {"schema": "analog-layout-align.pcell-placement-intent/v2", "coordinate_contract": {"manufacturing_grid": .1, "units": "micron", "space": "live Virtuoso evaluated PCell bbox"},
              "instances": items, "groups": [], "macro_instances": [], "dummy_associations": [],
              "floorplan": {"bbox": [[0, 0], [5, 4]]}, "validation": {"expected_instances": 2}}
    live = {"schema": "analog-layout-align.terminal-access/v1", "target": {"lib": "test", "cell": "block", "view": "layout"}, "instances": access}
    evidence = {"layers": {"m1": {"source": "synthetic test rule", "width_um": .4, "spacing_um": .2,
                                  "escape_length_um": 1., "via_envelope_um": [.6, .6], "preferred_direction": "vertical"}}}
    request = make_request(parent, live)
    return parent, live, request, evidence


def make_request(parent, access):
    return {"schema": "analog-layout-align.placement-optimization-request/v1", "target": access["target"],
            "parent_intent_sha256": digest(parent), "terminal_access_sha256": digest(access),
            "search": {"step_um": 1., "max_iterations": 2, "max_evaluations": 30, "top_k": 5},
            "constraints": {"channel_demands": [{"channel_id": "LEFT|RIGHT|0", "layer": "m1", "ordinary_nets": 3}]}}


class OptimizerTests(unittest.TestCase):
    def test_baseline_evaluates(self):
        p, a, r, e = fixture()
        value = evaluate_placement(p, a, r["constraints"], e)
        self.assertEqual(value["status"], "EVALUATED", value)
        self.assertEqual(value["metrics"]["channel_overflows"], 1)

    def test_channel_expansion_increases_capacity(self):
        p, a, r, e = fixture()
        before = evaluate_channels(p, r["constraints"], e["layers"])[0]
        child, _ = refine(p, {"schema": "analog-layout-align.refinement-spec/v1", "operations": [{"op": "translate", "selector": {"names": ["RIGHT"]}, "dx": 2, "dy": 0}]})
        after = evaluate_channels(child, r["constraints"], e["layers"])[0]
        self.assertTrue(before["overflow"])
        self.assertFalse(after["overflow"])
        self.assertGreater(after["capacity_by_layer"]["m1"]["ordinary_tracks"], before["capacity_by_layer"]["m1"]["ordinary_tracks"])

    def test_missing_rules_are_unknown(self):
        p, a, r, _ = fixture()
        v = evaluate_placement(p, a, r["constraints"], {})
        self.assertEqual(v["accesses"][0]["access_risk"], "unknown")
        self.assertIsNone(v["channels"][0]["overflow"])

    def test_nonfirst_access_is_selected(self):
        p, a, r, e = fixture()
        r["constraints"]["obstacles"] = [{"id": "block", "layer": "m1", "bbox": [[.8, .8], [1.2, 1.2]]}]
        v = evaluate_placement(p, a, r["constraints"], e)
        self.assertEqual(v["accesses"][0]["preferred_candidate"]["xy"], [1., 3.])

    def test_paired_access_selection(self):
        p, a, r, e = fixture()
        r["constraints"]["access_pairs"] = [{"first": "LEFT:G:p0", "second": "RIGHT:G:p0", "axis_x_um": 2.5}]
        v = evaluate_placement(p, a, r["constraints"], e)
        self.assertEqual(v["metrics"]["paired_access_error_um"], 0)
        x, y = [rec["preferred_candidate"]["xy"] for rec in v["accesses"]]
        self.assertEqual(x[1], y[1])

    def test_projection_preserves_all_islands(self):
        p, a, r, e = fixture()
        a["instances"][0]["terminals"]["G"]["pin_islands"].append({"id": "LEFT:G:p1", "candidate_centers": [[1., 2.]], "access_layers": ["m1"]})
        records = project_islands(p, p, a)
        self.assertEqual(len(records), 3)
        self.assertEqual(len({x["id"] for x in records}), 3)

    def test_missing_pin_island_blocks(self):
        p, a, r, e = fixture()
        a["instances"][0]["terminals"]["G"]["pin_islands"][0]["candidate_centers"] = []
        self.assertEqual(evaluate_placement(p, a, r["constraints"], e)["status"], "BLOCKED")

    def test_deterministic_complete_search_and_parent_immutable(self):
        p, a, r, e = fixture(); original = copy.deepcopy(p)
        first = optimize(p, a, r, e)
        self.assertEqual(first["status"], "READY_FOR_REVIEW", first)
        self.assertEqual(first, optimize(p, a, r, e))
        self.assertEqual(p, original)
        self.assertLessEqual(first["evaluations"], 30)
        self.assertTrue(any(c["candidate_id"] != "parent" for c in first["candidates"]))
        self.assertTrue(all(c["evaluation"]["status"] == "EVALUATED" for c in first["candidates"]))

    def test_pareto_retains_area_routeability_tradeoff(self):
        p, a, r, e = fixture()
        result = optimize(p, a, r, e)
        costs = [c["evaluation"]["metrics"] for c in result["candidates"]]
        self.assertGreater(len(costs), 1)
        self.assertTrue(any(v["channel_overflows"] == 0 for v in costs))
        self.assertTrue(any(v["area_um2"] <= 20 for v in costs))

    def test_dominated_and_invalid_candidates_removed(self):
        p, a, r, e = fixture()
        def c(name, area, route, status="EVALUATED"):
            intent = copy.deepcopy(p); intent["instances"][0]["origin"][0] = area
            return {"candidate_id": name, "intent": intent, "evaluation": {"status": status, "metrics": {"area_um2": area, "blocked_accesses": route}}}
        values = [c("a", 10, 1), c("b", 11, 2), c("bad", 1, 0, "BLOCKED")]
        self.assertEqual([x["candidate_id"] for x in pareto(values, ["area_um2", "blocked_accesses"], 5)], ["a"])

    def test_bad_geometry_orientation_parameters_identity_rejected(self):
        p, a, r, e = fixture()
        for mutate in [lambda c: c["instances"][0].update(orientation="R90"),
                       lambda c: c["instances"][0]["pcell_parameters"].update(w="2u"),
                       lambda c: c["instances"].pop(),
                       lambda c: c["instances"][0]["origin"].__setitem__(0, .03),
                       lambda c: c["instances"][0]["bbox"][1].__setitem__(0, 4)]:
            child = copy.deepcopy(p); mutate(child)
            self.assertEqual(evaluate_placement(child, a, r["constraints"], e, p)["status"], "BLOCKED")

    def test_group_translation_preserves_matching_and_single_move_rejected(self):
        p, a, r, e = fixture()
        for i in p["instances"]: i.update(group="MATCH", placement_role="active")
        p["groups"] = [{"name": "MATCH", "logical_devices": ["LEFT", "RIGHT"], "rows": [["LEFT", "RIGHT"]], "pattern_mode": "symmetric_interdigitated_fallback"}]
        self.assertEqual(movement_units(p), [["LEFT", "RIGHT"]])
        def move(names): return refine(p, {"schema": "analog-layout-align.refinement-spec/v1", "operations": [{"op": "translate", "selector": {"names": names}, "dx": 1, "dy": 0}]})[0]
        v = evaluate_placement(move(["LEFT", "RIGHT"]), a, {}, e, p)
        self.assertEqual(v["status"], "EVALUATED", v)
        self.assertFalse(v["matching"][0]["exact_common_centroid"])
        self.assertEqual(evaluate_placement(move(["LEFT"]), a, {}, e, p)["status"], "BLOCKED")

    def test_false_common_centroid_declaration_rejected(self):
        p, a, r, e = fixture()
        for i in p["instances"]: i.update(group="MATCH", placement_role="active")
        p["groups"] = [{"name": "MATCH", "logical_devices": ["LEFT", "RIGHT"], "rows": [["LEFT", "RIGHT"]], "pattern_mode": "exact_common_centroid"}]
        self.assertEqual(evaluate_placement(p, a, {}, e)["status"], "BLOCKED")

    def test_feedback_hash_and_target_gates(self):
        p, a, r, e = fixture()
        f = {"schema": "analog-layout-align.routeability-feedback/v1", "target": r["target"],
             "parent_intent_sha256": digest(p), "terminal_access_sha256": digest(a),
             "failures": [{"code": "NO_LEGAL_ACCESS", "affected_instances": ["RIGHT"]}]}
        result = optimize(p, a, r, e, f)
        self.assertFalse(result["materialized"])
        self.assertTrue(any("feedback" in h["reason"] for h in result["history"]))
        f["parent_intent_sha256"] = "stale"
        self.assertEqual(optimize(p, a, r, e, f)["status"], "BLOCKED")

    def test_blocked_escape_drives_proposal(self):
        p, a, r, e = fixture()
        r["constraints"]["obstacles"] = [{"id": "blocking", "layer": "m1", "bbox": [[.5, .5], [1.5, 3.5]]}]
        v = evaluate_placement(p, a, r["constraints"], e)
        self.assertEqual(v["accesses"][0]["access_risk"], "blocked")
        proposals = generate_candidates(p, v, r, [])
        self.assertTrue(any("LEFT" in x["affected_instances"] and "escape" in x["reason"] for x in proposals))

    def test_equivalent_copy_swap_preserves_electrical_identity(self):
        p, a, r, e = fixture()
        for i in p["instances"]: i["logical_device"] = "PARALLEL"
        v = evaluate_placement(p, a, {}, e)
        proposal = next(x for x in generate_candidates(p, v, r, []) if "exchange" in x["reason"])
        child, _ = refine(p, proposal["spec"])
        self.assertEqual(child["instances"][0]["origin"], p["instances"][1]["origin"])
        self.assertEqual(evaluate_placement(child, a, {}, e, p)["status"], "EVALUATED")
        self.assertEqual([i["terminals"] for i in child["instances"]], [i["terminals"] for i in p["instances"]])

    def test_stale_access_rejected(self):
        p, a, r, e = fixture(); a = copy.deepcopy(a)
        a["instances"][0]["origin"] = [10, 0]
        self.assertEqual(evaluate_placement(p, a, {}, e)["status"], "BLOCKED")

    def test_unknown_evidence_cannot_dominate_known_candidate(self):
        from placement_optimizer import dominates
        a = {"evaluation": {"metrics": {"area_um2": 1, "unknown_declared_channels": 1, "unknown_accesses": 0}}}
        b = {"evaluation": {"metrics": {"area_um2": 2, "unknown_declared_channels": 0, "unknown_accesses": 0}}}
        self.assertFalse(dominates(a, b, ["area_um2"]))

    def test_invalid_numbers_settings_and_constraints_are_structured(self):
        p, a, r, e = fixture()
        r["search"]["step_um"] = float("nan")
        self.assertEqual(optimize(p, a, r, e)["status"], "BLOCKED")
        r["search"]["step_um"] = 0
        r["search"]["max_evaluations"] = 1
        self.assertEqual(optimize(p, a, r, e)["status"], "BLOCKED")
        r["search"]["step_um"] = 1
        r["constraints"]["unknown_constraint"] = True
        self.assertEqual(optimize(p, a, r, e)["status"], "BLOCKED")

    def test_locked_units_stop_without_improvement(self):
        p, a, r, e = fixture()
        r["search"]["locked_instances"] = ["LEFT", "RIGHT"]
        result = optimize(p, a, r, e)
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertEqual(result["stop_reason"], "no_improvement")
        self.assertEqual(result["candidates"][0]["candidate_id"], "parent")

    def test_lost_channel_is_unknown_not_resolved(self):
        p, a, r, e = fixture()
        child, _ = refine(p, {"schema": "analog-layout-align.refinement-spec/v1", "operations": [{"op": "translate", "selector": {"names": ["RIGHT"]}, "dx": 0, "dy": 5}]})
        report = evaluate_channels(child, r["constraints"], e["layers"])
        declared = next(c for c in report if c["channel_id"] == "LEFT|RIGHT|0")
        self.assertIsNone(declared["overflow"])
        value = evaluate_placement(child, a, r["constraints"], e, p)
        self.assertEqual(value["status"], "BLOCKED")
        self.assertIn("DECLARED_CHANNEL_LOST", [f["code"] for f in value["hard_failures"]])

    def test_real_abba_group_stays_exact_after_translation(self):
        p, a, r, e = fixture()
        base, live = copy.deepcopy(p["instances"][0]), copy.deepcopy(a["instances"][0])
        p["instances"] = []; a["instances"] = []
        for idx, logical in enumerate(("A", "B", "B", "A")):
            item = copy.deepcopy(base); name = f"COPY{idx}"
            item.update(name=name, logical_device=logical, group="ABBA", placement_role="active", origin=[idx*3., 0.], bbox=[[idx*3., 0.], [idx*3.+2, 4.]])
            p["instances"].append(item)
            ai = copy.deepcopy(live); ai.update(name=name, origin=item["origin"], bbox=item["bbox"])
            ai["terminals"]["G"]["pin_islands"] = [{"id": name+":G:p0", "candidate_centers": [[idx*3.+1, 1]], "access_layers": ["m1"]}]
            a["instances"].append(ai)
        p["validation"]["expected_instances"] = 4
        p["groups"] = [{"name": "ABBA", "logical_devices": ["A", "B"], "rows": [[i["name"] for i in p["instances"]]], "pattern_mode": "explicit_m_copy_abba_common_centroid"}]
        child, _ = refine(p, {"schema": "analog-layout-align.refinement-spec/v1", "operations": [{"op": "translate", "selector": {"group": "ABBA"}, "dx": 1, "dy": 2}]})
        v = evaluate_placement(child, a, {}, e, p)
        self.assertEqual(v["status"], "EVALUATED", v)
        self.assertTrue(v["matching"][0]["exact_common_centroid"])

    def test_noise_thermal_and_boundary_metrics_are_optional_proxies(self):
        p, a, r, e = fixture()
        constraints = {"sensitive_instances": ["LEFT", "RIGHT"], "noise_sources": [{"instance": "RIGHT", "weight": 1}],
                       "heat_sources": [{"instance": "RIGHT", "weight": 2}], "boundary_connections": [{"instance": "LEFT", "target_xy_um": [0, 0]}]}
        v = evaluate_placement(p, a, constraints, e)
        self.assertGreater(v["metrics"]["noise_proximity_proxy"], 0)
        self.assertGreater(v["metrics"]["thermal_imbalance_proxy"], 0)
        self.assertEqual(v["metrics"]["high_current_escape_um"], 3)

    def test_legacy_projection_cli_keeps_physical_islands(self):
        p, a, r, e = fixture()
        a["nets"] = [{"name": "SIGNAL", "estimated_hpwl": 3}]
        a["instances"][0]["terminals"]["G"]["pin_islands"].append({"id": "LEFT:G:p1", "candidate_centers": [[1, 2]], "access_layers": ["m1"]})
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, value in (("p", p), ("a", a)):
                (root/(name+".json")).write_text(json.dumps(value), encoding="utf-8")
            run = subprocess.run([sys.executable, str(SCRIPTS/"project_intent_metrics.py"), str(root/"a.json"), str(root/"p.json"), str(root/"p.json"), str(root/"out.json")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            data = json.loads((root/"out.json").read_text())
            self.assertEqual(len(data["projected_pin_islands"]), 3)
            self.assertEqual(data["net_metrics"][0]["physical_access_count"], 3)
            self.assertEqual(data["net_metrics"][0]["terminal_count"], 2)

    def test_cli_exports_reviewable_files_without_bridge(self):
        p, a, r, e = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("p", p), ("a", a), ("r", r), ("e", e)):
                (root/(name+".json")).write_text(json.dumps(value), encoding="utf-8")
            cmd = [sys.executable, str(SCRIPTS/"placement_optimizer.py"), "--intent", str(root/"p.json"), "--access", str(root/"a.json"),
                   "--request", str(root/"r.json"), "--evidence", str(root/"e.json"), "--out", str(root/"out")]
            run = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads((root/"out"/"placement-candidates.json").read_text())
            self.assertTrue(list((root/"out").glob("*.svg")))
            self.assertEqual(len(result["candidates"]), len(list((root/"out").glob("*.svg"))))
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


if __name__ == "__main__": unittest.main()
