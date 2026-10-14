#!/usr/bin/env python3
"""Compact redundant collinear geometry in a reviewed route specification.

This is a topology-preserving cleanup pass.  It merges only same-net,
same-layer, same-purpose, equal-width Manhattan segments.  The authoritative
route-intent builder remains responsible for connectivity and spacing closure.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def on_segment(point: list[float], a: list[float], b: list[float], tolerance: float) -> bool:
    if abs(a[0] - b[0]) <= tolerance:
        return abs(point[0] - a[0]) <= tolerance and min(a[1], b[1]) - tolerance <= point[1] <= max(a[1], b[1]) + tolerance
    return abs(point[1] - a[1]) <= tolerance and min(a[0], b[0]) - tolerance <= point[0] <= max(a[0], b[0]) + tolerance


def access_key(item: dict[str, Any]) -> tuple[str, str, str, tuple[float, float]]:
    return (
        str(item.get("instance", "")), str(item.get("terminal", "")),
        str(item.get("pin_island_id", "")), tuple(float(value) for value in item["xy_um"]),
    )


def compact(spec: dict[str, Any], tolerance: float = 1e-9) -> tuple[dict[str, Any], dict[str, Any]]:
    result = copy.deepcopy(spec)
    groups: dict[tuple[Any, ...], list[tuple[float, float]]] = defaultdict(list)
    accesses: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = defaultdict(dict)
    input_segments = 0
    for route in spec.get("routes", []):
        points = route.get("points_um", [])
        for item in route.get("access", []):
            accesses[str(route["net"])][access_key(item)] = copy.deepcopy(item)
        for a, b in zip(points, points[1:]):
            if a == b:
                continue
            input_segments += 1
            if abs(a[0] - b[0]) <= tolerance:
                direction, constant = "v", float(a[0])
                lo, hi = sorted((float(a[1]), float(b[1])))
            elif abs(a[1] - b[1]) <= tolerance:
                direction, constant = "h", float(a[1])
                lo, hi = sorted((float(a[0]), float(b[0])))
            else:
                raise ValueError(f"non-Manhattan route {route.get('id')}: {a}->{b}")
            key = (
                str(route["net"]), str(route["layer"]), str(route.get("purpose", "drawing")),
                float(route["width_um"]), direction, constant,
            )
            groups[key].append((lo, hi))

    routes: list[dict[str, Any]] = []
    serials: dict[str, int] = defaultdict(int)
    for key in sorted(groups, key=lambda item: tuple(str(value) for value in item)):
        net, layer, purpose, width, direction, constant = key
        merged: list[list[float]] = []
        for lo, hi in sorted(groups[key]):
            if merged and lo <= merged[-1][1] + tolerance:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        for lo, hi in merged:
            points = [[constant, lo], [constant, hi]] if direction == "v" else [[lo, constant], [hi, constant]]
            safe_net = re.sub(r"[^A-Za-z0-9_]+", "_", net).strip("_") or "net"
            index = serials[net]
            serials[net] += 1
            routes.append({
                "id": f"compact_{safe_net}_{index}", "net": net, "layer": layer,
                "purpose": purpose, "width_um": width, "points_um": points,
                "access": [],
            })

    missing = []
    covered = set()
    for net, items in accesses.items():
        for key, item in items.items():
            candidates = [route for route in routes if route["net"] == net and on_segment(item["xy_um"], route["points_um"][0], route["points_um"][1], tolerance)]
            if not candidates:
                missing.append({"net": net, "access": list(key[:3]), "xy_um": list(key[3])})
                continue
            candidates[0]["access"].append(copy.deepcopy(item))
            covered.add(key)
    if missing:
        raise ValueError(f"compaction lost route access records: {missing}")

    vias: list[dict[str, Any]] = []
    seen_vias: set[tuple[Any, ...]] = set()
    for via in spec.get("vias", []):
        key = (str(via["net"]), str(via["via"]), tuple(float(value) for value in via["xy_um"]))
        if key not in seen_vias:
            seen_vias.add(key)
            vias.append(copy.deepcopy(via))

    result["routes"] = routes
    result["vias"] = vias
    evidence = {
        "method": "same-net/same-layer/same-purpose/equal-width collinear interval union",
        "topology_preserving": True,
        "input_routes": len(spec.get("routes", [])), "input_segments": input_segments,
        "output_routes": len(routes),
        "input_vias": len(spec.get("vias", [])), "output_vias": len(vias),
        "access_records": len(covered),
        "boundary": "Requires authoritative route-intent rebuild and live materialized readback; does not establish DRC/LVS/PEX.",
    }
    result["compaction_evidence"] = evidence
    return result, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--tolerance-um", type=float, default=1e-9)
    args = parser.parse_args()
    if args.tolerance_um < 0:
        raise ValueError("tolerance must be nonnegative")
    result, evidence = compact(load(args.spec), args.tolerance_um)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.report:
        args.report.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
