#!/usr/bin/env python3
"""Schematic -> explicit m-copy ALIGN placement -> PCell placement intent."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def scalar(value: Any, default: float = 1.0) -> float:
    if value is None:
        return default
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", str(value))
    if not match:
        return default
    number = float(match.group(0))
    suffix = str(value)[match.end():].strip().lower()
    return number * {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3}.get(suffix[:1], 1.0)


def positive_int(value: Any, default: int = 1) -> int:
    return max(1, int(round(scalar(value, float(default)))))


def bridge_client():
    from virtuoso_bridge import VirtuosoClient

    client = VirtuosoClient.from_env()
    client.ensure_ready()
    return client


def normalized_terms(inst: dict[str, Any]) -> dict[str, str]:
    return {str(k).upper(): str(v).strip() for k, v in inst.get("terms", {}).items() if v is not None and str(v).strip()}


def device_kind(inst: dict[str, Any]) -> str:
    if inst.get("kind") in ("nmos", "pmos", "capacitor", "resistor"):
        return inst["kind"]
    cell = inst.get("cell", "").lower()
    if cell.startswith("n") or "nmos" in cell:
        return "nmos"
    if cell.startswith("p") or "pmos" in cell:
        return "pmos"
    if cell.startswith("c") or "cap" in cell:
        return "capacitor"
    return "other"


def matching_signature(inst: dict[str, Any], include_m: bool = True) -> tuple | None:
    """Numeric physical dimensions only; unknown expressions never imply a match."""
    params = inst.get("params", {})
    def number(value):
        match = re.fullmatch(r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(p|n|u|µ|μ|m|)?(?:m)?\s*", str(value))
        if not match:
            return None
        result = float(match[1]) * {"p":1e-12,"n":1e-9,"u":1e-6,"µ":1e-6,"μ":1e-6,"m":1e-3,None:1,"":1}[match[2]]
        return round(result, 15) if result > 0 and math.isfinite(result) else None
    nf = number(params.get("fingers", params.get("nf", 1)))
    mult = number(params.get("m", 1))
    length = number(params.get("l"))
    width = number(params.get("w"))
    fw = number(params.get("fw"))
    if nf is None or int(nf) != nf or length is None or (include_m and (mult is None or int(mult) != mult)):
        return None
    if fw is None and width is not None:
        fw = round(width / nf, 15)
    if fw is None:
        return None
    width = round(fw * nf, 15) if width is None else width
    if abs(width - fw * nf) > max(1e-15, width * 1e-9):
        return None
    values = (device_kind(inst), inst.get("lib"), inst.get("cell"), params.get("model"), length, width, fw, nf)
    return values + (mult,) if include_m else values


def infer_intent(schematic: dict[str, Any], module_map: dict[str, str] | None = None) -> dict[str, Any]:
    module_map = module_map or {}
    devices = [i for i in schematic["instances"] if device_kind(i) != "other"]
    roles: dict[str, str] = {}
    dummies: list[str] = []
    matched: list[list[str]] = []
    differential: list[list[str]] = []
    mirrors: list[list[str]] = []
    ratioed_mirrors: list[list[str]] = []
    for inst in devices:
        terms = normalized_terms(inst)
        electrical = [terms.get(k) for k in ("D", "G", "S", "B") if terms.get(k)]
        if device_kind(inst) in ("nmos", "pmos") and len(electrical) >= 3 and len(set(electrical)) == 1:
            dummies.append(inst["name"])
            roles[inst["name"]] = "dummy"
    active = [i for i in devices if i["name"] not in dummies]
    for index, left in enumerate(active):
        left_terms = normalized_terms(left)
        for right in active[index + 1:]:
            right_terms = normalized_terms(right)
            if left["name"] in module_map and right["name"] in module_map and module_map[left["name"]] != module_map[right["name"]]:
                continue
            if device_kind(left) != device_kind(right):
                continue
            same = matching_signature(left) is not None and matching_signature(left) == matching_signature(right)
            source_body = all(left_terms.get(k) and left_terms[k] == right_terms.get(k) for k in ("S", "B"))
            if same:
                matched.append([left["name"], right["name"]])
            if same and device_kind(left) in ("nmos", "pmos") and source_body and left_terms.get("G") and right_terms.get("G") and left_terms["G"] != right_terms["G"] and left_terms.get("D") and right_terms.get("D") and left_terms["D"] != right_terms["D"]:
                differential.append([left["name"], right["name"]])
                roles[left["name"]] = roles[right["name"]] = "differential_pair"
            gate_left, gate_right = left_terms.get("G"), right_terms.get("G")
            if same and source_body and gate_left == gate_right and ((gate_left and gate_left == left_terms.get("D")) or (gate_right and gate_right == right_terms.get("D"))):
                mirrors.append([left["name"], right["name"]])
                roles[left["name"]] = roles[right["name"]] = "current_mirror"
    for inst in active:
        roles.setdefault(inst["name"], device_kind(inst))
    mirror_buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for inst in active:
        if device_kind(inst) not in ("nmos", "pmos"):
            continue
        params, terms = inst.get("params", {}), normalized_terms(inst)
        physical = matching_signature(inst, include_m=False)
        if physical is None or not all(terms.get(k) for k in ("G", "S", "B")):
            continue
        signature = physical + (terms["G"], terms["S"], terms["B"], module_map.get(inst["name"]))
        mirror_buckets[signature].append(inst)
    for members in mirror_buckets.values():
        if len(members) < 2:
            continue
        gate = normalized_terms(members[0]).get("G")
        if gate and any(normalized_terms(member).get("D") == gate for member in members):
            names = sorted((member["name"] for member in members), key=lambda name: positive_int(next(item for item in members if item["name"] == name).get("params", {}).get("m", 1)))
            if len({positive_int(member.get("params", {}).get("m", 1)) for member in members}) > 1:
                ratioed_mirrors.append(names)
                for name in names:
                    roles[name] = "ratioed_current_mirror"
    # Multiple eligible partners need an explicit functional grouping, not first-pair wins.
    ambiguities = []
    for role, pairs in (("differential_pair", differential), ("current_mirror", mirrors)):
        participants = [name for pair in pairs for name in pair]
        repeated = sorted({name for name in participants if participants.count(name) > 1})
        if repeated:
            ambiguities.append({"role": role, "devices": repeated, "candidate_pairs": pairs})
    terms_by_name = {i['name']:normalized_terms(i) for i in devices}
    return {
        "devices": [{"name": i["name"], "kind": device_kind(i), "params": i.get("params", {}), "terms": normalized_terms(i)} for i in devices],
        "roles": roles,
        "dummies": sorted(dummies),
        "matched_pairs": sorted(sorted(pair) for pair in matched),
        "matching_ambiguities": ambiguities,
        "differential_pairs": sorted(sorted(pair) for pair in differential),
        "mirror_pairs": sorted(sorted(pair, key=lambda name: (terms_by_name[name].get('D') != terms_by_name[name].get('G'), name)) for pair in mirrors),
        "ratioed_mirror_groups": sorted(ratioed_mirrors),
        "policy": {
            "placement_only": True,
            "matching_granularity": "explicit schematic multiplier copies",
            "each_mos_copy_uses_m": 1,
            "manual_layout_comparison": False,
            "absolute_area_comparable": False,
        },
    }


def cmd_snapshot(args: argparse.Namespace) -> None:
    plan = args.work / "plan"
    from virtuoso_bridge.virtuoso.schematic.reader import read_schematic

    data = read_schematic(bridge_client(), args.lib, args.cell, include_positions=False, param_filters=None)
    data["source"] = {"lib": args.lib, "cell": args.cell, "view": "schematic", "positions_included": False}
    dump(plan / "schematic.json", data)
    dump(plan / "intent.json", infer_intent(data))
    print(f"snapshotted {len(data['instances'])} instances, {len(data['nets'])} nets")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def spice_name(name: str, kind: str) -> str:
    return ({"nmos":"M", "pmos":"M", "capacitor":"C", "resistor":"R"}.get(kind,"X")) + safe_name(name)


def canonical_name(value: str) -> str:
    result = value.upper()
    if result.startswith("X_"):
        result = result[2:]
    return result


def terminal(terms: dict[str, str], *names: str, default: str = "0") -> str:
    return next((terms[name] for name in names if name in terms), default)


def pcell_parameters(params: dict[str, Any]) -> dict[str, Any]:
    keys = ("w", "fw", "l", "fingers", "nf", "model", "connectGates", "connectSD", "tap", "leftTap", "rightTap", "leftAbut", "rightAbut", "sdMtlWidth")
    result = {key: params[key] for key in keys if key in params}
    result["m"] = "1"
    return result


def expand_mos_copies(schematic: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    copies: list[dict[str, Any]] = []
    by_logical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for inst in schematic["instances"]:
        kind = device_kind(inst)
        if kind == "other":
            continue
        multiplier = inst.get("params", {}).get("m", 1)
        if not re.fullmatch(r"\s*\+?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*",str(multiplier)):
            raise ValueError(f"Unresolved multiplicity for {inst['name']}: {multiplier}")
        number = float(multiplier)
        if not math.isfinite(number) or number < 1 or number != int(number):
            raise ValueError(f"Invalid multiplicity for {inst['name']}: {multiplier}")
        count = int(number)
        for index in range(count):
            name = f"{inst['name']}__M{index}" if kind in ("nmos", "pmos") or count > 1 else inst["name"]
            copy = {
                "name": name,
                "align_instance": spice_name(name, kind),
                "logical_device": inst["name"],
                "copy_index": index,
                "copy_count": count,
                "kind": kind,
                "source_master": {"lib": inst.get("lib"), "cell": inst.get("cell"), "view": "schematic"},
                "pcell_master": {"lib": inst.get("lib"), "cell": inst.get("cell"), "view": "layout"},
                "pcell_parameters": pcell_parameters(inst.get("params", {})),
                "terminals": normalized_terms(inst),
            }
            copies.append(copy)
            by_logical[inst["name"]].append(copy)
    return copies, by_logical


def abba_rows(copies_a: list[dict[str, Any]], copies_b: list[dict[str, Any]], alternate: bool = False) -> list[list[dict[str, Any]]] | None:
    if len(copies_a) != len(copies_b) or len(copies_a) < 2 or len(copies_a) % 2:
        return None
    rows: list[list[dict[str, Any]]] = []
    ia = ib = 0
    for row_index in range(len(copies_a) // 2):
        if not alternate or row_index % 2 == 0:
            rows.append([copies_a[ia], copies_b[ib], copies_b[ib + 1], copies_a[ia + 1]])
        else:
            rows.append([copies_b[ib], copies_a[ia], copies_a[ia + 1], copies_b[ib + 1]])
        ia += 2
        ib += 2
    return rows


def rectangular_rows(copies: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    count = len(copies)
    columns = max(1, math.ceil(math.sqrt(count)))
    while count % columns:
        columns += 1
    return [copies[index:index + columns] for index in range(0, count, columns)]


def ratioed_common_centroid_rows(logicals: list[str], by_logical: dict[str, list[dict[str, Any]]]) -> list[list[dict[str, Any]]] | None:
    """Place odd/even unit-copy populations on rotationally symmetric slots."""
    counts = {name: len(by_logical[name]) for name in logicals}
    total = sum(counts.values())
    side = math.isqrt(total)
    odd = [name for name, count in counts.items() if count % 2]
    if side * side != total or side % 2 == 0 or len(odd) != 1:
        return None
    center = side // 2
    grid: list[list[dict[str, Any] | None]] = [[None for _ in range(side)] for _ in range(side)]
    copy_queues = {name: list(by_logical[name]) for name in logicals}
    center_name = odd[0]
    grid[center][center] = copy_queues[center_name].pop(0)
    pairs = []
    for row in range(side):
        for column in range(side):
            opposite = (side - 1 - row, side - 1 - column)
            if (row, column) >= opposite or (row, column) == (center, center):
                continue
            distance = abs(row - center) + abs(column - center)
            horizontal_middle = 0 if row == center else 1
            pairs.append((distance, horizontal_middle, row, column, opposite[0], opposite[1]))
    pairs.sort()
    for name in sorted(logicals, key=lambda item: len(copy_queues[item])):
        while copy_queues[name]:
            if len(copy_queues[name]) < 2 or not pairs:
                return None
            _, _, row, column, opposite_row, opposite_column = pairs.pop(0)
            grid[row][column] = copy_queues[name].pop(0)
            grid[opposite_row][opposite_column] = copy_queues[name].pop(0)
    if any(item is None for row in grid for item in row):
        return None
    return [[item for item in row if item is not None] for row in grid]


def group_constraints(rows: list[list[dict[str, Any]]], symmetrize: bool) -> list[dict[str, Any]]:
    align_rows = [[copy["align_instance"] for copy in row] for row in rows]
    result: list[dict[str, Any]] = [{"constraint": "Floorplan", "regions": align_rows, "order": True, "symmetrize": symmetrize}]
    result.extend({"constraint": "Align", "instances": row, "line": "h_center"} for row in align_rows if len(row) > 1)
    return result


def build_copy_groups(intent: dict[str, Any], by_logical: dict[str, list[dict[str, Any]]], matching_mode: str = "common_axis") -> list[dict[str, Any]]:
    if matching_mode not in ("common_axis", "common_centroid"):
        raise ValueError("Unsupported matching mode")
    if intent.get("matching_ambiguities"):
        raise ValueError("Ambiguous functional matching groups: " + str(intent["matching_ambiguities"]))
    groups: list[dict[str, Any]] = []
    used: set[str] = set()
    for logicals in intent.get("ratioed_mirror_groups", []):
        if any(name in used or name not in by_logical for name in logicals):
            continue
        rows = ratioed_common_centroid_rows(logicals, by_logical)
        if rows is None:
            continue
        group_name = "XCC_RATIO_" + "_".join(safe_name(name.upper()) for name in logicals)
        for row_index, row in enumerate(rows):
            for column_index, copy in enumerate(row):
                copy.update({"group": group_name, "row": row_index, "column": column_index})
        groups.append({
            "name": group_name,
            "kind": "ratioed_matching_group",
            "role": "ratioed_current_mirror",
            "logical_devices": logicals,
            "copy_ratio": {name: len(by_logical[name]) for name in logicals},
            "matching_mode": matching_mode,
            "pattern_mode": "rotational_unit_copy_common_centroid" if matching_mode == "common_centroid" else "ratioed_common_axis_rows",
            "align_constraint_status": "postprocess_only_due_ratioed_nf1_generator_limit",
            "rows": [[copy["name"] for copy in row] for row in rows],
            "align_rows": [[copy["align_instance"] for copy in row] for row in rows],
            "instances": [copy["align_instance"] for row in rows for copy in row],
            "constraints": group_constraints(rows, symmetrize=True),
        })
        used.update(logicals)
    candidates = [("differential_pair", pair) for pair in intent["differential_pairs"]]
    candidates += [("current_mirror", pair) for pair in intent["mirror_pairs"]]
    for role, pair in candidates:
        if any(name in used or name not in by_logical for name in pair):
            continue
        left, right = pair
        rows = abba_rows(by_logical[left], by_logical[right], alternate=matching_mode == "common_centroid")
        if rows is None:
            raise ValueError(f"ABBA requires equal even explicit copy counts >= 2: {left}, {right}; preserve source parameters and resolve decomposition before writing")
        mode = "explicit_m_copy_abba_common_axis" if matching_mode == "common_axis" else "explicit_m_copy_abba_common_centroid"
        if matching_mode == "common_centroid" and role == "differential_pair" and len(by_logical[left]) == len(by_logical[right]) == 2:
            rows = [[by_logical[left][0], by_logical[right][0]],
                    [by_logical[right][1], by_logical[left][1]]]
            mode = "rotational_2x2_diagonal_common_centroid"
        group_name = f"XCC_{safe_name(left.upper())}_{safe_name(right.upper())}"
        for row_index, row in enumerate(rows):
            for column_index, copy in enumerate(row):
                copy.update({"group": group_name, "row": row_index, "column": column_index})
        groups.append({
            "name": group_name,
            "kind": "matching_group",
            "role": role,
            "logical_devices": [left, right],
            "pattern_mode": mode,
            "matching_mode": matching_mode,
            **({"required_active_pattern": "ABBA"} if matching_mode == "common_axis" else {}),
            "rows": [[copy["name"] for copy in row] for row in rows],
            "align_rows": [[copy["align_instance"] for copy in row] for row in rows],
            "instances": [copy["align_instance"] for row in rows for copy in row],
            "constraints": group_constraints(rows, symmetrize=True),
        })
        used.update(pair)
    for logical, logical_copies in by_logical.items():
        if logical in used or logical in intent.get("dummies", []):
            continue
        rows = rectangular_rows(logical_copies)
        group_name = f"XARR_{safe_name(logical.upper())}"
        for row_index, row in enumerate(rows):
            for column_index, copy in enumerate(row):
                copy.update({"group": group_name, "row": row_index, "column": column_index})
        groups.append({
            "name": group_name,
            "kind": "multiplier_array",
            "role": intent["roles"].get(logical, "device_array"),
            "logical_devices": [logical],
            "pattern_mode": "compact_rectangular_m_copy_array",
            "rows": [[copy["name"] for copy in row] for row in rows],
            "align_rows": [[copy["align_instance"] for copy in row] for row in rows],
            "instances": [copy["align_instance"] for row in rows for copy in row],
            "constraints": group_constraints(rows, symmetrize=True),
        })
    return groups


def normalized_dimension(value: Any) -> float:
    return round(scalar(value, 0.0), 15)


def associate_dummies(
    groups: list[dict[str, Any]], intent: dict[str, Any], by_logical: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Attach rail-tied dummies to the unique active family sharing kind/master/L/fw."""
    associations: list[dict[str, Any]] = []
    for dummy in intent["dummies"]:
        dummy_copy = by_logical[dummy][0]
        dummy_key = (
            dummy_copy["kind"], dummy_copy["pcell_master"].get("lib"), dummy_copy["pcell_master"].get("cell"),
            normalized_dimension(dummy_copy["pcell_parameters"].get("l")),
            normalized_dimension(dummy_copy["pcell_parameters"].get("fw", dummy_copy["pcell_parameters"].get("w"))),
        )
        candidates = []
        for group in groups:
            representative = by_logical[group["logical_devices"][0]][0]
            active_key = (
                representative["kind"], representative["pcell_master"].get("lib"), representative["pcell_master"].get("cell"),
                normalized_dimension(representative["pcell_parameters"].get("l")),
                normalized_dimension(representative["pcell_parameters"].get("fw", representative["pcell_parameters"].get("w"))),
            )
            if active_key == dummy_key:
                candidates.append(group)
        if len(candidates) != 1:
            associations.append({"dummy_logical_device": dummy, "status": "ambiguous" if candidates else "unmatched", "candidate_groups": [group["name"] for group in candidates]})
            continue
        group = candidates[0]
        group.setdefault("dummy_logical_devices", []).append(dummy)
        group.setdefault("dummy_copies", []).extend(copy["name"] for copy in by_logical[dummy])
        associations.append({
            "dummy_logical_device": dummy,
            "dummy_copies": [copy["name"] for copy in by_logical[dummy]],
            "target_group": group["name"],
            "status": "associated_by_kind_master_l_fw_and_rail_tie",
        })
    return associations


