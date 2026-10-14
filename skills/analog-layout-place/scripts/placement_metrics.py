"""Unified, offline candidate evaluator. All capacity and noise results are proxies."""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from itertools import combinations, product

from placement_geometry import (area, box, center, channels, digest, distance, envelope, expand,
                                hpwl, obstacles_for, overlap, point, project_islands, segment_hits)


def validate_constraints(constraints, names, nets):
    allowed = {"bounds_um", "required_nets", "obstacles", "access_pairs", "channel_demands", "critical_net_weights",
               "differential_nets", "sensitive_instances", "noise_sources", "heat_sources", "boundary_connections",
               "centroid_tolerance_um", "preserve_core_axis"}
    if set(constraints)-allowed:
        raise ValueError(f"unsupported constraints: {sorted(set(constraints)-allowed)}")
    if "bounds_um" in constraints: box(constraints["bounds_um"])
    if set(constraints.get("sensitive_instances", []))-names: raise ValueError("unknown sensitive instance")
    for source in [*constraints.get("noise_sources", []), *constraints.get("heat_sources", []), *constraints.get("boundary_connections", [])]:
        if source.get("instance") not in names: raise ValueError("unknown source instance")
        weight = source.get("weight", 1)
        if not isinstance(weight, (float, int)) or not math.isfinite(weight) or weight < 0:
            raise ValueError("source weights must be finite and nonnegative")
    for key in constraints.get("critical_net_weights", {}):
        if key not in nets: raise ValueError(f"unknown weighted net: {key}")
    for pair in constraints.get("differential_nets", []):
        if len(pair) != 2 or pair[0] == pair[1] or set(pair)-nets: raise ValueError("invalid differential net pair")
    paired_ids = set()
    for pair in constraints.get("access_pairs", []):
        a, b = pair["first"], pair["second"]
        if a == b or {a, b} & paired_ids: raise ValueError("an island may belong to one access pair")
        paired_ids.update((a, b))
        if "axis_instances" in pair and (not pair["axis_instances"] or set(pair["axis_instances"])-names):
            raise ValueError("invalid access pair axis instances")
    ids = [d["channel_id"] for d in constraints.get("channel_demands", [])]
    if len(ids) != len(set(ids)): raise ValueError("duplicate channel demands")
    for d in constraints.get("channel_demands", []):
        for key in ("ordinary_nets", "matched_pairs", "power_trunks"):
            if not isinstance(d.get(key, 0), int) or isinstance(d.get(key, 0), bool) or d.get(key, 0) < 0:
                raise ValueError("invalid channel demand count")
    if "centroid_tolerance_um" in constraints:
        tol = constraints["centroid_tolerance_um"]
        if not isinstance(tol, (int, float)) or not math.isfinite(tol) or tol < 0:
            raise ValueError("invalid centroid tolerance")


def validate_rules(evidence):
    if set(evidence)-{"layers", "profile_fingerprint", "description"}:
        raise ValueError("expected extracted per-layer planning rules, not a raw PDK profile")
    rules = evidence.get("layers", {})
    for layer, rule in rules.items():
        if not rule.get("source"):
            raise ValueError(f"missing rule source: {layer}")
        for key in ("width_um", "spacing_um", "escape_length_um"):
            value = rule.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key != "spacing_um" and value == 0):
                raise ValueError(f"invalid {layer}/{key}")
        if rule.get("preferred_direction") not in (None, "horizontal", "vertical"):
            raise ValueError(f"invalid preferred direction: {layer}")
        for key in ("via_envelope_um",):
            if key in rule and any(v <= 0 for v in point(rule[key])):
                raise ValueError(f"invalid {layer}/{key}")
        for key in ("power_width_um", "pair_spacing_um"):
            if key in rule and (not math.isfinite(rule[key]) or rule[key] < 0):
                raise ValueError(f"invalid {layer}/{key}")
    return rules


