#!/usr/bin/env python3
"""Project live pin access through a refined placement intent."""

from __future__ import annotations

import argparse
import json
import hashlib
from collections import defaultdict
from pathlib import Path


def orient(point: list[float], orientation: str) -> list[float]:
    x, y = point
    return {
        "R0": [x, y],
        "MX": [x, -y],
        "MY": [-x, y],
        "R180": [-x, -y],
    }[orientation]


def inverse_placed(point: list[float], origin: list[float], orientation: str) -> list[float]:
    delta = [point[0] - origin[0], point[1] - origin[1]]
    return orient(delta, orientation)  # supported transforms are self-inverse


def place(local: list[float], origin: list[float], orientation: str) -> list[float]:
    delta = orient(local, orientation)
    return [delta[0] + origin[0], delta[1] + origin[1]]


def choose(terminals: list[dict]) -> list[list[float]]:
    candidates = [entry["candidate_centers"] for entry in terminals]
    selected = [points[0] for points in candidates]
    for _ in range(5):
        xs = sorted(point[0] for point in selected)
        ys = sorted(point[1] for point in selected)
        target = [xs[len(xs) // 2], ys[len(ys) // 2]]
        selected = [min(points, key=lambda p: abs(p[0] - target[0]) + abs(p[1] - target[1])) for points in candidates]
    return selected


def hpwl(points: list[list[float]]) -> float:
    return 0.0 if len(points) < 2 else max(p[0] for p in points) - min(p[0] for p in points) + max(p[1] for p in points) - min(p[1] for p in points)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("live_access", type=Path)
    parser.add_argument("parent_intent", type=Path)
    parser.add_argument("child_intent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--spec",
        type=Path,
        help="Optional refinement spec containing pin_templates {target_instance: live_source_instance}",
    )
    args = parser.parse_args()
    live = json.loads(args.live_access.read_text(encoding="utf-8"))
    parent = json.loads(args.parent_intent.read_text(encoding="utf-8"))
    child = json.loads(args.child_intent.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else {}
    pin_templates = spec.get("pin_templates", {})
    live_by_name = {item["name"]: item for item in live["instances"]}
    old_by_name = {item["name"]: item for item in parent["instances"]}
    new_by_name = {item["name"]: item for item in child["instances"]}
    if set(old_by_name) != set(new_by_name) or set(old_by_name) != set(live_by_name):
        raise ValueError("Parent, child, and live-access instance identities must match exactly")
    unknown_templates = set(pin_templates.values()) - set(live_by_name)
    if unknown_templates:
        raise ValueError(f"Unknown pin template instances: {sorted(unknown_templates)}")

    nets = defaultdict(list)
    projected_instances = {}
    projected_islands = []
    for name, new in new_by_name.items():
        old = old_by_name[name]
        live_inst = live_by_name[name]
        source_name = pin_templates.get(name, name)
        source_live = live_by_name[source_name]
        source_old = old_by_name[source_name]
        if old.get("pcell_parameters") != new.get("pcell_parameters") and name not in pin_templates:
            raise ValueError(f"Changed PCell {name} requires an explicit measured pin template")
        projected_instances[name] = {}
        for terminal, data in source_live["terminals"].items():
            islands = data.get("pin_islands")
            if islands is None:
                islands = [{"id": f"{source_name}:{terminal}:legacy", "candidate_centers": [f["center"] for f in data["preferred_figures"]]}]
            projected_instances[name][terminal] = []
            net = new.get("terminals", {}).get(terminal)
            for island in islands:
                local_points = [inverse_placed(p, source_old["origin"], source_old["orientation"]) for p in island["candidate_centers"]]
                points = [place(p, new["origin"], new["orientation"]) for p in local_points]
                if not points and net:
                    raise ValueError(f"Required physical island has no access: {island['id']}")
                island_id = island["id"] if source_name == name else f"{name}:{terminal}:template:{island['id']}"
                record = {"instance": name, "terminal": terminal, "net": net, "pin_island_id": island_id,
                          "source_pin_island_id": island["id"], "candidate_centers": points,
                          "access_layers": island.get("access_layers", data.get("access_layers", [])), "basis": "projection"}
                projected_islands.append(record)
                projected_instances[name][terminal].extend(points)
                if net: nets[net].append(record)

    parent_nets = {item["name"]: item for item in live["nets"]}
    net_metrics = []
    for name, terminals in nets.items():
        points = choose(terminals)
        metric = round(hpwl(points), 6)
        net_metrics.append(
            {
                "net": name,
                "parent_hpwl": parent_nets.get(name, {}).get("estimated_hpwl"),
                "child_projected_hpwl": metric,
                "delta": round(metric - parent_nets.get(name, {}).get("estimated_hpwl", metric), 6),
                "terminal_count": len({(r["instance"], r["terminal"]) for r in terminals}),
                "physical_access_count": len(terminals),
            }
        )
    net_metrics.sort(key=lambda item: (-item["child_projected_hpwl"], item["net"]))

    differential_balances = []
    metric_by_net = {item["net"]: item for item in net_metrics}
    for group in child.get("groups", []):
        if group.get("role") != "differential_pair" or len(group.get("logical_devices", [])) != 2:
            continue
        gate_nets = []
        for logical in group["logical_devices"]:
            values = {
                item.get("terminals", {}).get("G")
                for item in child["instances"]
                if item.get("logical_device") == logical and item.get("placement_role") == "active"
            }
            values.discard(None)
            gate_nets.append(next(iter(values)) if len(values) == 1 else None)
        projected = [metric_by_net[net]["child_projected_hpwl"] if net in metric_by_net else None for net in gate_nets]
        differential_balances.append(
            {
                "group": group["name"],
                "gate_nets": gate_nets,
                "parent_hpwl": [parent_nets.get(net, {}).get("estimated_hpwl") for net in gate_nets],
                "child_projected_hpwl": projected,
                "absolute_projected_delta": round(abs(projected[0] - projected[1]), 6) if None not in projected else None,
            }
        )

    source_target = live.get("target", {})
    proposed_target = spec.get("metadata", {}).get("target") or child.get("refinement", {}).get("target")
    result = {
        "schema": "analog-layout-align.pin-access-projection/v1",
        "source_live_target": source_target,
        "proposed_target": proposed_target,
        "materialized": bool(child.get("refinement", {}).get("materialized", False)),
        "parent_intent": str(args.parent_intent.resolve()),
        "child_intent": str(args.child_intent.resolve()),
        "pin_templates": pin_templates,
        "projection_basis": "Real parent pin figures transformed from master-local coordinates into child placements; optional changed-PCell templates come only from the refinement spec.",
        "net_metrics": net_metrics,
        "differential_balances": differential_balances,
        "projected_preferred_access_centers": projected_instances,
        "projected_pin_islands": projected_islands,
        "source_hashes": {key: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                          for key, value in (("parent", parent), ("child", child), ("live_access", live), ("refinement_spec", spec))},
        "limitations": [
            "Projected coordinates are not a Virtuoso readback.",
            "No routing, contact insertion, DRC, LVS, or extraction has been performed.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "differential_balances": differential_balances, "net_metrics": net_metrics}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