def mos_line(copy: dict[str, Any], source: dict[str, Any]) -> str:
    params, terms, kind = source.get("params", {}), copy["terminals"], copy["kind"]
    width = scalar(params.get("w", params.get("fw", "1u")), 1e-6)
    length = scalar(params.get("l", "1u"), 1e-6)
    nf = positive_int(params.get("fingers", params.get("nf", 1)))
    model = "nmos_rvt" if kind == "nmos" else "pmos_rvt"
    extra = f" nfin={positive_int(params['nfin'])}" if "nfin" in params else ""
    return (
        f"{copy['align_instance']} {terminal(terms,'D')} {terminal(terms,'G')} {terminal(terms,'S')} "
        f"{terminal(terms,'B','SUB')} {model} w={width:.9g} l={length:.9g} nf={nf} m=1{extra}"
    )


def cmd_build(args: argparse.Namespace) -> None:
    plan = args.work / "plan"
    schematic = load(plan / "schematic.json")
    intent = infer_intent(schematic)
    dump(plan / "intent.json", intent)
    out = plan / "align"
    out.mkdir(parents=True, exist_ok=True)
    subckt = safe_name(args.top.upper())
    pins = list(schematic["pins"].keys())
    copies, by_logical = expand_mos_copies(schematic)
    source_by_name = {inst["name"]: inst for inst in schematic["instances"]}
    lines = [f".subckt {subckt} {' '.join(pins)}"]
    align_exclusions: list[dict[str, Any]] = []
    for copy in copies:
        source = source_by_name[copy["logical_device"]]
        terms = copy["terminals"]
        ratioed_device = intent["roles"].get(copy["logical_device"]) == "ratioed_current_mirror"
        exclusion_reason = None
        if copy["logical_device"] in intent["dummies"]:
            exclusion_reason = "rail_tied_dummy_has_no_ALIGN_mock_generator"
        elif copy["kind"] == "capacitor":
            exclusion_reason = "target_capacitor_has_no_ALIGN_mock_generator"
        elif ratioed_device:
            exclusion_reason = "ratioed_nf1_mirror_uses_authoritative_target_PCell_postprocessing"
        if exclusion_reason:
            align_exclusions.append({"name": copy["name"], "logical_device": copy["logical_device"], "reason": exclusion_reason, "retained_in_pcell_legalization": True})
            continue
        if copy["kind"] in ("nmos", "pmos"):
            lines.append(mos_line(copy, source))
    lines.extend([f".ends {subckt}", ""])
    (out / f"{subckt}.sp").write_text("\n".join(lines), encoding="utf-8")

    from functional_groups import prepare_groups
    constraints = load(args.constraints) if getattr(args,"constraints",None) else {}
    constraints.setdefault("matching",getattr(args,"matching","common_axis"))
    intent, copies, groups, dummy_associations = prepare_groups(schematic, constraints)
    dump(plan / "intent.json", intent)
    constraints: list[dict[str, Any]] = [{"constraint": "ConfigureCompiler", "auto_constraint": False, "merge_parallel_devices": False}]
    power = [pin for pin in pins if re.search(r"VDD|AVDD", pin, re.I)]
    ground = [pin for pin in pins if re.search(r"VSS|GND|AVSS", pin, re.I)]
    if power:
        constraints.append({"constraint": "PowerPorts", "ports": power})
    if ground:
        constraints.append({"constraint": "GroundPorts", "ports": ground})
    for group in groups:
        if group.get("align_constraint_status", "enabled") != "enabled":
            continue
        constraints.append({
            "constraint": "GroupBlocks",
            "instances": group["instances"],
            "instance_name": group["name"],
            "template_name": group["name"][1:],
            "constraints": group["constraints"],
        })
    (out / f"{subckt}.const.json").write_text(json.dumps(constraints, indent=2) + "\n", encoding="utf-8")
    dump(out / "mapping.json", {copy["name"]: copy["align_instance"] for copy in copies})
    dump(plan / "device-copies.json", copies)
    dump(plan / "copy-groups.json", groups)
    dump(plan / "dummy-associations.json", dummy_associations)
    dump(plan / "align-exclusions.json", align_exclusions)
    abba = sum("abba" in group["pattern_mode"] for group in groups)
    ratioed = sum(group["kind"] == "ratioed_matching_group" for group in groups)
    associated = sum(item["status"].startswith("associated") for item in dummy_associations)
    print(f"built {len(copies)} physical copies in {len(groups)} groups; {abba} ABBA, {ratioed} ratioed matching; {associated}/{len(dummy_associations)} dummy families associated")


