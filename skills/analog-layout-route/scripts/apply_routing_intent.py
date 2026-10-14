#!/usr/bin/env python3
"""Transactionally materialize and read back a reviewed analog routing intent."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("analog_layout_route_intent", HERE / "route_intent.py")
ROUTE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ROUTE)

# Virtuoso may retain sub-grid binary floating-point residue in transformed
# mirrored bBoxes.  Keep the drift guard much tighter than any supported
# manufacturing grid while avoiding exact-list equality false positives.
PLACEMENT_TOLERANCE_UM = 1e-6
SVG_CHECK_SCHEMA = "analog-layout-route.svg-check/v1"


def q(value: Any) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def point(value: list[float]) -> str:
    return f"list({float(value[0]):.12g} {float(value[1]):.12g})"


def points(value: list[list[float]]) -> str:
    return "list(" + " ".join(point(item) for item in value) + ")"


def bbox(value: list[list[float]]) -> str:
    return f"list({point(value[0])} {point(value[1])})"


def point_close(actual: str, expected: list[float]) -> str:
    tol = f"{PLACEMENT_TOLERANCE_UM:.12g}"
    return (
        f"abs(difference(car({actual}) {float(expected[0]):.12g}))<={tol} && "
        f"abs(difference(cadr({actual}) {float(expected[1]):.12g}))<={tol}"
    )


def bbox_close(actual: str, expected: list[list[float]]) -> str:
    tol = f"{PLACEMENT_TOLERANCE_UM:.12g}"
    return " && ".join((
        f"abs(difference(car(car({actual})) {float(expected[0][0]):.12g}))<={tol}",
        f"abs(difference(cadr(car({actual})) {float(expected[0][1]):.12g}))<={tol}",
        f"abs(difference(car(cadr({actual})) {float(expected[1][0]):.12g}))<={tol}",
        f"abs(difference(cadr(cadr({actual})) {float(expected[1][1]):.12g}))<={tol}",
    ))


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


def validate_inputs(profile: dict[str, Any], terminal_access: dict[str, Any], intent: dict[str, Any]) -> None:
    errors = ROUTE.validate(profile, intent)
    if terminal_access.get("schema") != ROUTE.ACCESS_SCHEMA:
        errors.append("unsupported terminal-access schema")
    if terminal_access.get("target") != intent.get("target"):
        errors.append("terminal-access target differs from intent target")
    if ROUTE.digest(terminal_access) != intent.get("sources", {}).get("terminal_access_sha256"):
        errors.append("terminal-access hash drift")
    coverage = intent.get("physical_access_coverage", {})
    if coverage and not coverage.get("complete"):
        errors.append("physical pin-island coverage is incomplete")
    ids = [item["id"] for key in ("routes", "vias", "contact_landings") for item in intent.get(key, [])]
    if len(ids) != len(set(ids)):
        errors.append("intent contains duplicate object ids")
    if errors:
        raise ValueError("; ".join(errors))


def validate_svg_check(intent: dict[str, Any], svg_check: dict[str, Any]) -> None:
    errors = []
    if svg_check.get("schema") != SVG_CHECK_SCHEMA:
        errors.append("unsupported SVG-check schema")
    if svg_check.get("status") != "PASS" or svg_check.get("errors"):
        errors.append("SVG check is not passing")
    if svg_check.get("target") != intent.get("target"):
        errors.append("SVG-check target differs from intent target")
    if svg_check.get("intent_sha256") != ROUTE.digest(intent):
        errors.append("SVG-check intent hash drift")
    if not str(svg_check.get("svg_sha256", "")).strip():
        errors.append("SVG check lacks a preview fingerprint")
    if errors:
        raise ValueError("; ".join(errors))


def tag(obj: str, kind: str, object_id: str, net: str, intent_hash: str, profile_hash: str) -> str:
    values = (("alrKind", kind), ("alrObjectId", object_id), ("alrNet", net),
              ("alrIntentSha256", intent_hash), ("alrProfileFingerprint", profile_hash))
    return " ".join(f"dbReplaceProp({obj} {q(name)} \"string\" {q(value)})" for name, value in values)


def build_apply_skill(intent: dict[str, Any], terminal_access: dict[str, Any] | None = None) -> str:
    target = intent["target"]; intent_hash = ROUTE.digest(intent); profile_hash = intent["sources"]["profile_fingerprint"]
    nets = sorted({item["net"] for key in ("routes", "vias", "contact_landings") for item in intent.get(key, [])})
    commands = []
    placement_checks = []
    for instance in (terminal_access or {}).get("instances", []):
        expected_bbox = instance.get("bbox")
        expected_origin = instance.get("origin")
        expected_master = instance.get("master", {})
        if not (expected_bbox and expected_origin):
            continue
        placement_checks.append(
            f"inst=car(setof(x cv~>instances x~>name=={q(instance['name'])})) "
            f"if(!inst then failures=cons({q(instance['name']+':missing')} failures) else "
            f"ibbox=dbTransformBBox(inst~>master~>bBox inst~>transform) "
            f"unless({point_close('inst~>xy', expected_origin)} && inst~>orient=={q(instance['orientation'])} "
            f"&& {bbox_close('ibbox', expected_bbox)} "
            + (f"&& inst~>libName=={q(expected_master.get('lib'))} && inst~>cellName=={q(expected_master.get('cell'))} && inst~>viewName=={q(expected_master.get('view'))} " if expected_master else "")
            + f"failures=cons({q(instance['name']+':placement-drift')} failures)))"
        )
    for net in nets:
        commands.append(
            f"net=car(setof(n cv~>nets n~>name=={q(net)})) when(!net net=dbCreateNet(cv {q(net)})) "
            f"if(net then netTable[{q(net)}]=net else failures=cons({q('net:'+net)} failures))"
        )
    for route in intent.get("routes", []):
        commands.append(
            f"existing=setof(x cv~>shapes x~>alrObjectId=={q(route['id'])}) "
            f"if(existing then failures=cons({q(route['id']+':exists')} failures) else "
            f"obj=dbCreatePath(cv list({q(route['layer'])} {q(route['purpose'])}) {points(route['points_um'])} {float(route['width_um']):.12g}) "
            f"if(obj then dbAddFigToNet(obj netTable[{q(route['net'])}]) {tag('obj','route',route['id'],route['net'],intent_hash,profile_hash)} created=cons(obj created) "
            f"else failures=cons({q(route['id']+':create')} failures)))"
        )
    for via in intent.get("vias", []):
        commands.append(
            f"existing=setof(x cv~>vias x~>alrObjectId=={q(via['id'])}) "
            f"if(existing then failures=cons({q(via['id']+':exists')} failures) else "
            f"viaDef=techFindViaDefByName(tf {q(via['via'])}) "
            f"if(!viaDef then failures=cons({q(via['id']+':via-def')} failures) else "
            f"obj=dbCreateVia(cv viaDef {point(via['xy_um'])} \"R0\" nil) "
            f"if(obj then dbAddFigToNet(obj netTable[{q(via['net'])}]) {tag('obj','via',via['id'],via['net'],intent_hash,profile_hash)} created=cons(obj created) "
            f"else failures=cons({q(via['id']+':create')} failures))))"
        )
    for landing in intent.get("contact_landings", []):
        extension_id = landing["id"] + ":extension"; via_id = landing["id"] + ":via"
        commands.append(
            f"existing=append(setof(x cv~>shapes x~>alrObjectId=={q(extension_id)}) setof(x cv~>vias x~>alrObjectId=={q(via_id)})) "
            f"if(existing then failures=cons({q(landing['id']+':exists')} failures) else progn("
            f"ext=dbCreateRect(cv list({q(landing['source_layer'])} {q(landing['purpose'])}) {bbox(landing['extension_bbox_um'])}) "
            f"viaDef=techFindViaDefByName(tf {q(landing['via'])}) "
            f"when(viaDef viaObj=dbCreateVia(cv viaDef {point(landing['xy_um'])} \"R0\" nil)) "
            f"if(ext&&viaObj then dbAddFigToNet(ext netTable[{q(landing['net'])}]) dbAddFigToNet(viaObj netTable[{q(landing['net'])}]) "
            f"{tag('ext','contact-extension',extension_id,landing['net'],intent_hash,profile_hash)} "
            f"{tag('viaObj','contact-via',via_id,landing['net'],intent_hash,profile_hash)} created=cons(ext created) created=cons(viaObj created) "
            f"else failures=cons({q(landing['id']+':create')} failures))))"
        )
    expected = len(intent.get("routes", [])) + len(intent.get("vias", [])) + 2 * len(intent.get("contact_landings", []))
    return (
        "prog((cv tf net netTable created failures existing obj ext viaObj viaDef result inst ibbox) "
        "netTable=makeTable('alrNets nil) "
        "foreach(win hiGetWindowList() "
        f"when(win~>cellView && win~>cellView~>libName=={q(target['lib'])} && win~>cellView~>cellName=={q(target['cell'])} "
        f"&& win~>cellView~>viewName=={q(target['view'])} return({q('ERROR|target-open-in-window')}))) "
        f"unless(ddGetObj({q(target['lib'])} {q(target['cell'])} {q(target['view'])}) return({q('ERROR|target-missing')})) "
        f"cv=dbOpenCellViewByType({q(target['lib'])} {q(target['cell'])} {q(target['view'])} \"maskLayout\" \"a\") "
        f"unless(cv return({q('ERROR|open-failed')})) tf=techGetTechFile(cv) unless(tf dbClose(cv) return({q('ERROR|tech-file')})) "
        + " ".join(placement_checks)
        + " when(failures result=sprintf(nil \"ERROR|live-placement-drift|failures=%L\" reverse(failures)) dbClose(cv) return(result)) "
        + " ".join(commands)
        + f" if(failures || length(created)!={expected} then result=sprintf(nil \"ERROR|created=%d|failures=%L\" length(created) reverse(failures)) dbPurge(cv) "
        "else if(dbSave(cv) then result=sprintf(nil \"OK|created=%d|nets=%d\" length(created) length(cv~>nets)) dbClose(cv) "
        "else result=\"ERROR|dbSave-failed\" dbPurge(cv))) return(result))"
    )


def build_verify_skill(intent: dict[str, Any]) -> str:
    target=intent["target"]; intent_hash=ROUTE.digest(intent); profile_hash=intent["sources"]["profile_fingerprint"]
    checks=[]
    for route in intent.get("routes",[]):
        checks.append(
            f"matches=setof(x cv~>shapes x~>alrObjectId=={q(route['id'])}) obj=car(matches) "
            f"unless(length(matches)==1 && obj~>objType==\"path\" && obj~>net~>name=={q(route['net'])} "
            f"&& obj~>layerName=={q(route['layer'])} && obj~>purpose=={q(route['purpose'])} "
            f"&& abs(obj~>width-{float(route['width_um']):.12g})<1e-9 && obj~>points=={points(route['points_um'])} "
            f"&& obj~>alrIntentSha256=={q(intent_hash)} && obj~>alrProfileFingerprint=={q(profile_hash)} problems=cons({q(route['id'])} problems))"
        )
    for via in intent.get("vias",[]):
        checks.append(
            f"matches=setof(x cv~>vias x~>alrObjectId=={q(via['id'])}) obj=car(matches) "
            f"unless(length(matches)==1 && obj~>objType==\"stdVia\" && obj~>net~>name=={q(via['net'])} "
            f"&& obj~>viaHeader~>viaDefName=={q(via['via'])} && obj~>origin=={point(via['xy_um'])} "
            f"&& obj~>alrIntentSha256=={q(intent_hash)} && obj~>alrProfileFingerprint=={q(profile_hash)} problems=cons({q(via['id'])} problems))"
        )
    for landing in intent.get("contact_landings",[]):
        eid=landing["id"]+":extension"; vid=landing["id"]+":via"
        checks.append(
            f"matches=setof(x cv~>shapes x~>alrObjectId=={q(eid)}) obj=car(matches) "
            f"unless(length(matches)==1 && obj~>objType==\"rect\" && obj~>net~>name=={q(landing['net'])} "
            f"&& equal(obj~>lpp list({q(landing['source_layer'])} {q(landing['purpose'])})) && obj~>bBox=={bbox(landing['extension_bbox_um'])} problems=cons({q(eid)} problems)) "
            f"matches=setof(x cv~>vias x~>alrObjectId=={q(vid)}) obj=car(matches) "
            f"unless(length(matches)==1 && obj~>net~>name=={q(landing['net'])} && obj~>viaHeader~>viaDefName=={q(landing['via'])} "
            f"&& obj~>origin=={point(landing['xy_um'])} problems=cons({q(vid)} problems))"
        )
    expected_shapes=len(intent.get("routes",[]))+len(intent.get("contact_landings",[])); expected_vias=len(intent.get("vias",[]))+len(intent.get("contact_landings",[]))
    return (
        "prog((cv obj matches problems ownedShapes ownedVias result) "
        f"cv=dbOpenCellViewByType({q(target['lib'])} {q(target['cell'])} {q(target['view'])} \"maskLayout\" \"r\") "
        f"unless(cv return({q('ERROR|open-failed')})) " + " ".join(checks) + " "
        f"ownedShapes=setof(x cv~>shapes x~>alrIntentSha256=={q(intent_hash)}) ownedVias=setof(x cv~>vias x~>alrIntentSha256=={q(intent_hash)}) "
        f"unless(length(ownedShapes)=={expected_shapes} problems=cons(\"owned-shape-count\" problems)) "
        f"unless(length(ownedVias)=={expected_vias} problems=cons(\"owned-via-count\" problems)) "
        "if(problems then result=sprintf(nil \"ERROR|problems=%L\" reverse(problems)) "
        "else result=sprintf(nil \"OK|shapes=%d|vias=%d|nets=%d\" length(ownedShapes) length(ownedVias) length(cv~>nets))) "
        "dbClose(cv) return(result))"
    )


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("intent",type=Path); parser.add_argument("--profile",required=True,type=Path)
    parser.add_argument("--terminal-access",required=True,type=Path); parser.add_argument("--env",required=True,type=Path)
    parser.add_argument("--report",required=True,type=Path); parser.add_argument("--verify-only",action="store_true")
    parser.add_argument("--svg-check",type=Path)
    args=parser.parse_args()
    profile=ROUTE.load(args.profile); access=ROUTE.load(args.terminal_access); intent=ROUTE.load(args.intent)
    validate_inputs(profile,access,intent)
    svg_check=None
    if args.svg_check:
        svg_check=ROUTE.load(args.svg_check); validate_svg_check(intent,svg_check)
    elif not args.verify_only:
        raise ValueError("materialization requires a passing --svg-check artifact")
    from virtuoso_bridge import VirtuosoClient
    from virtuoso_bridge.env import set_runtime_env_file
    set_runtime_env_file(str(args.env.resolve())); client=VirtuosoClient.from_env()
    probe=client.execute_skill("1+2")
    if not probe.ok or output_text(probe.output)!="3": raise RuntimeError(f"Bridge round-trip failed: {probe.errors or probe.output}")
    apply_text="SKIPPED|verify-only"
    if not args.verify_only:
        response=client.execute_skill(build_apply_skill(intent,access)); apply_text=output_text(response.output)
        if not response.ok or not apply_text.startswith("OK|"): raise RuntimeError(f"Apply failed: {apply_text}; {response.errors}")
    response=client.execute_skill(build_verify_skill(intent)); verify_text=output_text(response.output)
    report={"schema":"analog-layout-route.readback/v1","target":intent["target"],"status":"PASS" if response.ok and verify_text.startswith("OK|") else "FAIL",
        "intent":str(args.intent.resolve()),"intent_sha256":ROUTE.digest(intent),"profile_fingerprint":intent["sources"]["profile_fingerprint"],
        "terminal_access_sha256":intent["sources"]["terminal_access_sha256"],"svg_check":str(args.svg_check.resolve()) if args.svg_check else None,"apply":apply_text,"readback":verify_text,
        "counts":{"routes":len(intent.get("routes",[])),"vias":len(intent.get("vias",[])),"contact_landings":len(intent.get("contact_landings",[]))},
        "boundary":"Database readback only; foundry DRC/LVS remain required."}
    args.report.parent.mkdir(parents=True,exist_ok=True); args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if report["status"]=="PASS" else 2


if __name__=="__main__": raise SystemExit(main())
