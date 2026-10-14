#!/usr/bin/env python3
"""Extract and validate a read-only Virtuoso technology routing profile."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "analog-pdk-profile/v1"
FINGERPRINT_ALGORITHM = "sha256"
UNKNOWN_SIGNOFF_CATEGORIES = [
    "antenna",
    "density",
    "electromigration",
    "end_of_line",
    "high_voltage_context",
    "latchup",
    "notch",
    "reliability",
]


def quote_skill(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def output_text(value: Any) -> str:
    text = str(value)
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            decoded = json.loads(text)
            if isinstance(decoded, str):
                return decoded
        except json.JSONDecodeError:
            pass
    return text


TOKEN = re.compile(r'\s*(?:(\()|(\))|("(?:\\.|[^"\\])*")|([^\s()]+))')


def parse_lisp(value: str) -> Any:
    """Parse the small list/atom subset emitted by SKILL %L."""
    tokens: list[Any] = []
    for match in TOKEN.finditer(value.strip()):
        left, right, quoted, atom = match.groups()
        if left:
            tokens.append("(")
        elif right:
            tokens.append(")")
        elif quoted is not None:
            tokens.append(("atom", json.loads(quoted)))
        elif atom is not None:
            lowered = atom.lower()
            if lowered == "nil":
                parsed: Any = None
            elif lowered == "t":
                parsed = True
            else:
                try:
                    parsed = float(atom) if any(char in atom for char in ".eE") else int(atom)
                except ValueError:
                    parsed = atom
            tokens.append(("atom", parsed))

    def consume(index: int) -> tuple[Any, int]:
        if index >= len(tokens):
            raise ValueError(f"Unexpected end of SKILL value: {value!r}")
        token = tokens[index]
        if token == "(":
            result = []
            index += 1
            while index < len(tokens) and tokens[index] != ")":
                item, index = consume(index)
                result.append(item)
            if index >= len(tokens):
                raise ValueError(f"Unclosed SKILL list: {value!r}")
            return result, index + 1
        if token == ")":
            raise ValueError(f"Unexpected ')' in SKILL value: {value!r}")
        return token[1], index + 1

    if not tokens:
        return None
    parsed, next_index = consume(0)
    if next_index != len(tokens):
        raise ValueError(f"Trailing SKILL tokens: {value!r}")
    return parsed


def build_skill_expression(lib: str, cell: str, view: str, constraint_group: str) -> str:
    return (
        "prog((cv tf cg out grid funcs) out=\"\" "
        f"cv=dbOpenCellViewByType({quote_skill(lib)} {quote_skill(cell)} {quote_skill(view)} \"maskLayout\" \"r\") "
        "unless(cv return(\"ERROR|open-failed\")) "
        "tf=techGetTechFile(cv) unless(tf dbClose(cv) return(\"ERROR|tech-file-missing\")) "
        f"cg=car(setof(g tf~>constraintGroups g~>name=={quote_skill(constraint_group)})) "
        "unless(cg out=strcat(out \"ERROR|constraint-group-missing|\") "
        "foreach(g tf~>constraintGroups out=strcat(out sprintf(nil \"%s,\" g~>name))) dbClose(cv) return(out)) "
        "grid=techGetMfgGridResolution(tf) "
        "out=strcat(out sprintf(nil \"@M|%s|%s|%s|%.12g^\" tf~>libName tf~>fileName tf~>timeStamp grid)) "
        "foreach(l tf~>layers out=strcat(out sprintf(nil \"@L|%s|%d|%s|%L^\" l~>name l~>number l~>material l~>valid))) "
        "foreach(lp tf~>lps out=strcat(out sprintf(nil \"@P|%s|%s|%L|%L^\" lp~>layer~>name lp~>purpose lp~>valid lp~>selectable))) "
        "funcs=techGetLayerFunctions(tf) "
        "foreach(f funcs out=strcat(out sprintf(nil \"@F|%s|%s|%L^\" car(f) cadr(f) if(length(f)>2 caddr(f) nil)))) "
        "foreach(o cg~>objects out=strcat(out sprintf(nil \"@C|%s|%s|%s|%s|%L|%L|%L^\" "
        "o~>name o~>defName if(o~>layers car(o~>layers) \"\") "
        "if(length(o~>layers)>1 cadr(o~>layers) \"\") o~>value o~>params o~>hard))) "
        "foreach(v tf~>viaDefs out=strcat(out sprintf(nil \"@V|%s|%s|%s|%.12g|%L^\" "
        "v~>name v~>layer1~>name v~>layer2~>name v~>resistancePerCut v~>params))) "
        "dbClose(cv) return(out))"
    )


def parse_records(text: str) -> dict[str, Any]:
    if text.startswith("ERROR|"):
        raise RuntimeError(text)
    result: dict[str, Any] = {
        "layers": [],
        "layer_purposes": [],
        "layer_functions": [],
        "constraints": [],
        "vias": [],
    }
    for record in (item for item in text.split("^") if item):
        fields = record.split("|")
        kind = fields[0]
        if kind == "@M" and len(fields) == 5:
            result["technology"] = {
                "library": fields[1],
                "file": fields[2],
                "timestamp": fields[3],
            }
            result["manufacturing_grid_um"] = float(fields[4])
        elif kind == "@L" and len(fields) == 5:
            result["layers"].append(
                {"name": fields[1], "number": int(fields[2]), "material": fields[3], "valid": parse_lisp(fields[4])}
            )
        elif kind == "@P" and len(fields) == 5:
            result["layer_purposes"].append(
                {"layer": fields[1], "purpose": fields[2], "valid": parse_lisp(fields[3]), "selectable": parse_lisp(fields[4])}
            )
        elif kind == "@F" and len(fields) == 4:
            result["layer_functions"].append(
                {"layer": fields[1], "function": fields[2], "rank": parse_lisp(fields[3])}
            )
        elif kind == "@C" and len(fields) == 8:
            layers = [name for name in fields[3:5] if name]
            result["constraints"].append(
                {
                    "name": fields[1],
                    "definition": fields[2],
                    "layers": layers,
                    "value": parse_lisp(fields[5]),
                    "parameters": parse_lisp(fields[6]),
                    "hard": parse_lisp(fields[7]),
                }
            )
        elif kind == "@V" and len(fields) == 6:
            result["vias"].append(
                {
                    "name": fields[1],
                    "layer1": fields[2],
                    "layer2": fields[3],
                    "resistance_per_cut": float(fields[4]),
                    "raw_parameters": parse_lisp(fields[5]),
                }
            )
        else:
            raise ValueError(f"Malformed technology record: {record!r}")
    if "technology" not in result:
        raise ValueError("Technology metadata record is missing")
    return result


def normalize_via(via: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(via)
    params = result.get("raw_parameters")
    if isinstance(params, list) and len(params) >= 8:
        result["standard_geometry"] = {
            "cut_layer": params[0],
            "cut_size_um": [params[1], params[2]],
            "rows": params[3],
            "columns": params[4],
            "cut_spacing_um": params[5],
            "layer1_enclosure_um": params[6],
            "layer2_enclosure_um": params[7],
        }
    else:
        result["standard_geometry"] = None
    return result


def fingerprint_payload(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "technology": profile["technology"],
        "manufacturing_grid_um": profile["manufacturing_grid_um"],
        "layers": profile["layers"],
        "layer_purposes": profile["layer_purposes"],
        "layer_functions": profile["layer_functions"],
        "constraints": profile["constraints"],
        "routing_layers": profile["routing_layers"],
        "vias": profile["vias"],
    }


def compute_fingerprint(profile: dict[str, Any]) -> str:
    canonical = json.dumps(fingerprint_payload(profile), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_profile(profile: dict[str, Any], check_fingerprint: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if profile.get("schema") != SCHEMA:
        errors.append(f"unsupported schema: {profile.get('schema')!r}")
    grid = profile.get("manufacturing_grid_um")
    if not isinstance(grid, (int, float)) or grid <= 0:
        errors.append("manufacturing_grid_um must be positive")
    for key in ("technology", "layers", "layer_purposes", "layer_functions", "constraints", "routing_layers", "vias", "coverage"):
        if key not in profile:
            errors.append(f"missing required field: {key}")
    layer_names = [item.get("name") for item in profile.get("layers", []) if isinstance(item, dict)]
    if len(layer_names) != len(set(layer_names)):
        errors.append("duplicate layer names")
    known_layers = set(layer_names)
    constraints = profile.get("constraints", {})
    rules = constraints.get("rules", []) if isinstance(constraints, dict) else []
    if not isinstance(constraints, dict):
        errors.append("constraints must be an object")
    for rule in rules:
        unknown = set(rule.get("layers", [])) - known_layers
        if unknown:
            errors.append(f"constraint {rule.get('name')} references unknown layers {sorted(unknown)}")
    for layer in profile.get("routing_layers", []):
        if layer.get("layer") not in known_layers:
            errors.append(f"routing layer {layer.get('layer')!r} is unknown")
        for key in ("minimum_width_rules", "minimum_spacing_rules"):
            for rule in layer.get(key, []):
                value = rule.get("value")
                if not isinstance(value, (int, float)) or value <= 0:
                    errors.append(f"{layer.get('layer')} has non-positive or non-scalar {key}: {value!r}")
    for via in profile.get("vias", []):
        unknown = {via.get("layer1"), via.get("layer2")} - known_layers
        if unknown:
            errors.append(f"via {via.get('name')} references unknown layers {sorted(unknown)}")
        geometry = via.get("standard_geometry")
        if geometry is None:
            warnings.append(f"via {via.get('name')} has no normalized standard geometry")
    if check_fingerprint:
        try:
            expected_fingerprint = compute_fingerprint(profile)
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"fingerprint cannot be computed: {error}")
        else:
            if profile.get("fingerprint", {}).get("value") != expected_fingerprint:
                errors.append("profile fingerprint mismatch")
    if not profile.get("coverage", {}).get("basic_routing_ready", False):
        warnings.append("basic routing coverage is incomplete")
    warnings.append("profile is preflight evidence only; original foundry DRC/LVS decks remain authoritative")
    return {"structurally_valid": not errors, "errors": errors, "warnings": sorted(set(warnings))}


def build_profile(raw: dict[str, Any], source_target: dict[str, str], constraint_group: str) -> dict[str, Any]:
    functions = {item["layer"]: item for item in raw["layer_functions"]}
    route_names = {
        item["layer"] for item in raw["layer_functions"] if str(item.get("function", "")).lower() == "metal"
    }
    route_names |= {item["name"] for item in raw["layers"] if str(item.get("material", "")).lower() == "metal"}
    route_order = sorted(
        route_names,
        key=lambda name: (
            functions.get(name, {}).get("rank") is None,
            functions.get(name, {}).get("rank") or 0,
            name,
        ),
    )
    constraints = raw["constraints"]
    routing_layers = []
    missing_rules = []
    for name in route_order:
        widths = [rule for rule in constraints if rule["definition"] == "minWidth" and rule["layers"] == [name]]
        spaces = [rule for rule in constraints if rule["definition"] == "minSpacing" and rule["layers"] == [name]]
        if not widths or not spaces:
            missing_rules.append({"layer": name, "min_width": bool(widths), "min_spacing": bool(spaces)})
        routing_layers.append(
            {
                "layer": name,
                "rank": functions.get(name, {}).get("rank"),
                "preferred_direction": None,
                "minimum_width_rules": widths,
                "minimum_spacing_rules": spaces,
            }
        )
    vias = [normalize_via(item) for item in raw["vias"]]
    via_pairs = {frozenset((item["layer1"], item["layer2"])) for item in vias if item["standard_geometry"]}
    adjacent_pairs = [route_order[index : index + 2] for index in range(max(0, len(route_order) - 1))]
    missing_vias = [pair for pair in adjacent_pairs if frozenset(pair) not in via_pairs]
    basic_ready = bool(route_order) and not missing_rules and not missing_vias
    profile: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "source_target": source_target,
        "technology": {**raw["technology"], "constraint_group": constraint_group},
        "manufacturing_grid_um": raw["manufacturing_grid_um"],
        "layers": raw["layers"],
        "layer_purposes": raw["layer_purposes"],
        "layer_functions": raw["layer_functions"],
        "constraints": {"group": constraint_group, "rules": constraints},
        "routing_layers": routing_layers,
        "vias": vias,
        "coverage": {
            "basic_routing_ready": basic_ready,
            "routing_layer_count": len(route_order),
            "constraint_count": len(constraints),
            "via_count": len(vias),
            "missing_basic_layer_rules": missing_rules,
            "missing_adjacent_metal_vias": missing_vias,
            "unknown_signoff_categories": UNKNOWN_SIGNOFF_CATEGORIES,
            "signoff_complete": False,
        },
        "boundaries": {
            "may_drive_automatic_routing": basic_ready,
            "foundry_signoff_equivalent": False,
            "requires_original_drc_lvs": True,
        },
    }
    profile["fingerprint"] = {
        "algorithm": FINGERPRINT_ALGORITHM,
        "value": compute_fingerprint(profile),
        "scope": "canonical extracted technology identity, grid, layers, LPPs, constraints, routing layers, and vias",
    }
    profile["validation"] = validate_profile(profile)
    return profile


def markdown_report(profile: dict[str, Any]) -> str:
    coverage = profile["coverage"]
    lines = [
        "# Analog PDK routing profile",
        "",
        f"- Source: `{profile['source_target']['lib']}/{profile['source_target']['cell']}/{profile['source_target']['view']}`",
        f"- Technology library: `{profile['technology']['library']}`",
        f"- Technology timestamp: `{profile['technology']['timestamp']}`",
        f"- Constraint group: `{profile['technology']['constraint_group']}`",
        f"- Manufacturing grid: **{profile['manufacturing_grid_um']:.6g} µm**",
        f"- Fingerprint: `{profile['fingerprint']['value']}`",
        f"- Structural validation: **{profile['validation']['structurally_valid']}**",
        f"- Basic routing ready: **{coverage['basic_routing_ready']}**",
        "",
        "## Routing layers",
        "",
        "| Layer | Rank | Min-width values (µm) | Min-spacing values (µm) | Preferred direction |",
        "|---|---:|---|---|---|",
    ]
    for layer in profile["routing_layers"]:
        widths = ", ".join(str(item["value"]) for item in layer["minimum_width_rules"]) or "missing"
        spaces = ", ".join(str(item["value"]) for item in layer["minimum_spacing_rules"]) or "missing"
        lines.append(f"| `{layer['layer']}` | {layer['rank']} | {widths} | {spaces} | unknown |")
    lines += ["", "## Vias", "", "| Via | Layers | Cut layer | Cut size (µm) | Enclosures (µm) |", "|---|---|---|---|---|"]
    for via in profile["vias"]:
        geometry = via["standard_geometry"]
        if geometry:
            lines.append(
                f"| `{via['name']}` | `{via['layer1']}`–`{via['layer2']}` | `{geometry['cut_layer']}` | "
                f"{geometry['cut_size_um']} | {geometry['layer1_enclosure_um']} / {geometry['layer2_enclosure_um']} |"
            )
        else:
            lines.append(f"| `{via['name']}` | `{via['layer1']}`–`{via['layer2']}` | unknown | unknown | unknown |")
    lines += [
        "",
        "## Coverage gaps",
        "",
        f"- Missing basic layer rules: `{coverage['missing_basic_layer_rules']}`",
        f"- Missing adjacent-metal vias: `{coverage['missing_adjacent_metal_vias']}`",
        f"- Unknown signoff categories: `{', '.join(coverage['unknown_signoff_categories'])}`",
        "",
        "This profile is read-only preflight evidence. It does not replace the original foundry DRC/LVS decks.",
        "",
    ]
    return "\n".join(lines)


def extract_command(args: argparse.Namespace) -> int:
    from virtuoso_bridge import VirtuosoClient
    from virtuoso_bridge.env import set_runtime_env_file

    set_runtime_env_file(str(args.env.resolve()))
    client = VirtuosoClient.from_env()
    probe = client.execute_skill("1+2")
    if not probe.ok or output_text(probe.output) != "3":
        raise RuntimeError(f"Bridge round-trip failed: {probe.errors or probe.output}")
    expression = build_skill_expression(args.lib, args.cell, args.view, args.constraint_group)
    response = client.execute_skill(expression)
    if not response.ok:
        raise RuntimeError(response.errors)
    raw = parse_records(output_text(response.output))
    profile = build_profile(raw, {"lib": args.lib, "cell": args.cell, "view": args.view}, args.constraint_group)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.report.write_text(markdown_report(profile), encoding="utf-8")
    print(
        json.dumps(
            {
                "profile": str(args.out),
                "report": str(args.report),
                "technology": profile["technology"]["library"],
                "fingerprint": profile["fingerprint"]["value"],
                "basic_routing_ready": profile["coverage"]["basic_routing_ready"],
                "validation": profile["validation"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if profile["validation"]["structurally_valid"] else 2


def validate_command(args: argparse.Namespace) -> int:
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    validation = validate_profile(profile)
    result = {
        "profile": str(args.profile),
        "fingerprint": profile.get("fingerprint", {}).get("value"),
        "basic_routing_ready": profile.get("coverage", {}).get("basic_routing_ready", False),
        "validation": validation,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if validation["structurally_valid"] else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--env", type=Path, required=True)
    extract.add_argument("--lib", required=True)
    extract.add_argument("--cell", required=True)
    extract.add_argument("--view", default="layout")
    extract.add_argument("--constraint-group", required=True)
    extract.add_argument("--out", type=Path, required=True)
    extract.add_argument("--report", type=Path, required=True)
    extract.set_defaults(func=extract_command)
    validate = commands.add_parser("validate")
    validate.add_argument("profile", type=Path)
    validate.set_defaults(func=validate_command)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