def evaluate_access(intent, records, constraints, rules):
    obstacles = obstacles_for(intent, constraints)
    bounds = constraints.get("bounds_um")
    centers = defaultdict(list)
    for rec in records:
        centers[rec["net"]].extend(c["xy"] for c in rec["candidates"])
    reports = []
    for rec in records:
        choices = []
        targets = centers[rec["net"]]
        target = [sorted(p[k] for p in targets)[len(targets)//2] for k in (0, 1)] if targets else [0, 0]
        for candidate in rec["candidates"]:
            xy = candidate["xy"]
            for layer in sorted(candidate["layers"]) or [None]:
                rule = rules.get(layer)
                obs = [o for o in obstacles if o.get("owner") != rec["instance"] and o.get("layer") in (None, layer)]
                clearance = min((max(o["bbox"][0][0]-xy[0], xy[0]-o["bbox"][1][0],
                                     o["bbox"][0][1]-xy[1], xy[1]-o["bbox"][1][1], 0) for o in obs), default=None)
                escapes = []; via_ok = None; turns = None; off = None
                if rule:
                    margin = rule["width_um"]/2 + rule["spacing_um"]
                    for direction, dx, dy in (("right", 1, 0), ("left", -1, 0), ("up", 0, 1), ("down", 0, -1)):
                        end = [xy[0]+dx*rule["escape_length_um"], xy[1]+dy*rule["escape_length_um"]]
                        inside = bounds is None or all(bounds[0][k] <= end[k] <= bounds[1][k] for k in (0, 1))
                        if inside and not any(segment_hits(xy, end, expand(o["bbox"], margin)) for o in obs):
                            escapes.append(direction)
                    dims = rule.get("via_envelope_um")
                    if dims:
                        vb = [[xy[k]-dims[k]/2-rule["spacing_um"] for k in (0, 1)],
                              [xy[k]+dims[k]/2+rule["spacing_um"] for k in (0, 1)]]
                        via_ok = not any(overlap(vb, o["bbox"]) for o in obs) and (bounds is None or
                            all(bounds[0][k] <= vb[0][k] and vb[1][k] <= bounds[1][k] for k in (0, 1)))
                    desired = []
                    if target[0] != xy[0]: desired.append("right" if target[0] > xy[0] else "left")
                    if target[1] != xy[1]: desired.append("up" if target[1] > xy[1] else "down")
                    turns = int(bool(desired) and not any(d in escapes for d in desired))
                    preferred = rule.get("preferred_direction")
                    off = int(bool(preferred) and not any((d in ("left", "right")) == (preferred == "horizontal") for d in escapes))
                competition = sum(1 for other in records if other["id"] != rec["id"] and other["net"] != rec["net"]
                                  and rule and any(distance(xy, c["xy"]) < 2*rule["escape_length_um"] for c in other["candidates"]))
                choices.append({"xy": xy, "layer": layer, "escape_directions": escapes if rule else None,
                                "legal_escape_direction_count": len(escapes) if rule else None,
                                "clearance_um": clearance, "via_envelope_fits": via_ok,
                                "distance_lower_bound_um": distance(xy, target), "immediate_bend_proxy": turns,
                                "off_direction_proxy": off, "escape_competition_proxy": competition,
                                "rule_source": rule.get("source") if rule else None,
                                "via_status": "unknown" if via_ok is None else "proxy_clear" if via_ok else "blocked"})
        def key(c):
            return (c["legal_escape_direction_count"] == 0, c["legal_escape_direction_count"] is None,
                    c["via_envelope_fits"] is False, -(c["legal_escape_direction_count"] or 0),
                    c["immediate_bend_proxy"] or 0, c["off_direction_proxy"] or 0,
                    c["escape_competition_proxy"], c["distance_lower_bound_um"], c["xy"], c["layer"] or "")
        choices.sort(key=key)
        preferred = choices[0] if choices else None
        reports.append({**rec, "candidate_count": len(rec["candidates"]), "preferred_candidate": preferred,
                        "alternate_candidates": choices[1:], "all_choices": choices,
                        "legal_escape_direction_count": preferred["legal_escape_direction_count"] if preferred else 0,
                        "access_risk": "missing" if not preferred else "unknown" if preferred["legal_escape_direction_count"] is None
                        else "blocked" if preferred["legal_escape_direction_count"] == 0 else "proxy_clear",
                        "paired_access_error": None})
    by_id = {r["id"]: r for r in reports}
    # Explicit island pairing avoids guessing that two complementary arrays are mirrors.
    for pair in constraints.get("access_pairs", []):
        a, b = by_id[pair["first"]], by_id[pair["second"]]
        axis = pair.get("axis_x_um")
        if "axis_instances" in pair:
            names = set(pair["axis_instances"])
            bb = envelope([i["bbox"] for i in intent["instances"] if i["name"] in names])
            axis = center(bb)[0]
        if axis is None or not math.isfinite(axis):
            raise ValueError("access pair requires finite axis_x_um or axis_instances")
        pairs = []
        for x, y in product(a["all_choices"], b["all_choices"]):
            error = distance([2*axis-x["xy"][0], x["xy"][1]], y["xy"])
            pairs.append(((x["legal_escape_direction_count"] == 0) + (y["legal_escape_direction_count"] == 0),
                          int(x["layer"] != y["layer"]), error, key(x), key(y), x, y))
        if pairs:
            best = min(pairs, key=lambda p: p[:5])
            for rec, choice in ((a, best[-2]), (b, best[-1])):
                rec["preferred_candidate"] = choice
                rec["alternate_candidates"] = [c for c in rec["all_choices"] if c != choice]
                rec["legal_escape_direction_count"] = choice["legal_escape_direction_count"]
                rec["access_risk"] = "unknown" if choice["legal_escape_direction_count"] is None else "blocked" if choice["legal_escape_direction_count"] == 0 else "proxy_clear"
                rec["paired_access_error"] = best[2]
    return reports


def evaluate_channels(intent, constraints, rules):
    result = channels(intent)
    demands = {d["channel_id"]: d for d in constraints.get("channel_demands", [])}
    for ch in result:
        demand = demands.get(ch["channel_id"])
        ch["demand"] = demand
        ch["usable_layers"] = sorted(rules)
        ch["capacity_by_layer"] = {}
        for layer, r in rules.items():
            gap = ch["width_um"]
            w, s = r["width_um"], r["spacing_um"]
            track = max(0, math.floor((gap-s+1e-12)/(w+s)))
            pair_width = 2*w+r.get("pair_spacing_um", s)
            pair_count = max(0, math.floor((gap-s+1e-12)/(pair_width+s)))
            power = r.get("power_width_um")
            dims = r.get("via_envelope_um")
            ch["capacity_by_layer"][layer] = {"ordinary_tracks": track, "matched_pairs": pair_count,
                "power_trunks": max(0, math.floor((gap-s+1e-12)/(power+s))) if power else None,
                "via_array_fits": (dims[ch["across_axis"]]+2*s <= gap and dims[1-ch["across_axis"]]+2*s <= ch["height_um"]) if dims else None,
                "source": r["source"], "preferred_direction": r.get("preferred_direction")}
        # Mixed demand is checked together on its explicitly assigned layer, never by summing capacities.
        ch["overflow"] = None; ch["required_width_um"] = None
        if demand and demand.get("layer") in rules:
            r = rules[demand["layer"]]; w, s = r["width_um"], r["spacing_um"]
            n, p, v = (demand.get(k, 0) for k in ("ordinary_nets", "matched_pairs", "power_trunks"))
            if any(not isinstance(c, int) or c < 0 for c in (n, p, v)):
                raise ValueError("channel demand counts must be nonnegative integers")
            if not v or r.get("power_width_um"):
                count = n+p+v
                required = n*w + p*(2*w+r.get("pair_spacing_um", s)) + v*r.get("power_width_um", 0) + ((count+1)*s if count else 0)
                ch["required_width_um"] = required
                ch["overflow"] = required > ch["width_um"] + 1e-10
        ch["uncertainty"] = "capacity_proxy_only" if ch["overflow"] is not None else "unknown_rules_or_demand"
        ch["obstacle_source"] = "conservative_PCell_bboxes; conditional rules not modeled"
    missing = set(demands) - {c["channel_id"] for c in result}
    for name in sorted(missing):
        result.append({"channel_id": name, "overflow": None, "uncertainty": "declared_channel_not_visible", "demand": demands[name]})
    return result


def evaluate_placement(intent, access, constraints, pdk_evidence, parent=None):
    parent = parent or intent
    failures = []; warnings = ["Projection and bbox-based routability are estimates, not live readback or signoff.",
                              "Owner PCell internal obstructions and conditional DRC are unmodeled."]
    def fail(code, detail): failures.append({"code": code, "detail": detail})
    try:
        rules = validate_rules(pdk_evidence)
        if intent.get("schema") != "analog-layout-align.pcell-placement-intent/v2":
            raise ValueError("optimizer requires target-PDK v2 intent")
        grid = float(intent["coordinate_contract"]["manufacturing_grid"])
        if not math.isfinite(grid) or grid <= 0: raise ValueError("invalid grid")
        old = {i["name"]: i for i in parent["instances"]}
        items = intent["instances"]; current = {i["name"]: i for i in items}
        if not items or len(current) != len(items) or set(current) != set(old):
            raise ValueError("instance identity mismatch")
        if access.get("schema") != "analog-layout-align.terminal-access/v1":
            raise ValueError("expected live terminal-access schema")
        if intent.get("coordinate_contract", {}).get("space") != "live Virtuoso evaluated PCell bbox":
            raise ValueError("target-PDK evaluated geometry evidence required")
        validate_constraints(constraints, set(current), {v for i in items for v in i.get("terminals", {}).values()})
        if parent.get("validation", {}).get("expected_instances") != len(items):
            fail("INSTANCE_COUNT", "expected_instances must match actual inventory")
        if intent.get("coordinate_contract") != parent.get("coordinate_contract"):
            fail("EVIDENCE_CHANGED", "coordinate contract differs")
        if intent.get("source_schematic") != parent.get("source_schematic"):
            fail("EVIDENCE_CHANGED", "source schematic differs")
        for field in ("groups", "dummy_associations"):
            if intent.get(field, []) != parent.get(field, []): fail("GROUP_CHANGED", field)
        for i in items:
            b = box(i["bbox"]); point(i["origin"])
            if i.get("orientation") not in {"R0", "MX", "MY", "R180"}: fail("ILLEGAL_ORIENTATION", i["name"])
            for field in ("pcell_master", "pcell_parameters", "terminals", "logical_device", "kind", "group", "placement_role", "grid_position"):
                if i.get(field) != old[i["name"]].get(field): fail("IDENTITY_OR_PARAMETERS_CHANGED", f"{i['name']}/{field}")
            if not i.get("pcell_master") or not i.get("pcell_parameters") or not i.get("terminals"):
                fail("INCOMPLETE_DEVICE", i["name"])
            if i.get("kind") in ("nmos", "pmos") and str(i.get("pcell_parameters", {}).get("m")) != "1": fail("MULTIPLIER", i["name"])
            if any(abs(v/grid-round(v/grid)) > 1e-7 for p in [i["origin"], *b] for v in p): fail("OFF_GRID", i["name"])
            prior = old[i["name"]]
            if i["orientation"] == prior["orientation"]:
                delta = [i["origin"][k]-prior["origin"][k] for k in (0, 1)]
                if any(abs(b[j][k]-prior["bbox"][j][k]-delta[k]) > 1e-8 for j in (0, 1) for k in (0, 1)):
                    fail("GEOMETRY_CHANGED", i["name"])
            else:
                fail("ORIENTATION_EVIDENCE_MISSING", "P0 optimizer preserves orientation: "+i["name"])
            bounds = constraints.get("bounds_um")
            if bounds and any(b[0][k] < bounds[0][k] or b[1][k] > bounds[1][k] for k in (0, 1)): fail("OUT_OF_BOUNDS", i["name"])
        for a, b in combinations(items, 2):
            if overlap(a["bbox"], b["bbox"]): fail("BBOX_OVERLAP", [a["name"], b["name"]])
        matching = []
        for group in intent.get("groups", []):
            names = [n for row in group.get("rows", []) for n in row]
            if set(names)-set(current) or len(names) != len(set(names)): fail("GROUP_MEMBERS", group["name"])
            actual_members = {i["name"] for i in items if i.get("group") == group["name"] and i.get("placement_role") != "dummy"}
            if names and set(names) != actual_members: fail("GROUP_MEMBERS", group["name"])
            centroids = {}
            for logical in group.get("logical_devices", []):
                members = [i for i in items if i.get("group") == group["name"] and i.get("logical_device") == logical and i.get("placement_role") != "dummy"]
                if not members: fail("GROUP_MEMBERS", f"{group['name']}/{logical}"); continue
                centroids[logical] = [sum(center(i["bbox"])[k] for i in members)/len(members) for k in (0, 1)]
            err = max((distance(a, b) for a, b in combinations(centroids.values(), 2)), default=0)
            exact = "common_centroid" in group.get("pattern_mode", "") and "fallback" not in group.get("pattern_mode", "")
            tolerance = constraints.get("centroid_tolerance_um", 1e-8)
            if exact and err > tolerance: fail("COMMON_CENTROID_BROKEN", group["name"])
            # Even fallback groups keep relative device geometry intact in this optimizer.
            members = [i for i in items if i.get("group") == group["name"]]
            shifts = [[center(i["bbox"])[k]-center(old[i["name"]]["bbox"])[k] for k in (0, 1)] for i in members]
            if shifts and any(distance(s, shifts[0]) > 1e-8 for s in shifts): fail("MATCHING_STRUCTURE_CHANGED", group["name"])
            matching.append({"group": group["name"], "centroids": centroids, "centroid_delta_um": err,
                             "exact_common_centroid": exact and err <= 1e-8,
                             "centroid_within_tolerance": err <= tolerance})
        core_names = intent.get("floorplan", {}).get("core_macros", [])
        if core_names and constraints.get("preserve_core_axis", True):
            axes = []
            for name in core_names:
                macro = next((m for m in intent.get("macro_instances", []) if m["name"] == name), None)
                if not macro: fail("CORE_MACRO_MISSING", name); continue
                members = [n for row in macro.get("rows", []) for n in row]
                axes.append(center(envelope([current[n]["bbox"] for n in members]))[0])
            if axes and max(axes)-min(axes) > grid+1e-9: fail("CORE_AXIS_BROKEN", core_names)
        for d in intent.get("dummy_associations", []):
            if not str(d.get("status", "")).startswith("associated"): fail("DUMMY_AMBIGUITY", d)
            if d.get("target_group") not in {g["name"] for g in intent.get("groups", [])}: fail("DUMMY_OWNERSHIP", d)
            if any(n not in current or current[n].get("group") != d.get("target_group") for n in d.get("dummy_copies", [])):
                fail("DUMMY_OWNERSHIP", d)
        if any(i.get("placement_role") == "dummy" and not i.get("group") for i in items): fail("DUMMY_OWNERSHIP", "ungrouped dummy")
        required = constraints.get("required_nets")
        all_nets = {v for i in items for v in i.get("terminals", {}).values()}
        if required is not None and (not required or set(required)-all_nets): fail("REQUIRED_NETS", "empty or unknown required nets")
        records = project_islands(parent, intent, access, required)
        for r in records:
            if not r["candidates"]: fail("NO_LEGAL_ACCESS", r["id"])
        accesses = evaluate_access(intent, records, constraints, rules)
        channel_results = evaluate_channels(intent, constraints, rules)
        original_channels = {c["channel_id"] for c in channels(parent)}
        for c in channel_results:
            if c.get("uncertainty") == "declared_channel_not_visible" and c["channel_id"] in original_channels:
                fail("DECLARED_CHANNEL_LOST", "Explicit demand needs a revised corridor mapping: "+c["channel_id"])
        net_points = defaultdict(list)
        for r in accesses:
            if r["preferred_candidate"]: net_points[r["net"]].append(r["preferred_candidate"]["xy"])
        nets = []
        for net, pts in sorted(net_points.items()):
            median = [sorted(p[k] for p in pts)[len(pts)//2] for k in (0, 1)]
            weight = constraints.get("critical_net_weights", {}).get(net, 0)
            if not math.isfinite(weight) or weight < 0: raise ValueError("invalid net weight")
            nets.append({"net": net, "hpwl_um": hpwl(pts), "median_star_um": sum(distance(p, median) for p in pts),
                         "critical_weight": weight, "bbox": envelope([[p, p] for p in pts])})
        floor = envelope([i["bbox"] for i in items]); total_area = area(floor)
        device_area = sum(area(i["bbox"]) for i in items)
        net_index = {n["net"]: n for n in nets}
        differential = []
        for pair in constraints.get("differential_nets", []):
            a, b = pair
            differential.append(abs(net_index[a]["hpwl_um"]-net_index[b]["hpwl_um"]))
        paired = [a["paired_access_error"] for a in accesses if a["paired_access_error"] is not None]
        metrics = {"area_um2": total_area, "device_area_um2": device_area, "whitespace_um2": total_area-device_area,
            "utilization": device_area/total_area, "hpwl_um": sum(n["hpwl_um"] for n in nets),
            "ordinary_hpwl_um": sum(n["hpwl_um"] for n in nets if n["critical_weight"] == 0),
            "critical_hpwl_um": sum(n["hpwl_um"]*n["critical_weight"] for n in nets),
            "median_star_um": sum(n["median_star_um"] for n in nets),
            "differential_hpwl_delta_um": max(differential) if differential else None,
            "paired_access_error_um": max(paired) if paired else None,
            "blocked_accesses": sum(r["access_risk"] in ("blocked", "missing") for r in accesses),
            "unknown_accesses": sum(r["access_risk"] == "unknown" for r in accesses),
            "via_envelope_blocked": sum(r["preferred_candidate"] is not None and r["preferred_candidate"]["via_envelope_fits"] is False for r in accesses),
            "channel_overflows": sum(c["overflow"] is True for c in channel_results),
            "unknown_channels": sum(c["overflow"] is None for c in channel_results),
            "unknown_declared_channels": sum(c["overflow"] is None and c["channel_id"] in {d["channel_id"] for d in constraints.get("channel_demands", [])} for c in channel_results),
            "channel_overflow_um": sum(max(0, c["required_width_um"]-c["width_um"]) for c in channel_results if c.get("required_width_um") is not None),
            "critical_crossing_proxy": sum(overlap(a["bbox"], b["bbox"]) for a, b in combinations(nets, 2) if a["critical_weight"] or b["critical_weight"]),
            "noise_proximity_proxy": None, "thermal_imbalance_proxy": None, "high_current_escape_um": None}
        sensitive = constraints.get("sensitive_instances", [])
        noise = constraints.get("noise_sources", [])
        heat = constraints.get("heat_sources", [])
        if noise and sensitive:
            metrics["noise_proximity_proxy"] = sum(n.get("weight", 1)/(distance(center(current[n["instance"]]["bbox"]), center(current[v]["bbox"]))+grid)
                                                     for n in noise for v in sensitive)
        if heat and sensitive:
            exposure = [sum(h.get("weight", 1)/(distance(center(current[h["instance"]]["bbox"]), center(current[v]["bbox"]))+grid) for h in heat) for v in sensitive]
            metrics["thermal_imbalance_proxy"] = max(exposure)-min(exposure)
        escapes = constraints.get("boundary_connections", [])
        if escapes:
            metrics["high_current_escape_um"] = sum(distance(center(current[e["instance"]]["bbox"]), point(e["target_xy_um"])) * e.get("weight", 1) for e in escapes)
        unknown = metrics["unknown_accesses"] or metrics["unknown_channels"]
        if unknown: warnings.append("Missing rule/demand evidence is unknown; zero measured violations does not establish routability.")
        return {"status": "BLOCKED" if failures else "EVALUATED", "hard_failures": failures,
                "metrics": metrics, "soft_objectives": {k: v for k, v in metrics.items() if v is not None},
                "accesses": accesses, "channels": channel_results, "nets": nets, "matching": matching,
                "warnings": warnings, "intent_sha256": digest(intent), "basis": "offline_projection"}
    except (ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
        fail("INVALID_INPUT", str(exc))
        return {"status": "BLOCKED", "hard_failures": failures, "metrics": {}, "soft_objectives": {}, "warnings": warnings}
