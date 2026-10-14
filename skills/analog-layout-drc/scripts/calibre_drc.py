#!/usr/bin/env python3
"""Run or parse a provenance-bound Calibre DRC-H job."""

import argparse
import hashlib
import json
import re
import subprocess
import time
import sys
from pathlib import Path
from string import Formatter
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_binding as binding


SCHEMA = "analog-layout-drc.calibre-run/v1"
REPORT_SCHEMA = "analog-layout-drc.report/v1"
RULE_RE = re.compile(
    r"^\s*RULECHECK\s+(\S+)\s+\.*\s*TOTAL Result Count\s*=\s*(\d+)\s+\((\d+)\)"
)
CELL_RE = re.compile(
    r"^CELL\s+(\S+)\s+\.*\s*TOTAL Result Count\s*=\s*(\d+)\s+\((\d+)\)"
)
PRIMARY_RE = re.compile(r"^Layout Primary Cell:\s*(\S+)")
RESULT_RULE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RESULT_COUNT_RE = re.compile(r"^(\d+)\s+(\d+)\s+(\d+)\b")
POLYGON_RE = re.compile(r"^p\s+(\d+)\s+(\d+)\s*$")
COORD_RE = re.compile(r"^(-?\d+)\s+(-?\d+)\s*$")
ALLOWED_FIELDS = {
    "lib", "cell", "view", "working_directory", "rule_deck", "layer_map",
    "stream", "summary", "results",
}


def now_ns() -> int:
    """Return a wall-clock nanosecond timestamp on Python 3.6+."""
    time_ns = getattr(time, "time_ns", None)
    return time_ns() if time_ns else int(time.time() * 1_000_000_000)


