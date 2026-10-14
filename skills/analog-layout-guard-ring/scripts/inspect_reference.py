#!/usr/bin/env python3
"""Read a Virtuoso shortcut-built guard ring without changing its cellview."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()]+')


def parse_lisp(value: str):
    tokens = TOKEN.findall(value)
    pos = 0

    def one():
        nonlocal pos
        token = tokens[pos]
        pos += 1
        if token == "(":
            values = []
            while tokens[pos] != ")":
                values.append(one())
            pos += 1
            return values
        if token == "nil":
            return None
        if token == "t":
            return True
        if token.startswith('"'):
            return json.loads(token)
        try:
            return float(token)
        except ValueError:
            return token

    result = one()
    if pos != len(tokens):
        raise ValueError("Unparsed Virtuoso SKILL response")
    return result


def center(box):
    return [(box[0][axis] + box[1][axis]) / 2 for axis in (0, 1)]


def same_points(a, b, tolerance=1e-8):
    return len(a) == len(b) and all(abs(a[i][axis] - b[i][axis]) <= tolerance
                                    for i in range(len(a)) for axis in (0, 1))


def rectangular_centerline(points):
    if len(points) != 6 or not same_points([points[0]], [points[-1]]):
        return None
    xs = sorted(set(round(point[0], 9) for point in points))
    ys = sorted(set(round(point[1], 9) for point in points))
    if len(xs) != 3 or len(ys) != 2:
        return None
    if not (xs[0] < xs[1] < xs[2] and ys[0] < ys[1]):
        return None
    return [[xs[0], ys[0]], [xs[2], ys[1]]]


def on_ring(box, outline, width):
    x, y = center(box)
    x0, y0 = outline[0]
    x1, y1 = outline[1]
    tolerance = width / 2 + 1e-8
    return ((abs(x-x0) <= tolerance or abs(x-x1) <= tolerance) and y0-tolerance <= y <= y1+tolerance) or (
        (abs(y-y0) <= tolerance or abs(y-y1) <= tolerance) and x0-tolerance <= x <= x1+tolerance)


def extract(raw: list, source: dict) -> dict:
    paths = [{"lpp": entry[0], "points_um": entry[1], "width_um": entry[2], "bbox_um": entry[3]}
             for entry in raw[0] if entry]
    contacts = [{"lpp": entry[0], "bbox_um": entry[1]} for entry in raw[1] if entry]
    rings = []
    for path in paths:
        if path["lpp"] != ["thin", "drawing"]:
            continue
        outline = rectangular_centerline(path["points_um"])
        if outline is None:
            continue
        companions = [other for other in paths if same_points(other["points_um"], path["points_um"])]
        cuts = [cut for cut in contacts if on_ring(cut["bbox_um"], outline, path["width_um"])]
        sizes = sorted({(round(cut["bbox_um"][1][0]-cut["bbox_um"][0][0], 9),
                         round(cut["bbox_um"][1][1]-cut["bbox_um"][0][1], 9)) for cut in cuts})
        rings.append({"id": f"reference_ring_{len(rings)}", "centerline_bbox_um": outline,
                      "path_layers": [{"lpp": item["lpp"], "width_um": item["width_um"]}
                                      for item in companions],
                      "contact_lpp": ["cont", "drawing"], "contact_count": len(cuts),
                      "contact_sizes_um": [list(value) for value in sizes],
                      "contact_boxes_um": [cut["bbox_um"] for cut in cuts],
                      "polarity": "p_substrate" if any(x["lpp"][0] == "pplus" for x in companions)
                      else "n_well" if any(x["lpp"][0] == "nplus" for x in companions) else "unknown"})
    payload = {"schema": "analog-layout-guard-ring.reference-geometry/v1",
               "source": source,
               "method": "read-only top-level path/cont inspection; Shift+G maps to leHiCreateGuardRing() in this session",
               "qualification": "reference geometry only; not foundry DRC/LVS proof",
               "rings": rings}
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--lib", required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--view", default="layout")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from virtuoso_bridge import VirtuosoClient
    from virtuoso_bridge.env import set_runtime_env_file
    set_runtime_env_file(args.env)
    client = VirtuosoClient.from_env()
    ready = client.execute_skill("1+2")
    if not ready.ok:
        raise RuntimeError(ready.errors)
    for value in (args.lib, args.cell, args.view):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
            raise ValueError(f"Invalid Cadence identifier: {value}")
    expression = (
        f'let((cv out) cv=dbOpenCellViewByType("{args.lib}" "{args.cell}" "{args.view}" "maskLayout" "r") '
        'unless(cv error("reference cellview not found")) '
        'out=list('
        'foreach(mapcar s setof(s cv~>shapes s~>objType=="path" && length(s~>points)>=5) '
        'list(s~>lpp s~>points s~>width s~>bBox)) '
        'foreach(mapcar s setof(s cv~>shapes car(s~>lpp)=="cont") list(s~>lpp s~>bBox))) '
        'dbClose(cv) out)'
    )
    result = client.execute_skill(expression)
    if not result.ok:
        raise RuntimeError(result.errors)
    raw = parse_lisp(str(result.output))
    source = {"lib": args.lib, "cell": args.cell, "view": args.view,
              "raw_geometry_sha256": hashlib.sha256(str(result.output).encode()).hexdigest()}
    profile = extract(raw, source)
    if not profile["rings"]:
        raise ValueError("No closed thin-path guard-ring candidates found")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "rings": [{"id": ring["id"],
          "polarity": ring["polarity"], "contacts": ring["contact_count"],
          "layers": ring["path_layers"]} for ring in profile["rings"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
