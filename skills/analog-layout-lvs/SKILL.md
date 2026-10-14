---
name: analog-layout-lvs
description: Run and diagnose independent layout-versus-schematic checks; perform authorized symmetric connectivity repairs with transactional adapters and LVS/DRC rechecks.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Analog Layout LVS

Identify layout and authoritative schematic/config separately. Checking an existing report does not start a new run or edit.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Select the mode

- Report analysis: `python scripts/inspect_report.py REPORT [--log LOG] [--output NEW_JSON]`. It classifies observed Calibre text reports; it never grants signoff.
- Run/verify: read [run-evidence.md](references/run-evidence.md); for the local Nuvoton setup also [site.md](references/site.md). Use the bridge for live CAD access and a verified site exporter/run command.
- Locate/diagnose: retain hierarchical instance/net/device/terminal mappings and measured units/transforms; distinguish missing ports, open/short nets, device and property differences. Unknown ownership blocks edits.
- Repair: read [repair.md](references/repair.md); `scripts/lvs_repair.py` offers pure plan checking and a bounded transaction controller. A qualified site adapter is required for real OA writes.

## Comparison invariants

1. Bind saved OA layout/hierarchy to fresh stream extraction and separately bind checked/saved schematic/config to SPICE. Verify tops, layer map, labels, terminal order, global nets, CDF/models, units, W/L/m/nf and includes. Never use layout-extracted SPICE as the schematic reference.
2. Preserve PDK originals; isolate run-local configuration/results. Record tool/argv/exit/time and all input/deck/dependency/output hashes. Check effective settings in execution evidence, not wrapper names alone. A deck named xrc does not imply PEX should run.
3. Reject self-comparison, aliased inputs, stale exports and incomplete execution. Different paths do not prove independence. Review all hierarchical results, warnings, soft/supply connections, unresolved subcircuits, blackboxes, virtual connects, filtering/reduction and tolerances. Only documented foundry device stubs are acceptable.
4. CORRECT, zero exit or equal raw counts is insufficient. Honor legal reductions/pin swaps; retain exclusions and limitations. Historical reports do not describe current OA. DRC density/CONOPC exceptions never waive LVS.

States: INVALID_COMPARISON; EXECUTION_FAILED/INCOMPLETE; REPORT_MISMATCH; REPORT_MATCH_UNVERIFIED; VERIFIED_MATCH only with the complete run-evidence checks. Approved limitations remain explicit.

## Repair

Fix invalid exports/run settings before geometry. For a bound mismatch, establish electrical cause and use the current working layout by default (an absent target only for explicit staged/save-as requests), with preserved schematic, device dimensions, intended nets, shared active, rings and axis. The controller supports route/pin create/replace/delete and unchanged-mate verification; it does not resize devices or solve topology automatically.

Verify the complete pair/self scope including real cuts/landing. An already-correct mate may remain unchanged but must be checked. Preserve common-net axis/dual-side collection and scoped exceptions. Never widen tolerances, suppress ports/filter devices or alter the reference to manufacture a pass.

Each transaction reads back full state, verifies expected connectivity delta/no unintended changes, saves, and reruns independent LVS plus same-policy DRC. REPAIR_CLOSED requires VERIFIED_MATCH + CLEAN; otherwise retain SAVED_NOT_CLOSED. Continue authorized iterations only with fresh evidence and progress; stop on failed gates/drift/repeated cause.

Deliver raw evidence links and one concise result/repair summary. Run script tests when modifying the skill/adapter, not each design use. [research.md](references/research.md) is optional background.
