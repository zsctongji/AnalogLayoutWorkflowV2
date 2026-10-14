#!/usr/bin/env python3
"""Find same-net MOS source pairs that may qualify for PDK-backed abutment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from itertools import combinations
from pathlib import Path
from typing import Any


INTENT_SCHEMA = "analog-layout-align.pcell-placement-intent/v2"


def digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "net"


def find_candidates(intent: dict[str, Any]) -> dict[str, Any]:
    if intent.get("schema") != INTENT_SCHEMA:
        raise ValueError(f"Unsupported intent schema: {intent.get('schema')!r}")
    instances = intent.get("instances", [])
    names = [item.get("name") for item in instances]
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("Intent requires unique non-empty instance names")

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    excluded: list[dict[str, str]] = []
    for item in instances:
        if item.get("kind") not in {"nmos", "pmos"}:
            continue
        net = item.get("terminals", {}).get("S")
        master = item.get("pcell_master")
        if net is None:
            excluded.append({"instance": item["name"], "reason": "missing_source_net"})
            continue
        if not isinstance(master, dict) or not all(master.get(key) for key in ("lib", "cell", "view")):
            excluded.append({"instance": item["name"], "reason": "missing_pcell_master"})
            continue
        master_key = json.dumps(master, sort_keys=True, separators=(",", ":"))
        buckets.setdefault((str(net), str(item["kind"]), master_key), []).append(item)

    candidates = []
    serial = 0
    for (net, kind, master_key), members in sorted(buckets.items()):
        for left, right in combinations(sorted(members, key=lambda item: item["name"]), 2):
            candidates.append({
                "id": f"shared_s_{safe(net)}_{serial}",
                "instances": [left["name"], right["name"]],
                "net": net,
                "terminal": "S",
                "kind": kind,
                "pcell_master": json.loads(master_key),
                "same_group": left.get("group") == right.get("group") and left.get("group") is not None,
                "same_logical_device": left.get("logical_device") == right.get("logical_device"),
                "status": "REQUIRES_PDK_PAIR_PROBE",
                "required_evidence": [
                    "orientations_and_abutment_parameters", "evaluated_pair_origins_and_bboxes",
                    "pdk_fingerprint", "pair_probe_sha256", "source_continuity",
                    "no_ds_short", "well_tap_implant_and_access_review",
                ],
            })
            serial += 1
    return {
        "schema": "analog-layout-place.shared-source-candidates/v1",
        "source_intent_sha256": digest(intent),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "excluded": excluded,
        "decision": "REQUIRES_PDK_PAIR_PROBE" if candidates else "NO_COMPATIBLE_SAME_NET_SOURCE_PAIRS",
        "boundary": "Candidate discovery only; no placement or PCell mutation and no connectivity, DRC, or LVS claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    intent = json.loads(args.intent.read_text(encoding="utf-8"))
    result = find_candidates(intent)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": result["candidate_count"], "decision": result["decision"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
