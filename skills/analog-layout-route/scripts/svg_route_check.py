#!/usr/bin/env python3
"""Validate an ALR SVG preview against its intent and declared symmetry constraints."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA = "analog-layout-route.svg-check/v1"
PREVIEW_SCHEMA = "analog-layout-route.preview/v1"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol + 1e-12


def points_close(first: list[list[float]], second: list[list[float]], tol: float) -> bool:
    return len(first) == len(second) and all(close(a[0], b[0], tol) and close(a[1], b[1], tol) for a, b in zip(first, second))


def multiset_close(first: list[tuple[Any, ...]], second: list[tuple[Any, ...]], numeric_start: int, tol: float) -> bool:
    if len(first) != len(second):
        return False
    used: set[int] = set()
    for item in first:
        for index, candidate in enumerate(second):
            if index in used or item[:numeric_start] != candidate[:numeric_start]:
                continue
            if all(close(float(a), float(b), tol) for a, b in zip(item[numeric_start:], candidate[numeric_start:])):
                used.add(index)
                break
        else:
            return False
    return True


def parse_points(raw: str) -> list[list[float]]:
    result = []
    for token in raw.replace("\n", " ").split():
        x, y = token.split(",", 1)
        result.append([float(x), float(y)])
    return result


def inverse_point(point: list[float], frame: dict[str, float]) -> list[float]:
    return [
        frame["minx"] + (point[0] - frame["pad"]) / frame["scale"],
        frame["miny"] + (frame["height"] - frame["pad"] - point[1]) / frame["scale"],
    ]


def parse_svg(path: Path, errors: list[str]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        errors.append(f"SVG parse failed: {exc}")
        return {}, {}
    attrs = dict(root.attrib)
    if attrs.get("data-schema") != PREVIEW_SCHEMA:
        errors.append("SVG is not an annotated analog-layout-route preview")
        return attrs, {}
    try:
        frame = {
            "minx": float(attrs["data-minx-um"]), "miny": float(attrs["data-miny-um"]),
            "scale": float(attrs["data-scale"]), "pad": float(attrs["data-pad"]),
            "height": float(attrs["data-height"]),
        }
        if frame["scale"] <= 0:
            raise ValueError("scale must be positive")
    except (KeyError, ValueError) as exc:
        errors.append(f"SVG coordinate frame is invalid: {exc}")
        return attrs, {}
    objects: dict[str, dict[str, Any]] = {}
    for element in root.iter():
        kind = element.attrib.get("data-kind")
        if kind not in {"route", "via", "contact"}:
            continue
        object_id = element.attrib.get("data-object-id", "")
        if not object_id:
            errors.append(f"SVG {kind} element lacks data-object-id")
            continue
        if object_id in objects:
            errors.append(f"SVG contains duplicate object id {object_id}")
            continue
        item: dict[str, Any] = {"kind": kind, **element.attrib}
        try:
            if kind == "route":
                if local_name(element.tag) != "polyline":
                    raise ValueError("route is not a polyline")
                item["points_um"] = [inverse_point(p, frame) for p in parse_points(element.attrib["points"])]
            elif kind == "via":
                if local_name(element.tag) != "rect":
                    raise ValueError("via is not a rect")
                center = [float(element.attrib["x"]) + float(element.attrib["width"]) / 2,
                          float(element.attrib["y"]) + float(element.attrib["height"]) / 2]
                item["xy_um"] = inverse_point(center, frame)
            else:
                if local_name(element.tag) != "circle":
                    raise ValueError("contact is not a circle")
                item["xy_um"] = inverse_point([float(element.attrib["cx"]), float(element.attrib["cy"])], frame)
        except (KeyError, ValueError) as exc:
            errors.append(f"SVG object {object_id} has invalid geometry: {exc}")
            continue
        objects[object_id] = item
    return attrs, objects


def compare_structure(intent: dict[str, Any], attrs: dict[str, str], objects: dict[str, dict[str, Any]], tol: float, errors: list[str]) -> None:
    expected_hash = digest(intent)
    if attrs.get("data-intent-sha256") != expected_hash:
        errors.append("SVG intent hash does not match the reviewed intent")
    expected_ids = {item["id"] for key in ("routes", "vias", "contact_landings") for item in intent.get(key, [])}
    actual_ids = set(objects)
    for object_id in sorted(expected_ids - actual_ids):
        errors.append(f"SVG is missing object {object_id}")
    for object_id in sorted(actual_ids - expected_ids):
        errors.append(f"SVG contains unexpected object {object_id}")
    for route in intent.get("routes", []):
        item = objects.get(route["id"])
        if not item:
            continue
        if item["kind"] != "route" or item.get("data-net") != route["net"] or item.get("data-layer") != route["layer"] or item.get("data-purpose") != route["purpose"]:
            errors.append(f"SVG route metadata differs for {route['id']}")
        try:
            width = float(item.get("data-width-um", "nan"))
        except ValueError:
            width = math.nan
        if not close(width, route["width_um"], tol) or not points_close(item.get("points_um", []), route["points_um"], tol):
            errors.append(f"SVG route geometry differs for {route['id']}")
    for via in intent.get("vias", []):
        item = objects.get(via["id"])
        if not item:
            continue
        if item["kind"] != "via" or item.get("data-net") != via["net"] or item.get("data-via") != via["via"]:
            errors.append(f"SVG via metadata differs for {via['id']}")
        if not points_close([item.get("xy_um", [])], [via["xy_um"]], tol):
            errors.append(f"SVG via geometry differs for {via['id']}")
    for contact in intent.get("contact_landings", []):
        item = objects.get(contact["id"])
        if not item:
            continue
        if (item["kind"] != "contact" or item.get("data-net") != contact["net"] or
                item.get("data-via") != contact["via"] or item.get("data-source-layer") != contact["source_layer"]):
            errors.append(f"SVG contact metadata differs for {contact['id']}")
        if not points_close([item.get("xy_um", [])], [contact["xy_um"]], tol):
            errors.append(f"SVG contact geometry differs for {contact['id']}")


def route_segments(objects: dict[str, dict[str, Any]], net: str, tol: float) -> list[tuple[Any, ...]]:
    groups: dict[tuple[Any, ...], list[list[float]]] = defaultdict(list)
    for item in objects.values():
        if item["kind"] != "route" or item.get("data-net") != net:
            continue
        points = item["points_um"]
        for first, second in zip(points, points[1:]):
            if close(first[1], second[1], tol):
                key = (item.get("data-layer"), item.get("data-purpose"), float(item["data-width-um"]), "h", round((first[1] + second[1]) / 2, 9))
                groups[key].append(sorted([first[0], second[0]]))
            elif close(first[0], second[0], tol):
                key = (item.get("data-layer"), item.get("data-purpose"), float(item["data-width-um"]), "v", round((first[0] + second[0]) / 2, 9))
                groups[key].append(sorted([first[1], second[1]]))
    result = []
    for key, intervals in groups.items():
        intervals.sort()
        merged: list[list[float]] = []
        for lo, hi in intervals:
            if merged and lo <= merged[-1][1] + tol:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        result.extend((*key, lo, hi) for lo, hi in merged)
    return result


def route_points(objects: dict[str, dict[str, Any]], net: str) -> list[tuple[Any, ...]]:
    result = []
    for item in objects.values():
        if item.get("data-net") != net or item["kind"] not in {"via", "contact"}:
            continue
        descriptor = item.get("data-via", "")
        if item["kind"] == "contact":
            descriptor += ":" + item.get("data-source-layer", "")
        result.append((item["kind"], descriptor, item["xy_um"][0], item["xy_um"][1]))
    return result


def transform_xy(x: float, y: float, group: dict[str, Any]) -> tuple[float, float]:
    transform = group.get("transform")
    if transform == "mirror_x":
        return 2 * float(group["axis_um"]) - x, y
    if transform == "mirror_y":
        return x, 2 * float(group["axis_um"]) - y
    if transform == "rotate_180":
        return 2 * float(group["axis_x_um"]) - x, 2 * float(group["axis_y_um"]) - y
    raise ValueError(f"unsupported transform {transform!r}")


def transform_segments(items: list[tuple[Any, ...]], group: dict[str, Any]) -> list[tuple[Any, ...]]:
    result = []
    for layer, purpose, width, orient, fixed, lo, hi in items:
        if orient == "h":
            first = transform_xy(lo, fixed, group); second = transform_xy(hi, fixed, group)
            result.append((layer, purpose, width, "h", (first[1] + second[1]) / 2, *sorted([first[0], second[0]])))
        else:
            first = transform_xy(fixed, lo, group); second = transform_xy(fixed, hi, group)
            result.append((layer, purpose, width, "v", (first[0] + second[0]) / 2, *sorted([first[1], second[1]])))
    return result


def transform_points(items: list[tuple[Any, ...]], group: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [(*item[:2], *transform_xy(float(item[2]), float(item[3]), group)) for item in items]


def check_symmetry(intent: dict[str, Any], objects: dict[str, dict[str, Any]], base_tol: float,
                   errors: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    results = []
    groups = intent.get("symmetry_groups", [])
    if not groups:
        warnings.append("intent declares no SVG geometry symmetry groups")
    for index, group in enumerate(groups):
        group_id = str(group.get("id") or f"group_{index}")
        tol = float(group.get("tolerance_um", base_tol))
        mode = group.get("mode")
        try:
            if mode == "self":
                first_net = second_net = str(group["net"])
            elif mode == "pair":
                first_net, second_net = str(group["first_net"]), str(group["second_net"])
            else:
                raise ValueError("mode must be self or pair")
            transformed_segments = transform_segments(route_segments(objects, first_net, tol), group)
            expected_segments = route_segments(objects, second_net, tol)
            transformed_points = transform_points(route_points(objects, first_net), group)
            expected_points = route_points(objects, second_net)
            segment_pass = multiset_close(transformed_segments, expected_segments, 4, tol)
            point_pass = multiset_close(transformed_points, expected_points, 2, tol)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"symmetry group {group_id} is invalid: {exc}")
            results.append({"id": group_id, "pass": False, "error": str(exc)})
            continue
        passed = segment_pass and point_pass
        results.append({"id": group_id, "mode": mode, "first_net": first_net, "second_net": second_net,
                        "transform": group.get("transform"), "tolerance_um": tol,
                        "segments_pass": segment_pass, "vias_contacts_pass": point_pass, "pass": passed})
        if not passed:
            errors.append(f"SVG symmetry group {group_id} does not match within {tol:g} um")
    return results


def check_matching(intent: dict[str, Any], errors: list[str]) -> list[dict[str, Any]]:
    results = []
    for pair in intent.get("matching", []):
        first, second = pair.get("first_net"), pair.get("second_net")
        passed = pair.get("pass") is True
        results.append({"first_net": first, "second_net": second, "pass": passed,
                        "length_delta_um": pair.get("length_delta_um"),
                        "max_per_layer_length_delta_um_observed": pair.get("max_per_layer_length_delta_um_observed"),
                        "via_type_delta": pair.get("via_type_delta"), "bend_delta": pair.get("bend_delta")})
        if not passed:
            errors.append(f"intent matching result {first}/{second} is not passing")
    return results


def build_check(intent_path: Path, svg_path: Path) -> dict[str, Any]:
    intent = load(intent_path)
    errors: list[str] = []
    warnings: list[str] = []
    grid = float(intent.get("manufacturing_grid_um", 0.001))
    render_tol = max(grid, 0.001)
    attrs, objects = parse_svg(svg_path, errors)
    if attrs:
        compare_structure(intent, attrs, objects, render_tol, errors)
    symmetry = check_symmetry(intent, objects, grid, errors, warnings) if objects else []
    matching = check_matching(intent, errors)
    status = "PASS" if not errors else "BLOCKED"
    return {
        "schema": SCHEMA, "status": status, "target": intent.get("target"),
        "intent_sha256": digest(intent), "svg_sha256": file_digest(svg_path),
        "counts": {
            "expected_routes": len(intent.get("routes", [])), "expected_vias": len(intent.get("vias", [])),
            "expected_contacts": len(intent.get("contact_landings", [])),
            "svg_routes": sum(x["kind"] == "route" for x in objects.values()),
            "svg_vias": sum(x["kind"] == "via" for x in objects.values()),
            "svg_contacts": sum(x["kind"] == "contact" for x in objects.values()),
        },
        "matching": matching, "symmetry": symmetry, "errors": errors, "warnings": warnings,
        "boundary": "SVG structure and vector geometry review only; not electrical extraction, DRC, or LVS.",
    }


def markdown(result: dict[str, Any]) -> str:
    lines = ["# Analog routing SVG check", "", f"- Status: **{result['status']}**",
             f"- Target: `{result.get('target')}`", f"- Intent SHA-256: `{result['intent_sha256']}`",
             f"- SVG SHA-256: `{result['svg_sha256']}`", "", "## Counts", ""]
    for key, value in result["counts"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Symmetry", ""]
    lines += [f"- {item['id']}: {'PASS' if item.get('pass') else 'FAIL'}" for item in result["symmetry"]] or ["- No explicit geometry symmetry groups"]
    lines += ["", "## Matching", ""]
    lines += [f"- {item['first_net']}/{item['second_net']}: {'PASS' if item['pass'] else 'FAIL'}" for item in result["matching"]] or ["- No matched pairs"]
    lines += ["", "## Errors", ""] + ([f"- {item}" for item in result["errors"]] or ["- None"])
    lines += ["", "## Warnings", ""] + ([f"- {item}" for item in result["warnings"]] or ["- None"])
    lines += ["", "## Boundary", "", result["boundary"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", required=True, type=Path)
    parser.add_argument("--svg", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = build_check(args.intent, args.svg)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.report.write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "errors": len(result["errors"]),
                      "warnings": len(result["warnings"]), "out": str(args.out.resolve())}))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
