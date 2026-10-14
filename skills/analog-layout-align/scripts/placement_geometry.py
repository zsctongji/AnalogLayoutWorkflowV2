"""Pure geometry and evidence-preserving pin projection for offline optimization."""
from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("expected a two-coordinate point")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError("nonfinite coordinate")
    return result


def box(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("expected bbox")
    a, b = map(point, value)
    if any(a[k] >= b[k] for k in (0, 1)):
        raise ValueError("nonpositive bbox")
    return [a, b]


def center(b):
    return [(b[0][k] + b[1][k]) / 2 for k in (0, 1)]


def distance(a, b):
    return sum(abs(a[k] - b[k]) for k in (0, 1))


def envelope(boxes):
    return [[min(b[0][k] for b in boxes) for k in (0, 1)],
            [max(b[1][k] for b in boxes) for k in (0, 1)]]


def overlap(a, b):
    return all(min(a[1][k], b[1][k]) > max(a[0][k], b[0][k]) + 1e-10 for k in (0, 1))


def area(b):
    return (b[1][0] - b[0][0]) * (b[1][1] - b[0][1])


def hpwl(points):
    return sum(max(p[k] for p in points) - min(p[k] for p in points) for k in (0, 1)) if points else 0.0


def transform(p, orientation):
    signs = {"R0": (1, 1), "MX": (1, -1), "MY": (-1, 1), "R180": (-1, -1)}
    if orientation not in signs:
        raise ValueError(f"unsupported orientation: {orientation}")
    return [p[k] * signs[orientation][k] for k in (0, 1)]


def project(p, old, new):
    local = transform([p[k] - old["origin"][k] for k in (0, 1)], old["orientation"])
    delta = transform(local, new["orientation"])
    return [round(delta[k] + new["origin"][k], 12) for k in (0, 1)]


def project_box(b, old, new):
    corners = [project(p, old, new) for p in b]
    return [[min(p[k] for p in corners) for k in (0, 1)], [max(p[k] for p in corners) for k in (0, 1)]]


def project_islands(parent, child, access, required_nets=None):
    """Keep each physical pin object; never relabel projected data as live access."""
    old = {i["name"]: i for i in parent["instances"]}
    new = {i["name"]: i for i in child["instances"]}
    live = {i["name"]: i for i in access.get("instances", [])}
    if len(live) != len(access.get("instances", [])) or set(old) != set(new) or set(old) != set(live):
        raise ValueError("parent/child/access instance identities differ")
    records = []
    for name in sorted(new):
        measured = live[name]
        for field in ("origin", "orientation"):
            if measured.get(field) != old[name].get(field):
                raise ValueError(f"stale live {field}: {name}")
        if measured.get("master") != old[name].get("pcell_master"):
            raise ValueError(f"stale live master: {name}")
        grid = parent["coordinate_contract"]["manufacturing_grid"]
        if "bbox" not in measured or any(abs(measured["bbox"][j][k] - old[name]["bbox"][j][k]) > grid + 1e-9 for j in (0, 1) for k in (0, 1)):
            raise ValueError(f"stale live bbox: {name}")
        for terminal, net in sorted(new[name].get("terminals", {}).items()):
            if required_nets is not None and net not in required_nets:
                continue
            data = measured.get("terminals", {}).get(terminal, {})
            if data.get("net") not in (None, net):
                raise ValueError(f"access net mismatch: {name}/{terminal}")
            islands = data.get("pin_islands")
            if islands is None:  # explicit legacy compatibility, no synthetic contact points
                islands = [{"id": f"{name}:{terminal}:legacy", "candidate_centers": data.get("candidate_centers", []),
                            "access_layers": data.get("access_layers", []), "figures": data.get("preferred_figures", [])}]
            if not islands:
                islands = [{"id": f"{name}:{terminal}:missing", "candidate_centers": []}]
            for island in islands:
                candidates = []
                figures = island.get("figures", island.get("preferred_figures", []))
                for xy in island.get("candidate_centers", []):
                    xy = point(xy)
                    layers = sorted({f["layer"] for f in figures if f.get("center") == xy}) or island.get("access_layers", [])
                    candidates.append({"xy": project(xy, old[name], new[name]), "layers": layers})
                records.append({"id": island["id"], "instance": name, "terminal": terminal, "net": net,
                                "candidates": candidates, "basis": "projected_parent_pin_island"})
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("duplicate pin island identity")
    return records


def obstacles_for(intent, constraints):
    result = [{"id": i["name"], "owner": i["name"], "layer": None, "bbox": i["bbox"], "basis": "conservative_PCell_bbox"}
              for i in intent["instances"]]
    for ob in constraints.get("obstacles", []):
        result.append({**ob, "bbox": box(ob["bbox"]), "basis": ob.get("basis", "project_obstacle")})
    return result


def segment_hits(a, b, rect):
    # Closed contact with obstacle is conservatively blocked.
    if a[1] == b[1]:
        return rect[0][1] <= a[1] <= rect[1][1] and max(min(a[0], b[0]), rect[0][0]) <= min(max(a[0], b[0]), rect[1][0])
    if a[0] == b[0]:
        return rect[0][0] <= a[0] <= rect[1][0] and max(min(a[1], b[1]), rect[0][1]) <= min(max(a[1], b[1]), rect[1][1])
    raise ValueError("non-Manhattan segment")


def expand(b, margin):
    return [[b[0][k] - margin for k in (0, 1)], [b[1][k] + margin for k in (0, 1)]]


def channels(intent):
    """Visible gaps between boxes, excluding intervening third boxes."""
    items = sorted(intent["instances"], key=lambda i: i["name"])
    result = []
    for a, b in combinations(items, 2):
        for across in (0, 1):
            along = 1 - across
            first, second = sorted((a, b), key=lambda i: i["bbox"][0][across])
            lo = first["bbox"][1][across]; hi = second["bbox"][0][across]
            bottom = max(a["bbox"][0][along], b["bbox"][0][along])
            top = min(a["bbox"][1][along], b["bbox"][1][along])
            if hi <= lo or top <= bottom:
                continue
            bb = [[0., 0.], [0., 0.]]
            bb[0][across], bb[1][across] = lo, hi
            bb[0][along], bb[1][along] = bottom, top
            if any(overlap(bb, i["bbox"]) for i in items if i not in (a, b)):
                continue
            result.append({"channel_id": f"{first['name']}|{second['name']}|{across}",
                           "members": [first["name"], second["name"]], "across_axis": across,
                           "orientation": "vertical" if across == 0 else "horizontal", "bbox": bb,
                           "width_um": hi - lo, "height_um": top - bottom, "basis": "PCell_bbox_gap"})
    return result
