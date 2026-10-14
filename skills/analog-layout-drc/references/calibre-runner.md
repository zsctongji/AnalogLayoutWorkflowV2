# Calibre automatic runner

Use one immutable `analog-layout-drc.calibre-run/v1` JSON for a closure sequence. Commands are ordered argument arrays and are executed without a shell. Run the script on the EDA host; paths are interpreted there.

The runner supports Python 3.6 or newer so it can use older Python installations bundled with established Calibre releases. Prefer a project-managed Python when available; record the interpreter path and version in the execution evidence.

```json
{
  "schema": "analog-layout-drc.calibre-run/v1",
  "target": {"lib": "mylib", "cell": "OTA1_routeV5", "view": "layout"},
  "working_directory": "/project/run",
  "inputs": {
    "rule_deck": "/project/run/drc.cal",
    "layer_map": "/project/pdk/layer.map"
  },
  "streamout": {
    "argv": ["strmout", "-library", "{lib}", "-topCell", "{cell}", "-view", "{view}", "-strmFile", "{stream}"],
    "stdout": "streamout.stdout.log",
    "stderr": "streamout.stderr.log",
    "timeout_seconds": 600
  },
  "drc": {
    "argv": ["calibre", "-drc", "-hier", "{rule_deck}"],
    "stdout": "calibre.stdout.log",
    "stderr": "calibre.stderr.log",
    "timeout_seconds": 3600
  },
  "artifacts": {
    "stream": "OTA1_routeV5.calibre.db",
    "summary": "OTA1_routeV5.drc.summary",
    "results": "OTA1_routeV5.drc.results"
  }
}
```

Supported placeholders are `{lib}`, `{cell}`, `{view}`, `{working_directory}`, `{rule_deck}`, `{layer_map}`, `{stream}`, `{summary}`, and `{results}`. Unknown placeholders are rejected. Log paths and relative artifacts resolve under `working_directory`.

The dry run is the approval surface. The example above is a legacy preview, NOT an executable provenance-complete config. `--execute` now refuses existing result/log/receipt outputs and all input/output aliases (including existing hard links). Reports also use exclusive creation. Use a dedicated new directory per iteration; never erase prior artifacts to make execution pass.

For a remote Virtuoso setup, either run this script in the CAD host environment or have `operate-virtuoso-bridge` execute the equivalent recorded stream-out and Calibre stages. Do not claim that a local dry run executed remote DRC. After remote execution, parse the remote files on the same host or transfer them through an authorized channel.

## Required binding extension for execution

Add `binding` to the JSON. It contains:

```json
{
  "oa_files": ["/project/lib/cell/layout/layout.oa", "/project/evidence/saved-layout-snapshot.json"],
  "deck_dependencies": ["/pdk/includes/device_rules.cal"],
  "metal_option": "project-confirmed process option",
  "hierarchy_mode": "hier",
  "result_limit": "ALL",
  "adapter_id": "site-reviewed-calibre-adapter-v1",
  "export_receipt": "export-receipt.json",
  "drc_receipt": "drc-receipt.json"
}
```

Paths are interpreted on the CAD host, relative to working_directory when not absolute. Inventories must include the actual saved source and resolved hierarchy, PCell evaluation/technology dependencies affecting export, stream mapping and evaluated include closure. If there are no separate includes, list the root deck in deck_dependencies rather than using an unverifiable empty inventory. The adapter must verify saved OA, not infer it from a timestamp; enumerate evaluated dependencies, not just search literal INCLUDE lines. Runtime-generated deck/config inputs must be staged and frozen before execution.

`streamout.argv` and `drc.argv` call a reviewed site adapter. The adapter runs the real tools and inspects their actual effective target/input/options/completion. It must NOT manufacture success receipts by merely copying config fields. Core Python cannot independently decode every Calibre release's effective rule configuration or every OA hierarchy. Without this adapter, execution is blocked before commands; a plain `strmout`/`calibre` invocation alone cannot satisfy this contract.

