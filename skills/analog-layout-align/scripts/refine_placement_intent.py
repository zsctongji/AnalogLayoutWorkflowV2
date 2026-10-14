#!/usr/bin/env python3
"""Apply a declarative, circuit-agnostic refinement spec to a placement intent."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_ORIENTATIONS = {"R0", "MX", "MY", "R180"}
SPEC_SCHEMA = "analog-layout-align.refinement-spec/v1"
INTENT_SCHEMA = "analog-layout-align.pcell-placement-intent/v2"


def numeric_bbox(value: Any) -> list[list[float]]:
    if len(value) != 2:
        raise ValueError(f"Invalid bbox: {value!r}")
    if isinstance(value[0], str):
        result = [[float(part) for part in point.split()] for point in value]
    else:
        result = [[float(part) for part in point] for point in value]
    if any(len(point) != 2 for point in result):
        raise ValueError(f"Invalid bbox: {value!r}")
    if result[0][0] >= result[1][0] or result[0][1] >= result[1][1]:
        raise ValueError(f"Non-positive bbox: {value!r}")
    return result


def snap(value: float, grid: float) -> float:
    return round(round(float(value) / grid) * grid, 12)


def snap_point(point: list[float], grid: float) -> list[float]:
    if len(point) != 2:
        raise ValueError(f"Invalid point: {point!r}")
    return [snap(point[0], grid), snap(point[1], grid)]


def snap_bbox(value: Any, grid: float) -> list[list[float]]:
    return [snap_point(point, grid) for point in numeric_bbox(value)]


def bbox_center(bbox: list[list[float]]) -> list[float]:
    return [(bbox[0][0] + bbox[1][0]) / 2, (bbox[0][1] + bbox[1][1]) / 2]


def positive_overlap(a: list[list[float]], b: list[list[float]]) -> bool:
    return (
        min(a[1][0], b[1][0]) > max(a[0][0], b[0][0])
        and min(a[1][1], b[1][1]) > max(a[0][1], b[0][1])
    )


def macro_members(intent: dict[str, Any], macro_name: str) -> set[str]:
    macro = next((item for item in intent.get("macro_instances", []) if item["name"] == macro_name), None)
    if macro is None:
        raise ValueError(f"Unknown macro: {macro_name}")
    return {name for row in macro.get("rows", []) for name in row}


def select_names(intent: dict[str, Any], selector: dict[str, Any]) -> list[str]:
    if not selector:
        raise ValueError("A non-empty selector is required")
    records = intent["instances"]
    names = set(selector.get("names", [item["name"] for item in records]))
    if "macro" in selector:
        names &= macro_members(intent, selector["macro"])
    filters = {
        "group": "group",
        "logical_device": "logical_device",
        "kind": "kind",
        "placement_role": "placement_role",
    }
    for selector_key, record_key in filters.items():
        if selector_key in selector:
            wanted = selector[selector_key]
            wanted = set(wanted if isinstance(wanted, list) else [wanted])
            names &= {item["name"] for item in records if item.get(record_key) in wanted}
    known = {item["name"] for item in records}
    unknown = names - known
    if unknown:
        raise ValueError(f"Unknown selected instances: {sorted(unknown)}")
    result = sorted(names)
    if not result:
        raise ValueError(f"Selector matched no instances: {selector!r}")
    return result


def update_instance_geometry(
    item: dict[str, Any], origin: list[float], orientation: str, bbox: Any, grid: float
) -> None:
    if orientation not in SUPPORTED_ORIENTATIONS:
        raise ValueError(f"Unsupported orientation for {item['name']}: {orientation}")
    item["origin"] = snap_point(origin, grid)
    item["orientation"] = orientation
    item["bbox"] = snap_bbox(bbox, grid)
    item["bbox_center"] = bbox_center(item["bbox"])
    item["align_anchor"] = list(item["origin"])
    item["align_bbox"] = copy.deepcopy(item["bbox"])


def translate_instance(item: dict[str, Any], dx: float, dy: float, grid: float) -> None:
    bbox = numeric_bbox(item["bbox"])
    update_instance_geometry(
        item,
        [item["origin"][0] + dx, item["origin"][1] + dy],
        item["orientation"],
        [[bbox[0][0] + dx, bbox[0][1] + dy], [bbox[1][0] + dx, bbox[1][1] + dy]],
        grid,
    )


def allowed_update(target: dict[str, Any], fields: dict[str, Any], allowed: set[str], kind: str) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unsupported {kind} fields: {sorted(unknown)}")
    target.update(copy.deepcopy(fields))


def rebuild_derived(intent: dict[str, Any], grid: float) -> None:
    by_name = {item["name"]: item for item in intent["instances"]}
    for item in intent["instances"]:
        item["origin"] = snap_point(item["origin"], grid)
        item["bbox"] = snap_bbox(item["bbox"], grid)
        item["bbox_center"] = bbox_center(item["bbox"])
        item["align_anchor"] = list(item["origin"])
        item["align_bbox"] = copy.deepcopy(item["bbox"])

    for macro in intent.get("macro_instances", []):
        names = [name for row in macro.get("rows", []) for name in row]
        missing = set(names) - set(by_name)
        if missing:
            raise ValueError(f"Macro {macro['name']} references missing instances: {sorted(missing)}")
        if not names:
            continue
        boxes = [by_name[name]["bbox"] for name in names]
        bbox = [
            [min(box[0][0] for box in boxes), min(box[0][1] for box in boxes)],
            [max(box[1][0] for box in boxes), max(box[1][1] for box in boxes)],
        ]
        macro["bbox"] = [snap_point(point, grid) for point in bbox]
        macro["origin"] = list(macro["bbox"][0])
        macro["size"] = [
            snap(macro["bbox"][1][0] - macro["bbox"][0][0], grid),
            snap(macro["bbox"][1][1] - macro["bbox"][0][1], grid),
        ]
        macro["center"] = bbox_center(macro["bbox"])

    boxes = [item["bbox"] for item in intent["instances"]]
    floorplan = [
        [min(box[0][0] for box in boxes), min(box[0][1] for box in boxes)],
        [max(box[1][0] for box in boxes), max(box[1][1] for box in boxes)],
    ]
    intent.setdefault("floorplan", {})["bbox"] = [snap_point(point, grid) for point in floorplan]
    width = floorplan[1][0] - floorplan[0][0]
    height = floorplan[1][1] - floorplan[0][1]
    for item in intent["instances"]:
        center = item["bbox_center"]
        item["relative_center"] = [
            (center[0] - floorplan[0][0]) / width if width else 0.0,
            (center[1] - floorplan[0][1]) / height if height else 0.0,
        ]

    overlaps = []
    for index, left in enumerate(intent["instances"]):
        for right in intent["instances"][index + 1 :]:
            if positive_overlap(left["bbox"], right["bbox"]):
                overlaps.append([left["name"], right["name"]])
    if overlaps:
        raise ValueError(f"Refined intent has bbox overlaps: {overlaps}")

    validation = intent.setdefault("validation", {})
    validation["bbox_overlap_free"] = True
    validation["bbox_overlaps"] = []
    validation["expected_instances"] = len(intent["instances"])
    validation["placed_instances"] = len(intent["instances"])
    validation["missing_instances"] = []
    validation["all_origins_on_manufacturing_grid"] = all(
        abs(value / grid - round(value / grid)) < 1e-8
        for item in intent["instances"]
        for value in item["origin"]
    )
    validation["all_mos_copies_have_m_1"] = all(
        str(item.get("pcell_parameters", {}).get("m")) == "1"
        for item in intent["instances"]
        if item.get("kind") in {"nmos", "pmos"}
    )

    matching_checks = []
    for group in intent.get("groups", []):
        logicals = group.get("logical_devices", [])
        if len(logicals) < 2:
            continue
        centroids = {}
        for logical in logicals:
            centers = [
                item["bbox_center"]
                for item in intent["instances"]
                if item.get("group") == group["name"]
                and item.get("logical_device") == logical
                and item.get("placement_role") == "active"
            ]
            if not centers:
                raise ValueError(f"Group {group['name']} has no active copies for {logical}")
            centroids[logical] = [
                sum(point[0] for point in centers) / len(centers),
                sum(point[1] for point in centers) / len(centers),
            ]
        first = centroids[logicals[0]]
        deltas = {
            logical: [centroids[logical][0] - first[0], centroids[logical][1] - first[1]]
            for logical in logicals
        }
        common = all(abs(value) <= grid for delta in deltas.values() for value in delta)
        matching_checks.append(
            {
                "group": group["name"],
                "physical_centroids": centroids,
                "delta_from_first": deltas,
                "common_centroid": common,
            }
        )
    validation["matching_checks"] = matching_checks

    macro_by_name = {macro["name"]: macro for macro in intent.get("macro_instances", [])}
    core_names = intent.get("floorplan", {}).get("core_macros", [])
    core_centers = {name: macro_by_name[name]["center"][0] for name in core_names if name in macro_by_name}
    if core_centers:
        reference = next(iter(core_centers.values()))
        validation["core_center_x"] = core_centers
        validation["core_center_aligned"] = all(abs(value - reference) <= grid for value in core_centers.values())
        intent["floorplan"]["core_axis_x"] = reference


def summarize_delta(parent: dict[str, Any], child: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    old = {item["name"]: item for item in parent["instances"]}
    new = {item["name"]: item for item in child["instances"]}
    changes = []
    for name in sorted(old):
        fields = {}
        for key in ("origin", "orientation", "bbox", "pcell_parameters", "grid_position", "row", "column"):
            if old[name].get(key) != new[name].get(key):
                fields[key] = {"before": old[name].get(key), "after": new[name].get(key)}
        if fields:
            changes.append({"instance": name, "fields": fields})
    return {
        "schema": "analog-layout-align.intent-delta/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": copy.deepcopy(spec.get("metadata", {})),
        "changed_instances": changes,
        "changed_instance_count": len(changes),
        "floorplan_before": parent.get("floorplan", {}).get("bbox"),
        "floorplan_after": child.get("floorplan", {}).get("bbox"),
        "validation_after": copy.deepcopy(child["validation"]),
        "operations": copy.deepcopy(spec["operations"]),
    }


def refine(parent: dict[str, Any], spec: dict[str, Any], parent_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if parent.get("schema") != INTENT_SCHEMA:
        raise ValueError(f"Unsupported intent schema: {parent.get('schema')!r}")
    if spec.get("schema") != SPEC_SCHEMA:
        raise ValueError(f"Unsupported refinement schema: {spec.get('schema')!r}")
    if not isinstance(spec.get("operations"), list) or not spec["operations"]:
        raise ValueError("Refinement spec requires a non-empty operations list")
    child = copy.deepcopy(parent)
    grid = float(child.get("coordinate_contract", {}).get("manufacturing_grid", 0.001))
    by_name = {item["name"]: item for item in child["instances"]}
    explicitly_placed = {
        record["name"]
        for operation in spec["operations"]
        if operation.get("op") == "place"
        for record in operation.get("placements", [])
    }

    for operation in spec["operations"]:
        op = operation.get("op")
        if op == "translate":
            names = select_names(child, operation["selector"])
            dx, dy = float(operation["dx"]), float(operation["dy"])
            for name in names:
                translate_instance(by_name[name], dx, dy, grid)
        elif op == "place":
            placements = operation.get("placements", [])
            if not placements:
                raise ValueError("place requires placements")
            for record in placements:
                name = record["name"]
                if name not in by_name:
                    raise ValueError(f"Unknown placement instance: {name}")
                update_instance_geometry(
                    by_name[name], record["origin"], record["orientation"], record["bbox"], grid
                )
                for key in ("grid_position", "row", "column"):
                    if key in record:
                        by_name[name][key] = copy.deepcopy(record[key])
        elif op == "set_parameters":
            names = select_names(child, operation["selector"])
            geometry_unchanged = operation.get("geometry_unchanged") is True
            stale = set(names) - explicitly_placed
            if stale and not geometry_unchanged:
                raise ValueError(
                    "Parameter changes require explicit placements with evaluated bboxes or geometry_unchanged=true; "
                    f"missing placements for {sorted(stale)}"
                )
            for name in names:
                by_name[name].setdefault("pcell_parameters", {}).update(copy.deepcopy(operation["parameters"]))
        elif op == "update_group":
            target = next((item for item in child.get("groups", []) if item["name"] == operation["name"]), None)
            if target is None:
                raise ValueError(f"Unknown group: {operation['name']}")
            allowed_update(target, operation["fields"], {"pattern_mode", "rows", "align_rows", "constraints", "role"}, "group")
        elif op == "update_macro":
            target = next((item for item in child.get("macro_instances", []) if item["name"] == operation["name"]), None)
            if target is None:
                raise ValueError(f"Unknown macro: {operation['name']}")
            allowed_update(target, operation["fields"], {"rows", "dummy_strategy", "role"}, "macro")
        else:
            raise ValueError(f"Unsupported refinement operation: {op!r}")

    rebuild_derived(child, grid)
    metadata = copy.deepcopy(spec.get("metadata", {}))
    child["refinement"] = {
        **metadata,
        "schema": SPEC_SCHEMA,
        "parent_intent": parent_path,
        "materialized": False,
        "changed_by": "refine_placement_intent.py",
        "requires_live_pcell_readback": True,
    }
    delta = summarize_delta(parent, child, spec)
    return child, delta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("parent_intent", type=Path)
    parser.add_argument("refinement_spec", type=Path)
    parser.add_argument("output_intent", type=Path)
    parser.add_argument("--delta", required=True, type=Path)
    args = parser.parse_args()
    parent = json.loads(args.parent_intent.read_text(encoding="utf-8"))
    spec = json.loads(args.refinement_spec.read_text(encoding="utf-8"))
    child, delta = refine(parent, spec, str(args.parent_intent.resolve()))
    args.output_intent.parent.mkdir(parents=True, exist_ok=True)
    args.delta.parent.mkdir(parents=True, exist_ok=True)
    args.output_intent.write_text(json.dumps(child, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.delta.write_text(json.dumps(delta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output_intent": str(args.output_intent),
                "delta": str(args.delta),
                "changed_instances": delta["changed_instance_count"],
                "floorplan": child["floorplan"]["bbox"],
                "bbox_overlap_free": child["validation"]["bbox_overlap_free"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
