#!/usr/bin/env python3
"""Plan deterministic routing candidates behind a RALF-compatible artifact seam.

This vertical slice implements multi-layer, multi-terminal rectilinear routing,
legal via transitions, and deterministic contact landings for non-metal pin
islands.  It intentionally produces the existing route-spec contract and never
talks to Virtuoso.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import importlib.util
import json
import math
import types
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROUTE_SPEC = importlib.util.spec_from_file_location("analog_layout_route_intent", HERE / "route_intent.py")
ROUTE = importlib.util.module_from_spec(ROUTE_SPEC)
assert ROUTE_SPEC.loader is not None
ROUTE_SPEC.loader.exec_module(ROUTE)


def _load_helper(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEARCH = _load_helper("routing_search")
TREE = _load_helper("routing_tree")
BACKEND_IMPL = _load_helper("routing_backend")


def _module_api():
    return types.SimpleNamespace(**globals())

REQUEST_SCHEMA = "analog-layout-route.plan-request/v1"
OBSTACLE_SCHEMA = "analog-layout-route.obstacles/v1"
CANDIDATE_SCHEMA = "analog-layout-route.plan-candidates/v1"
BACKEND = "ralf-adapter-prototype/v1"
NET_CLASSES = {"ordinary", "power", "ground", "high_current", "sensitive", "high_impedance", "differential", "matched", "feedback", "bias", "output"}
COUPLED_STRATEGIES = {"common_centroid_columns", "mirror_guided", "rotate180_guided", "partial_mirror_guided"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def unconditional_floor(rules: list[dict[str, Any]], label: str) -> float:
    values = [float(rule["value"]) for rule in rules if isinstance(rule.get("value"), (int, float)) and not rule.get("parameters")]
    if not values:
        raise ValueError(f"{label} has no unconditional scalar rule")
    return max(values)


def snap(value: float, grid: float) -> float:
    return round(round(float(value) / grid) * grid, 12)


def snap_down(value: float, grid: float) -> float:
    return round(math.floor((float(value) + 1e-12) / grid) * grid, 12)


def snap_up(value: float, grid: float) -> float:
    return round(math.ceil((float(value) - 1e-12) / grid) * grid, 12)


def probe_ralf_source(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"available": False, "mode": "compatibility-kernel", "reason": "--ralf-root was not supplied"}
    names = ["WirePlanning.py", "PlanningGraph.py", "Router.py", "Obstacles.py"]
    files = [root / "Routing_v2" / name for name in names]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise ValueError(f"RALF source tree is incomplete: {missing}")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return {
        "available": True,
        "mode": "compatibility-kernel",
        "root": str(root.resolve()),
        "routing_core_sha256": digest.hexdigest(),
        "note": "Upstream is fingerprinted but not imported: its runtime is coupled to MagicDie, global_pdk, RALF Net objects, and rtree.",
    }


def validate_sources(profile: dict[str, Any], access: dict[str, Any], obstacles: dict[str, Any], request: dict[str, Any]) -> None:
    errors: list[str] = []
    if request.get("schema") != REQUEST_SCHEMA:
        errors.append("unsupported plan-request schema")
    if obstacles.get("schema") != OBSTACLE_SCHEMA:
        errors.append("unsupported obstacles schema")
    expected_fp = ROUTE.fingerprint(profile) if all(key in profile for key in ROUTE.FP_KEYS) else ""
    actual_fp = profile.get("fingerprint", {}).get("value")
    if expected_fp != actual_fp:
        errors.append("profile fingerprint mismatch")
    if not profile.get("coverage", {}).get("basic_routing_ready"):
        errors.append("profile is not basic-routing-ready")
    if not profile.get("boundaries", {}).get("may_drive_automatic_routing"):
        errors.append("profile may not drive automatic routing")
    if request.get("target") != access.get("target") or obstacles.get("target") != access.get("target"):
        errors.append("request/obstacles/terminal-access target mismatch")
    sources = obstacles.get("sources", {})
    if sources.get("profile_fingerprint") != actual_fp:
        errors.append("obstacle profile fingerprint drift")
    if sources.get("terminal_access_sha256") != ROUTE.digest(access):
        errors.append("obstacle terminal-access hash drift")
    requested_sources = request.get("sources", {})
    if requested_sources.get("profile_fingerprint") not in (None, actual_fp):
        errors.append("request profile fingerprint drift")
    if requested_sources.get("terminal_access_sha256") not in (None, ROUTE.digest(access)):
        errors.append("request terminal-access hash drift")
    if requested_sources.get("obstacles_sha256") not in (None, ROUTE.digest(obstacles)):
        errors.append("request obstacle hash drift")
    if errors:
        raise ValueError("; ".join(errors))


def terminal_islands(instance: str, terminal: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    return data.get("pin_islands") or [{
        "id": f"{instance}:{terminal}:legacy",
        "candidate_centers": data.get("candidate_centers", []),
        "selected_center": data.get("selected_center"),
        "access_layers": data.get("access_layers", []),
    }]


def via_catalog(profile: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in profile.get("vias", []):
        lower, upper = item.get("layer1"), item.get("layer2")
        if item.get("name") and lower and upper and item.get("standard_geometry"):
            result.append({"name": item["name"], "lower": lower, "upper": upper, "geometry": item["standard_geometry"]})
    return sorted(result, key=lambda item: item["name"])


def resolve_terminal(
    access: dict[str, Any], raw: dict[str, Any], layers: list[str], vias: list[dict[str, Any]], grid: float
) -> dict[str, Any]:
    instances = {item["name"]: item for item in access.get("instances", [])}
    instance_name, terminal_name = raw.get("instance"), raw.get("terminal")
    instance = instances.get(instance_name)
    terminal = instance.get("terminals", {}).get(terminal_name) if instance else None
    if not terminal:
        raise ValueError(f"terminal not found: {instance_name}/{terminal_name}")
    island_id = raw.get("pin_island_id")
    islands = terminal_islands(str(instance_name), str(terminal_name), terminal)
    matches = [item for item in islands if item.get("id") == island_id] if island_id else islands
    if len(matches) != 1:
        raise ValueError(f"terminal {instance_name}/{terminal_name} requires one explicit pin_island_id")
    island = matches[0]
    access_layers = list(island.get("access_layers", []))
    direct = next((layer for layer in layers if layer in access_layers), None)
    contact = None
    if direct is None:
        choices = []
        for via in vias:
            for source, target in ((via["lower"], via["upper"]), (via["upper"], via["lower"])):
                if source in access_layers and target in layers:
                    choices.append((layers.index(target), via["name"], source, target))
        if not choices:
            raise ValueError(
                f"terminal {instance_name}/{terminal_name}/{island.get('id')} has neither direct access nor a legal contact into {layers}"
            )
        _, via_name, source_layer, direct = sorted(choices)[0]
        contact = {"source_layer": source_layer, "via": via_name}
    candidates = island.get("candidate_centers", [])
    requested_xy = raw.get("xy_um")
    xy = requested_xy or island.get("selected_center") or (candidates[0] if candidates else None)
    if not isinstance(xy, list) or len(xy) != 2:
        raise ValueError(f"terminal {instance_name}/{terminal_name}/{island.get('id')} has no candidate center")
    xy = [snap(xy[0], grid), snap(xy[1], grid)]
    snapped_candidates = [[snap(point[0], grid), snap(point[1], grid)] for point in candidates]
    if xy not in snapped_candidates:
        raise ValueError(f"terminal access {xy} is not a candidate for {island.get('id')}")
    return {
        "instance": instance_name,
        "terminal": terminal_name,
        "pin_island_id": island.get("id"),
        "xy_um": xy,
        "pin_xy_um": xy,
        "route_layer": direct,
        "contact": contact,
    }


def legalize_contact_escape(
    terminal: dict[str, Any], raw_obstacles: list[dict[str, Any]], net: str,
    width: float, spacing: float, bounds: list[list[float]], grid: float,
    landing_half_um: tuple[float, float] | None = None,
) -> None:
    """Move a contact target beyond the complete landing envelope of nearby obstacles."""
    if not terminal.get("contact"):
        return
    layer = terminal["route_layer"]
    half_x, half_y = landing_half_um or (width / 2, width / 2)
    margin_x, margin_y = max(width / 2, half_x) + spacing, max(width / 2, half_y) + spacing
    rects = []
    for item in raw_obstacles:
        if item.get("hard", True) is False or item.get("layer") != layer or item.get("net") == net:
            continue
        bbox = item.get("bbox_um")
        if not isinstance(bbox, list) or len(bbox) != 2:
            continue
        rects.append((snap_down(bbox[0][0]-margin_x, grid), snap_down(bbox[0][1]-margin_y, grid),
                      snap_up(bbox[1][0]+margin_x, grid), snap_up(bbox[1][1]+margin_y, grid)))
    pin = (terminal["pin_xy_um"][0], terminal["pin_xy_um"][1])
    if not point_blocked(pin, rects):
        return
    candidates = {(pin[0], pin[1])}
    for x0, y0, x1, y1 in rects:
        if x0 < pin[0] < x1 and y0 < pin[1] < y1:
            candidates.update(((x0, pin[1]), (x1, pin[1]), (pin[0], y0), (pin[0], y1)))

    # A pin can sit inside a chain of overlapping expanded obstacles.  The
    # nearest boundary of one member may still lie inside another member, so
    # first-order candidates alone incorrectly report NO_LEGAL_ACCESS.  Merge
    # the fixed-axis interval component containing the pin and also try the
    # outer boundary of that complete union.  Candidates remain Manhattan
    # aligned with the source pin, preserving the contact-extension contract.
    def union_boundaries(axis: int) -> tuple[float, float] | None:
        fixed_axis = 1 - axis
        fixed = pin[fixed_axis]
        intervals = []
        for x0, y0, x1, y1 in rects:
            bounds_by_axis = ((x0, x1), (y0, y1))
            fixed_lo, fixed_hi = bounds_by_axis[fixed_axis]
            if fixed_lo < fixed < fixed_hi:
                intervals.append(bounds_by_axis[axis])
        low = high = pin[axis]
        changed = True
        while changed:
            changed = False
            for start, end in intervals:
                if start <= high and end >= low:
                    new_low, new_high = min(low, start), max(high, end)
                    if new_low != low or new_high != high:
                        low, high, changed = new_low, new_high, True
        return (low, high) if low != high else None

    horizontal = union_boundaries(0)
    vertical = union_boundaries(1)
    if horizontal:
        candidates.update(((horizontal[0], pin[1]), (horizontal[1], pin[1])))
    if vertical:
        candidates.update(((pin[0], vertical[0]), (pin[0], vertical[1])))
    candidates = {
        point for point in candidates
        if bounds[0][0] <= point[0] <= bounds[1][0] and bounds[0][1] <= point[1] <= bounds[1][1]
        and not point_blocked(point, rects)
    }
    if not candidates:
        raise ValueError(f"no legal contact escape for {terminal['pin_island_id']} on {layer}")
    chosen = min(candidates, key=lambda point: (abs(point[0] - pin[0]) + abs(point[1] - pin[1]), point[0], point[1]))
    terminal["xy_um"] = [chosen[0], chosen[1]]


def expanded_obstacles(
    raw_obstacles: list[dict[str, Any]], layer: str, net: str, width: float, spacing: float, grid: float
) -> list[tuple[float, float, float, float]]:
    result = []
    margin = width / 2 + spacing
    for item in raw_obstacles:
        if item.get("hard", True) is False or item.get("layer") != layer or item.get("net") == net:
            continue
        bbox = item.get("bbox_um")
        if not isinstance(bbox, list) or len(bbox) != 2:
            raise ValueError(f"invalid obstacle bbox: {item.get('id')}")
        result.append((
            snap_down(float(bbox[0][0]) - margin, grid),
            snap_down(float(bbox[0][1]) - margin, grid),
            snap_up(float(bbox[1][0]) + margin, grid),
            snap_up(float(bbox[1][1]) + margin, grid),
        ))
    return sorted(set(result))


def point_blocked(point: tuple[float, float], rects: list[tuple[float, float, float, float]]) -> bool:
    x, y = point
    return any(x0 < x < x1 and y0 < y < y1 for x0, y0, x1, y1 in rects)


def segment_clear(a: tuple[float, float], b: tuple[float, float], rects: list[tuple[float, float, float, float]]) -> bool:
    if a[0] == b[0]:
        x, lo, hi = a[0], min(a[1], b[1]), max(a[1], b[1])
        return not any(x0 < x < x1 and max(lo, y0) < min(hi, y1) for x0, y0, x1, y1 in rects)
    if a[1] == b[1]:
        y, lo, hi = a[1], min(a[0], b[0]), max(a[0], b[0])
        return not any(y0 < y < y1 and max(lo, x0) < min(hi, x1) for x0, y0, x1, y1 in rects)
    return False


def compact(points: list[tuple[float, float]]) -> list[list[float]]:
    kept: list[tuple[float, float]] = []
    for point in points:
        if len(kept) >= 2:
            a, b = kept[-2], kept[-1]
            if (a[0] == b[0] == point[0]) or (a[1] == b[1] == point[1]):
                kept[-1] = point
                continue
        kept.append(point)
    return [[point[0], point[1]] for point in kept]


def astar_rectilinear(
    start: list[float], goals: list[list[float]], rects: list[tuple[float, float, float, float]],
    bounds: list[list[float]], grid: float,
) -> list[list[float]] | None:
    start_node = (snap(start[0], grid), snap(start[1], grid))
    goal_nodes = {(snap(goal[0], grid), snap(goal[1], grid)) for goal in goals}
    if point_blocked(start_node, rects) or any(point_blocked(goal, rects) for goal in goal_nodes):
        return None
    x0, y0 = bounds[0]; x1, y1 = bounds[1]
    xs = {snap(x0, grid), snap(x1, grid), start_node[0], *(goal[0] for goal in goal_nodes)}
    ys = {snap(y0, grid), snap(y1, grid), start_node[1], *(goal[1] for goal in goal_nodes)}
    for rx0, ry0, rx1, ry1 in rects:
        xs.update((rx0, rx1)); ys.update((ry0, ry1))
    xs = sorted(value for value in xs if x0 - 1e-12 <= value <= x1 + 1e-12)
    ys = sorted(value for value in ys if y0 - 1e-12 <= value <= y1 + 1e-12)
    x_index, y_index = {value: i for i, value in enumerate(xs)}, {value: i for i, value in enumerate(ys)}

    def heuristic(node: tuple[float, float]) -> float:
        return min(abs(node[0] - goal[0]) + abs(node[1] - goal[1]) for goal in goal_nodes)

    queue: list[tuple[float, float, tuple[float, float]]] = [(heuristic(start_node), 0.0, start_node)]
    distance = {start_node: 0.0}
    parent: dict[tuple[float, float], tuple[float, float]] = {}
    reached = None
    while queue:
        _, cost, node = heapq.heappop(queue)
        if cost != distance.get(node):
            continue
        if node in goal_nodes:
            reached = node
            break
        xi, yi = x_index[node[0]], y_index[node[1]]
        neighbors = []
        if xi: neighbors.append((xs[xi - 1], node[1]))
        if xi + 1 < len(xs): neighbors.append((xs[xi + 1], node[1]))
        if yi: neighbors.append((node[0], ys[yi - 1]))
        if yi + 1 < len(ys): neighbors.append((node[0], ys[yi + 1]))
        for nxt in sorted(neighbors):
            if point_blocked(nxt, rects) or not segment_clear(node, nxt, rects):
                continue
            new_cost = cost + abs(node[0] - nxt[0]) + abs(node[1] - nxt[1])
            if new_cost + 1e-12 < distance.get(nxt, math.inf):
                distance[nxt] = new_cost
                parent[nxt] = node
                heapq.heappush(queue, (new_cost + heuristic(nxt), new_cost, nxt))
    if reached is None:
        return None
    path = [reached]
    while path[-1] != start_node:
        path.append(parent[path[-1]])
    path.reverse()
    return compact(path)


def layer_adjacency(vias: list[dict[str, Any]], layers: list[str]) -> dict[str, list[tuple[str, str]]]:
    result = {layer: [] for layer in layers}
    for via in vias:
        lower, upper = via["lower"], via["upper"]
        if lower in result and upper in result:
            result[lower].append((upper, via["name"]))
            result[upper].append((lower, via["name"]))
    for layer in result:
        result[layer].sort()
    return result


def astar_layered(
    start, goals, rects_by_layer, bounds, adjacency, protected_xy, grid,
    via_cost, preferred_directions=None, off_direction_penalty=0.25,
    bend_cost_um=0.0, guidance=(), guide_weight=0.0, cost_regions=(),
):
    """Backward-compatible entry point; direction is tracked in the search state."""
    return SEARCH.directional_astar(
        _module_api(), start, goals, rects_by_layer, bounds, adjacency, protected_xy,
        grid, via_cost, preferred_directions, off_direction_penalty, bend_cost_um,
        guidance, guide_weight, cost_regions)


def split_layered_path(path: list[tuple[float, float, str]]) -> tuple[list[tuple[str, list[list[float]]]], list[tuple[float, float, str, str]]]:
    runs: list[tuple[str, list[list[float]]]] = []
    transitions: list[tuple[float, float, str, str]] = []
    layer = path[0][2]
    points: list[tuple[float, float]] = [(path[0][0], path[0][1])]
    for previous, current in zip(path, path[1:]):
        if previous[2] == current[2]:
            points.append((current[0], current[1]))
            continue
        if len(points) >= 2:
            runs.append((layer, compact(points)))
        transitions.append((current[0], current[1], previous[2], current[2]))
        layer = current[2]
        points = [(current[0], current[1])]
    if len(points) >= 2:
        runs.append((layer, compact(points)))
    return runs, transitions


def segment_touches(points: list[list[float]], xy: list[float], tolerance: float = 1e-12) -> bool:
    return any(ROUTE.on_segment(xy, a, b, tolerance) for a, b in zip(points, points[1:]))


def path_obstacles(points: list[list[float]], layer: str, net: str, width: float, serial: int) -> list[dict[str, Any]]:
    result = []
    half = width / 2
    for index, (a, b) in enumerate(zip(points, points[1:])):
        result.append({
            "id": f"planned/{serial}/{index}", "layer": layer, "net": net, "hard": True,
            "bbox_um": [[min(a[0], b[0]) - half, min(a[1], b[1]) - half], [max(a[0], b[0]) + half, max(a[1], b[1]) + half]],
        })
    return result


def tune_route_length(
    routes: list[dict[str, Any]], extra_length: float, raw_obstacles: list[dict[str, Any]],
    net: str, widths: dict[str, float], spacings: dict[str, float], bounds: list[list[float]], grid: float,
) -> float:
    """Insert one obstacle-aware rectangular trombone and return added length."""
    if extra_length <= grid / 2:
        return 0.0
    offset = snap(extra_length / 2, grid)
    if offset <= 0:
        return 0.0
    for route in routes:
        layer, points = route["layer"], route["points_um"]
        rects = expanded_obstacles(raw_obstacles, layer, net, widths[layer], spacings[layer], grid)
        for index, (a, b) in enumerate(zip(points, points[1:])):
            candidates = []
            if a[1] == b[1]:
                candidates = [([a[0], a[1] - offset], [b[0], b[1] - offset]), ([a[0], a[1] + offset], [b[0], b[1] + offset])]
            elif a[0] == b[0]:
                candidates = [([a[0] - offset, a[1]], [b[0] - offset, b[1]]), ([a[0] + offset, a[1]], [b[0] + offset, b[1]])]
            for p1, p2 in candidates:
                trial = [a, p1, p2, b]
                if any(not (bounds[0][0] <= p[0] <= bounds[1][0] and bounds[0][1] <= p[1] <= bounds[1][1]) for p in (p1, p2)):
                    continue
                if all(segment_clear(x, y, rects) and not point_blocked((y[0], y[1]), rects) for x, y in zip(trial, trial[1:])):
                    route["points_um"] = points[:index] + trial + points[index + 2:]
                    return 2 * offset
    raise ValueError(f"no obstacle-aware tuning corridor for {net}, requested extra length {extra_length}")


def synthesize_common_centroid_pair(
    profile: dict[str, Any], access: dict[str, Any], raw_obstacles: list[dict[str, Any]],
    first_request: dict[str, Any], second_request: dict[str, Any], matching: dict[str, Any],
    bounds: list[list[float]], grid: float, serial: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], int]:
    """Build complementary column-and-bus trees for a two-row, even-column common-centroid pair."""
    layer_rules = {item["layer"]: item for item in profile.get("routing_layers", [])}
    contact_layer = str(matching.get("contact_layer", "mt1"))
    bus_layer = str(matching.get("bus_layer", "mt2"))
    if contact_layer not in layer_rules or bus_layer not in layer_rules:
        raise ValueError("common-centroid pair strategy requires declared contact_layer and bus_layer")
    distance = float(matching.get("contact_escape_um", 0))
    stub = float(matching.get("landing_stub_um", 0))
    clearance = float(matching.get("bus_clearance_um", 0))
    if min(distance, stub, clearance) <= 0:
        raise ValueError("common-centroid pair strategy requires positive contact_escape_um, landing_stub_um, and bus_clearance_um")
    widths, spacings = {}, {}
    for layer in (contact_layer, bus_layer):
        rules = layer_rules[layer]
        widths[layer] = unconditional_floor(rules.get("minimum_width_rules", []), f"{layer} minimum width")
        spacings[layer] = unconditional_floor(rules.get("minimum_spacing_rules", []), f"{layer} minimum spacing")
    catalog = via_catalog(profile)
    transition = next((via for via in catalog if {via["lower"], via["upper"]} == {contact_layer, bus_layer}), None)
    if transition is None:
        raise ValueError(f"no normalized via connects {contact_layer} and {bus_layer}")

    pair_data = []
    for request in (first_request, second_request):
        net = str(request["net"])
        terminals = [resolve_terminal(access, item, [contact_layer], catalog, grid) for item in request.get("terminals", [])]
        if len(terminals) < 4 or len(terminals) % 4 or any(not terminal.get("contact") for terminal in terminals):
            raise ValueError(f"{net}: common-centroid pair strategy requires 4N contact-backed physical islands")
        xs = sorted({terminal["pin_xy_um"][0] for terminal in terminals})
        ys = sorted({terminal["pin_xy_um"][1] for terminal in terminals})
        if len(xs) < 2 or len(xs) % 2 or len(ys) != 2 or len(terminals) != len(xs) * len(ys):
            raise ValueError(f"{net}: terminals are not a complete two-row, even-column access grid")
        pair_data.append({"net": net, "request": request, "terminals": terminals, "xs": xs, "ys": ys, "span": xs[-1] - xs[0]})
    if pair_data[0]["ys"] != pair_data[1]["ys"]:
        raise ValueError("common-centroid pair rows are not aligned")
    center0 = sum(pair_data[0]["xs"]) / len(pair_data[0]["xs"])
    center1 = sum(pair_data[1]["xs"]) / len(pair_data[1]["xs"])
    if abs(center0 - center1) > grid / 2:
        raise ValueError("common-centroid pair columns do not share a symmetry axis")
    inner, outer = sorted(pair_data, key=lambda item: (item["span"], item["net"]))
    if abs(inner["span"] - outer["span"]) <= grid / 2:
        raise ValueError("common-centroid pair strategy needs distinct inner and outer column spans")

    routes: list[dict[str, Any]] = []
    placed_vias: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    geometries: dict[str, dict[str, Any]] = {}
    ymin, ymax = inner["ys"]
    ycenter = (ymin + ymax) / 2
    for data in pair_data:
        net = data["net"]
        is_inner = data is inner
        bus_y = snap(ymin - clearance if is_inner else ymax + clearance, grid)
        exits = []
        for index, terminal in enumerate(data["terminals"]):
            pin_x, pin_y = terminal["pin_xy_um"]
            side = -1 if pin_x < center0 else 1
            move = side if is_inner else -side
            contact_xy = [snap(pin_x + move * distance, grid), pin_y]
            terminal["xy_um"] = contact_xy
            # A verified PCell access escape may pass the owning device's other
            # terminal figures; those figures are not arbitrary PCell blockage.
            local_obstacles = [
                item for item in raw_obstacles
                if not str(item.get("id", "")).startswith(f"pin/{terminal['instance']}/")
            ]
            rects = expanded_obstacles(local_obstacles, contact_layer, net, widths[contact_layer], spacings[contact_layer], grid)
            if point_blocked((contact_xy[0], contact_xy[1]), rects):
                raise ValueError(f"{net}: paired contact escape is blocked for {terminal['pin_island_id']}")
            stub_end = [snap(contact_xy[0] - move * stub, grid), contact_xy[1]]
            if not segment_clear(tuple(contact_xy), tuple(stub_end), rects):
                raise ValueError(f"{net}: paired contact landing stub is blocked for {terminal['pin_island_id']}")
            routes.append({
                "id": f"{net}_pair_stub_{index}", "net": net, "layer": contact_layer, "purpose": "drawing",
                "width_um": widths[contact_layer], "points_um": [contact_xy, stub_end], "access": [],
            })
            contacts.append({
                "id": f"{net}_pair_contact_{index}", "net": net, "instance": terminal["instance"],
                "terminal": terminal["terminal"], "pin_island_id": terminal["pin_island_id"],
                "pin_xy_um": terminal["pin_xy_um"], "source_layer": terminal["contact"]["source_layer"],
                "via": terminal["contact"]["via"], "xy_um": contact_xy,
            })
            placed_vias.append({
                "id": f"{net}_pair_via_{index}", "net": net, "via": transition["name"], "xy_um": contact_xy,
            })
            exits.append(contact_xy)
        columns = sorted({point[0] for point in exits})
        if len(columns) < 2 or len(columns) % 2:
            raise ValueError(f"{net}: paired contact escapes did not preserve an even column count")
        geometries[net] = {"data": data, "bus_y": bus_y, "columns": columns, "exits": exits}

    # Span the complete union of escaped columns.  An adjacent-column pitch
    # creates an equal-length but electrically disconnected bus.
    bus_left = snap(min(min(geometry["columns"]) for geometry in geometries.values()), grid)
    bus_right = snap(max(max(geometry["columns"]) for geometry in geometries.values()), grid)
    common_span = bus_right - bus_left
    metrics = {}
    for net, geometry in geometries.items():
        bus_y, columns = geometry["bus_y"], geometry["columns"]
        start_y = ymax if bus_y < ycenter else ymin
        rects = expanded_obstacles(raw_obstacles, bus_layer, net, widths[bus_layer], spacings[bus_layer], grid)
        pair_routes = []
        for index, x in enumerate(columns):
            points = [[x, start_y], [x, bus_y]]
            if not segment_clear(tuple(points[0]), tuple(points[1]), rects):
                raise ValueError(f"{net}: paired vertical column {index} is blocked")
            pair_routes.append({
                "id": f"{net}_pair_column_{index}", "net": net, "layer": bus_layer, "purpose": "drawing",
                "width_um": widths[bus_layer], "points_um": points, "access": [],
            })
        bus_points = [[bus_left, bus_y], [bus_right, bus_y]]
        if not segment_clear(tuple(bus_points[0]), tuple(bus_points[1]), rects):
            raise ValueError(f"{net}: paired bus is blocked")
        pair_routes.append({
            "id": f"{net}_pair_bus", "net": net, "layer": bus_layer, "purpose": "drawing",
            "width_um": widths[bus_layer], "points_um": bus_points, "access": [],
        })
        routes.extend(pair_routes)
        vertical = len(columns) * abs(start_y - bus_y)
        actual = len(geometry["exits"]) * stub + vertical + common_span
        metrics[net] = {"length_um": round(actual, 12), "bends": 0, "vias": len(geometry["exits"]), "layers": [contact_layer, bus_layer], "paired_topology": True}

    # Validate pair-to-pair geometry as a unit before exposing it to later nets.
    temporary_spec = {
        "schema": ROUTE.SPEC_SCHEMA, "target": access["target"], "routes": routes,
        "vias": placed_vias, "contact_landings": contacts, "matching": [matching],
    }
    checked = ROUTE.build(profile, access, temporary_spec)
    if checked["decision"]["status"] != "READY_FOR_REVIEW":
        raise ValueError("paired topology failed route-intent preflight: " + "; ".join(checked["validation"]["errors"]))
    for route in routes:
        raw_obstacles.extend(path_obstacles(route["points_um"], route["layer"], route["net"], route["width_um"], serial))
        serial += 1
    return routes, placed_vias, contacts, metrics, serial


def plan(
    profile: dict[str, Any], access: dict[str, Any], obstacles: dict[str, Any], request: dict[str, Any],
    ralf_root: Path | None = None,
) -> dict[str, Any]:
    validate_sources(profile, access, obstacles, request)
    grid = float(profile["manufacturing_grid_um"])
    layer_rules = {item["layer"]: item for item in profile.get("routing_layers", [])}
    bounds = obstacles.get("bounds_um")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("obstacles bounds_um is required")
    raw_obstacles = list(obstacles.get("obstacles", []))
    preferred=ROUTE.preferred_directions(profile,request)
    catalog = via_catalog(profile)
    routes: list[dict[str, Any]] = []
    placed_vias: list[dict[str, Any]] = []
    contact_landings: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    serial = 0
    ordered_requests = list(request.get("nets", []))
    if request.get("reserve_matched_pairs_first"):
        pair_heads = [
            str(item.get("first_net")) for item in request.get("matching", [])
            if item.get("strategy") in COUPLED_STRATEGIES
        ]
        rank = {net: index for index, net in enumerate(pair_heads)}
        ordered_requests.sort(key=lambda item: (0, rank[str(item.get("net"))]) if str(item.get("net")) in rank else (1, 0))
    net_requests = {str(item.get("net", "")): item for item in ordered_requests}
    if len(net_requests)!=len(ordered_requests) or "" in net_requests:
        failures.append({"reason": "plan request contains duplicate or empty net names"})
    pair_members: dict[str, dict[str, Any]] = {}
    for pair in request.get("matching", []):
        first,second=str(pair.get("first_net", "")),str(pair.get("second_net", ""))
        strategy=pair.get("strategy")
        if not first or not second or first==second:
            failures.append({"net":f"{first}/{second}","reason":"matching requires two distinct non-empty net names"}); continue
        if first not in net_requests or second not in net_requests:
            failures.append({"net":f"{first}/{second}","reason":"matching references a missing net request"}); continue
        if first in pair_members or second in pair_members:
            failures.append({"net":f"{first}/{second}","reason":"a net may belong to only one coupled matching rule"}); continue
        if strategy not in COUPLED_STRATEGIES:
            failures.append({"net":f"{first}/{second}","reason":f"matched nets require a supported coupled strategy {sorted(COUPLED_STRATEGIES)}; independent routing and post-route length tuning are forbidden"}); continue
        required_parameters = ({"contact_layer","bus_layer","contact_escape_um","landing_stub_um","bus_clearance_um"}
                               if strategy == "common_centroid_columns" else {"pin_pairs"})
        if strategy != "common_centroid_columns":
            transform = pair.get("transform", "rotate_180" if strategy == "rotate180_guided" else "mirror_x")
            required_parameters |= {"axis_x_um", "axis_y_um"} if transform == "rotate_180" else {"axis_um"}
        missing=sorted(required_parameters-set(pair))
        if missing:
            failures.append({"net":f"{first}/{second}","reason":f"{strategy} requires explicit parameters {missing}"}); continue
        pair_members[first]=pair; pair_members[second]=pair
    if request.get("matching") and not request.get("reserve_matched_pairs_first"):
        failures.append({"reason":"matching requires reserve_matched_pairs_first=true"})
    for net,item in net_requests.items():
        net_class=item.get("net_class")
        if net_class is None:
            failures.append({"net":net,"reason":"net_class is required; do not let analog-critical nets fall back to ordinary routing"}); continue
        net_class=str(net_class)
        if net_class not in NET_CLASSES:
            failures.append({"net":net,"reason":f"unsupported net_class {net_class!r}"})
        if net_class in {"differential","matched"} and net not in pair_members:
            failures.append({"net":net,"reason":f"{net_class} net requires a coupled matching rule"})
        if net_class in {"sensitive","high_impedance","differential","matched","feedback"} and item.get("max_detour_ratio") is None and item.get("max_bbox_excursion_um") is None:
            failures.append({"net":net,"reason":f"{net_class} net requires max_detour_ratio or max_bbox_excursion_um"})
        if net in pair_members and net_class not in {"differential","matched"}:
            failures.append({"net":net,"reason":"a coupled matching rule requires net_class differential or matched"})
        if net in pair_members and item.get("target_length_um") is not None:
            failures.append({"net":net,"reason":"target_length_um is forbidden on a matched net; tune both branches inside the coupled strategy"})
    if failures:
        ordered_requests=[]
    paired_done: set[str] = set()
    for net_request in ordered_requests:
        net = str(net_request.get("net", ""))
        if net in paired_done:
            continue
        pair_rule = next((
            item for item in request.get("matching", [])
            if item.get("strategy") in COUPLED_STRATEGIES
            and net in (item.get("first_net"), item.get("second_net"))
        ), None)
        if pair_rule is not None:
            first, second = str(pair_rule.get("first_net")), str(pair_rule.get("second_net"))
            if first not in net_requests or second not in net_requests:
                failures.append({"net": net, "reason": "paired topology references a missing net request"})
                paired_done.update((first, second))
                continue
            try:
                if pair_rule["strategy"] == "common_centroid_columns":
                    pair_routes, pair_vias, pair_contacts, pair_metrics, serial = synthesize_common_centroid_pair(
                        profile, access, raw_obstacles, net_requests[first], net_requests[second],
                        pair_rule, bounds, grid, serial)
                else:
                    defaults = {key:request[key] for key in ("bend_cost_um", "via_cost_um", "off_direction_penalty",
                                "access_candidate_limit", "access_beam_width", "topology_frontier_limit", "shared_tree", "metal_area_weight") if key in request}
                    pair_routes, pair_vias, pair_contacts, pair_metrics = BACKEND_IMPL.route_coupled_pair(
                        _module_api(), profile, access, raw_obstacles, {**defaults, **net_requests[first]},
                        {**defaults, **net_requests[second]}, pair_rule, bounds, grid, preferred)
                    for member in (first, second):
                        BACKEND_IMPL.reserve_geometry(_module_api(), profile, raw_obstacles,
                            [r for r in pair_routes if r["net"] == member],
                            [v for v in pair_vias + pair_contacts if v["net"] == member], net_requests[member])
                routes.extend(pair_routes)
                placed_vias.extend(pair_vias)
                contact_landings.extend(pair_contacts)
                metrics.update(pair_metrics)
            except (ValueError, KeyError, TypeError) as exc:
                failures.append({"net": f"{first}/{second}", "code": getattr(exc, "code", "INVALID_PAIR"), "reason": str(exc)})
            paired_done.update((first, second))
            continue
        layers = net_request.get("layers") or [net_request.get("layer")]
        layers = [str(layer) for layer in layers if layer]
        if not net or not layers or any(layer not in layer_rules for layer in layers):
            failures.append({"net": net, "reason": f"unknown net or routing layers {layers!r}"})
            continue
        net_class=str(net_request.get("net_class", "ordinary"))
        if net_class in {"power","ground","high_current"}:
            if net_request.get("width_um") is None and not net_request.get("widths_um"):
                failures.append({"net":net,"reason":f"{net_class} net requires explicit width from current/IR/EM analysis"}); continue
            if not str(net_request.get("width_basis", "")).strip():
                failures.append({"net":net,"reason":f"{net_class} net requires width_basis"}); continue
        if net_class in {"sensitive","high_impedance","differential","matched","feedback"} and net_request.get("max_detour_ratio") is None and net_request.get("max_bbox_excursion_um") is None:
            failures.append({"net":net,"reason":f"{net_class} net requires max_detour_ratio or max_bbox_excursion_um"}); continue
        try:
            effective = {**{key: request[key] for key in (
                "bend_cost_um", "via_cost_um", "off_direction_penalty",
                "access_candidate_limit", "access_beam_width", "topology_frontier_limit", "shared_tree", "metal_area_weight") if key in request}, **net_request}
            net_routes, net_vias, net_contacts, net_metrics = BACKEND_IMPL.route_net(
                _module_api(), profile, access, raw_obstacles, effective, bounds, grid, preferred)
            routes.extend(net_routes)
            placed_vias.extend(net_vias)
            contact_landings.extend(net_contacts)
            metrics[net] = net_metrics
            BACKEND_IMPL.reserve_geometry(_module_api(), profile, raw_obstacles,
                                          net_routes, net_vias + net_contacts, effective)
        except (ValueError, KeyError, TypeError) as exc:
            failures.append({"net": net, "code": getattr(exc, "code", "INVALID_REQUEST"), "reason": str(exc)})
    spec = {
        "schema": ROUTE.SPEC_SCHEMA,
        "target": request["target"],
        "required_nets": sorted(net_requests),
        "routes": routes,
        "vias": placed_vias,
        "contact_landings": contact_landings,
        "terminal_waivers": request.get("terminal_waivers", []),
        "matching": request.get("matching", []),
        "symmetry_groups": request.get("symmetry_groups", []),
        "preferred_directions": preferred,
        "planning_evidence": {
            "obstacles_sha256": request.get("sources",{}).get("obstacles_sha256"),
            "obstacle_coverage": obstacles.get("coverage",{}),
            "offline_obstacle_review": request.get("offline_obstacle_review"),
        },
        "net_constraints": [{key:value for key,value in item.items() if key in {"net","net_class","max_detour_ratio","max_bends","max_bbox_excursion_um","width_basis"}} for item in ordered_requests],
    }
    preflight = ROUTE.build(profile, access, spec)
    rule_coverage = {
        "normalized_via_envelope_vs_supplied_obstacles": "checked_for_mst_and_guided_strategies",
        "width_spacing_rules": "conservative_maximum_of_explicit_normalized_table",
        "parallel_run_length": "unknown", "end_of_line": "unknown",
        "conditional_cut_spacing": "unknown", "minimum_area": "unknown",
        "stacked_via_legality": "unknown", "environmental_parasitics": "unknown",
    }
    if not failures and preflight["decision"]["status"] != "READY_FOR_REVIEW":
        failures.append({
            "reason": "generated route spec failed authoritative route-intent preflight",
            "errors": preflight["validation"]["errors"],
        })
    for failure in failures:
        failure.setdefault("code", "PREFLIGHT_FAILED" if "preflight" in failure.get("reason", "") else "INVALID_REQUEST")
    breakdown = SEARCH.empty_cost()
    for net, item in metrics.items():
        parts = item.get("cost_breakdown")
        if parts is None:
            parts = SEARCH.empty_cost()
            via_cost = float(net_requests[net].get("via_cost_um", request.get("via_cost_um", 2.0)))
            bend_cost = float(net_requests[net].get("bend_cost_um", request.get("bend_cost_um", grid)))
            off_cost = float(net_requests[net].get("off_direction_penalty", request.get("off_direction_penalty", 0.25)))
            for route in routes:
                if route["net"] != net:
                    continue
                cost = SEARCH.evaluate_path([(*xy, route["layer"]) for xy in route["points_um"]],
                                            preferred, via_cost, bend_cost, off_cost)
                for key in parts:
                    parts[key] += cost[key]
            parts["via_penalty"] = item["vias"] * via_cost
            item["cost_breakdown"] = parts
            item["electrical_data_status"] = "unavailable"
        for key in breakdown:
            breakdown[key] += parts[key]
    breakdown = {key:round(value,12) for key,value in breakdown.items()}
    status = "PLANNED" if not failures else "BLOCKED"
    candidates = [] if failures else [{
        "id": "candidate_001", "status": "PLANNED", "route_spec": spec,
        "cost": round(sum(breakdown.values()), 12),
        "cost_breakdown": breakdown,
        "metrics": metrics,
        "rule_coverage": rule_coverage,
        "authoritative_preflight": {
            "status": preflight["decision"]["status"],
            "warnings": preflight["validation"]["warnings"] + [
                "Planner rule coverage remains unknown for PRL, EOL, conditional cut spacing, minimum area, stacked-via legality and environmental parasitics; foundry DRC/PEX required."],
        },
    }]
    return {
        "schema": CANDIDATE_SCHEMA,
        "backend": BACKEND,
        "status": status,
        "sources": {
            "profile_fingerprint": profile["fingerprint"]["value"],
            "terminal_access_sha256": ROUTE.digest(access),
            "obstacles_sha256": ROUTE.digest(obstacles),
            "request_sha256": ROUTE.digest(request),
            "ralf": probe_ralf_source(ralf_root),
        },
        "candidates": candidates,
        "failures": failures,
        "diagnostic_metrics": metrics,
        "diagnostic_route_spec": spec if failures else None,
        "limitations": [
            "Prototype uses a deterministic layered Hanan graph; it does not yet implement negotiated GCell congestion.",
            "Ordinary and guided routes check normalized via landing/cut envelopes against supplied obstacles; conditional cut spacing, EOL, PRL, minimum area, stack legality and full PCell geometry remain unknown until foundry verification.",
            "Guided pairs use explicit island correspondence and sequential reference/guidance search inside one checked transaction; simultaneous pair wavefront search, shielding synthesis, electromigration sizing and upstream RALF execution are not implemented.",
            "Access beam search, actual-cost shared-tree growth and current-weighted reparenting are bounded heuristics, not globally optimal Steiner routing. Physical pruning is disabled for current/matched/tuned trees. Environmental matching requires PEX.",
            "Planner output is not foundry DRC/LVS signoff and must pass route_intent.py build/validate.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    plan_parser = subs.add_parser("plan")
    for name in ("profile", "terminal-access", "obstacles", "request", "out"):
        plan_parser.add_argument("--" + name, required=True, type=Path)
    plan_parser.add_argument("--ralf-root", type=Path)
    export_parser = subs.add_parser("export")
    export_parser.add_argument("--candidates", required=True, type=Path)
    export_parser.add_argument("--candidate-id", required=True)
    export_parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        result = plan(load(args.profile), load(args.terminal_access), load(args.obstacles), load(args.request), args.ralf_root)
        dump(args.out, result)
        print(json.dumps({"status": result["status"], "candidates": len(result["candidates"]), "failures": result["failures"], "out": str(args.out.resolve())}, ensure_ascii=False))
        return 0 if result["status"] == "PLANNED" else 2
    candidates = load(args.candidates)
    matches = [item for item in candidates.get("candidates", []) if item.get("id") == args.candidate_id]
    if len(matches) != 1:
        raise ValueError(f"candidate not found or ambiguous: {args.candidate_id}")
    dump(args.out, matches[0]["route_spec"])
    print(json.dumps({"candidate": args.candidate_id, "out": str(args.out.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