def sha256_path(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str, working_directory: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else working_directory / path


def parse_summary(text: str) -> Dict[str, Any]:
    primary = None
    global_rules: Dict[str, Dict[str, int]] = {}
    cells: Dict[str, Dict[str, Any]] = {}
    runtime_warnings: List[str] = []
    in_warnings = False
    in_by_cell = False
    current_cell = None
    for line in text.splitlines():
        if 'RULECHECK' in line and 'TOTAL Result Count' in line and not RULE_RE.match(line):
            raise ValueError('Unsupported/truncated RULECHECK statistic: '+line)
        primary_match = PRIMARY_RE.match(line)
        if primary_match:
            primary = primary_match.group(1)
        if line.startswith("--- RUNTIME WARNINGS"):
            in_warnings = True
            continue
        if in_warnings:
            # Native Calibre 2019 inserts a bare '---' immediately after the
            # heading. It is a separator, not the end of the warning section.
            if re.fullmatch(r'\s*-+\s*', line) or not line.strip():
                continue
            if line.startswith('---'):
                in_warnings = False
            else:
                runtime_warnings.append(line.strip())
                continue
        if line.startswith("--- RULECHECK RESULTS STATISTICS (BY CELL)"):
            in_by_cell = True
            current_cell = None
            continue
        if line.startswith("--- SUMMARY"):
            in_by_cell = False
            current_cell = None
        if in_by_cell:
            cell_match = CELL_RE.match(line)
            if cell_match:
                current_cell = cell_match.group(1)
                cells[current_cell] = {
                    "count": int(cell_match.group(2)),
                    "flattened_count": int(cell_match.group(3)),
                    "rules": {},
                }
                continue
            rule_match = RULE_RE.match(line)
            if rule_match and current_cell:
                cells[current_cell]["rules"][rule_match.group(1)] = {
                    "count": int(rule_match.group(2)),
                    "flattened_count": int(rule_match.group(3)),
                }
        else:
            rule_match = RULE_RE.match(line)
            if rule_match:
                if rule_match.group(1) in global_rules:raise ValueError('Duplicate global rule statistic')
                global_rules[rule_match.group(1)] = {
                    "count": int(rule_match.group(2)),
                    "flattened_count": int(rule_match.group(3)),
                }
    if not primary:
        raise ValueError("Layout Primary Cell was not found")
    if not global_rules:
        raise ValueError("No global RULECHECK statistics were found")
    return {
        "primary_cell": primary,
        "global_rules": global_rules,
        "cells": cells,
        "runtime_warnings": runtime_warnings,
    }


def parse_results(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    markers: List[Dict[str, Any]] = []
    declared_counts: Dict[str, int] = {}
    current_rule = None
    current_cell = None
    issues = []
    current_cn = None
    header = None
    density_databases = []
    if lines:
        match = re.fullmatch(r'(\S+)\s+([1-9]\d*)', lines[0].strip())
        if match:
            header = {'primary_cell': match.group(1), 'dbu_per_um': int(match.group(2))}
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        # Calibre 2019 density sidecar inventory is not a RULECHECK. Keep it
        # explicit; recognizing the inventory does not validate RDB contents.
        if stripped == 'DENSITY_RDBS':
            metadata = re.match(r'^0\s+0\s+(\d+)\b', lines[index+1].strip()) if index+1 < len(lines) else None
            if density_databases or metadata is None:
                issues.append('invalid/duplicate DENSITY_RDBS inventory');index+=1;continue
            number=int(metadata.group(1));cursor=index+2
            for _ in range(number):
                entry=re.fullmatch(r'([A-Za-z0-9_.-]+\.db)\s+(\d+)',lines[cursor].strip()) if cursor<len(lines) else None
                if entry is None:
                    issues.append('truncated/unsupported DENSITY_RDBS entry');break
                name=entry.group(1)
                if name in {v['path'] for v in density_databases}:issues.append('duplicate density RDB path')
                density_databases.append({'path':name,'reported_count':int(entry.group(2)),'status':'UNPARSED_EXTERNAL_RDB'})
                cursor+=1
            index=cursor;continue
        if (
            RESULT_RULE_RE.match(stripped)
            and index + 1 < len(lines)
            and RESULT_COUNT_RE.match(lines[index + 1].strip())
        ):
            current_rule = stripped
            if current_rule in declared_counts:
                issues.append('duplicate rule section: ' + current_rule)
            declared_counts[current_rule] = int(
                RESULT_COUNT_RE.match(lines[index + 1].strip()).group(1)  # type: ignore[union-attr]
            )
            current_cell = None
            current_cn = None
            index += 2
            continue
        if stripped.startswith("CN "):
            parts = stripped.split()
            current_cell = parts[1] if len(parts) > 1 else None
            current_cn = stripped
            index += 1
            continue
        polygon_match = POLYGON_RE.match(stripped)
        if polygon_match and current_rule:
            marker_index = int(polygon_match.group(1))
            vertex_count = int(polygon_match.group(2))
            cursor = index + 1
            marker_cell = current_cell
            marker_cn = current_cn
            if cursor < len(lines) and lines[cursor].strip().startswith("CN "):
                parts = lines[cursor].strip().split()
                marker_cell = parts[1] if len(parts) > 1 else None
                marker_cn = lines[cursor].strip()
                cursor += 1
            points: List[List[int]] = []
            while cursor < len(lines) and len(points) < vertex_count:
                coordinate = COORD_RE.match(lines[cursor].strip())
                if not coordinate:
                    break
                points.append([int(coordinate.group(1)), int(coordinate.group(2))])
                cursor += 1
            if len(points) == vertex_count and vertex_count >= 3:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                markers.append({
                    "rule": current_rule,
                    "index": marker_index,
                    "cell": marker_cell,
                    "polygon_db_units": points,
                    "bbox_db_units": [min(xs), min(ys), max(xs), max(ys)],
                    "owner": "unknown",
                    "cause": "unclassified",
                    "cn_raw": marker_cn,
                    "coordinate_status": "UNRESOLVED",
                })
                index = cursor
                continue
            issues.append('truncated/invalid polygon {}:{}'.format(current_rule, marker_index))
        elif re.match(r'^[pe]\s+\d+', stripped):
            issues.append('unsupported marker record at line {}: {}'.format(index + 1, stripped))
        index += 1
    for rule, count in declared_counts.items():
        actual = sum(m['rule'] == rule for m in markers)
        if count != actual:
            issues.append('marker count mismatch {}: declared {}, parsed {}'.format(rule, count, actual))
    ids = [(m['rule'], m['index'], m['cn_raw']) for m in markers]
    if len(ids) != len(set(ids)):
        issues.append('duplicate marker identities')
    if not declared_counts and not header:
        issues.append('no supported result header or rule sections')
    return {"declared_counts": declared_counts, "markers": markers, "parse_issues": issues, 'header': header, 'density_databases': density_databases}


def evaluate(global_rules: Dict[str, Dict[str, int]], patterns: List[str]) -> Dict[str, Any]:
    compiled = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    nonzero = {name: value for name, value in global_rules.items() if value["count"] > 0}
    ignored = {
        name: value for name, value in nonzero.items()
        if any(pattern.search(name) for pattern in compiled)
    }
    actionable = {name: value for name, value in nonzero.items() if name not in ignored}
    return {
        "status": "VIOLATIONS" if actionable else "WAIVED" if ignored else "CLEAN",
        "actionable_rules": actionable,
        "ignored_rules": ignored,
        "actionable_result_count": sum(value["count"] for value in actionable.values()),
        "ignored_result_count": sum(value["count"] for value in ignored.values()),
    }


def parse_artifacts(summary: Path, results: Optional[Path], patterns: List[str], waivers=None) -> Dict[str, Any]:
    summary_data = parse_summary(summary.read_text(encoding="utf-8"))
    result_data = {"declared_counts": {}, "markers": [], "parse_issues": []}
    issues = []
    if results is None or not results.is_file():
        issues.append('result database missing: summary-only analysis cannot establish closure')
    else:
        result_data = parse_results(results.read_text(encoding="utf-8"))
        if not result_data.get('header'):
            issues.append('result primary cell / database unit header unavailable')
        elif result_data['header']['primary_cell'] != summary_data['primary_cell']:
            issues.append('summary/result primary cell mismatch')
        for rule, value in summary_data['global_rules'].items():
            if value['count'] != result_data['declared_counts'].get(rule, 0):
                issues.append('summary/result count mismatch: ' + rule)
        for rule, count in result_data['declared_counts'].items():
            if rule not in summary_data['global_rules']:
                issues.append('result rule absent from summary: ' + rule)
    waiver_records = waivers or []
    for w in waiver_records:
        if not isinstance(w,dict) or not all(isinstance(w.get(k), str) and w[k].strip() for k in ('rule_regex','reason','approval','scope')):
            raise ValueError('Waiver requires rule_regex, reason, approval, scope')
    approved_patterns = [w['rule_regex'] for w in waiver_records]
    if any(p not in approved_patterns for p in patterns):
        issues.append('legacy regex lacks documented waiver reason/approval/scope')
    findings = evaluate(summary_data['global_rules'], list(dict.fromkeys(patterns + approved_patterns)))
    # Unknown warnings are deliberately blocking; there is no broad warning waiver.
    issues.extend('runtime warning requires review: ' + w for w in summary_data['runtime_warnings'])
    issues.extend(result_data['parse_issues'])
    for db in result_data.get('density_databases',[]):
        path=results.parent/db['path']
        db['sha256']=sha256_path(path)
        issues.append('density sidecar requires format/content validation: '+db['path'] if db['sha256'] else 'missing density sidecar: '+db['path'])
    result = {
        **summary_data,
        **result_data,
        **findings,
        "summary": str(summary.resolve()),
        "summary_sha256": sha256_path(summary),
        "results": str(results.resolve()) if results else None,
        "results_sha256": sha256_path(results) if results else None,
        "ignore_rule_regex": patterns,
        "waivers": waiver_records,
        "integrity_issues": issues,
        "findings_status": findings['status'],
        "provenance_status": "UNBOUND",
    }
    result['status'] = 'INCOMPLETE' if issues else ('UNVERIFIED' if findings['status'] == 'CLEAN' else findings['status'])
    return result


def format_argv(argv: List[str], context: Dict[str, str]) -> List[str]:
    formatter = Formatter()
    rendered: List[str] = []
    for argument in argv:
        fields = {name for _, name, _, _ in formatter.parse(argument) if name}
        unknown = fields - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"Unknown command placeholder(s): {sorted(unknown)}")
        rendered.append(argument.format_map(context))
    return rendered


def load_config(path: Path) -> Tuple[Dict[str, Any], bytes]:
    raw = path.read_bytes()
    config = json.loads(raw)
    if config.get("schema") != SCHEMA:
        raise ValueError(f"Expected config schema {SCHEMA}")
    target = config.get("target", {})
    if not all(isinstance(target.get(key), str) and target[key] for key in ("lib", "cell", "view")):
        raise ValueError("target.lib/cell/view are required")
    for stage in ("streamout", "drc"):
        argv = config.get(stage, {}).get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise ValueError(f"{stage}.argv must be a non-empty string array")
    for artifact in ("stream", "summary", "results"):
        if not config.get("artifacts", {}).get(artifact):
            raise ValueError(f"artifacts.{artifact} is required")
    if not config.get("inputs", {}).get("rule_deck"):
        raise ValueError("inputs.rule_deck is required")
    return config, raw


def prepare_run(config_path: Path) -> Dict[str, Any]:
    config, raw = load_config(config_path)
    workdir = Path(config["working_directory"]).resolve()
    artifacts = {
        key: resolve_path(value, workdir).resolve()
        for key, value in config["artifacts"].items()
    }
    inputs = {
        key: resolve_path(value, workdir).resolve()
        for key, value in config.get("inputs", {}).items()
        if value
    }
    context = {
        **config["target"],
        "working_directory": str(workdir),
        "rule_deck": str(inputs["rule_deck"]),
        "layer_map": str(inputs.get("layer_map", "")),
        **{key: str(value) for key, value in artifacts.items()},
    }
    stages = []
    for name in ("streamout", "drc"):
        stage = config[name]
        stages.append({
            "name": name,
            "argv": format_argv(stage["argv"], context),
            "stdout": str(resolve_path(stage.get("stdout", f"{name}.stdout.log"), workdir).resolve()),
            "stderr": str(resolve_path(stage.get("stderr", f"{name}.stderr.log"), workdir).resolve()),
            "timeout_seconds": int(stage.get("timeout_seconds", 3600)),
        })
    return {
        "config": config,
        "config_path": str(config_path.resolve()),
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "working_directory": str(workdir),
        "artifacts": {key: str(value) for key, value in artifacts.items()},
        "inputs": {
            key: {"path": str(value), "sha256": sha256_path(value)}
            for key, value in inputs.items()
        },
        "stages": stages,
    }


def execute_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    bound = binding.prepare(plan)
    plan['binding_evidence'] = bound
    workdir = Path(plan["working_directory"])
    workdir.mkdir(parents=True, exist_ok=True)
    records = []
    stream_hash = None
    for stage in plan["stages"]:
        stdout_path = Path(stage["stdout"])
        stderr_path = Path(stage["stderr"])
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        started = now_ns()
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                completed = subprocess.run(
                    stage["argv"], cwd=workdir, stdout=stdout, stderr=stderr,
                    timeout=stage["timeout_seconds"], check=False, shell=False,
                )
            record = {**stage, "started_ns": started, "finished_ns": now_ns(), "returncode": completed.returncode}
            if completed.returncode == 0:
                receipt = binding.verify_stage(plan, bound, stage['name'], stream_hash)
                stream_hash = receipt['stream_sha256']
                record['verified_receipt'] = receipt
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            record = {**stage, "started_ns": started, "finished_ns": now_ns(), "returncode": None, "error": str(exc)}
        records.append(record)
        if record.get("returncode") != 0:
            break
    return records


def render_report(result: Dict[str, Any]) -> str:
    lines = [
        "# Analog layout DRC report", "",
        f"- Status: **{result['status']}**",
        f"- Primary cell: `{result.get('primary_cell', 'unknown')}`",
        f"- Actionable result groups: {result.get('actionable_result_count', 0)}",
        f"- Explicitly ignored result groups: {result.get('ignored_result_count', 0)}",
        f"- Marker polygons parsed: {len(result.get('markers', []))}", "",
    ]
    for heading, key in (("Actionable rules", "actionable_rules"), ("Ignored rules", "ignored_rules")):
        lines.extend([f"## {heading}", ""])
        values = result.get(key, {})
        lines.extend(
            f"- `{name}`: {count['count']} group(s), {count['flattened_count']} flattened"
            for name, count in sorted(values.items())
        )
        if not values:
            lines.append("None.")
        lines.append("")
    lines.extend(["## Runtime warnings", ""])
    lines.extend([f"- {warning}" for warning in result.get("runtime_warnings", [])] or ["None."])
    lines.extend(['', '## Integrity / provenance', ''])
    lines.extend('- '+x for x in result.get('integrity_issues', []))
    if result.get('error'):lines.append('- '+result['error'])
    lines.append('- Provenance: '+result.get('provenance_status','UNBOUND'))
    lines.extend(['','## Documented waivers',''])
    lines.extend('- '+json.dumps(w,ensure_ascii=False) for w in result.get('waivers',[]))
    lines.extend(["", "## Boundary", "", "Waiver-filtered DRC does not establish LVS, PEX, ERC, antenna, EM/reliability, density, or analog-performance signoff.", ""])
    return "\n".join(lines)


def write_outputs(result: Dict[str, Any], out: Path, report: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x',encoding='utf-8') as f:f.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    with report.open('x',encoding='utf-8') as f:f.write(render_report(result))


def main() -> int:
    parser = argparse.ArgumentParser()
    # argparse did not support required=True for subparsers until Python 3.7.
    subparsers = parser.add_subparsers(dest="command")
    parse_cmd = subparsers.add_parser("parse")
    parse_cmd.add_argument("--summary", required=True, type=Path)
    parse_cmd.add_argument("--results", type=Path)
    run_cmd = subparsers.add_parser("run")
    run_cmd.add_argument("--config", required=True, type=Path)
    run_cmd.add_argument("--execute", action="store_true")
    for command in (parse_cmd, run_cmd):
        command.add_argument("--ignore-rule-regex", action="append", default=[])
        command.add_argument('--waivers', type=Path)
        command.add_argument("--out", required=True, type=Path)
        command.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if not args.command:
        parser.error("a command is required: parse or run")

    safe_output = False
    try:
        protected = [p for p in (getattr(args,'summary',None),getattr(args,'results',None),getattr(args,'config',None),args.waivers) if p]
        plan = prepare_run(args.config) if args.command == 'run' else None
        if plan:
            protected += [x['path'] for x in plan['inputs'].values()] + list(plan['artifacts'].values())
            protected += [s[k] for s in plan['stages'] for k in ('stdout','stderr')]
            b=plan['config'].get('binding',{});root=Path(plan['working_directory'])
            protected += [root/x for key in ('oa_files','deck_dependencies') for x in b.get(key,[])]
            protected += [root/b[k] for k in ('export_receipt','drc_receipt') if b.get(k)]
        binding.distinct_paths(protected,[args.out,args.report])
        if args.out.exists() or args.report.exists():raise ValueError('Report output exists; choose a new run directory')
        safe_output = True
        waivers=json.loads(args.waivers.read_text(encoding='utf-8')) if args.waivers else []
        if not isinstance(waivers,list):raise ValueError('waivers must be a list')
        if args.command == "parse":
            result = {"schema": REPORT_SCHEMA, "mode": "parse", **parse_artifacts(args.summary, args.results, args.ignore_rule_regex,waivers)}
        else:
            if not args.execute:
                result = {"schema": REPORT_SCHEMA, "mode": "run", "status": "PLANNED", **plan}
                write_outputs(result, args.out, args.report)
                return 0
            started_ns = now_ns()
            stages = execute_plan(plan)
            if len(stages) != 2 or any(stage.get("returncode") != 0 for stage in stages):
                result = {"schema": REPORT_SCHEMA, "mode": "run", "status": "EXECUTION_FAILED", **plan, "stage_results": stages}
                write_outputs(result, args.out, args.report)
                return 3
            summary = Path(plan["artifacts"]["summary"])
            results = Path(plan["artifacts"]["results"])
            stale = [str(path) for path in (summary, results) if not path.is_file() or path.stat().st_mtime_ns < started_ns - 1_000_000_000]
            if stale:
                result = {"schema": REPORT_SCHEMA, "mode": "run", "status": "PROVENANCE_FAILED", **plan, "stage_results": stages, "stale_or_missing_artifacts": stale}
                write_outputs(result, args.out, args.report)
                return 3
            parsed = parse_artifacts(summary, results, args.ignore_rule_regex,waivers)
            for stage in stages:
                for key in ('stdout','stderr'):
                    log=Path(stage[key]).read_text(encoding='utf-8',errors='replace')
                    for line in log.splitlines():
                        if re.search(r'\bwarning\b|\bfatal\b|\baborted\b|license.*(?:fail|denied)|(?:result|maximum).*limit.*reach|truncat',line,re.I):
                            parsed['runtime_warnings'].append(stage['name']+': '+line)
                            parsed['integrity_issues'].append('tool log warning requires review: '+line)
            if parsed['integrity_issues']:parsed['status']='INCOMPLETE'
            if parsed["primary_cell"] != plan["config"]["target"]["cell"]:
                raise ValueError("Summary primary cell does not match configured target cell")
            result = {"schema": REPORT_SCHEMA, "mode": "run", **plan, "stage_results": stages, **parsed}
            result['provenance_status']='BOUND_ADAPTER_ATTESTED'
            result['policy_sha256']=binding.fingerprint(dict(
                inputs=plan['binding_evidence']['inputs'],dependencies=plan['binding_evidence']['dependencies'],
                process=plan['binding_evidence']['policy'],waivers=waivers,
                stage_templates={k:plan['config'][k]['argv'] for k in ('streamout','drc')}))
            if not result['integrity_issues']:
                result['status']=result['findings_status']
        write_outputs(result, args.out, args.report)
        return 0 if result["status"] == "CLEAN" else 2 if result['status'] in ('VIOLATIONS','WAIVED') else 3
    except (OSError, ValueError, KeyError, TypeError, re.error) as exc:
        result = {"schema": REPORT_SCHEMA, "mode": args.command, "status": "PROVENANCE_FAILED", "error": str(exc)}
        if safe_output and not args.out.exists() and not args.report.exists():write_outputs(result, args.out, args.report)
        else:print(json.dumps(result),file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