def find_raw_placement(run_dir: Path) -> Path:
    found = list(run_dir.rglob("*.scaled_placement_verilog.json")) or list(run_dir.rglob("*.placement_verilog.json"))
    if not found:
        raise FileNotFoundError("ALIGN placement JSON not found")
    largest = max(path.stat().st_size for path in found)
    candidates = [path for path in found if path.stat().st_size >= 0.9 * largest]
    return sorted(candidates, key=lambda path: path.name)[0]


def compose_transform(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, float]:
    return {
        "oX": float(parent.get("oX", 0)) + float(parent.get("sX", 1)) * float(child.get("oX", 0)),
        "oY": float(parent.get("oY", 0)) + float(parent.get("sY", 1)) * float(child.get("oY", 0)),
        "sX": float(parent.get("sX", 1)) * float(child.get("sX", 1)),
        "sY": float(parent.get("sY", 1)) * float(child.get("sY", 1)),
    }


def transform_bbox(bbox: list[Any], transform: dict[str, Any]) -> list[list[float]]:
    if len(bbox) == 4 and not isinstance(bbox[0], list):
        bbox = [[bbox[0], bbox[1]], [bbox[2], bbox[3]]]
    ox, oy = float(transform.get("oX", 0)), float(transform.get("oY", 0))
    sx, sy = float(transform.get("sX", 1)), float(transform.get("sY", 1))
    points = [(ox + sx * bbox[0][0], oy + sy * bbox[0][1]), (ox + sx * bbox[1][0], oy + sy * bbox[1][1])]
    return [[min(point[0] for point in points), min(point[1] for point in points)], [max(point[0] for point in points), max(point[1] for point in points)]]


def orientation(transform: dict[str, Any]) -> str:
    signs = (int(transform.get("sX", 1)), int(transform.get("sY", 1)))
    return {(1, 1): "R0", (-1, 1): "MY", (1, -1): "MX", (-1, -1): "R180"}.get(signs, "UNKNOWN")


def select_top_module(modules: list[dict[str, Any]]) -> dict[str, Any]:
    referenced = {inst.get("concrete_template_name") for module in modules for inst in module.get("instances", [])}
    roots = [module for module in modules if module.get("concrete_name") not in referenced]
    return max(roots or modules, key=lambda module: len(module.get("instances", [])))


