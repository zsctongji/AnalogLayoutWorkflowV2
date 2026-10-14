#!/usr/bin/env python3
"""Apply an analog-layout-align PCell placement intent to a new Virtuoso view."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


ANNOTATION_KIND = "analog-layout-align/drain-net"


def scalar(value: Any) -> float:
    match = re.fullmatch(
        r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*([pnumk]?)\s*",
        str(value),
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Cannot convert to scalar: {value!r}")
    number = float(match.group(1))
    scale = {"": 1.0, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3}
    return number * scale[match.group(2).lower()]


def q(value: Any) -> str:
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


def pcell_params(instance: dict[str, Any]) -> str:
    # Pass only geometry inputs exercised during live-PCell bbox measurement.
    # m is represented by explicit copies; each PCell record is one instance.
    if instance.get("pcell_parameter_entries") is not None:
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"analog-layout-workflow/scripts"))
        from project_config import typed_params
        return typed_params(instance,q)
    params = instance["pcell_parameters"]
    entries: list[str] = []
    if instance["kind"] == "capacitor":
        entries.append(f"list({q('w')} \"float\" {scalar(params['w']):.12g})")
        entries.append(f"list({q('l')} \"float\" {scalar(params['l']):.12g})")
    else:
        for key in ("w", "connectGates", "connectSD", "tap"):
            if key in params:
                entries.append(f"list({q(key)} \"string\" {q(params[key])})")
        for key in ("fw", "l", "fingers", "nf"):
            if key in params:
                entries.append(f"list({q(key)} \"float\" {scalar(params[key]):.12g})")
    return "list(" + " ".join(entries) + ")"


def capacitor_parameter_guard(instance: dict[str, Any], failure: str) -> str:
    """Check evaluated supermaster values, not instance override properties.

    Wrong dbCreateParamInst types can silently leave a default parameter active.
    The supported capacitor mapping uses SI-valued numeric w/l; fail closed for
    masters that do not satisfy that contract.
    """
    if instance.get('pcell_parameter_entries') is not None:
        # Mapped types/values must be evaluated by the PCell, not merely stored as overrides.
        checks=[]
        for e in instance['pcell_parameter_entries']:
            if e['type']=='string': test='equal(p~>value '+q(str(e['value']))+')'
            else:
                value=float(e['value']);tol=max(abs(value)*1e-9,1e-15)
                test=f'numberp(p~>value) && abs(p~>value-{value:.12g})<={tol:.12g}'
            checks.append('p=car(setof(v i~>master~>parameters~>value v~>name=='+q(e['name'])+')) unless(p && equal(p~>valueType '+q(e['type'])+') && '+test+' '+failure+')')
        return 'let((p) '+' '.join(checks)+') '
    if instance['kind'] != 'capacitor':
        return ''
    checks = []
    for key in ('w', 'l'):
        expected = scalar(instance['pcell_parameters'][key])
        if not math.isfinite(expected) or expected <= 0:
            raise ValueError(f"Invalid capacitor {key}: {expected}")
        checks.append(
            f'p=car(setof(v i~>master~>parameters~>value v~>name=={q(key)})) '
            f'unless(p && numberp(p~>value) && abs(p~>value-{expected:.12g})<={expected*1e-9:.12g} {failure})'
        )
    return 'let((p) ' + ' '.join(checks) + ') '


def validate_intent(intent: dict[str, Any]) -> list[dict[str, Any]]:
    if intent.get("schema") != "analog-layout-align.pcell-placement-intent/v2":
        raise ValueError(f"Unsupported schema: {intent.get('schema')!r}")
    instances = intent.get("instances", [])
    expected = intent.get("validation", {}).get("expected_instances")
    if not isinstance(expected, int) or expected < 1 or len(instances) != expected:
        raise ValueError(f"Invalid instance count: intent={expected!r}, records={len(instances)}")
    placed = intent.get("validation", {}).get("placed_instances")
    if placed is not None and placed != expected:
        raise ValueError(f"Intent is incomplete: expected={expected}, placed={placed}")
    names = [item["name"] for item in instances]
    if len(names) != len(set(names)):
        raise ValueError("Intent contains duplicate instance names")
    for item in instances:
        if item["kind"] in {"nmos", "pmos"} and str(item["pcell_parameters"].get("m")) != "1":
            raise ValueError(f"{item['name']} is not an explicit m=1 MOS copy")
    checks = intent.get("validation", {})
    for key in (
        "all_mos_copies_have_m_1",
        "all_origins_on_manufacturing_grid",
        "bbox_overlap_free",
        "dummy_families_associated",
    ):
        if checks.get(key) is not True:
            raise ValueError(f"Intent validation prerequisite failed: {key}")
    return instances


def build_apply_skill(instances: list[dict[str, Any]], lib: str, cell: str, view: str,
                      annotations: list[dict[str, str]] | None = None,
                      layer: str = "annotate", purpose: str = "drawing", height: float = .5) -> str:
    commands: list[str] = []
    for item in instances:
        master = item["pcell_master"]
        x, y = item["origin"]
        commands.append(
            "i=dbCreateParamInstByMasterName(cv "
            f"{q(master['lib'])} {q(master['cell'])} {q(master['view'])} {q(item['name'])} "
            f"list({float(x):.12g} {float(y):.12g}) {q(item['orientation'])} 1 {pcell_params(item)}) "
            f"if(i then {capacitor_parameter_guard(item, 'failures=cons(' + q(item['name'] + ':evaluated-capacitor-parameter') + ' failures)')}created=cons(i created) else failures=cons({q(item['name'])} failures))"
        )
    body = " ".join(commands)
    records = annotations or []
    if height <= 0 or not math.isfinite(height):
        raise ValueError("Annotation height must be finite and positive")
    labels = " ".join(annotation_commands(records, layer, purpose, height, "labels"))
    return (
        "prog((cv i term masterTerm pin candidate fig bb xy label labels created failures existing result) "
        f"existing=ddGetObj({q(lib)} {q(cell)} {q(view)}) "
        f"when(existing return({q('ERROR|target-exists')})) "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"w\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        f"{body} {labels} "
        f"if(failures || length(created)!={len(instances)} || length(labels)!={len(records)} then "
        "result=sprintf(nil \"ERROR|created=%d|failures=%L\" length(created) reverse(failures)) dbPurge(cv) "
        "else dbSave(cv) result=sprintf(nil \"OK|created=%d|shapes=%d\" length(cv~>instances) length(cv~>shapes)) dbClose(cv)) "
        "return(result))"
    )


def drain_annotation_records(instances: list[dict[str, Any]]) -> list[dict[str, str]]:
    records = []
    for item in instances:
        if item["kind"] not in {"nmos", "pmos"}:
            continue
        net = item.get("terminals", {}).get("D")
        if not net:
            raise ValueError(f"{item['name']} has no drain-net mapping")
        records.append({"instance": item["name"], "terminal": "D", "net": str(net), "text": f"D/{net}"})
    return records


def annotation_commands(records, layer, purpose, height, created_variable="created"):
    commands: list[str] = []
    for record in records:
        commands.append(
            f"i=car(setof(x cv~>instances x~>name=={q(record['instance'])})) "
            f"if(!i then failures=cons({q(record['instance'] + ':instance')} failures) else "
            f"term=car(setof(masterTerm i~>master~>terminals masterTerm~>name=={q(record['terminal'])})) "
            f"if(!term then failures=cons({q(record['instance'] + ':terminal-D')} failures) else "
            "fig=nil "
            "foreach(pin term~>pins foreach(candidate pin~>figs "
            "when(!fig fig=candidate) "
            "when(car(candidate~>lpp)==\"mt1\" fig=candidate))) "
            f"if(!fig then failures=cons({q(record['instance'] + ':pin-figure')} failures) else "
            "bb=dbTransformBBox(fig~>bBox i~>transform) "
            "xy=list((xCoord(car(bb))+xCoord(cadr(bb)))/2 (yCoord(car(bb))+yCoord(cadr(bb)))/2) "
            f"label=dbCreateLabel(cv list({q(layer)} {q(purpose)}) xy {q(record['text'])} "
            f"\"centerCenter\" \"R0\" \"roman\" {height:.12g}) "
            f"if(!label then failures=cons({q(record['instance'] + ':label')} failures) else "
            f"dbCreateProp(label \"alaKind\" \"string\" {q(ANNOTATION_KIND)}) "
            f"dbCreateProp(label \"alaInstance\" \"string\" {q(record['instance'])}) "
            f"dbCreateProp(label \"alaTerminal\" \"string\" {q(record['terminal'])}) "
            f"dbCreateProp(label \"alaNet\" \"string\" {q(record['net'])}) "
            f"{created_variable}=cons(label {created_variable})))))"
        )
    return commands


def build_annotate_skill(
    records: list[dict[str, str]],
    lib: str,
    cell: str,
    view: str,
    layer: str,
    purpose: str,
    height: float,
) -> str:
    commands = annotation_commands(records, layer, purpose, height)
    return (
        "prog((cv i term masterTerm pin candidate fig bb xy label created failures existing result) "
        "foreach(win hiGetWindowList() "
        f"when(win~>cellView && win~>cellView~>libName=={q(lib)} && win~>cellView~>cellName=={q(cell)} "
        f"&& win~>cellView~>viewName=={q(view)} return({q('ERROR|target-open-in-window')}))) "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"a\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        f"existing=setof(s cv~>shapes s~>objType==\"label\" && s~>alaKind=={q(ANNOTATION_KIND)}) "
        f"when(existing dbClose(cv) return({q('ERROR|drain-annotations-exist')})) "
        + " ".join(commands)
        + f" if(failures || length(created)!={len(records)} then "
        "result=sprintf(nil \"ERROR|created=%d|failures=%L\" length(created) reverse(failures)) dbPurge(cv) "
        "else dbSave(cv) result=sprintf(nil \"OK|annotations=%d|nets=%d|terminals=%d\" length(created) length(cv~>nets) length(cv~>terminals)) dbClose(cv)) "
        "return(result))"
    )


def parse_record(text: str) -> dict[str, Any]:
    fields = text.split("|")
    if not fields or fields[0] != "OK":
        return {"status": text}
    return {
        "status": "OK",
        "name": fields[1],
        "lib": fields[2],
        "cell": fields[3],
        "view": fields[4],
        "orientation": fields[5],
        "origin": [float(fields[6]), float(fields[7])],
        "bbox": [[float(fields[8]), float(fields[9])], [float(fields[10]), float(fields[11])]],
    }


def read_instance(client: Any, lib: str, cell: str, view: str, name: str) -> dict[str, Any]:
    expression = (
        "prog((cv i bb) "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"r\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        f"i=car(setof(x cv~>instances x~>name=={q(name)})) "
        f"unless(i dbClose(cv) return({q('MISSING|' + name)})) "
        "bb=dbTransformBBox(i~>master~>bBox i~>transform) "
        "return(sprintf(nil \"OK|%s|%s|%s|%s|%s|%.12g|%.12g|%.12g|%.12g|%.12g|%.12g\" "
        "i~>name i~>libName i~>cellName i~>viewName i~>orient "
        "xCoord(i~>xy) yCoord(i~>xy) xCoord(car(bb)) yCoord(car(bb)) xCoord(cadr(bb)) yCoord(cadr(bb)))))"
    )
    response = client.execute_skill(expression)
    if not response.ok:
        raise RuntimeError(f"Readback failed for {name}: {response.errors}")
    return parse_record(output_text(response.output))


def read_drain_annotation(
    client: Any, lib: str, cell: str, view: str, record: dict[str, str]
) -> dict[str, Any]:
    expression = (
        "prog((cv i term masterTerm pin candidate fig bb expected labels label out) "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"r\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        f"i=car(setof(x cv~>instances x~>name=={q(record['instance'])})) "
        f"unless(i dbClose(cv) return({q('ERROR|instance-missing')})) "
        f"term=car(setof(masterTerm i~>master~>terminals masterTerm~>name=={q(record['terminal'])})) "
        f"unless(term dbClose(cv) return({q('ERROR|terminal-missing')})) "
        "fig=nil foreach(pin term~>pins foreach(candidate pin~>figs "
        "when(!fig fig=candidate) when(car(candidate~>lpp)==\"mt1\" fig=candidate))) "
        f"unless(fig dbClose(cv) return({q('ERROR|pin-figure-missing')})) "
        "bb=dbTransformBBox(fig~>bBox i~>transform) "
        "expected=list((xCoord(car(bb))+xCoord(cadr(bb)))/2 (yCoord(car(bb))+yCoord(cadr(bb)))/2) "
        f"labels=setof(s cv~>shapes s~>objType==\"label\" && s~>alaKind=={q(ANNOTATION_KIND)} "
        f"&& s~>alaInstance=={q(record['instance'])} && s~>alaTerminal=={q(record['terminal'])}) "
        f"unless(length(labels)==1 dbClose(cv) return(sprintf(nil \"ERROR|label-count=%d\" length(labels)))) "
        "label=car(labels) "
        "out=sprintf(nil \"OK|%s|%s|%s|%s|%s|%s|%.12g|%.12g|%.12g|%.12g\" "
        "label~>alaInstance label~>alaTerminal label~>alaNet label~>theLabel car(label~>lpp) cadr(label~>lpp) "
        "xCoord(label~>xy) yCoord(label~>xy) xCoord(expected) yCoord(expected)) "
        "dbClose(cv) return(out))"
    )
    response = client.execute_skill(expression)
    if not response.ok:
        raise RuntimeError(f"Annotation readback failed for {record['instance']}: {response.errors}")
    fields = output_text(response.output).split("|")
    if not fields or fields[0] != "OK":
        return {"status": output_text(response.output), "instance": record["instance"]}
    return {
        "status": "OK",
        "instance": fields[1],
        "terminal": fields[2],
        "net": fields[3],
        "text": fields[4],
        "layer": fields[5],
        "purpose": fields[6],
        "xy": [float(fields[7]), float(fields[8])],
        "expected_xy": [float(fields[9]), float(fields[10])],
    }


def verify(
    client: Any,
    instances: list[dict[str, Any]],
    lib: str,
    cell: str,
    view: str,
    manufacturing_grid: float,
    annotation_records: list[dict[str, str]] | None = None,
    annotation_layer: str = "annotate",
    annotation_purpose: str = "drawing",
) -> dict[str, Any]:
    annotation_records = annotation_records or []
    summary_expr = (
        "prog((cv owned out) "
        f"cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} \"maskLayout\" \"r\") "
        f"unless(cv return({q('ERROR|open-failed')})) "
        f"owned=setof(s cv~>shapes s~>objType==\"label\" && s~>alaKind=={q(ANNOTATION_KIND)}) "
        "out=sprintf(nil \"OK|instances=%d|shapes=%d|annotations=%d|other_shapes=%d|nets=%d|terminals=%d\" "
        "length(cv~>instances) length(cv~>shapes) length(owned) length(cv~>shapes)-length(owned) length(cv~>nets) length(cv~>terminals)) "
        "dbClose(cv) return(out))"
    )
    response = client.execute_skill(summary_expr)
    if not response.ok:
        raise RuntimeError(response.errors)
    summary = output_text(response.output)
    summary_counts = {
        key: int(value)
        for key, value in re.findall(r"(instances|shapes|annotations|other_shapes|nets|terminals)=(\d+)", summary)
    }
    actual = {item["name"]: read_instance(client, lib, cell, view, item["name"]) for item in instances}
    mismatches: list[dict[str, Any]] = []
    coordinate_tol = 5e-7
    # Legalization stores an outward-snapped planning envelope. Evaluated
    # PCell geometry may sit up to one manufacturing grid inside that envelope.
    bbox_tol = manufacturing_grid + coordinate_tol
    max_bbox_delta = 0.0
    for expected in instances:
        got = actual[expected["name"]]
        reasons: list[str] = []
        master = expected["pcell_master"]
        if got.get("status") != "OK":
            reasons.append(got.get("status", "unknown readback failure"))
        else:
            if expected['kind'] == 'capacitor' or expected.get('pcell_parameter_entries') is not None:
                guard = capacitor_parameter_guard(expected, 'valid=nil')
                result = client.execute_skill(
                    'let((cv i valid out) '
                    f'cv=dbOpenCellViewByType({q(lib)} {q(cell)} {q(view)} "maskLayout" "r") '
                    f'i=car(setof(x cv~>instances x~>name=={q(expected["name"])})) '
                    f'valid=t {guard} out=if(valid "OK" "MISMATCH") dbClose(cv) out)'
                )
                got['evaluated_capacitor_dimensions_match'] = result.ok and output_text(result.output) == 'OK'
                if not got['evaluated_capacitor_dimensions_match']:
                    reasons.append('evaluated-capacitor-parameters')
            if [got["lib"], got["cell"], got["view"]] != [master["lib"], master["cell"], master["view"]]:
                reasons.append("master")
            if got["orientation"] != expected["orientation"]:
                reasons.append("orientation")
            if any(not math.isclose(a, float(b), abs_tol=coordinate_tol) for a, b in zip(got["origin"], expected["origin"])):
                reasons.append("origin")
            flat_got = [v for pair in got["bbox"] for v in pair]
            flat_expected = [float(v) for pair in expected["bbox"] for v in pair]
            deltas = [abs(a - b) for a, b in zip(flat_got, flat_expected)]
            max_bbox_delta = max(max_bbox_delta, *deltas)
            if any(delta > bbox_tol for delta in deltas):
                reasons.append("bbox")
        if reasons:
            mismatches.append({"name": expected["name"], "reasons": reasons, "expected": expected, "actual": got})

    # Reconfirm physical bbox non-overlap from the persisted view.
    overlaps: list[list[str]] = []
    present = [item for item in actual.values() if item.get("status") == "OK"]
    for index, left in enumerate(present):
        (lx0, ly0), (lx1, ly1) = left["bbox"]
        for right in present[index + 1 :]:
            (rx0, ry0), (rx1, ry1) = right["bbox"]
            if min(lx1, rx1) - max(lx0, rx0) > coordinate_tol and min(ly1, ry1) - max(ly0, ry0) > coordinate_tol:
                overlaps.append([left["name"], right["name"]])
    annotations = {
        record["instance"]: read_drain_annotation(client, lib, cell, view, record)
        for record in annotation_records
    }
    annotation_mismatches = []
    for record in annotation_records:
        got = annotations[record["instance"]]
        reasons = []
        if got.get("status") != "OK":
            reasons.append(got.get("status", "unknown annotation readback failure"))
        else:
            if [got["instance"], got["terminal"], got["net"], got["text"]] != [
                record["instance"], record["terminal"], record["net"], record["text"]
            ]:
                reasons.append("mapping")
            if [got["layer"], got["purpose"]] != [annotation_layer, annotation_purpose]:
                reasons.append("lpp")
            if any(not math.isclose(a, b, abs_tol=coordinate_tol) for a, b in zip(got["xy"], got["expected_xy"])):
                reasons.append("pin-center")
        if reasons:
            annotation_mismatches.append({"instance": record["instance"], "reasons": reasons, "actual": got})
    placement_only = (
        summary_counts.get("nets") == 0
        and summary_counts.get("terminals") == 0
        and summary_counts.get("other_shapes") == 0
        and summary_counts.get("annotations") == len(annotation_records)
    )
    report = {
        "target": {"lib": lib, "cell": cell, "view": view},
        "summary": summary,
        "top_level_counts": summary_counts,
        "placement_only": placement_only,
        "expected_instances": len(instances),
        "readback_instances": len(present),
        "readback_match": not mismatches,
        "manufacturing_grid": manufacturing_grid,
        "max_bbox_delta": max_bbox_delta,
        "bbox_matches_within_one_grid": max_bbox_delta <= bbox_tol,
        "bbox_overlap_free": not overlaps,
        "mismatches": mismatches,
        "bbox_overlaps": overlaps,
        "drain_annotations": {
            "expected": len(annotation_records),
            "readback": len([item for item in annotations.values() if item.get("status") == "OK"]),
            "layer": annotation_layer,
            "purpose": annotation_purpose,
            "electrical_objects_created": False,
            "mismatches": annotation_mismatches,
            "items": sorted(annotations.values(), key=lambda item: item.get("instance", "")),
        },
        "instances": sorted(actual.values(), key=lambda item: item.get("name", "")),
    }
    return report


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("intent", type=Path)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--lib", required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--view", default="layout")
    parser.add_argument("--report", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--annotate-only", action="store_true")
    parser.add_argument(
        "--annotate-drains",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="add/expect non-electrical D/<net> labels (default: enabled)",
    )
    parser.add_argument("--annotation-layer", default="annotate")
    parser.add_argument("--annotation-purpose", default="drawing")
    parser.add_argument("--annotation-height", type=float, default=0.5)
    return parser


def main() -> None:
    args = parser().parse_args()

    intent = json.loads(args.intent.read_text(encoding="utf-8"))
    instances = validate_intent(intent)
    from virtuoso_bridge import VirtuosoClient
    from virtuoso_bridge.env import set_runtime_env_file

    set_runtime_env_file(args.env)
    client = VirtuosoClient.from_env()

    if args.annotation_height <= 0:
        raise ValueError("--annotation-height must be positive")
    annotations = drain_annotation_records(instances) if (args.annotate_drains or args.annotate_only) else []
    apply_text = "SKIPPED|existing-target"
    annotation_apply_text = "SKIPPED|not-requested"
    if args.annotate_only:
        pre_report = verify(client, instances, args.lib, args.cell, args.view, manufacturing_grid=float(intent["coordinate_contract"]["manufacturing_grid"]))
        if not pre_report["readback_match"] or not pre_report["bbox_overlap_free"] or not pre_report["placement_only"]:
            raise RuntimeError("Refusing annotation: existing target does not pass unannotated placement readback")
    elif not args.verify_only:
        apply_response = client.execute_skill(build_apply_skill(instances, args.lib, args.cell, args.view, annotations, args.annotation_layer, args.annotation_purpose, args.annotation_height))
        apply_text = output_text(apply_response.output)
        if not apply_response.ok or not apply_text.startswith("OK|"):
            raise RuntimeError(f"Apply failed: output={apply_response.output!r}, errors={apply_response.errors}")
        if annotations:
            annotation_apply_text = "OK|included-in-placement-transaction"
    if annotations and args.annotate_only and not args.verify_only:
        annotation_response = client.execute_skill(
            build_annotate_skill(
                annotations,
                args.lib,
                args.cell,
                args.view,
                args.annotation_layer,
                args.annotation_purpose,
                args.annotation_height,
            )
        )
        annotation_apply_text = output_text(annotation_response.output)
        if not annotation_response.ok or not annotation_apply_text.startswith("OK|"):
            raise RuntimeError(
                f"Annotation failed: output={annotation_response.output!r}, errors={annotation_response.errors}"
            )
    manufacturing_grid = float(intent["coordinate_contract"]["manufacturing_grid"])
    report = verify(
        client,
        instances,
        args.lib,
        args.cell,
        args.view,
        manufacturing_grid,
        annotation_records=annotations,
        annotation_layer=args.annotation_layer,
        annotation_purpose=args.annotation_purpose,
    )
    report["apply"] = apply_text
    report["annotation_apply"] = annotation_apply_text
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "instances"}, indent=2, ensure_ascii=False))
    if (
        not report["readback_match"]
        or not report["bbox_overlap_free"]
        or not report["placement_only"]
        or report["drain_annotations"]["mismatches"]
        or report["readback_instances"] != len(instances)
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