Each adapter writes its receipt only after flushing its captured stage logs. It must emit no further log bytes after hashing them. Receipt JSON:

- `schema`: `analog-layout-drc.stage-receipt/v1`; `stage`: `streamout` or `drc`; `completed`: true only after actual successful completion.
- `target`: exact `{lib,cell,view}`; `config_sha256`: file byte hash.
- `adapter_id`; `argv_sha256`: `evidence_binding.fingerprint()` of the actual planned stage argv.
- `input_hashes`, `oa_hashes`, `dependency_hashes`: absolute resolved path → byte SHA-256 inventories, exactly matching fresh core snapshots.
- `policy`: exact metal_option, hierarchy_mode, result_limit, adapter_id dictionary from binding; these must match inspected effective tool settings.
- `tool_version`, `interpreter_version`: observed versions, not assumed executable names.
- `log_hashes`: stdout/stderr byte hashes; `stream_path`, `stream_sha256`: actual exported/consumed stream.
- Export additionally: `saved_oa: true`, `oa_inventory_complete: true`, `stream_format_validated: "GDSII" | "OASIS"`. Validate file structure/top cell, not just nonempty bytes.
- DRC additionally: `dependencies_complete: true`, `result_limit_reached: false`, `output_hashes: {summary,results}`. Confirm effective layout input, top, policy and normal completion from real tool evidence.

Receipts are trusted adapter attestations, not signatures or proof against a malicious adapter. Preserve adapter source/version and effective tool logs for audit. Inputs are rehashed after both stages; stream must be fresh/nonempty after export and unchanged when consumed by DRC. Summary/result headers must agree with the target. Result bytes and receipt hashes are retained.

Each iteration records its own config hash, including its new paths and OA revision. `policy_sha256` excludes the changing OA revision/output paths but includes input/dependency inventories, process settings, command templates and waivers. Keep commands parameterized by placeholders for stable comparison; any change in this fingerprint starts a new closure series. Exact target revision is still separately bound per run; policy equality never substitutes for that identity.

## Results and waivers

Supported native subset: UTF-8 ASCII polygon results with first line `<primary> <positive DBU-per-um>`, named rule blocks and integer-coordinate `p` records. `CN` is retained verbatim. Edge/binary/other result dialects and truncated polygons are NOT silently accepted; use a release-qualified adapter/exporter or retain INCOMPLETE. Declared counts, parsed polygons and summary group counts must agree; a hierarchy representation with different counting semantics needs an explicit supported parser, not suppression of the mismatch.

The trailing `DENSITY_RDBS` inventory in Calibre 2019 is recorded separately as external density databases, rather than fabricated RULECHECK entries. Preserve each reported_count, path and actual file hash. Missing, truncated or unparsed RDB content remains INCOMPLETE. Recognizing the inventory does not establish a density pass; density findings must not be deleted to obtain CLEAN.

Every runtime warning is conservatively blocking today, including unclassified warnings. There is no broad warning regex waiver. Standalone parse has no execution receipt and cannot produce CLEAN. It may classify findings while retaining UNBOUND provenance; repair requires separate fresh bindings.

`--waivers` is a JSON array with nonempty `rule_regex`, `reason`, `approval`, `scope`. Each entry is an explicit user/project decision; review exact scope against this run before use. Whole-rule regex waivers remain coarse-grained, not per-marker waivers. The CLI preserves legacy `--ignore-rule-regex` only for analysis; an undocumented pattern makes the report INCOMPLETE. Accepted findings produce WAIVED, never CLEAN. Config/waiver policy changes require a new comparison series.

Exit codes: 0 CLEAN or PLANNED preview; 2 VIOLATIONS/WAIVED; 3 UNVERIFIED/INCOMPLETE/EXECUTION_FAILED/PROVENANCE_FAILED. These states intentionally replace the old ambiguous PASS/FAIL interface.
