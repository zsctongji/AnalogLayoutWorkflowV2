#!/usr/bin/env python3
"""Compare a route intent with read-only reference-layout evidence.

The comparison is deliberately policy-oriented.  Raw wirelength and via-count
deltas are suppressed unless placement equivalence is explicitly proven by the
caller; a visually similar or logically equivalent cell is not enough.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _metrics_map(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items() if isinstance(item, dict)}
    if isinstance(value, list):
        return {str(item["name"]): item for item in value if isinstance(item, dict) and "name" in item}
    return {}


def _fractions(lengths: dict[str, Any], total: float) -> dict[str, float]:
    if total <= 0:
        return {}
    return {str(layer): round(float(length) / total, 6) for layer, length in lengths.items()}


def _dominant_layer(fractions: dict[str, float]) -> str | None:
    return max(fractions, key=fractions.get) if fractions else None


def _terminal_footprint(terminal_access: dict[str, Any]) -> dict[str, Any] | None:
    points: list[tuple[float, float]] = []
    for net in terminal_access.get("nets", []):
        for terminal in net.get("terminals", []):
            xy = terminal.get("selected_center")
            if isinstance(xy, list) and len(xy) == 2:
                points.append((float(xy[0]), float(xy[1])))
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    bbox = [[min(xs), min(ys)], [max(xs), max(ys)]]
    return {"bbox_um": bbox, "span_um": [bbox[1][0] - bbox[0][0], bbox[1][1] - bbox[0][1]]}


def _reference_assignment(reference: dict[str, Any]) -> dict[str, Any]:
    counts = reference.get("route_object_counts", {})
    unassigned = reference.get("unassigned", {})
    kinds = ("paths", "rects", "polygons", "vias")
    per_kind = {
        kind: {"total": int(counts.get(kind, 0) or 0), "unassigned": int(unassigned.get(kind, 0) or 0)}
        for kind in kinds
    }
    considered = sum(item["total"] for item in per_kind.values())
    missed = sum(item["unassigned"] for item in per_kind.values())
    ratio = None if considered == 0 else round((considered - missed) / considered, 6)
    return {"per_kind": per_kind, "considered_route_objects": considered, "unassigned_route_objects": missed, "assigned_fraction": ratio}


def _target_widths(intent: dict[str, Any], net: str) -> dict[str, list[float]]:
    widths: dict[str, set[float]] = {}
    for route in intent.get("routes", []):
        if str(route.get("net")) != net:
            continue
        widths.setdefault(str(route.get("layer")), set()).add(float(route.get("width_um", 0.0)))
    return {layer: sorted(values) for layer, values in widths.items()}


def _pair_delta(metrics: dict[str, dict[str, Any]], first: str, second: str, route_key: str) -> dict[str, Any] | None:
    if first not in metrics or second not in metrics:
        return None
    a, b = metrics[first], metrics[second]
    layers = set(a.get("layer_lengths_um", {})) | set(b.get("layer_lengths_um", {}))
    return {
        "length_delta_um": round(abs(float(a.get("path_length_um", 0.0)) - float(b.get("path_length_um", 0.0))), 6),
        "via_delta": abs(int(a.get("via_count", 0)) - int(b.get("via_count", 0))),
        "route_count_delta": abs(int(a.get(route_key, 0)) - int(b.get(route_key, 0))),
        "max_per_layer_length_delta_um": round(max((abs(float(a.get("layer_lengths_um", {}).get(layer, 0.0)) - float(b.get("layer_lengths_um", {}).get(layer, 0.0))) for layer in layers), default=0.0), 6),
    }


def compare(
    intent: dict[str, Any],
    reference: dict[str, Any],
    terminal_access: dict[str, Any],
    route_spec: dict[str, Any] | None = None,
    placement_equivalent: bool = False,
) -> dict[str, Any]:
    route_spec = route_spec or {}
    target_metrics = _metrics_map(intent.get("net_metrics", {}))
    reference_metrics = _metrics_map(reference.get("net_metrics", {}))
    terminal_nets = _metrics_map(terminal_access.get("nets", []))
    classes = {str(item.get("net")): str(item.get("net_class", "unspecified")) for item in route_spec.get("net_constraints", [])}
    required = set(str(name) for name in intent.get("required_nets", target_metrics))
    reference_nets = set(reference_metrics)
    target_nets = set(target_metrics)

    per_net: list[dict[str, Any]] = []
    findings: list[dict[str, str]] = []
    for net in sorted(target_nets | reference_nets):
        tm = target_metrics.get(net, {})
        rm = reference_metrics.get(net, {})
        tlen = float(tm.get("path_length_um", 0.0) or 0.0)
        rlen = float(rm.get("path_length_um", 0.0) or 0.0)
        terminal_count = int(terminal_nets.get(net, {}).get("terminal_count", 0) or 0)
        tf = _fractions(tm.get("layer_lengths_um", {}), tlen)
        rf = _fractions(rm.get("layer_lengths_um", {}), rlen)
        target_vias = int(tm.get("via_count", 0) or 0)
        item: dict[str, Any] = {
            "net": net,
            "net_class": classes.get(net, "unspecified"),
            "target": {
                "length_um": tlen,
                "route_count": int(tm.get("route_count", 0) or 0),
                "via_count": target_vias,
                "bend_count": int(tm.get("bend_count", 0) or 0),
                "terminal_count": terminal_count,
                "detour_ratio": tm.get("detour_ratio"),
                "off_preference_ratio": tm.get("off_preference_ratio"),
                "layer_fractions": tf,
                "widths_um": _target_widths(intent, net),
                "vias_per_terminal": None if terminal_count == 0 else round(target_vias / terminal_count, 6),
                "routes_per_terminal": None if terminal_count == 0 else round(int(tm.get("route_count", 0) or 0) / terminal_count, 6),
            },
            "reference": {
                "length_um": rlen,
                "path_count": int(rm.get("path_count", 0) or 0),
                "via_count": int(rm.get("via_count", 0) or 0),
                "bend_count": int(rm.get("bend_count", 0) or 0),
                "closed_path_count": int(rm.get("closed_path_count", 0) or 0),
                "layer_fractions": rf,
                "widths_um": rm.get("widths_um", {}),
            },
            "policy_comparison": {
                "dominant_layer_match": _dominant_layer(tf) == _dominant_layer(rf) if tf and rf else None,
                "raw_length_delta_um": round(tlen - rlen, 6) if placement_equivalent else None,
                "raw_via_delta": target_vias - int(rm.get("via_count", 0) or 0) if placement_equivalent else None,
            },
        }
        per_net.append(item)

        net_class = classes.get(net)
        if net_class in {"power", "ground"} and int(rm.get("closed_path_count", 0) or 0) > 0:
            findings.append({"severity": "review", "net": net, "code": "REFERENCE_POWER_LOOP", "message": "Reference uses closed supply paths; compare ring/tree return-path and IR/EM behavior before adopting topology."})
        ref_widths = [float(width) for values in rm.get("widths_um", {}).values() for width in values]
        tgt_widths = [float(width) for values in item["target"]["widths_um"].values() for width in values]
        if net_class in {"power", "ground"} and ref_widths and tgt_widths and max(ref_widths) > max(tgt_widths):
            findings.append({"severity": "review", "net": net, "code": "POWER_WIDTH_BASIS", "message": "Reference uses materially wider supply metal; require current, IR-drop, EM, and via-array basis rather than copying either width."})
        if net_class == "bias" and float(tm.get("off_preference_ratio", 0.0) or 0.0) > 0.30:
            findings.append({"severity": "review", "net": net, "code": "BIAS_COLLECTION_TOPOLOGY", "message": "Target bias route has high off-preference exposure; review center/bilateral/shared-bus collection before length tuning."})

    matching_reports: list[dict[str, Any]] = []
    matching = route_spec.get("matching") or intent.get("matching")
    matching_items = matching if isinstance(matching, list) else ([matching] if isinstance(matching, dict) and matching else [])
    for rule in matching_items:
        first, second = str(rule.get("first_net", "")), str(rule.get("second_net", ""))
        if not first or not second:
            continue
        target_delta = _pair_delta(target_metrics, first, second, "route_count")
        reference_delta = _pair_delta(reference_metrics, first, second, "path_count")
        limits = {
            "length_delta_um": float(rule.get("max_length_delta_um", 0.0) or 0.0),
            "via_delta": int(rule.get("max_via_delta", 0) or 0),
            "route_count_delta": int(rule.get("max_route_count_delta", 0) or 0),
            "max_per_layer_length_delta_um": float(rule.get("max_per_layer_length_delta_um", 0.0) or 0.0),
        }
        reference_self_consistent = bool(reference_delta) and all(float(reference_delta[key]) <= float(limit) for key, limit in limits.items())
        matching_reports.append({
            "pair": [first, second], "limits": limits, "target_delta": target_delta,
            "reference_delta": reference_delta, "reference_self_consistent": reference_self_consistent,
            "reference_matching_transfer_allowed": reference_self_consistent,
        })
        if not reference_self_consistent:
            findings.append({"severity": "block_transfer", "net": f"{first}/{second}", "code": "REFERENCE_PAIR_NOT_MATCHED", "message": "Reference pair fails the target matching rule; do not transfer its pair geometry or asymmetry."})

    assignment = _reference_assignment(reference)
    reference_boundary = str(reference.get("boundary", ""))
    provenance_checks = {
        "required_net_set_complete": required <= reference_nets,
        "reference_extra_nets": sorted(reference_nets - required),
        "reference_missing_nets": sorted(required - reference_nets),
        "assignment": assignment,
        "reference_claims_signoff_or_equivalence": not any(word in reference_boundary.lower() for word in ("no drc", "no lvs", "no schematic-equivalence")),
    }
    raw_reason = "explicit placement-equivalence proof supplied" if placement_equivalent else "blocked: exact placement transform and terminal correspondence were not explicitly proven"
    return {
        "schema": "analog-layout-route.reference-comparison/v1",
        "target": intent.get("target"),
        "reference_target": reference.get("target"),
        "reference_quality_gate": provenance_checks,
        "placement_comparison": {
            "raw_geometry_comparison_allowed": placement_equivalent,
            "reason": raw_reason,
            "target_instance_count": terminal_access.get("intent_instance_count"),
            "reference_instance_count": reference.get("database_counts", {}).get("instances"),
            "target_terminal_footprint": _terminal_footprint(terminal_access),
            "reference_layout_bbox_um": reference.get("bbox_um"),
        },
        "per_net": per_net,
        "matching": matching_reports,
        "findings": findings,
        "transfer_policy": {
            "allowed": ["topology hypotheses", "layer-sequence hypotheses", "collection-style hypotheses"],
            "conditional": ["width classes after current/IR/EM proof", "matching style only when reference pair is self-consistent"],
            "blocked_without_additional_proof": ["absolute coordinates", "raw length/via ranking", "reference pin-island identities", "DRC/LVS/PEX claims"],
        },
    }


def markdown(report: dict[str, Any]) -> str:
    placement = report["placement_comparison"]
    lines = [
        "# Reference-layout comparison", "",
        f"- Target: `{report.get('target')}`",
        f"- Reference: `{report.get('reference_target')}`",
        f"- Raw geometry comparison: **{'allowed' if placement['raw_geometry_comparison_allowed'] else 'blocked'}** — {placement['reason']}",
        "", "## Per-net policy metrics", "",
        "| Net | Class | Target L/HPWL | Target vias/terminal | Off-dir | Target dominant | Reference dominant | Ref loops |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["per_net"]:
        target, reference = item["target"], item["reference"]
        tdom = _dominant_layer(target["layer_fractions"]) or "-"
        rdom = _dominant_layer(reference["layer_fractions"]) or "-"
        detour = target.get("detour_ratio")
        vias_per = target.get("vias_per_terminal")
        off = target.get("off_preference_ratio")
        lines.append(f"| {item['net']} | {item['net_class']} | {detour if detour is not None else '-'} | {vias_per if vias_per is not None else '-'} | {off if off is not None else '-'} | {tdom} | {rdom} | {reference['closed_path_count']} |")
    lines += ["", "## Findings", ""]
    if report["findings"]:
        lines += [f"- **{item['code']}** `{item['net']}`: {item['message']}" for item in report["findings"]]
    else:
        lines.append("- No structural reference-transfer findings.")
    lines += ["", "> This report compares routing policy evidence. It is not DRC, LVS, PEX, EM/IR, or simulation signoff.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--reference-summary", type=Path, required=True)
    parser.add_argument("--terminal-access", type=Path, required=True)
    parser.add_argument("--route-spec", type=Path)
    parser.add_argument("--placement-equivalent", action="store_true", help="Use only after exact placement transform and terminal correspondence are proven")
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    report = compare(load(args.intent), load(args.reference_summary), load(args.terminal_access), load(args.route_spec) if args.route_spec else None, args.placement_equivalent)
    if args.out_json:
        args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
