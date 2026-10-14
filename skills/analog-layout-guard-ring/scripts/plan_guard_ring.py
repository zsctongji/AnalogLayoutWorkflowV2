#!/usr/bin/env python3
"""Plan a reference-shaped P+ substrate guard ring around selected ALIGN PCells."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from partition_modules import partition
from check_gate_access import check_gate_access


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snap_out(value: float, grid: float, upper: bool) -> float:
    quotient = value / grid
    return round((math.ceil if upper else math.floor)(quotient - (1e-9 if upper else -1e-9)) * grid, 9)


def overlaps(a, b, margin=0.0):
    return (a[0][0] < b[1][0] + margin and a[1][0] > b[0][0] - margin
            and a[0][1] < b[1][1] + margin and a[1][1] > b[0][1] - margin)


def bbox_union(boxes):
    return [[min(box[0][axis] for box in boxes) for axis in (0, 1)],
            [max(box[1][axis] for box in boxes) for axis in (0, 1)]]


def ring_points(box):
    x0, y0 = box[0]
    x1, y1 = box[1]
    xm = round((x0 + x1) / 2, 9)
    return [[xm, y1], [x1, y1], [x1, y0], [x0, y0], [x0, y1], [xm, y1]]


def sample_pitch(reference):
    box = reference["centerline_bbox_um"]
    centers = []
    for cut in reference["contact_boxes_um"]:
        x = (cut[0][0] + cut[1][0]) / 2
        y = (cut[0][1] + cut[1][1]) / 2
        if abs(y - box[0][1]) < 0.02 and box[0][0] + 1 < x < box[1][0] - 1:
            centers.append(x)
    steps = [b - a for a, b in zip(sorted(set(centers)), sorted(set(centers))[1:]) if b - a > 0.1]
    if len(steps) < 2:
        raise ValueError("Reference lacks enough regular contacts to infer a candidate pitch")
    return min(steps)


def make_contacts(box, size, pitch, grid, corner_inset):
    x0, y0 = box[0]
    x1, y1 = box[1]
    sites = []
    for fixed, low, high, horizontal in ((y0, x0, x1, True), (y1, x0, x1, True),
                                         (x0, y0, y1, False), (x1, y0, y1, False)):
        start = snap_out(low + corner_inset, grid, True)
        end = snap_out(high - corner_inset, grid, False)
        if start > end:
            raise ValueError("Ring side too short for a contact")
        count = math.floor((end - start) / pitch) + 1
        for index in range(count):
            moving = snap_out(start + index * pitch, grid, True)
            cx, cy = (moving, fixed) if horizontal else (fixed, moving)
            sites.append([[round(cx-size/2, 9), round(cy-size/2, 9)],
                          [round(cx+size/2, 9), round(cy+size/2, 9)]])
    return sites


def plan(intent, reference_profile, request, hashes, terminal_access=None, gate_review=None):
    if intent.get("schema") != "analog-layout-align.pcell-placement-intent/v2":
        raise ValueError("Requires legalized ALIGN placement intent v2")
    if request.get("schema") != "analog-layout-guard-ring.request/v1":
        raise ValueError("Unsupported request schema")
    checks = intent.get("validation", {})
    shared = intent.get("shared_diffusion_groups", [])
    if not checks.get("bbox_overlap_free") and not (
            shared and checks.get("shared_diffusion_complete") is True
            and checks.get("shared_diffusion_only_bbox_overlaps") is True):
        raise ValueError("ALIGN intent has unresolved bbox overlap")
    if intent.get("validation", {}).get("missing_instances"):
        raise ValueError("ALIGN intent has missing instances")
    if not request.get("reference_qualified_for_pdk"):
        raise ValueError("Explicit PDK recipe qualification is required; reference geometry alone is insufficient")
    if request.get("polarity") != "p_substrate":
        raise ValueError("This materializer currently supports P+ substrate rings only")
    rings = [item for item in reference_profile["rings"] if item["id"] == request.get("reference_ring_id")]
    if len(rings) != 1 or rings[0]["polarity"] != "p_substrate":
        raise ValueError("Select exactly one P+ substrate reference ring")
    reference = rings[0]
    layers = {item["lpp"][0]: item["width_um"] for item in reference["path_layers"]}
    recipe=request.get("qualified_recipe", {})
    roles=recipe.get("layer_roles", {"active":"thin", "implant":"pplus", "metal":"mt1"})
    contact=recipe.get("contact_size_um", [0.45,0.45])
    if not all(roles.get(k) in layers for k in ("active","implant","metal")) or reference["contact_sizes_um"] != [contact]:
        raise ValueError("Reference ring cross-section is not supported by this adapter")
    if not isinstance(request.get("tie_net"), str) or not request["tie_net"].strip():
        raise ValueError("Specify a deliberate substrate tie net in request")
    if request.get("source") == request.get("target") or not request.get("source") or not request.get("target"):
        raise ValueError("Source and target must be distinct, explicit cellviews")
    names = request.get("instance_names")
    if not isinstance(names, list) or not names or len(names) != len(set(names)):
        raise ValueError("Provide unique, nonempty instance_names")
    instances = {item["name"]: item for item in intent["instances"]}
    if set(names) - set(instances):
        raise ValueError("Selected instance absent from ALIGN intent")
    domains = partition(intent, request.get('modules'))
    if domains['unresolved']:
        raise ValueError('Resolve all MOS module ownership and body nets before planning')
    owner = {name: index for index, domain in enumerate(domains['domains'])
             for name in domain['instance_names']}
    approved = {}
    for edge in shared:
        edge_names = edge.get('instances', [])
        evidence = edge.get('evidence', {})
        if (len(edge_names) != 2 or any(n not in owner for n in edge_names)
                or owner[edge_names[0]] != owner[edge_names[1]]):
            raise ValueError('Shared diffusion crosses module domains')
        if (edge.get('terminal') != 'S' or edge.get('axis') not in ('x', 'y')
                or not evidence.get('source_contact_overlap_verified')
                or not evidence.get('overlap_isolation_verified')
                or not evidence.get('pair_probe_sha256')):
            raise ValueError('Shared diffusion lacks contact/isolation evidence')
        approved[frozenset(edge_names)] = edge
    items = list(instances.values())
    for index, a in enumerate(items):
        for b in items[index+1:]:
            if not overlaps(a['bbox'], b['bbox']):
                continue
            edge = approved.get(frozenset((a['name'], b['name'])))
            if edge is None:
                raise ValueError('ALIGN intent has unresolved bbox overlap')
            axis = 0 if edge['axis'] == 'x' else 1
            depth = min(a['bbox'][1][axis], b['bbox'][1][axis]) - max(a['bbox'][0][axis], b['bbox'][0][axis])
            if abs(depth - float(edge['evidence'].get('expected_bbox_overlap_um', 0))) > 1e-8:
                raise ValueError('Shared diffusion overlap depth changed')
    matching = [d for d in domains['domains'] if set(d['instance_names']) == set(names)]
    if len(matching) != 1:
        raise ValueError('Each ring must enclose exactly one complete module domain; no cross-module merge')
    if matching[0]['tie_net'] != request['tie_net'] or matching[0]['polarity'] != request['polarity']:
        raise ValueError('Ring polarity/tie net conflicts with module body terminals')
    selected = [instances[name] for name in names]
    gate_check = check_gate_access(intent, terminal_access, gate_review, request['source'], names)
    if gate_check['status'] != 'GATE_ACCESS_EVIDENCE_COMPLETE':
        raise ValueError('BLOCKED_GATE_ACCESS: '+ '; '.join(gate_check['failures']))
    others = [item for name, item in instances.items() if name not in names]
    grid = float(intent["coordinate_contract"]["manufacturing_grid"])
    clearance = float(request["active_to_inner_edge_um"])
    if grid <= 0 or clearance <= 0:
        raise ValueError("Grid and clearance must be positive")
    recipe = request.get("qualified_recipe", {})
    if not recipe.get("pdk_id") or not recipe.get("rule_source"):
        raise ValueError("Qualified recipe must identify PDK and rule/generator provenance")
    pitch = float(recipe.get("contact_pitch_um", 0))
    min_pitch = sample_pitch(reference)
    if contact[0]!=contact[1] or contact[0]<=0:
        raise ValueError("This ring generator requires a positive qualified square contact")
    size = reference["contact_sizes_um"][0][0]
    if pitch <= 0 or pitch < min_pitch - grid or pitch < size:
        raise ValueError("Qualified contact pitch absent or below reference minimum")
    outer_half_width = max(layers.values()) / 2
    extent = bbox_union([item["bbox"] for item in selected] + gate_check['access_envelopes_um'])
    offset = clearance + outer_half_width
    box = [[snap_out(extent[0][axis] - offset, grid, False) for axis in (0, 1)],
           [snap_out(extent[1][axis] + offset, grid, True) for axis in (0, 1)]]
    exterior = [[box[0][axis] - outer_half_width for axis in (0, 1)],
                [box[1][axis] + outer_half_width for axis in (0, 1)]]
    interior = [[box[0][axis] + outer_half_width for axis in (0, 1)],
                [box[1][axis] - outer_half_width for axis in (0, 1)]]
    if any(not (interior[0][0] <= item["bbox"][0][0] and interior[0][1] <= item["bbox"][0][1]
                    and interior[1][0] >= item["bbox"][1][0] and interior[1][1] >= item["bbox"][1][1])
           for item in selected):
        raise ValueError("Ring does not enclose all selected PCells")
    if any(overlaps(item["bbox"], exterior, float(request.get("foreign_keepout_um", 0)))
           for item in others):
        raise ValueError("Unselected PCell lies inside or intersects proposed ring envelope")
    corner_inset = float(recipe.get("corner_contact_inset_um", 0))
    if corner_inset < outer_half_width + size / 2:
        raise ValueError("Corner contact inset does not clear path turn")
    contacts = make_contacts(box, size, pitch, grid, corner_inset)
    return {"schema": "analog-layout-guard-ring.plan/v1", "status": "PREFLIGHT_ONLY",
            "source_hashes": hashes, "source": request["source"], "target": request["target"],
            "reference": {"source": reference_profile["source"], "ring_id": reference["id"]},
            "polarity": "p_substrate", "tie_net_intent": request["tie_net"],
            "selected_instances": names, "centerline_bbox_um": box, "ring_envelope_um": exterior,
            "points_um": ring_points(box), "path_layers": reference["path_layers"],
            "contact_lpp": reference["contact_lpp"], "contact_boxes_um": contacts,
            "gate_access_check": gate_check,
            "checks": {"selected_count": len(selected), "foreign_count": len(others),
                       "contact_count": len(contacts), "clearance_um": clearance,
                       "reference_min_pitch_um": min_pitch, "qualified_pitch_um": pitch,
                       "requires_drc_lvs": True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("intent", "reference", "request", "out", "terminal-access", "gate-review"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    inputs = {name: getattr(args, name) for name in ("intent", "reference", "request", "terminal_access", "gate_review")}
    data = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in inputs.items()}
    result = plan(data["intent"], data["reference"], data["request"],
                  {name: digest(path) for name, path in inputs.items()}, data['terminal_access'], data['gate_review'])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "status": result["status"],
                      "contacts": len(result["contact_boxes_um"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
