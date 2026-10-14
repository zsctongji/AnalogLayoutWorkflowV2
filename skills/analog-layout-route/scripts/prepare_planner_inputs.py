#!/usr/bin/env python3
"""Prepare conservative offline planner inputs from terminal-access evidence.

The snapshot includes foreign-net routing-layer pin figures as hard obstacles.
PCell bodies, pre-existing wires, and top-level shapes are intentionally not
invented; callers must record that missing coverage in review.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("route_planner", HERE / "route_planner.py")
PLANNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PLANNER)


def build(profile: dict, access: dict, margin: float, net_order: list[str] | None = None) -> tuple[dict, dict]:
    routing_layers = [item["layer"] for item in profile.get("routing_layers", [])]
    boxes = [item.get("bbox") for item in access.get("instances", []) if item.get("bbox")]
    if not boxes:
        raise ValueError("terminal-access has no instance bboxes")
    bounds = [
        [min(box[0][0] for box in boxes) - margin, min(box[0][1] for box in boxes) - margin],
        [max(box[1][0] for box in boxes) + margin, max(box[1][1] for box in boxes) + margin],
    ]
    raw_obstacles = []
    by_net: dict[str, list[dict]] = {}
    for instance in access.get("instances", []):
        for terminal_name, terminal in instance.get("terminals", {}).items():
            net = terminal.get("net")
            for island in PLANNER.terminal_islands(instance["name"], terminal_name, terminal):
                by_net.setdefault(net, []).append({
                    "instance": instance["name"], "terminal": terminal_name,
                    "pin_island_id": island["id"],
                })
                for index, figure in enumerate(island.get("figures", [])):
                    if figure.get("layer") in routing_layers and figure.get("bbox"):
                        raw_obstacles.append({
                            "id": f"pin/{instance['name']}/{terminal_name}/{island['id']}/{index}",
                            "layer": figure["layer"], "bbox_um": figure["bbox"], "net": net, "hard": True,
                            "provenance": "terminal-access pin figure",
                        })
    profile_fp = profile["fingerprint"]["value"]
    obstacles = {
        "schema": PLANNER.OBSTACLE_SCHEMA, "target": access["target"],
        "sources": {"profile_fingerprint": profile_fp, "terminal_access_sha256": PLANNER.ROUTE.digest(access)},
        "bounds_um": bounds, "obstacles": raw_obstacles,
        "coverage": {
            "included": ["routing-layer terminal pin figures"],
            "not_included": ["arbitrary PCell bodies", "pre-existing routes", "top-level shapes", "conditional/EOL/notch spacing"],
            "live_snapshot": False,
        },
    }
    order = net_order or sorted(by_net)
    order += [net for net in sorted(by_net) if net not in order]
    request = {
        "schema": PLANNER.REQUEST_SCHEMA, "target": access["target"],
        "sources": {
            "profile_fingerprint": profile_fp, "terminal_access_sha256": PLANNER.ROUTE.digest(access),
            "obstacles_sha256": PLANNER.ROUTE.digest(obstacles),
        },
        "nets": [
            {"net": net, "layers": routing_layers, "terminals": by_net[net]}
            for net in order if net in by_net and len(by_net[net]) >= 2
        ],
        "matching": [],
        "review_notes": [
            "Offline replay input: refresh profile, terminal access, and obstacles before any live apply.",
            "Widths default to each routing layer's unconditional minimum; power/EM sizing remains a review blocker.",
        ],
    }
    return obstacles, request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--terminal-access", required=True, type=Path)
    parser.add_argument("--obstacles-out", required=True, type=Path)
    parser.add_argument("--request-out", required=True, type=Path)
    parser.add_argument("--margin-um", type=float, default=5.0)
    parser.add_argument("--net-order", nargs="*")
    args = parser.parse_args()
    profile, access = PLANNER.load(args.profile), PLANNER.load(args.terminal_access)
    obstacles, request = build(profile, access, args.margin_um, args.net_order)
    PLANNER.dump(args.obstacles_out, obstacles)
    PLANNER.dump(args.request_out, request)
    print(json.dumps({
        "nets": len(request["nets"]), "obstacles": len(obstacles["obstacles"]),
        "bounds_um": obstacles["bounds_um"], "live_snapshot": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
