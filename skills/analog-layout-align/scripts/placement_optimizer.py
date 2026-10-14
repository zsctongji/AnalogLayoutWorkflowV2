"""Bounded offline placement search, pure evaluation, Pareto retention and export."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from placement_geometry import digest
from placement_metrics import evaluate_placement
from placement_candidates import feedback_hints, generate_candidates
from refine_placement_intent import refine


REQUEST_SCHEMA = "analog-layout-align.placement-optimization-request/v1"
OBJECTIVES = {
    "matching": ["paired_access_error_um", "differential_hpwl_delta_um", "blocked_accesses", "area_um2", "hpwl_um"],
    "routeability": ["blocked_accesses", "channel_overflows", "channel_overflow_um", "unknown_declared_channels", "unknown_accesses", "critical_crossing_proxy", "hpwl_um", "area_um2"],
    "critical_hpwl": ["critical_hpwl_um", "hpwl_um", "blocked_accesses", "area_um2"],
    "compactness": ["area_um2", "blocked_accesses", "channel_overflows", "hpwl_um"],
    "balanced": ["blocked_accesses", "channel_overflows", "channel_overflow_um", "unknown_declared_channels", "unknown_accesses", "paired_access_error_um", "differential_hpwl_delta_um", "critical_hpwl_um", "hpwl_um", "area_um2"],
}


def state_hash(intent):
    # Geometry identity, independent of refinement metadata or timestamps.
    return digest({"instances": sorted(intent["instances"], key=lambda i: i["name"]), "groups": intent.get("groups", [])})


def dominates(a, b, objectives):
    av, bv = a["evaluation"]["metrics"], b["evaluation"]["metrics"]
    keys = [k for k in objectives if av.get(k) is not None and bv.get(k) is not None]
    # Unknown must not dominate a candidate with measured evidence.
    if any(av.get(k) is None and bv.get(k) is not None for k in objectives): return False
    if any(av.get(k, 0) > bv.get(k, 0) for k in ("unknown_declared_channels", "unknown_accesses")):
        return False
    return bool(keys) and all(av[k] <= bv[k]+1e-10 for k in keys) and any(av[k] < bv[k]-1e-10 for k in keys)


def pareto(candidates, objectives, top_k):
    valid = [c for c in candidates if c["evaluation"]["status"] == "EVALUATED"]
    unique = {}
    for c in sorted(valid, key=lambda c: c["candidate_id"]): unique.setdefault(state_hash(c["intent"]), c)
    valid = list(unique.values())
    frontier = [c for c in valid if not any(dominates(d, c, objectives) for d in valid if d is not c)]
    # Keep one representative of metric-equivalent layouts, preferring the baseline.
    representatives = {}
    for c in sorted(frontier, key=lambda c: (c["candidate_id"] != "parent", c["candidate_id"])):
        representatives.setdefault(digest(c["evaluation"]["metrics"]), c)
    frontier = list(representatives.values())
    frontier.sort(key=lambda c: (c["evaluation"]["metrics"].get("unknown_declared_channels", 0),
                                 c["evaluation"]["metrics"].get("unknown_accesses", 0))+
                  tuple((c["evaluation"]["metrics"].get(k) is None, c["evaluation"]["metrics"].get(k) or 0) for k in objectives)+(c["candidate_id"],))
    return frontier[:top_k]


def optimize(parent, access, request, evidence=None, feedback=None):
    evidence = evidence or {}; feedback = feedback or {}
    result = {"schema": "analog-layout-align.placement-candidates/v1", "status": "BLOCKED", "candidates": [],
              "history": [], "failures": [], "materialized": False,
              "sources": {},
              "limitations": ["Offline candidate estimates; not live terminal-access or foundry verification.",
                              "Rigid group translation and equivalent standalone swaps; no automatic resizing, diffusion sharing or array redesign."]}
    try:
        result["sources"] = {"parent_intent_sha256": digest(parent), "terminal_access_sha256": digest(access),
                             "request_sha256": digest(request), "evidence_sha256": digest(evidence), "feedback_sha256": digest(feedback)}
        if request.get("schema") != REQUEST_SCHEMA: raise ValueError("unsupported optimization request schema")
        if request.get("parent_intent_sha256") != digest(parent) or request.get("terminal_access_sha256") != digest(access):
            raise ValueError("request input hashes are stale")
        if request.get("target") != access.get("target") or not request.get("target"):
            raise ValueError("request/source access target mismatch")
        result["target"] = request["target"]
        hints = feedback_hints(feedback, parent, access, request)
        constraints = request.get("constraints", {})
        # Automatic optimizer preserves electrical parameters, including geometry-changing ones.
        if constraints.get("orientation_evidence"):
            raise ValueError("orientation search is not enabled in this P0 optimizer")
        settings = request.get("search", {})
        if set(settings)-{"max_iterations", "max_evaluations", "top_k", "step_um", "priority", "locked_instances", "macro_relocation_gap_um"}:
            raise ValueError("unsupported search settings")
        iterations, budget, top_k = (settings.get(k, v) for k, v in (("max_iterations", 5), ("max_evaluations", 100), ("top_k", 5)))
        if any(not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in (iterations, budget, top_k)):
            raise ValueError("search budgets must be positive integers")
        mode = settings.get("priority", "balanced")
        if mode not in OBJECTIVES: raise ValueError("unknown priority mode")
        objectives = list(request.get("objectives", OBJECTIVES[mode]))
        if not objectives or len(set(objectives)) != len(objectives): raise ValueError("objectives must be unique and nonempty")
        baseline = evaluate_placement(parent, access, constraints, evidence, parent)
        if "objectives" not in request:
            for key in ("noise_proximity_proxy", "thermal_imbalance_proxy", "high_current_escape_um", "via_envelope_blocked"):
                if baseline["metrics"].get(key) is not None: objectives.append(key)
        if any(k not in baseline["metrics"] for k in objectives) and baseline["status"] == "EVALUATED":
            raise ValueError("unknown objective")
        if any(k in {"utilization", "device_area_um2"} for k in objectives):
            raise ValueError("objectives must be minimization costs, not utilization/device area")
        result["baseline"] = baseline; result["objectives"] = objectives
        if baseline["status"] == "BLOCKED":
            result["failures"] = baseline["hard_failures"]; return result
        # Validate settings even when max_evaluations=1 prevents any expansion.
        generate_candidates(parent, baseline, request, hints)
        seed = {"candidate_id": "parent", "parent_id": None, "generation": 0, "intent": copy.deepcopy(parent), "evaluation": baseline,
                "operations": [], "reason": "baseline", "metric_delta": {}}
        frontier = [seed]; archive = [seed]; seen = {state_hash(parent)}; evaluations = 1
        result["stop_reason"] = "iteration_budget"
        for generation in range(1, iterations+1):
            children = []
            previous_ids = [c["candidate_id"] for c in frontier]
            for candidate in frontier:
                proposals = generate_candidates(candidate["intent"], candidate["evaluation"], request, hints)
                for proposal in proposals:
                    if evaluations >= budget: break
                    evaluations += 1
                    try:
                        child, delta = refine(candidate["intent"], proposal["spec"], candidate["candidate_id"])
                        delta.pop("generated_at", None)
                        key = state_hash(child)
                        if key in seen: continue
                        seen.add(key)
                        evaluation = evaluate_placement(child, access, constraints, evidence, parent)
                        identifier = "candidate_"+key[:16]
                        entry = {"candidate_id": identifier, "parent_id": candidate["candidate_id"], "generation": generation,
                                 "intent": child, "evaluation": evaluation, "refinement_spec": proposal["spec"], "delta": delta,
                                 "operations": proposal["spec"]["operations"], "reason": proposal["reason"],
                                 "metric_delta": {k: v-candidate["evaluation"]["metrics"][k] for k, v in evaluation["metrics"].items()
                                                  if v is not None and candidate["evaluation"]["metrics"].get(k) is not None}}
                        archive.append(entry)
                        result["history"].append({k: entry[k] for k in ("candidate_id", "parent_id", "generation", "operations", "reason", "metric_delta")})
                        if evaluation["status"] == "EVALUATED": children.append(entry)
                        else: result["failures"].append({"candidate_id": identifier, "reasons": evaluation["hard_failures"]})
                    except (ValueError, KeyError, TypeError) as exc:
                        result["failures"].append({"parent_id": candidate["candidate_id"], "operations": proposal["spec"]["operations"], "code": "REFINEMENT_REJECTED", "detail": str(exc)})
                if evaluations >= budget: break
            frontier = pareto(frontier+children, objectives, top_k)
            if evaluations >= budget: result["stop_reason"] = "evaluation_budget"; break
            # Equal-metric shuffles do not count as improvement.
            old_vectors = {tuple(c["evaluation"]["metrics"].get(k) for k in objectives) for c in archive if c["candidate_id"] in previous_ids}
            if not any(tuple(c["evaluation"]["metrics"].get(k) for k in objectives) not in old_vectors for c in frontier):
                result["stop_reason"] = "no_improvement"; break
        result["candidates"] = pareto([c for c in archive if c["evaluation"]["status"] == "EVALUATED"], objectives, top_k)
        result["status"] = "READY_FOR_REVIEW"
        result["evaluations"] = evaluations
        # Full ancestry is retained for every finalist, including pruned intermediate parents.
        selected = {c["candidate_id"] for c in result["candidates"]}
        by_id = {c["candidate_id"]: c for c in archive}
        for name in list(selected):
            while by_id[name]["parent_id"]:
                name = by_id[name]["parent_id"]; selected.add(name)
        result["ancestry"] = [c for c in archive if c["candidate_id"] in selected]
        return result
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        result["failures"].append({"code": "INVALID_OPTIMIZATION_INPUT", "detail": str(exc)})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--access", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--feedback", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args()
    def read(path): return json.loads(path.read_text(encoding="utf-8-sig")) if path else {}
    result = optimize(read(args.intent), read(args.access), read(args.request), read(args.evidence), read(args.feedback))
    if args.out.exists(): parser.error("output directory must be new")
    args.out.mkdir(parents=True)
    def write(name, data):
        (args.out/name).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    write("placement-candidates.json", result)
    from placement_flow import render_svg
    for c in result["candidates"]:
        write(c["candidate_id"]+".json", c["intent"])
        preview = copy.deepcopy(c["intent"])
        for i in preview["instances"]: i["align_bbox"] = i["bbox"]
        render_svg(preview, args.out/(c["candidate_id"]+".svg"), c["candidate_id"])
    print(json.dumps({"status": result["status"], "candidates": len(result["candidates"]), "out": str(args.out)}))
    return 0 if result["status"] == "READY_FOR_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
