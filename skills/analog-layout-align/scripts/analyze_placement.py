#!/usr/bin/env python3
"""Read-only live-PCell access and placement-closure analysis."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from virtuoso_bridge import VirtuosoClient


def q(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def output_text(value: Any) -> str:
    text = str(value)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                return decoded
        except json.JSONDecodeError:
            pass
    return text


def center(bbox: list[list[float]]) -> list[float]:
    return [(bbox[0][0] + bbox[1][0]) / 2, (bbox[0][1] + bbox[1][1]) / 2]


def read_summary(client: VirtuosoClient, lib: str, cell: str, view: str) -> dict[str, Any]:
    expr = (
        "prog((cv out) "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"r\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        "out=sprintf(nil \"OK|%s|%s|%s|instances=%d|shapes=%d|nets=%d|terminals=%d\" "
        "cv~>libName cv~>cellName cv~>viewName length(cv~>instances) length(cv~>shapes) "
        "length(cv~>nets) length(cv~>terminals)) dbClose(cv) return(out))"
    )
    response = client.execute_skill(expr)
    if not response.ok:
        raise RuntimeError(response.errors)
    text = output_text(response.output)
    fields = text.split("|")
    if not fields or fields[0] != "OK":
        raise RuntimeError(text)
    counts = {key: int(value) for key, value in re.findall(r"(instances|shapes|nets|terminals)=(\d+)", text)}
    return {"lib": fields[1], "cell": fields[2], "view": fields[3], **counts}


def read_instance_access(
    client: VirtuosoClient, lib: str, cell: str, view: str, name: str
) -> dict[str, Any]:
    expr = (
        "prog((cv i out bb ibb pinIndex) out=\"\" "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"r\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        f"i=car(setof(x cv~>instances x~>name=={q(name)})) "
        f"unless(i dbClose(cv) return({q('ERROR|instance-missing')})) "
        "ibb=dbTransformBBox(i~>master~>bBox i~>transform) "
        "out=strcat(out sprintf(nil \"@I|%s|%s|%s|%s|%s|%.12g|%.12g|%.12g|%.12g|%.12g|%.12g^\" "
        "i~>name i~>libName i~>cellName i~>viewName i~>orient xCoord(car(ibb)) yCoord(car(ibb)) "
        "xCoord(cadr(ibb)) yCoord(cadr(ibb)) xCoord(i~>xy) yCoord(i~>xy))) "
        "foreach(term i~>master~>terminals pinIndex=0 foreach(pin term~>pins foreach(fig pin~>figs "
        "bb=dbTransformBBox(fig~>bBox i~>transform) "
        "out=strcat(out sprintf(nil \"@F|%s|%d|%s|%s|%s|%.12g|%.12g|%.12g|%.12g^\" "
        "term~>name pinIndex car(fig~>lpp) cadr(fig~>lpp) fig~>objType xCoord(car(bb)) yCoord(car(bb)) "
        "xCoord(cadr(bb)) yCoord(cadr(bb))))) pinIndex=pinIndex+1)) "
        "dbClose(cv) return(out))"
    )
    response = client.execute_skill(expr)
    if not response.ok:
        raise RuntimeError(f"{name}: {response.errors}")
    text = output_text(response.output)
    records = [record for record in text.split("^") if record]
    if not records or not records[0].startswith("@I|"):
        raise RuntimeError(f"{name}: malformed output {text!r}")
    header = records[0].split("|")
    result: dict[str, Any] = {
        "name": header[1],
        "master": {"lib": header[2], "cell": header[3], "view": header[4]},
        "orientation": header[5],
        "bbox": [[float(header[6]), float(header[7])], [float(header[8]), float(header[9])]],
        "origin": [float(header[10]), float(header[11])],
        "terminals": {},
    }
    figures: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records[1:]:
        fields = record.split("|")
        if len(fields) != 10 or fields[0] != "@F":
            raise RuntimeError(f"{name}: malformed figure {record!r}")
        bbox = [[float(fields[6]), float(fields[7])], [float(fields[8]), float(fields[9])]]
        figures[fields[1]].append(
            {
                "pin_index": int(fields[2]),
                "layer": fields[3],
                "purpose": fields[4],
                "object_type": fields[5],
                "bbox": bbox,
                "center": center(bbox),
            }
        )
    result["terminals"] = dict(figures)
    return result


def preferred_figures(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not figures:
        return []
    metal = [fig for fig in figures if re.fullmatch(r"(?:mt|metal)\d+", fig["layer"], re.I)]
    if metal:
        min_level = min(int(re.search(r"\d+", fig["layer"])[0]) for fig in metal)
        return [fig for fig in metal if int(re.search(r"\d+", fig["layer"])[0]) == min_level]
    conductive = [fig for fig in figures if fig["layer"].lower() not in {"thin", "annotate"}]
    return conductive or figures


def physical_pin_islands(
    instance_name: str, terminal: str, figures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Preserve every Cadence pin object as a required physical access island."""
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for figure in figures:
        grouped[int(figure.get("pin_index", 0))].append(figure)
    islands = []
    for pin_index, pin_figures in sorted(grouped.items()):
        preferred = preferred_figures(pin_figures)
        islands.append(
            {
                "id": f"{instance_name}:{terminal}:p{pin_index}",
                "pin_index": pin_index,
                "figures": pin_figures,
                "preferred_figures": preferred,
                "candidate_centers": [figure["center"] for figure in preferred],
                "selected_center": preferred[0]["center"] if preferred else None,
                "access_layers": sorted({figure["layer"] for figure in preferred}),
            }
        )
    return islands