def flatten_placement(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    modules = data.get("modules", [])
    if not modules:
        raise ValueError("ALIGN JSON has no modules")
    module_concrete = {module.get("concrete_name"): module for module in modules}
    module_abstract = {module.get("abstract_name"): module for module in modules}
    leaf_concrete = {leaf.get("concrete_name"): leaf for leaf in data.get("leaves", [])}
    leaf_abstract = {leaf.get("abstract_name"): leaf for leaf in data.get("leaves", [])}
    top = select_top_module(modules)
    identity = {"oX": 0.0, "oY": 0.0, "sX": 1.0, "sY": 1.0}
    macros: list[dict[str, Any]] = []
    leaves: list[dict[str, Any]] = []

    def lookup_module(inst: dict[str, Any]) -> dict[str, Any] | None:
        return module_concrete.get(inst.get("concrete_template_name")) or module_abstract.get(inst.get("abstract_template_name"))

    def lookup_leaf(inst: dict[str, Any]) -> dict[str, Any] | None:
        return leaf_concrete.get(inst.get("concrete_template_name")) or leaf_abstract.get(inst.get("abstract_template_name"))

    def walk(module: dict[str, Any], parent_transform: dict[str, Any], path: list[str]) -> None:
        for inst in module.get("instances", []):
            transform = compose_transform(parent_transform, inst.get("transformation", {}))
            child_module = lookup_module(inst)
            child_leaf = lookup_leaf(inst)
            item_path = path + [inst.get("instance_name", "?")]
            template = child_module or child_leaf
            if template and "bbox" in template:
                bbox = transform_bbox(template["bbox"], transform)
                item = {
                    "name": inst.get("instance_name", "?"),
                    "path": "/".join(item_path),
                    "template": inst.get("abstract_template_name"),
                    "bbox": bbox,
                    "center": [(bbox[0][0] + bbox[1][0]) / 2, (bbox[0][1] + bbox[1][1]) / 2],
                    "transformation": transform,
                    "orientation": orientation(transform),
                }
                if len(path) == 0:
                    macros.append(item)
            if child_module:
                walk(child_module, transform, item_path)
            elif child_leaf:
                leaves.append(item)

    walk(top, identity, [])
    if not leaves:
        raise ValueError("No placed leaf instances found")
    return top, macros, leaves


def placement_bbox(items: list[dict[str, Any]]) -> list[list[float]]:
    return [
        [min(item["bbox"][0][0] for item in items), min(item["bbox"][0][1] for item in items)],
        [max(item["bbox"][1][0] for item in items), max(item["bbox"][1][1] for item in items)],
    ]


def normalize_align(data: dict[str, Any]) -> dict[str, Any]:
    top, macros, leaves = flatten_placement(data)
    return {
        "source": "ALIGN placement-only",
        "top": top.get("abstract_name"),
        "units": "ALIGN mock-PDK database units",
        "bbox": placement_bbox(leaves),
        "macro_instances": macros,
        "leaf_instances": leaves,
    }


PL_ORIENTATIONS = {"N": "R0", "FN": "MY", "FS": "MX", "S": "R180"}


def read_pl(path: Path) -> dict[str, Any]:
    """Read the small UCLA .pl subset emitted by ALIGN's placer."""
    die = [0.0, 0.0, 0.0, 0.0]
    instances: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        die_match = re.match(r"DIE\s*\{\s*([-+\d.]+)\s*,\s*([-+\d.]+)\s*\}\s*\{\s*([-+\d.]+)\s*,\s*([-+\d.]+)\s*\}", line)
        if die_match:
            die = [float(value) for value in die_match.groups()]
            continue
        match = re.match(r"(\S+)\s+([-+\d.]+)\s+([-+\d.]+)\s+(N|FN|FS|S)\s*$", line)
        if match:
            instances.append({
                "name": match.group(1),
                "anchor": [float(match.group(2)), float(match.group(3))],
                "pl_orientation": match.group(4),
                "orientation": PL_ORIENTATIONS[match.group(4)],
            })
    return {"path": str(path), "die": die, "instances": instances}


def pl_point_in_parent(point: list[float], child_die: list[float], parent: dict[str, Any]) -> list[float]:
    """Compose a child anchor with the parent macro transform (intent-grade, not PDK geometry)."""
    x, y = point
    width, height = child_die[2] - child_die[0], child_die[3] - child_die[1]
    code = parent["pl_orientation"]
    if code in ("FN", "S"):
        x = width - x
    if code in ("FS", "S"):
        y = height - y
    return [parent["anchor"][0] + x, parent["anchor"][1] + y]


def compose_pl_orientation(parent: str, child: str) -> str:
    signs = {"N": (1, 1), "FN": (-1, 1), "FS": (1, -1), "S": (-1, -1)}
    reverse = {value: PL_ORIENTATIONS[key] for key, value in signs.items()}
    a, b = signs[parent], signs[child]
    return reverse[(a[0] * b[0], a[1] * b[1])]


def resolved_group_terminals(top_inst: dict[str, Any], child_inst: dict[str, Any]) -> dict[str, str]:
    ports = {item["formal"].upper(): str(item["actual"]).upper() for item in top_inst.get("fa_map", [])}
    return {
        item["formal"].upper(): ports.get(str(item["actual"]).upper(), str(item["actual"]).upper())
        for item in child_inst.get("fa_map", [])
    }


def logical_for_group_child(
    top_inst: dict[str, Any], child_inst: dict[str, Any], logical_devices: list[str], copies: list[dict[str, Any]]
) -> str:
    actual = resolved_group_terminals(top_inst, child_inst)
    candidates = {name: next(copy for copy in copies if copy["logical_device"] == name)["terminals"] for name in logical_devices}
    scores = {
        name: sum(actual.get(pin) == str(terms.get(pin, "")).upper() for pin in ("D", "G", "S", "B") if pin in actual and pin in terms)
        for name, terms in candidates.items()
    }
    return max(scores, key=scores.get)


def grid_positions(items: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    ys = sorted({item["anchor"][1] for item in items}, reverse=True)
    result: dict[str, tuple[int, int]] = {}
    for row, y in enumerate(ys):
        members = sorted((item for item in items if item["anchor"][1] == y), key=lambda item: item["anchor"][0])
        for column, item in enumerate(members):
            result[item["name"]] = (row, column)
    return result


def matching_parameter_warnings(groups: list[dict[str, Any]], copies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_logical = {copy["logical_device"]: copy for copy in copies}
    warnings = []
    for group in groups:
        logical = group["logical_devices"]
        if len(logical) != 2:
            continue
        left, right = (by_logical[name] for name in logical)
        differing = sorted(key for key in set(left["pcell_parameters"]) | set(right["pcell_parameters"]) if left["pcell_parameters"].get(key) != right["pcell_parameters"].get(key))
        if left["pcell_master"] != right["pcell_master"] or differing:
            warnings.append({
                "group": group["name"],
                "logical_devices": logical,
                "differing_pcell_parameters": differing,
                "message": "Normalize or explicitly validate these PCell choices before abutment; differing geometry can invalidate equal-pitch common-centroid placement.",
            })
    return warnings


def recover_pl_placement(plan: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover a PCell placement intent when ALIGN completed placement but not JSON emission."""
    schematic = load(plan / "schematic.json")
    copies = load(plan / "device-copies.json")
    groups = load(plan / "copy-groups.json")
    pnr = plan / "align-run" / "3_pnr"
    verilog_path = pnr / "inputs" / f"{safe_name(schematic['source']['cell'].upper())}.verilog.json"
    if not verilog_path.exists():
        candidates = list((pnr / "inputs").glob("*.verilog.json"))
        if not candidates:
            raise FileNotFoundError("ALIGN PNR input verilog JSON not found")
        verilog_path = candidates[0]
    netlist = load(verilog_path)
    modules = {module["name"]: module for module in netlist["modules"]}
    top_module = netlist["modules"][0]
    results = pnr / "Results"
    top_pl_path = results / f"{top_module['name']}_0.pl"
    top_pl = read_pl(top_pl_path)
    top_entries = {item["name"]: item for item in top_pl["instances"]}
    top_net_instances = {item["instance_name"]: item for item in top_module["instances"]}
    copy_by_align = {canonical_name(copy["align_instance"]): copy for copy in copies}
    mapped: list[dict[str, Any]] = []
    hierarchy: list[dict[str, Any]] = []

    for group in groups:
        top_inst = top_net_instances[group["name"]]
        macro = top_entries[group["name"]]
        template_name = top_inst["abstract_template_name"]
        child_path = results / f"{template_name}_0.pl"
        child_pl = read_pl(child_path)
        child_module = modules[template_name]
        child_net = {item["instance_name"]: item for item in child_module["instances"]}
        slots = grid_positions(child_pl["instances"])
        classified: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for child in child_pl["instances"]:
            logical = logical_for_group_child(top_inst, child_net[child["name"]], group["logical_devices"], copies)
            classified[logical].append(child)
        assigned: dict[str, dict[str, Any]] = {}
        for logical, children in classified.items():
            physical = sorted(children, key=lambda item: slots[item["name"]])
            identities = sorted((copy for copy in copies if copy["logical_device"] == logical), key=lambda copy: copy["copy_index"])
            if len(physical) != len(identities):
                raise ValueError(f"{group['name']}: {logical} placement/copy count mismatch")
            assigned.update({copy["name"]: child for copy, child in zip(identities, physical)})
        for copy in (copy for copy in copies if copy["logical_device"] in group["logical_devices"]):
            child = assigned[copy["name"]]
            row, column = slots[child["name"]]
            anchor = pl_point_in_parent(child["anchor"], child_pl["die"], macro)
            mapped.append({
                **copy,
                "group": group["name"],
                "grid_position": {"row": row, "column": column},
                "align_path": f"{group['name']}/{child['name']}",
                "align_anchor": anchor,
                "orientation": compose_pl_orientation(macro["pl_orientation"], child["pl_orientation"]),
                "align_hierarchy": {
                    "macro_instance": group["name"], "macro_template": template_name,
                    "macro_anchor": macro["anchor"], "macro_orientation": macro["orientation"],
                    "local_instance": child["name"], "local_anchor": child["anchor"],
                    "local_orientation": child["orientation"], "local_die": child_pl["die"],
                },
            })
        hierarchy.append({"name": group["name"], "template": template_name, "anchor": macro["anchor"], "orientation": macro["orientation"], "die": child_pl["die"]})

    grouped = {copy["name"] for copy in mapped}
    for top_name, item in top_entries.items():
        copy = copy_by_align.get(canonical_name(top_name))
        if copy and copy["name"] not in grouped:
            mapped.append({**copy, "group": None, "grid_position": {"row": None, "column": None}, "align_path": top_name, "align_anchor": item["anchor"], "orientation": item["orientation"], "align_hierarchy": None})

    inferred = infer_intent(schematic)
    mapped_names = {item["name"] for item in mapped}
    deferred = []
    for copy in copies:
        if copy["name"] not in mapped_names and copy["logical_device"] in inferred["dummies"]:
            deferred.append({**copy, "placement_status": "deferred_dummy_edge_placement", "reason": "ALIGN prunes four-terminal rail-tied devices before placement"})
    missing = [copy["name"] for copy in copies if copy["name"] not in mapped_names]
    xs = [item["align_anchor"][0] for item in mapped]
    ys = [item["align_anchor"][1] for item in mapped]
    bbox = [[min(xs), min(ys)], [max(xs) + 1.0, max(ys) + 1.0]]
    for item in mapped:
        item["relative_anchor"] = [(item["align_anchor"][0] - bbox[0][0]) / max(1.0, bbox[1][0] - bbox[0][0]), (item["align_anchor"][1] - bbox[0][1]) / max(1.0, bbox[1][1] - bbox[0][1])]
    checks = []
    for group in groups:
        if len(group["logical_devices"]) != 2:
            continue
        logical_centroids = {}
        for logical in group["logical_devices"]:
            positions = [item["grid_position"] for item in mapped if item["logical_device"] == logical]
            logical_centroids[logical] = [sum(p["row"] for p in positions) / len(positions), sum(p["column"] for p in positions) / len(positions)]
        left, right = group["logical_devices"]
        delta = [abs(logical_centroids[left][axis] - logical_centroids[right][axis]) for axis in (0, 1)]
        checks.append({"group": group["name"], "logical_devices": [left, right], "grid_centroid_delta": delta, "common_centroid": delta == [0.0, 0.0]})
    deferred_names = {item["name"] for item in deferred}
    intent = {
        "schema": "analog-layout-align.pcell-placement-intent/v1",
        "source_schematic": schematic.get("source"),
        "coordinate_contract": {
            "space": "ALIGN mock-PDK hierarchical .pl anchors",
            "absolute_coordinates_reusable": False,
            "reuse": ["explicit instance identity", "PCell master and parameters", "grouping", "actual row/column order", "orientation intent", "hierarchical and relative anchors"],
            "requires_target_pdk_legalization": True,
        },
        "instances": mapped,
        "deferred_instances": deferred,
        "groups": [{key: value for key, value in group.items() if key not in ("constraints", "instances", "align_rows")} for group in groups],
        "legalization_warnings": matching_parameter_warnings(groups, copies),
        "validation": {
            "expected_instances": len(copies), "mapped_instances": len(mapped), "missing_instances": missing,
            "deferred_dummy_instances": sorted(deferred_names),
            "unexpected_missing_instances": [name for name in missing if name not in deferred_names],
            "complete_for_nonpruned_instances": not any(name not in deferred_names for name in missing),
            "all_mos_copies_have_m_1": all(item["pcell_parameters"].get("m") == "1" for item in mapped if item["kind"] in ("nmos", "pmos")),
            "matching_checks": checks,
        },
    }
    placement = {"source": "ALIGN placement-only recovered from hierarchical .pl", "top": top_module["name"], "units": "ALIGN mock-PDK database units", "die": top_pl["die"], "macro_instances": hierarchy, "instance_anchors": [{"name": item["name"], "anchor": item["align_anchor"], "orientation": item["orientation"]} for item in mapped]}
    return placement, intent


def skill_pcell_params(params: dict[str, Any], kind: str) -> str:
    if kind == "capacitor":
        from apply_placement_intent import pcell_params
        return pcell_params({"kind": kind, "pcell_parameters": params})
    # Schematic snapshots may include derived/read-only CDF fields. Pass only
    # the geometry inputs covered by this flow's live measurement contract.
    strings = {"w", "connectGates", "connectSD", "tap"}
    numeric = {"fw", "l", "fingers", "nf"}
    entries = []
    for key, value in params.items():
        if key == "m" or key not in strings | numeric:
            continue
        if key in strings:
            escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
            entries.append(f'list("{key}" "string" "{escaped}")')
        else:
            entries.append(f'list("{key}" "float" {scalar(value, 0.0):.12g})')
    if kind == "capacitor":
        entries = [entry for entry in entries if any(f'"{key}"' in entry for key in ("w", "l"))]
    return "list(" + " ".join(entries) + ")"


def parse_skill_bbox(output: str) -> tuple[list[list[float]], float]:
    numbers = [float(value) for value in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", output)]
    if len(numbers) < 5:
        raise ValueError(f"Cannot parse PCell bbox/grid from Virtuoso output: {output}")
    return [[numbers[0], numbers[1]], [numbers[2], numbers[3]]], numbers[4]


def cmd_measure_pcells(args: argparse.Namespace) -> None:
    plan = args.work / "plan"
    copies = load(plan / "device-copies.json")
    logicals: dict[str, dict[str, Any]] = {}
    for copy in copies:
        logicals.setdefault(copy["logical_device"], copy)
    client = bridge_client()
    measured: dict[str, Any] = {}
    grids: list[float] = []
    for index, (logical, copy) in enumerate(sorted(logicals.items())):
        master = copy["pcell_master"]
        from apply_placement_intent import pcell_params
        params = pcell_params(copy) if copy.get("pcell_parameter_entries") is not None else skill_pcell_params(copy["pcell_parameters"], copy["kind"])
        from apply_placement_intent import capacitor_parameter_guard
        guard = capacitor_parameter_guard(copy, 'dbPurge(cv) error("Evaluated capacitor dimensions differ from intent\\n")')
        expr = (
            "let((cv i bb grid out) "
            f'cv=dbOpenCellViewByType("{args.probe_lib}" "{args.probe_cell}" "alignBBoxProbe" "maskLayout" "w") '
            'unless(cv error("PCell probe cellview failed\\n")) '
            f'i=dbCreateParamInstByMasterName(cv "{master["lib"]}" "{master["cell"]}" "{master["view"]}" '
            f'"PROBE_{index}" list(0.0 0.0) "R0" 1 {params}) '
            f'unless(i error("PCell probe failed: {logical}\\n")) '
            f'{guard}'
            "bb=dbTransformBBox(i~>master~>bBox i~>transform) "
            "grid=techGetMfgGridResolution(techGetTechFile(cv)) "
            "out=list(bb grid) dbPurge(cv) out)"
        )
        response = client.execute_skill(expr)
        if not response.ok:
            raise RuntimeError(f"PCell measurement failed for {logical}: {response.errors}")
        bbox, grid = parse_skill_bbox(str(response.output))
        grids.append(grid)
        measured[logical] = {
            "logical_device": logical,
            "kind": copy["kind"],
            "pcell_master": master,
            "pcell_parameters": copy["pcell_parameters"],
            "bbox_at_r0_origin": bbox,
            "width": bbox[1][0] - bbox[0][0],
            "height": bbox[1][1] - bbox[0][1],
            "evaluated_capacitor_dimensions_match": True if copy['kind'] == 'capacitor' else None,
            "pcell_parameter_entries": copy.get("pcell_parameter_entries"),
            "pdk_mapping_sha256": copy.get("pdk_mapping_sha256"),
        }
    geometry = {
        "schema": "analog-layout-align.pcell-geometry/v1",
        "source": "live Virtuoso evaluated PCells",
        "master_libraries": sorted({item["pcell_master"]["lib"] for item in measured.values()}),
        "probe_saved": False,
        "probe_target": {"lib": args.probe_lib, "cell": args.probe_cell, "view": "alignBBoxProbe"},
        "units": "micron",
        "manufacturing_grid": max(grids) if grids else 0.001,
        "devices": measured,
    }
    dump(plan / "pcell-geometry.json", geometry)
    print(f"measured {len(measured)} logical PCell variants; grid={geometry['manufacturing_grid']} um; probe was purged without save")


def oriented_local_bbox(bbox: list[list[float]], orient: str) -> list[list[float]]:
    x0, y0 = bbox[0]
    x1, y1 = bbox[1]
    if orient in ("MY", "R180"):
        x0, x1 = -x1, -x0
    if orient in ("MX", "R180"):
        y0, y1 = -y1, -y0
    return [[min(x0, x1), min(y0, y1)], [max(x0, x1), max(y0, y1)]]


def snap(value: float, grid: float) -> float:
    return round(round(value / grid) * grid, 9)


def dummy_augmented_rows(group: dict[str, Any]) -> tuple[list[list[str]], str]:
    rows = [list(row) for row in group["rows"]]
    if group.get("configured_dummy_copies") is not None:
        return rows, "explicit_project_rows"
    dummies = list(group.get("dummy_copies", []))
    if not dummies:
        return rows, "none"
    if group.get("pattern_mode") == "rotational_2x2_diagonal_common_centroid" and len(dummies) == 2:
        return rows, "centered_lateral_pair"
    row_count = len(rows)
    if len(dummies) % (2 * row_count) == 0:
        per_side = len(dummies) // (2 * row_count)
        cursor = 0
        for row_index in range(row_count):
            left = dummies[cursor:cursor + per_side]
            cursor += per_side
            right = dummies[cursor:cursor + per_side]
            cursor += per_side
            rows[row_index] = left + rows[row_index] + list(reversed(right))
        return rows, "symmetric_left_right_per_row"
    if len(dummies) == row_count and row_count % 2 == 0:
        half = row_count // 2
        for row_index, dummy in enumerate(dummies):
            rows[row_index] = ([dummy] + rows[row_index]) if row_index < half else (rows[row_index] + [dummy])
        return rows, "rotational_outer_pair"
    left_count = len(dummies) // 2
    rows[0] = dummies[:left_count] + rows[0]
    rows[-1] = rows[-1] + list(reversed(dummies[left_count:]))
    return rows, "symmetric_outer_fallback"


def checkerboard_orientation(row: int, column: int) -> str:
    return (("R0", "MY"), ("MX", "R180"))[row % 2][column % 2]


def build_local_macro(
    group: dict[str, Any], copies_by_name: dict[str, dict[str, Any]], geometry: dict[str, Any], gap: float, grid: float
) -> dict[str, Any]:
    rows, dummy_strategy = dummy_augmented_rows(group)
    metrics = []
    for row_index, names in enumerate(rows):
        cells = []
        for column_index, name in enumerate(names):
            copy = copies_by_name[name]
            orient = ("R0" if column_index < (len(names)+1)//2 else "MY") if group.get("matching_mode", "common_axis") == "common_axis" else checkerboard_orientation(row_index, column_index)
            orient = group.get("configured_orientations", {}).get(name, orient)
            if orient not in ("R0","MY","MX","R180"):
                raise ValueError("Unsupported configured orientation")
            measured = geometry["devices"][copy["logical_device"]]
            local_bbox = oriented_local_bbox(measured["bbox_at_r0_origin"], orient)
            cells.append({"copy": copy, "orientation": orient, "local_bbox": local_bbox, "width": local_bbox[1][0] - local_bbox[0][0], "height": local_bbox[1][1] - local_bbox[0][1]})
        metrics.append({"cells": cells, "width": sum(cell["width"] for cell in cells) + gap * max(0, len(cells) - 1), "height": max(cell["height"] for cell in cells)})
    macro_width = max(row["width"] for row in metrics)
    macro_height = sum(row["height"] for row in metrics) + gap * max(0, len(metrics) - 1)
    y_top = macro_height
    placed = []
    for row_index, row in enumerate(metrics):
        y_top -= row["height"]
        cursor = (macro_width - row["width"]) / 2
        for column_index, cell in enumerate(row["cells"]):
            bbox_x0 = cursor
            bbox_y0 = y_top + (row["height"] - cell["height"]) / 2
            origin = [snap(bbox_x0 - cell["local_bbox"][0][0], grid), snap(bbox_y0 - cell["local_bbox"][0][1], grid)]
            bbox = [[snap(bbox_x0, grid), snap(bbox_y0, grid)], [snap(bbox_x0 + cell["width"], grid), snap(bbox_y0 + cell["height"], grid)]]
            copy = cell["copy"]
            placed.append({
                **copy,
                "orientation": cell["orientation"],
                "origin": origin,
                "bbox": bbox,
                "bbox_center": [snap((bbox[0][0] + bbox[1][0]) / 2, grid), snap((bbox[0][1] + bbox[1][1]) / 2, grid)],
                "group": group["name"],
                "grid_position": {"row": row_index, "column": column_index},
                "placement_role": "dummy" if copy["logical_device"] in group.get("dummy_logical_devices", []) else "active",
            })
            cursor += cell["width"] + gap
        y_top -= gap
    if dummy_strategy == "centered_lateral_pair":
        # Two retained dummies flank the active array at its vertical midpoint.
        # Do not stagger one dummy per row: that recreates unequal A/B spans.
        dummy_data = []
        for name, orient in zip(group["dummy_copies"], ("R0", "MY")):
            copy = copies_by_name[name]
            bb = oriented_local_bbox(geometry["devices"][copy["logical_device"]]["bbox_at_r0_origin"], orient)
            dummy_data.append((copy, orient, bb, bb[1][0]-bb[0][0], bb[1][1]-bb[0][1]))
        if abs(dummy_data[0][3]-dummy_data[1][3]) > grid or abs(dummy_data[0][4]-dummy_data[1][4]) > grid:
            raise ValueError("Centered lateral dummies require equal measured geometry")
        side_width = dummy_data[0][3]
        full_height = max(macro_height, *(d[4] for d in dummy_data))
        shift = [side_width+gap, (full_height-macro_height)/2]
        for item in placed:
            item['origin'] = [snap(item['origin'][a]+shift[a], grid) for a in (0,1)]
            item['bbox'] = [[snap(p[a]+shift[a],grid) for a in (0,1)] for p in item['bbox']]
            item['bbox_center'] = [snap(item['bbox_center'][a]+shift[a],grid) for a in (0,1)]
        macro_width += 2*(side_width+gap)
        macro_height = full_height
        for side, (copy, orient, bb, width, height) in enumerate(dummy_data):
            ll = [0 if side == 0 else macro_width-width, (macro_height-height)/2]
            bbox = [[snap(v,grid) for v in ll], [snap(ll[0]+width,grid),snap(ll[1]+height,grid)]]
            placed.append({**copy, 'orientation':orient,
                           'origin':[snap(ll[a]-bb[0][a],grid) for a in (0,1)], 'bbox':bbox,
                           'bbox_center':[snap((bbox[0][a]+bbox[1][a])/2,grid) for a in (0,1)],
                           'group':group['name'], 'grid_position':{'row':None,'column':side}, 'placement_role':'dummy'})
    return {
        "name": group["name"],
        "kind": group["kind"],
        "role": group["role"],
        "logical_devices": group["logical_devices"],
        "dummy_logical_devices": group.get("dummy_logical_devices", []),
        "dummy_strategy": dummy_strategy,
        "matching_mode": group.get("matching_mode", "common_axis"),
        "pattern_mode": group["pattern_mode"],
        **({"required_active_pattern": group["required_active_pattern"]} if "required_active_pattern" in group else {}),
        "rows": rows,
        "size": [snap(macro_width, grid), snap(macro_height, grid)],
        "instances": placed,
    }


def translate_macro(macro: dict[str, Any], origin: list[float], grid: float) -> None:
    macro["origin"] = [snap(origin[0], grid), snap(origin[1], grid)]
    macro["bbox"] = [macro["origin"], [snap(origin[0] + macro["size"][0], grid), snap(origin[1] + macro["size"][1], grid)]]
    macro["center"] = [snap((macro["bbox"][0][0] + macro["bbox"][1][0]) / 2, grid), snap((macro["bbox"][0][1] + macro["bbox"][1][1]) / 2, grid)]
    for item in macro["instances"]:
        item["origin"] = [snap(item["origin"][0] + origin[0], grid), snap(item["origin"][1] + origin[1], grid)]
        item["bbox"] = [[snap(value + origin[axis], grid) for axis, value in enumerate(corner)] for corner in item["bbox"]]
        item["bbox_center"] = [snap(item["bbox_center"][axis] + origin[axis], grid) for axis in (0, 1)]
        item["align_anchor"] = item["origin"]
        item["align_bbox"] = item["bbox"]


def bbox_overlap(left: list[list[float]], right: list[list[float]]) -> bool:
    return left[0][0] < right[1][0] and left[1][0] > right[0][0] and left[0][1] < right[1][1] and left[1][1] > right[0][1]


def compact_standalone_anchor(width, height, obstacles, fallback, gap, grid):
    """Bounded bbox seed packing; no device resizing, routing or PDK legality claim."""
    candidates = [fallback]
    for bb in obstacles:
        cx, cy = (bb[0][0]+bb[1][0])/2, (bb[0][1]+bb[1][1])/2
        candidates += [[bb[0][0], bb[0][1]-gap-height], [cx-width/2, bb[0][1]-gap-height],
                       [cx-width/2, bb[1][1]+gap], [bb[1][0]+gap, cy-height/2],
                       [bb[0][0]-gap-width, cy-height/2]]
    scored = []
    for ll in candidates:
        ll = [snap(v,grid) for v in ll]
        if min(ll) < 0: continue
        bb = [ll,[snap(ll[0]+width,grid),snap(ll[1]+height,grid)]]
        if any(not (bb[1][0]+gap <= o[0][0]+1e-8 or o[1][0]+gap <= bb[0][0]+1e-8 or
                       bb[1][1]+gap <= o[0][1]+1e-8 or o[1][1]+gap <= bb[0][1]+1e-8) for o in obstacles): continue
        boxes = obstacles+[bb]
        area = (max(b[1][0] for b in boxes)-min(b[0][0] for b in boxes))*(max(b[1][1] for b in boxes)-min(b[0][1] for b in boxes))
        scored.append((area, ll[0], ll[1]))
    if not scored: raise ValueError('No standalone anchor satisfies planning gap')
    _, x, y = min(scored)
    return [x,y]


def cmd_legalize_pcells(args: argparse.Namespace) -> None:
    plan = args.work / "plan"
    schematic = load(plan / "schematic.json")
    copies = load(plan / "device-copies.json")
    groups = load(plan / "copy-groups.json")
    geometry = load(plan / "pcell-geometry.json")
    grid = float(geometry["manufacturing_grid"])
    device_gap = snap(max(args.device_gap, grid), grid)
    macro_gap = snap(max(args.macro_gap, grid), grid)
    copies_by_name = {copy["name"]: copy for copy in copies}
    macros = [build_local_macro(group, copies_by_name, geometry, device_gap, grid) for group in groups]
    if not macros:
        raise ValueError("No functional macros")
    policy = getattr(args, "floorplan_policy", None)
    if policy:
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"analog-layout-workflow/scripts"))
        from project_config import position_macros
        origins, target_center = position_macros(macros, policy, snap, grid, macro_gap)
        for macro in macros:
            translate_macro(macro, origins[macro["name"]], grid)
        core_width = max(m["bbox"][1][0] for m in macros)
        core_top = max(m["bbox"][1][1] for m in macros)
    else:
        # Legacy compatibility: configured_flow supplies explicit floorplan policy.
        role_order = {"ratioed_current_mirror":0, "differential_pair":1, "current_mirror":2}
        macros.sort(key=lambda m: (role_order.get(m["role"], 3), m["name"]))
        core_width = max(m["size"][0] for m in macros)
        target_center = snap(core_width / 2, grid)
        y = 0.0
        for macro in macros:
            translate_macro(macro, [target_center - macro["size"][0]/2, y], grid)
            y += macro["size"][1] + macro_gap
        core_top = y - macro_gap
    x = core_width + macro_gap
    grouped_names = {item["name"] for macro in macros for item in macro["instances"]}
    standalone = []
    for copy in copies:
        if copy["name"] in grouped_names:
            continue
        measured = geometry["devices"][copy["logical_device"]]
        local_bbox = measured["bbox_at_r0_origin"]
        width, height = measured["width"], measured["height"]
        bbox_ll = compact_standalone_anchor(width, height,
            [m['bbox'] for m in macros]+[i['bbox'] for i in standalone],
            [x, max(0.0, core_top-height)], macro_gap, grid)
        origin = [snap(bbox_ll[0] - local_bbox[0][0], grid), snap(bbox_ll[1] - local_bbox[0][1], grid)]
        bbox = [[snap(bbox_ll[0], grid), snap(bbox_ll[1], grid)], [snap(bbox_ll[0] + width, grid), snap(bbox_ll[1] + height, grid)]]
        standalone.append({**copy, "orientation": "R0", "origin": origin, "bbox": bbox, "align_anchor": origin, "align_bbox": bbox, "bbox_center": [snap((bbox[0][0] + bbox[1][0]) / 2, grid), snap((bbox[0][1] + bbox[1][1]) / 2, grid)], "group": None, "grid_position": {"row": None, "column": None}, "placement_role": "standalone"})
        x += width + macro_gap
    instances = [item for macro in macros for item in macro["instances"]] + standalone
    overlaps = []
    for index, left in enumerate(instances):
        for right in instances[index + 1:]:
            if bbox_overlap(left["bbox"], right["bbox"]):
                overlaps.append([left["name"], right["name"]])
    core_centers = {macro["name"]: macro["center"][0] for macro in macros}
    matching_checks = []
    for macro in macros:
        if len(macro["logical_devices"]) < 2:
            continue
        centroids = {}
        for logical in macro["logical_devices"]:
            members = [item for item in macro["instances"] if item["logical_device"] == logical and item["placement_role"] == "active"]
            centroids[logical] = [snap(sum(item["bbox_center"][axis] for item in members) / len(members), grid) for axis in (0, 1)]
        reference = centroids[macro["logical_devices"][0]]
        deltas = {logical: [snap(abs(center[axis] - reference[axis]), grid) for axis in (0, 1)] for logical, center in centroids.items()}
        matching_checks.append({"group": macro["name"], "physical_centroids": centroids, "delta_from_first": deltas, "common_centroid": all(delta == [0.0, 0.0] for delta in deltas.values())})
    overall_bbox = [[min(item["bbox"][0][0] for item in instances), min(item["bbox"][0][1] for item in instances)], [max(item["bbox"][1][0] for item in instances), max(item["bbox"][1][1] for item in instances)]]
    width, height = overall_bbox[1][0] - overall_bbox[0][0], overall_bbox[1][1] - overall_bbox[0][1]
    for item in instances:
        item["relative_center"] = [(item["bbox_center"][0] - overall_bbox[0][0]) / width, (item["bbox_center"][1] - overall_bbox[0][1]) / height]
    intent = {
        "schema": "analog-layout-align.pcell-placement-intent/v2",
        "source_schematic": schematic.get("source"),
        "coordinate_contract": {"space": "live Virtuoso evaluated PCell bbox", "units": "micron", "manufacturing_grid": grid, "device_bbox_gap": device_gap, "macro_gap": macro_gap, "bbox_overlap_legalized": True, "drc_signoff": False},
        "floorplan": {"bbox": overall_bbox, "core_axis_x": target_center, "core_macros": [m["name"] for m in macros], "output_side": "axis"},
        "macro_instances": [{key: value for key, value in macro.items() if key != "instances"} for macro in macros],
        "instances": instances,
        "groups": groups,
        "dummy_associations": load(plan / "dummy-associations.json"),
        "validation": {
            "expected_instances": len(copies), "placed_instances": len(instances), "missing_instances": sorted(set(copies_by_name) - {item["name"] for item in instances}),
            "all_mos_copies_have_m_1": all(item["pcell_parameters"].get("m") == "1" for item in instances if item["kind"] in ("nmos", "pmos")),
            "bbox_overlaps": overlaps, "bbox_overlap_free": not overlaps,
            "all_origins_on_manufacturing_grid": all(abs(value / grid - round(value / grid)) < 1e-6 for item in instances for value in item["origin"]),
            "core_center_x": core_centers, "core_center_aligned": all(abs(value - target_center) <= grid for value in core_centers.values()),
            "matching_checks": matching_checks,
            "dummy_families_associated": all(item["status"].startswith("associated") for item in load(plan / "dummy-associations.json")),
        },
    }
    from functional_groups import check_abba_geometry
    if policy and policy.get("mode", "stack") != "stack":
        intent["validation"]["ABBA_matching_checks"] = []
        for macro in macros:
            selected=[g for g in groups if g["name"]==macro["name"]]
            intent["validation"]["ABBA_matching_checks"].extend(check_abba_geometry(selected, instances, macro["center"][0], grid))
    else:
        intent["validation"]["ABBA_matching_checks"] = check_abba_geometry(groups, instances, target_center, grid)
    if overlaps or intent["validation"]["missing_instances"]:
        raise ValueError("Incomplete or overlapping placement; do not write")
    dump(plan / "placement-intent.json", intent)
    dump(plan / "pcell-floorplan.json", {"bbox": overall_bbox, "macros": macros, "standalone": standalone})
    source = schematic.get("source") or {}
    source_cell = source.get("cell") if isinstance(source, dict) else None
    render_svg(intent, plan / "placement.svg", f"{source_cell or 'Analog'} target-PDK PCell placement")
    summary_lines = [
        "# Target-PCell placement legalization",
        "",
        f"- Evaluated PCell variants: **{len(geometry['devices'])}**",
        f"- Placed explicit copies: **{len(instances)} / {len(copies)}**",
        f"- BBox overlap free: **{str(not overlaps).lower()}**",
        f"- Core macro center aligned at x = **{target_center:.3f} um**: **{str(intent['validation']['core_center_aligned']).lower()}**",
        f"- Dummy families associated: **{str(intent['validation']['dummy_families_associated']).lower()}**",
        f"- Floorplan bbox: **{overall_bbox[1][0] - overall_bbox[0][0]:.3f} um x {overall_bbox[1][1] - overall_bbox[0][1]:.3f} um**",
        "",
        "## Physical centroid checks",
        "",
    ]
    for check in matching_checks:
        summary_lines.append(f"- `{check['group']}`: common centroid **{str(check['common_centroid']).lower()}**, centers `{check['physical_centroids']}`")
    summary_lines.extend([
        "",
        f"The coordinates use live evaluated PCell bounding boxes and the {grid:g} um manufacturing grid. The configured {device_gap:g} um bbox gap prevents geometric overlap but is not a substitute for the foundry DRC deck. Routing, wells/guard rings, pins, extraction, LVS, and DRC were not run.",
        "",
    ])
    (plan / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"PCell legalization placed {len(instances)}/{len(copies)} copies; overlap_free={not overlaps}; core_center_aligned={intent['validation']['core_center_aligned']}")


def build_pcell_intent(schematic: dict[str, Any], placement: dict[str, Any], copies: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, Any]:
    leaf_by_name = {canonical_name(leaf["name"]): leaf for leaf in placement["leaf_instances"]}
    bbox = placement["bbox"]
    width, height = max(1.0, bbox[1][0] - bbox[0][0]), max(1.0, bbox[1][1] - bbox[0][1])
    instances: list[dict[str, Any]] = []
    missing: list[str] = []
    deferred: list[dict[str, Any]] = []
    inferred = infer_intent(schematic)
    for copy in copies:
        leaf = leaf_by_name.get(canonical_name(copy["align_instance"]))
        if leaf is None:
            missing.append(copy["name"])
            if copy["logical_device"] in inferred["dummies"]:
                deferred.append({
                    "name": copy["name"],
                    "logical_device": copy["logical_device"],
                    "copy_index": copy["copy_index"],
                    "pcell_master": copy["pcell_master"],
                    "pcell_parameters": copy["pcell_parameters"],
                    "terminals": copy["terminals"],
                    "placement_status": "deferred_dummy_edge_placement",
                    "reason": "ALIGN prunes four-terminal rail-tied devices before placement",
                })
            continue
        center = leaf["center"]
        instances.append({
            "name": copy["name"],
            "logical_device": copy["logical_device"],
            "copy_index": copy["copy_index"],
            "copy_count": copy["copy_count"],
            "kind": copy["kind"],
            "pcell_master": copy["pcell_master"],
            "pcell_parameters": copy["pcell_parameters"],
            "terminals": copy["terminals"],
            "group": copy.get("group"),
            "grid_position": {"row": copy.get("row"), "column": copy.get("column")},
            "align_path": leaf["path"],
            "align_bbox": leaf["bbox"],
            "align_center": center,
            "relative_center": [(center[0] - bbox[0][0]) / width, (center[1] - bbox[0][1]) / height],
            "orientation": leaf["orientation"],
        })
    by_logical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in instances:
        by_logical[item["logical_device"]].append(item)
    centroids = {
        logical: [sum(item["align_center"][axis] for item in items) / len(items) for axis in (0, 1)]
        for logical, items in by_logical.items()
    }
    matching_checks = []
    for group in groups:
        if len(group["logical_devices"]) != 2:
            continue
        left, right = group["logical_devices"]
        delta = [abs(centroids[left][axis] - centroids[right][axis]) for axis in (0, 1)] if left in centroids and right in centroids else [None, None]
        matching_checks.append({"group": group["name"], "logical_devices": [left, right], "centroid_delta": delta, "common_centroid": delta == [0.0, 0.0]})
    return {
        "schema": "analog-layout-align.pcell-placement-intent/v1",
        "source_schematic": schematic.get("source"),
        "coordinate_contract": {
            "space": "ALIGN mock-PDK",
            "absolute_coordinates_reusable": False,
            "reuse": ["instance identity", "PCell parameters", "grouping", "row/column order", "orientation intent", "relative centers"],
            "requires_target_pdk_legalization": True,
        },
        "instances": instances,
        "deferred_instances": deferred,
        "groups": [{key: value for key, value in group.items() if key != "constraints" and key != "instances" and key != "align_rows"} for group in groups],
        "validation": {
            "expected_instances": len(copies),
            "mapped_instances": len(instances),
            "missing_instances": missing,
            "deferred_dummy_instances": [item["name"] for item in deferred],
            "unexpected_missing_instances": [name for name in missing if name not in {item["name"] for item in deferred}],
            "all_mos_copies_have_m_1": all(item["pcell_parameters"].get("m") == "1" for item in instances if item["kind"] in ("nmos", "pmos")),
            "matching_checks": matching_checks,
        },
    }


def render_svg(intent: dict[str, Any], path: Path, title: str) -> None:
    items = intent["instances"]
    if not items:
        raise ValueError("Cannot render an empty placement intent")
    if "align_bbox" not in items[0]:
        xs = sorted({item["align_anchor"][0] for item in items})
        ys = sorted({item["align_anchor"][1] for item in items})
        dx = min((b - a for a, b in zip(xs, xs[1:]) if b > a), default=10000.0) * 0.72
        dy = min((b - a for a, b in zip(ys, ys[1:]) if b > a), default=10000.0) * 0.72
        for item in items:
            x, y = item["align_anchor"]
            item["align_bbox"] = [[x - dx / 2, y - dy / 2], [x + dx / 2, y + dy / 2]]
    all_bbox = placement_bbox([{"bbox": item["align_bbox"]} for item in items])
    width, height = max(1.0, all_bbox[1][0] - all_bbox[0][0]), max(1.0, all_bbox[1][1] - all_bbox[0][1])
    scale, margin = min(1000 / width, 700 / height), 50
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * scale + 2 * margin:.0f}" height="{height * scale + 2 * margin + 35:.0f}" viewBox="0 0 {width * scale + 2 * margin:.1f} {height * scale + 2 * margin + 35:.1f}">', '<rect width="100%" height="100%" fill="#0f172a"/>', f'<text x="{margin}" y="28" fill="white" font-family="sans-serif" font-size="18">{html.escape(title)}</text>']
    palette = ["#38bdf8", "#f59e0b", "#a78bfa", "#34d399", "#fb7185", "#facc15"]
    logical_names = sorted({item["logical_device"] for item in items})
    colors = {name: palette[index % len(palette)] for index, name in enumerate(logical_names)}
    for item in items:
        bbox = item["align_bbox"]
        x = margin + (bbox[0][0] - all_bbox[0][0]) * scale
        y = margin + 35 + (all_bbox[1][1] - bbox[1][1]) * scale
        w, h = max(2, (bbox[1][0] - bbox[0][0]) * scale), max(2, (bbox[1][1] - bbox[0][1]) * scale)
        label = item["name"]
        body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{colors[item["logical_device"]]}" fill-opacity="0.78" stroke="#f8fafc"/><text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" fill="#0f172a" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="8">{html.escape(label)}</text>')
    body.append("</svg>")
    path.write_text("\n".join(body), encoding="utf-8")


def write_summary(plan: Path, intent: dict[str, Any]) -> None:
    validation = intent["validation"]
    lines = [
        "# ALIGN explicit-m placement",
        "",
        "Routing, target-PDK legalization, and Virtuoso editing were not run.",
        "",
        f"- PCell-mappable instances: **{validation['mapped_instances']} / {validation['expected_instances']}**",
        f"- Deferred ALIGN-pruned dummy copies: **{len(validation['deferred_dummy_instances'])}**",
        f"- Complete for all non-pruned instances: **{str(validation.get('complete_for_nonpruned_instances', not validation['unexpected_missing_instances'])).lower()}**",
        f"- Every MOS copy has `m=1`: **{str(validation['all_mos_copies_have_m_1']).lower()}**",
        "",
        "## Matching checks",
        "",
    ]
    for check in validation["matching_checks"]:
        delta = check.get("centroid_delta", check.get("grid_centroid_delta"))
        lines.append(f"- `{check['logical_devices'][0]}` / `{check['logical_devices'][1]}`: centroid delta `{delta}`, common centroid **{str(check['common_centroid']).lower()}**")
    if intent.get("legalization_warnings"):
        lines.extend(["", "## Target-PDK legalization warnings", ""])
        for warning in intent["legalization_warnings"]:
            lines.append(f"- `{warning['group']}` differs in PCell parameters `{warning['differing_pcell_parameters']}`. {warning['message']}")
    lines.extend(["", "The absolute coordinates use the ALIGN mock PDK. Map the listed PCell masters and parameters, then legalize sizes and spacing in the active target PDK while preserving groups, row/column order, relative centers, and orientation intent.", ""])
    (plan / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def cmd_place(args: argparse.Namespace) -> None:
    plan = args.work / "plan"
    input_dir, run_dir = plan / "align", plan / "align-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.python), str(args.align_repo / "bin" / "schematic2layout.py"), str(input_dir),
        "-p", str(args.pdk), "-w", str(run_dir), "-n", str(args.nvariants), "-e", str(args.effort),
        "--flow_stop", "3_pnr:place", "--skipGDS", "--placer_sa_iterations", str(args.placer_sa_iterations),
        "--seed", str(args.seed),
    ]
    log_path = plan / "align-place.log"
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"ALIGN failed ({result.returncode}); see {log_path}")
    raw = find_raw_placement(run_dir)
    placement = normalize_align(load(raw))
    schematic = load(plan / "schematic.json")
    copies, _ = expand_mos_copies(schematic)
    saved_copies = load(plan / "device-copies.json")
    saved_by_name = {copy["name"]: copy for copy in saved_copies}
    for copy in copies:
        copy.update({key: saved_by_name[copy["name"]][key] for key in ("group", "row", "column") if key in saved_by_name[copy["name"]]})
    intent = build_pcell_intent(schematic, placement, copies, load(plan / "copy-groups.json"))
    dump(plan / "placement.json", placement)
    dump(plan / "placement-intent.json", intent)
    render_svg(intent, plan / "placement.svg", "ALIGN explicit m-copy placement")
    write_summary(plan, intent)
    print(f"placement complete: {raw}; mapped {len(intent['instances'])}/{len(copies)} PCell copies")


def cmd_recover(args: argparse.Namespace) -> None:
    plan = args.work / "plan"
    placement, intent = recover_pl_placement(plan)
    dump(plan / "placement.json", placement)
    dump(plan / "placement-intent.json", intent)
    render_svg(intent, plan / "placement.svg", "ALIGN explicit m-copy placement (.pl recovery)")
    write_summary(plan, intent)
    validation = intent["validation"]
    print(
        f"recovered {validation['mapped_instances']}/{validation['expected_instances']} PCell copies; "
        f"unexpected missing={len(validation['unexpected_missing_instances'])}"
    )


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name, function in (
        ("snapshot", cmd_snapshot), ("build", cmd_build), ("place", cmd_place), ("recover", cmd_recover),
        ("measure-pcells", cmd_measure_pcells), ("legalize-pcells", cmd_legalize_pcells),
    ):
        command = sub.add_parser(name)
        command.set_defaults(func=function)
        command.add_argument("--work", type=Path, required=True)
        if name == "snapshot":
            command.add_argument("--lib", required=True)
            command.add_argument("--cell", required=True)
        if name == "build":
            command.add_argument("--top", required=True)
            command.add_argument("--matching", choices=("common_axis", "common_centroid"), default="common_axis")
            command.add_argument("--constraints", type=Path, help="Saved matching, module_map and dummy_module_map constraints")
        if name == "place":
            command.add_argument("--align-repo", type=Path, required=True)
            command.add_argument("--python", type=Path, required=True)
            command.add_argument("--pdk", type=Path, required=True)
            command.add_argument("--seed", type=int, default=0)
            command.add_argument("--nvariants", type=int, default=1)
            command.add_argument("--effort", type=int, default=0)
            command.add_argument("--placer-sa-iterations", type=int, default=1000)
        if name == "measure-pcells":
            command.add_argument("--probe-lib", required=True)
            command.add_argument("--probe-cell", required=True)
        if name == "legalize-pcells":
            command.add_argument("--device-gap", type=float, default=0.5, help="bbox-to-bbox gap in target PDK microns")
            command.add_argument("--macro-gap", type=float, default=5.0, help="macro-to-macro gap in target PDK microns")
    return parser


def main() -> None:
    args = parser().parse_args()
    args.work = args.work.resolve()
    args.func(args)


if __name__ == "__main__":
    main()