def select_access_points(terminals: list[dict[str, Any]]) -> list[list[float]]:
    """Choose one access point per terminal using repeated Manhattan-median selection."""
    if not terminals:
        return []
    candidates = [entry["candidate_centers"] for entry in terminals]
    chosen = [points[0] for points in candidates]
    for _ in range(5):
        xs = sorted(point[0] for point in chosen)
        ys = sorted(point[1] for point in chosen)
        target = [xs[len(xs) // 2], ys[len(ys) // 2]]
        chosen = [min(points, key=lambda p: abs(p[0] - target[0]) + abs(p[1] - target[1])) for points in candidates]
    return chosen


def hpwl(points: list[list[float]]) -> float:
    if len(points) < 2:
        return 0.0
    return (max(p[0] for p in points) - min(p[0] for p in points)) + (
        max(p[1] for p in points) - min(p[1] for p in points)
    )


def total_to_median(points: list[list[float]]) -> tuple[float, list[float]]:
    if not points:
        return 0.0, [0.0, 0.0]
    xs, ys = sorted(p[0] for p in points), sorted(p[1] for p in points)
    median = [xs[len(xs) // 2], ys[len(ys) // 2]]
    return sum(abs(p[0] - median[0]) + abs(p[1] - median[1]) for p in points), median


def overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def nearest_terminal_on_side(instance: dict[str, Any], axis: str, side: str) -> dict[str, Any] | None:
    choices = []
    for term, data in instance["terminals"].items():
        for fig in data["preferred_figures"]:
            point = fig["center"]
            value = point[0] if axis == "x" else point[1]
            choices.append((value, term, point, data.get("net"), fig["layer"]))
    if not choices:
        return None
    selected = (max if side in {"right", "top"} else min)(choices, key=lambda item: item[0])
    return {"terminal": selected[1], "xy": selected[2], "net": selected[3], "layer": selected[4]}


def build_channels(instances: list[dict[str, Any]], threshold: float = 1.001) -> list[dict[str, Any]]:
    channels = []
    mos = [inst for inst in instances if inst["kind"] in {"nmos", "pmos"}]
    for index, a in enumerate(mos):
        for b in mos[index + 1 :]:
            abb, bbb = a["bbox"], b["bbox"]
            y_overlap = overlap_1d(abb[0][1], abb[1][1], bbb[0][1], bbb[1][1])
            x_overlap = overlap_1d(abb[0][0], abb[1][0], bbb[0][0], bbb[1][0])
            entry = None
            if y_overlap > 0:
                if abb[1][0] <= bbb[0][0]:
                    left, right, gap = a, b, bbb[0][0] - abb[1][0]
                elif bbb[1][0] <= abb[0][0]:
                    left, right, gap = b, a, abb[0][0] - bbb[1][0]
                else:
                    left = right = None
                    gap = math.inf
                if gap <= threshold:
                    la = nearest_terminal_on_side(left, "x", "right")
                    ra = nearest_terminal_on_side(right, "x", "left")
                    entry = {
                        "direction": "horizontal",
                        "first": left["name"],
                        "second": right["name"],
                        "gap": round(gap, 6),
                        "overlap": round(y_overlap, 6),
                        "facing_access": [la, ra],
                    }
            if entry is None and x_overlap > 0:
                if abb[1][1] <= bbb[0][1]:
                    lower, upper, gap = a, b, bbb[0][1] - abb[1][1]
                elif bbb[1][1] <= abb[0][1]:
                    lower, upper, gap = b, a, abb[0][1] - bbb[1][1]
                else:
                    lower = upper = None
                    gap = math.inf
                if gap <= threshold:
                    la = nearest_terminal_on_side(lower, "y", "top")
                    ua = nearest_terminal_on_side(upper, "y", "bottom")
                    entry = {
                        "direction": "vertical",
                        "first": lower["name"],
                        "second": upper["name"],
                        "gap": round(gap, 6),
                        "overlap": round(x_overlap, 6),
                        "facing_access": [la, ua],
                    }
            if entry:
                accesses = entry["facing_access"]
                entry["same_net_facing"] = bool(
                    accesses[0] and accesses[1] and accesses[0]["net"] == accesses[1]["net"]
                )
                channels.append(entry)
    return sorted(channels, key=lambda item: (item["gap"], item["direction"], item["first"]))


def mirror_symmetry(
    instances_by_name: dict[str, dict[str, Any]], group: dict[str, Any], tolerance: float = 0.001
) -> dict[str, Any]:
    names = [name[1:] if name.startswith("M") and name[1:] in instances_by_name else name for name in group["instances"]]
    members = [instances_by_name[name] for name in names if name in instances_by_name]
    if not members:
        return {"group": group["name"], "status": "missing-members"}
    min_x = min(inst["bbox"][0][0] for inst in members)
    max_x = max(inst["bbox"][1][0] for inst in members)
    axis = (min_x + max_x) / 2
    min_y = min(inst["bbox"][0][1] for inst in members)
    max_y = max(inst["bbox"][1][1] for inst in members)
    axis_y = (min_y + max_y) / 2
    rotational = "rotational" in group.get("pattern_mode", "")
    logicals = group.get("logical_devices", [])
    result: dict[str, Any] = {
        "group": group["name"],
        "axis_x": axis,
        "axis_y": axis_y,
        "symmetry_transform": "R180" if rotational else "MY",
        "logical_devices": logicals,
    }
    if len(logicals) == 2:
        per_device = {}
        all_errors = []
        for logical in logicals:
            family = [inst for inst in members if inst["logical_device"] == logical]
            terminal_errors = {}
            for terminal in ("D", "G", "S"):
                points = [
                    point
                    for inst in family
                    if terminal in inst["terminals"]
                    for point in inst["terminals"][terminal]["candidate_centers"]
                ]
                reflected = [
                    [2 * axis - p[0], 2 * axis_y - p[1] if rotational else p[1]]
                    for p in points
                ]
                unmatched = points.copy()
                errors = []
                for point in reflected:
                    if not unmatched:
                        break
                    match = min(unmatched, key=lambda p: abs(p[0] - point[0]) + abs(p[1] - point[1]))
                    errors.append(abs(match[0] - point[0]) + abs(match[1] - point[1]))
                    unmatched.remove(match)
                max_error = max(errors, default=0.0)
                all_errors.append(max_error)
                terminal_errors[terminal] = {
                    "max_mirror_error": round(max_error, 6),
                    "mean_mirror_error": round(sum(errors) / len(errors), 6) if errors else 0.0,
                }
            per_device[logical] = terminal_errors
        result["per_logical_device_terminal_mirror_errors"] = per_device
        result["status"] = "pass" if max(all_errors, default=0.0) <= tolerance else "issue"
    else:
        result["status"] = "not-pairwise-applicable"
    return result


def global_floorplan_metrics(instances: list[dict[str, Any]]) -> dict[str, Any]:
    """All PCells, including passives; bbox occupancy is not diffusion utilization."""
    if not instances:
        return {"bbox": None, "bbox_occupancy": None, "groups": []}
    def bounds(items):
        return [[min(i["bbox"][0][a] for i in items) for a in (0, 1)],
                [max(i["bbox"][1][a] for i in items) for a in (0, 1)]]
    def area(bb):
        return (bb[1][0]-bb[0][0])*(bb[1][1]-bb[0][1])
    bb = bounds(instances)
    groups = defaultdict(list)
    for inst in instances:
        groups[inst.get("group") or inst["name"]].append(inst)
    return {"bbox": bb, "width_um": bb[1][0]-bb[0][0], "height_um": bb[1][1]-bb[0][1],
            "area_um2": area(bb),
            "bbox_occupancy": sum(area(i["bbox"]) for i in instances)/area(bb) if area(bb) else None,
            "groups": [{"name": name, "bbox": bounds(items), "instance_count": len(items),
                        "nets": sorted({net for i in items for net in i.get("intent_terminals", {}).values() if net})}
                       for name, items in sorted(groups.items())],
            "boundary": "BBox occupancy may double-count overlaps; not active-area utilization or DRC."}


def closure_decision(structural_issues, long_nets, routing_precheck):
    if structural_issues:
        return {"status": "REFINE PLACEMENT INTENT", "summary": "Placement-structure issues require refinement.",
                "needs_refinement": True, "actions": ["Preserve identities and matching; refine a new intent and remeasure changed geometry."]}
    if long_nets:
        return {"status": "GLOBAL FLOORPLAN REVIEW REQUIRED", "summary": "Local matching checks do not close long-span global connections.",
                "needs_refinement": None, "actions": ["Review long nets by circuit role; the configured span threshold is a screening value, not a PDK or performance limit.",
                    "Compare rigid peripheral-macro relocations using critical-net HPWL, area, access and channel metrics before accepting the floorplan."]}
    return {"status": "PLACEMENT PROXIES REVIEWED; SIGNOFF NOT ESTABLISHED",
            "summary": "No structural defect at the configured checks; unmodeled context remains unverified.",
            "needs_refinement": False, "actions": ["Review routing access and channels; verify bulk/well/tap environment and foundry checks separately."]}


def markdown_report(data: dict[str, Any]) -> str:
    lines = [
        f"# {data['target']['cell']} placement closure",
        "",
        f"- Target: `{data['target']['lib']}/{data['target']['cell']}/{data['target']['view']}`",
        "- Operating mode: read-only; no routing and no Virtuoso database mutation",
        f"- Live instances: {data['live_summary']['instances']} (intent: {data['intent_instance_count']})",
        f"- MOS terminal sets complete (D/G/S): {data['checks']['all_mos_have_dgs']}",
        f"- Top-level electrical nets/terminals remain zero: {data['checks']['placement_only_boundary']}",
        "",
        "## Executive result",
        "",
        f"**{data['decision']['status']}** — {data['decision']['summary']}",
        "",
        "## Confirmed evidence",
        "",
    ]
    for item in data["findings"]:
        lines.append(f"- **{item['classification']} — {item['title']}**: {item['evidence']}")
    lines += ["", "## Net routability estimates", "", "| Net | Logical terminals | Required physical accesses | HPWL (µm) | Median-star length (µm) |", "|---|---:|---:|---:|---:|"]
    for net in data["nets"]:
        lines.append(
            f"| `{net['name']}` | {net['terminal_count']} | {net['physical_access_count']} | {net['estimated_hpwl']:.3f} | {net['estimated_median_star_length']:.3f} |"
        )
    lines += ["", "Each Cadence pin object is retained as a required physical access island. These are placement-only Manhattan estimates, not routed lengths or extracted parasitics.", "", "## Matching symmetry", ""]
    for group in data["symmetry"]:
        detail = group.get("per_logical_device_terminal_mirror_errors")
        if detail:
            metrics = "; ".join(
                f"{logical}: " + ", ".join(f"{term}={values['max_mirror_error']:.3f} µm" for term, values in terminals.items())
                for logical, terminals in detail.items()
            )
            lines.append(f"- `{group['group']}`: **{group['status']}**, max mirrored access error: {metrics}.")
        else:
            lines.append(f"- `{group['group']}`: {group['status']}.")
    lines += ["", "## Tight channels", ""]
    lines.append(
        f"Found {len(data['channels'])} adjacent MOS channel relations at ≤{data['thresholds']['channel_um']:.3f} µm; "
        f"{sum(1 for c in data['channels'] if c['same_net_facing'])} have the nearest facing access on the same intended net."
    )
    lines += ["", "## Recommended action", ""]
    for item in data["decision"]["actions"]:
        lines.append(f"- {item}")
    lines += ["", "## Boundaries", "", "- Pin labels and intent net names are metadata; no electrical connectivity is created.", "- PCell bbox/channel observations are not DRC, LVS, EM, density, well, guard-ring, or PEX signoff.", "- The PDK/rule decks remain authoritative for contacts, spacings, routing layers, wells, and taps.", ""]
    return "\n".join(lines)


def main() -> int:
    from virtuoso_bridge import VirtuosoClient
    from virtuoso_bridge.env import set_runtime_env_file

    parser = argparse.ArgumentParser()
    parser.add_argument("intent", type=Path)
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--lib", required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--view", default="layout")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--long-net-hpwl", type=float, default=50.0)
    parser.add_argument("--channel-threshold", type=float, default=1.001)
    parser.add_argument("--symmetry-tolerance", type=float, default=0.001)
    parser.add_argument("--differential-hpwl-tolerance", type=float, default=0.001)
    args = parser.parse_args()

    intent = json.loads(args.intent.read_text(encoding="utf-8"))
    set_runtime_env_file(str(args.env.resolve()))
    client = VirtuosoClient.from_env()
    # The CLI health check is performed before this script.  Reuse the live
    # local tunnel directly; do not let a read-only audit restart SSH state.
    probe = client.execute_skill("1+2")
    if not probe.ok or output_text(probe.output) != "3":
        raise RuntimeError(f"Bridge round-trip failed: {probe.errors or probe.output}")

    summary = read_summary(client, args.lib, args.cell, args.view)
    intent_by_name = {item["name"]: item for item in intent["instances"]}
    live_instances = []
    for name, expected in intent_by_name.items():
        live = read_instance_access(client, args.lib, args.cell, args.view, name)
        live["kind"] = expected["kind"]
        live["logical_device"] = expected.get("logical_device")
        live["group"] = expected.get("group")
        live["placement_role"] = expected.get("placement_role")
        expected_terms = expected.get("terminals", {})
        for terminal, figures in live["terminals"].items():
            preferred = preferred_figures(figures)
            islands = physical_pin_islands(live["name"], terminal, figures)
            live["terminals"][terminal] = {
                "net": expected_terms.get(terminal),
                "figures": figures,
                "preferred_figures": preferred,
                "candidate_centers": [fig["center"] for fig in preferred],
                "selected_center": preferred[0]["center"] if preferred else None,
                "access_layers": sorted({fig["layer"] for fig in figures}),
                "pin_islands": islands,
                "required_physical_access_count": len(islands),
            }
        live["intent_terminals"] = expected_terms
        live["missing_master_terminals"] = sorted(set(expected_terms) - set(live["terminals"]))
        live_instances.append(live)

    net_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    physical_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for inst in live_instances:
        for terminal, data in inst["terminals"].items():
            if not data.get("net") or not data["candidate_centers"]:
                continue
            terminal_entry = {
                "instance": inst["name"],
                "logical_device": inst["logical_device"],
                "terminal": terminal,
                "candidate_centers": data["candidate_centers"],
                "layers": [fig["layer"] for fig in data["preferred_figures"]],
                "pin_islands": data["pin_islands"],
                "required_physical_access_count": data["required_physical_access_count"],
            }
            net_entries[data["net"]].append(terminal_entry)
            for island in data["pin_islands"]:
                if not island["candidate_centers"]:
                    continue
                physical_entries[data["net"]].append(
                    {
                        "id": island["id"],
                        "instance": inst["name"],
                        "logical_device": inst["logical_device"],
                        "terminal": terminal,
                        "pin_island_id": island["id"],
                        "pin_index": island["pin_index"],
                        "candidate_centers": island["candidate_centers"],
                        "layers": island["access_layers"],
                    }
                )
    nets = []
    for net_name, terminals in net_entries.items():
        required = physical_entries[net_name]
        points = select_access_points(required)
        selected_by_id = {}
        for physical, point in zip(required, points):
            physical["selected_center"] = point
            selected_by_id[physical["pin_island_id"]] = point
        for terminal in terminals:
            for island in terminal["pin_islands"]:
                island["selected_center"] = selected_by_id.get(island["id"])
            selected = [item["selected_center"] for item in terminal["pin_islands"] if item.get("selected_center")]
            terminal["selected_center"] = selected[0] if selected else None
        length, median = total_to_median(points)
        nets.append(
            {
                "name": net_name,
                "terminal_count": len(terminals),
                "physical_access_count": len(required),
                "estimated_hpwl": round(hpwl(points), 6),
                "estimated_median_star_length": round(length, 6),
                "median": median,
                "terminals": terminals,
                "physical_accesses": required,
            }
        )
    nets.sort(key=lambda item: (-item["estimated_median_star_length"], item["name"]))

    live_by_name = {inst["name"]: inst for inst in live_instances}
    symmetry = [
        mirror_symmetry(live_by_name, group, args.symmetry_tolerance)
        for group in intent.get("groups", [])
    ]
    channels = build_channels(live_instances, args.channel_threshold)
    mos = [inst for inst in live_instances if inst["kind"] in {"nmos", "pmos"}]
    all_mos_have_dgs = all(set(("D", "G", "S")).issubset(inst["terminals"]) for inst in mos)
    gates_without_metal = [
        inst["name"]
        for inst in mos
        if not any(re.fullmatch(r"(?:mt|metal)\d+", fig["layer"], re.I) for fig in inst["terminals"].get("G", {}).get("figures", []))
    ]
    multi_island_terminals = [
        {
            "instance": inst["name"],
            "terminal": terminal,
            "net": data.get("net"),
            "physical_access_count": data["required_physical_access_count"],
        }
        for inst in live_instances
        for terminal, data in inst["terminals"].items()
        if data["required_physical_access_count"] > 1
    ]
    mismatched = [inst["name"] for inst in live_instances if inst["missing_master_terminals"]]
    unexpected_missing = [
        inst["name"]
        for inst in live_instances
        if set(inst["missing_master_terminals"]) - ({"B"} if inst["kind"] in {"nmos", "pmos"} else set())
    ]
    parameter_mismatches = []
    for group in intent.get("groups", []):
        logicals = group.get("logical_devices", [])
        if len(logicals) != 2:
            continue
        records = [item for item in intent["instances"] if item.get("logical_device") in logicals and item.get("placement_role") == "active"]
        signatures = {
            item["logical_device"]: {
                key: item.get("pcell_parameters", {}).get(key)
                for key in ("w", "fw", "l", "fingers", "nf", "connectGates", "connectSD", "tap")
            }
            for item in records
        }
        if len({json.dumps(value, sort_keys=True) for value in signatures.values()}) > 1:
            parameter_mismatches.append({"group": group["name"], "signatures": signatures})
    long_nets = [net for net in nets if net["estimated_hpwl"] >= args.long_net_hpwl]
    symmetry_issues = [group for group in symmetry if group["status"] == "issue"]
    net_by_name = {net["name"]: net for net in nets}
    differential_balances = []
    for group in intent.get("groups", []):
        if group.get("role") != "differential_pair" or len(group.get("logical_devices", [])) != 2:
            continue
        logicals = group["logical_devices"]
        gate_nets = []
        for logical in logicals:
            candidates = {
                item.get("terminals", {}).get("G")
                for item in intent["instances"]
                if item.get("logical_device") == logical and item.get("placement_role") == "active"
            }
            candidates.discard(None)
            gate_nets.append(next(iter(candidates)) if len(candidates) == 1 else None)
        hpwls = [net_by_name[net]["estimated_hpwl"] if net in net_by_name else None for net in gate_nets]
        delta = abs(hpwls[0] - hpwls[1]) if None not in hpwls else None
        differential_balances.append(
            {
                "group": group["name"],
                "logical_devices": logicals,
                "gate_nets": gate_nets,
                "gate_net_hpwls": hpwls,
                "absolute_hpwl_delta": round(delta, 6) if delta is not None else None,
                "status": "pass" if delta is not None and delta <= args.differential_hpwl_tolerance else "issue",
            }
        )
    differential_issues = [item for item in differential_balances if item["status"] == "issue"]

    findings = [
        {
            "classification": "Pass",
            "title": "Instance and terminal completeness",
            "evidence": f"Read back {len(live_instances)}/{len(intent_by_name)} intent instances; all {len(mos)} MOS expose D/G/S terminals={all_mos_have_dgs}.",
        },
        {
            "classification": "Issue" if unexpected_missing else ("Needs confirmation" if mismatched else "Pass"),
            "title": "Intent-to-master terminal mapping",
            "evidence": "D/G/S mappings are present. Missing bulk B figures do not prove a body tie; verify well/tap connectivity separately."
            if not mismatched or all(live_by_name[name]["missing_master_terminals"] == ["B"] for name in mismatched)
            else f"Missing mappings on: {', '.join(mismatched)}.",
        },
        {
            "classification": "Issue" if parameter_mismatches else "Pass",
            "title": "Pair-group PCell parameter equivalence",
            "evidence": "; ".join(
                f"{item['group']} differs: "
                + ", ".join(
                    key
                    for key in next(iter(item["signatures"].values()))
                    if len({str(signature.get(key)) for signature in item["signatures"].values()}) > 1
                )
                for item in parameter_mismatches
            )
            if parameter_mismatches
            else "All pairwise matching groups use equivalent checked PCell parameters.",
        },
        {
            "classification": "Issue" if gates_without_metal else "Pass",
            "title": "Gate metal accessibility",
            "evidence": f"{len(gates_without_metal)}/{len(mos)} MOS gate terminals expose no metal pin figure. Missing metal access needs a verified contact plan; present figures alone do not prove legal escape.",
        },
        {
            "classification": "Issue" if long_nets else "Pass",
            "title": "Long-span critical nets",
            "evidence": ", ".join(f"{net['name']} HPWL={net['estimated_hpwl']:.3f} µm" for net in long_nets)
            if long_nets
            else f"No net has estimated HPWL ≥{args.long_net_hpwl:g} µm.",
        },
        {
            "classification": "Issue" if symmetry_issues else "Pass",
            "title": "Mirrored terminal access",
            "evidence": f"{len(symmetry_issues)} pairwise matching groups exceed {args.symmetry_tolerance:g} µm mirrored D/G/S access error.",
        },
        {
            "classification": "Issue" if differential_issues else "Pass",
            "title": "Differential input access-span balance",
            "evidence": "; ".join(
                f"{item['group']}: {item['gate_nets'][0]}={item['gate_net_hpwls'][0]} µm, "
                f"{item['gate_nets'][1]}={item['gate_net_hpwls'][1]} µm, delta={item['absolute_hpwl_delta']} µm"
                for item in differential_balances
            )
            if differential_balances
            else "No two-device group with role=differential_pair was present.",
        },
        {
            "classification": "Needs confirmation",
            "title": "Placement channels",
            "evidence": f"Channels at or below {args.channel_threshold:g} µm are planning observations only; they have not been checked against routing/contact/well/implant DRC decks.",
        },
    ]

    structural_issues = bool(
        unexpected_missing or symmetry_issues or parameter_mismatches or differential_issues
    )
    routing_precheck = bool(gates_without_metal or long_nets or channels)

    # Do not allow local symmetry to silently certify a globally poor floorplan.
    decision = closure_decision(structural_issues or not all_mos_have_dgs or summary["instances"] != len(intent_by_name), long_nets, routing_precheck)
    floorplan = global_floorplan_metrics(live_instances)
    findings.append({"classification": "Needs confirmation", "title": "Global floorplan and passive placement",
                     "evidence": f"All-PCell envelope {floorplan['width_um']:.3f} x {floorplan['height_um']:.3f} um; bbox occupancy {floorplan['bbox_occupancy']:.1%}. Inspect output/passive macro adjacency, not only MOS pair symmetry."})
    findings[0]["classification"] = "Pass" if all_mos_have_dgs and summary["instances"] == len(intent_by_name) else "Issue"
    data = {
        "schema": "analog-layout-align.terminal-access/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "target": {"lib": args.lib, "cell": args.cell, "view": args.view},
        "source_intent": str(args.intent.resolve()),
        "thresholds": {
            "long_net_hpwl_um": args.long_net_hpwl,
            "channel_um": args.channel_threshold,
            "symmetry_um": args.symmetry_tolerance,
            "differential_hpwl_um": args.differential_hpwl_tolerance,
        },
        "intent_instance_count": len(intent_by_name),
        "live_summary": summary,
        "global_floorplan": floorplan,
        "checks": {
            "all_intent_instances_read": len(live_instances) == len(intent_by_name),
            "all_mos_have_dgs": all_mos_have_dgs,
            "placement_only_boundary": summary["nets"] == 0 and summary["terminals"] == 0,
            "missing_master_terminal_mappings": mismatched,
            "unexpected_missing_master_terminal_mappings": unexpected_missing,
            "gates_without_metal_access": gates_without_metal,
            "multi_island_terminals": multi_island_terminals,
            "pair_group_parameter_mismatches": parameter_mismatches,
        },
        "instances": live_instances,
        "nets": nets,
        "channels": channels,
        "symmetry": symmetry,
        "differential_balances": differential_balances,
        "findings": findings,
        "decision": decision,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "terminal-access.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    closure = {key: value for key, value in data.items() if key != "instances"}
    (args.out / "placement-closure.json").write_text(json.dumps(closure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.out / "net-routability-report.md").write_text(markdown_report(data), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "decision": decision, "counts": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
