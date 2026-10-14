---
name: analog-layout-drc
description: Run, diagnose and repair foundry-deck DRC with revision-bound results, explicit waivers and symmetry-preserving transactions.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Analog Layout DRC

Operate on one exact saved layout revision and authoritative foundry deck. Analysis requests stay read-only; repair requests include necessary candidate verification.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Select the mode

- Parse/analyze: `scripts/calibre_drc.py parse`. Supports the documented ASCII polygon subset; preserve global/primary/inherited counts. A standalone parse cannot bind OA identity.
- Run: [calibre-runner.md](references/calibre-runner.md). Preview the versioned config, then `calibre_drc.py run --execute --config ... --out ... --report ...` on the CAD host. Existing authorization covers the preview→execute sequence. Use new outputs and immutable dependency fingerprints.
- Locate: [marker-diagnosis.md](references/marker-diagnosis.md), `marker_geometry.py`; require verified units, hierarchy transforms, instance paths and fresh geometry. Bbox overlap identifies candidates, not causes.
- Repair: [symmetric-repair.md](references/symmetric-repair.md), `symmetric_repair.py`; qualified site adapter required. No generic OA writer is bundled.
- Close: bound complete execution/results, reviewed warnings and no findings are required for CLEAN.

## Evidence and states

Bind OA revision/hierarchy → stream/map → deck/includes/options → result/summary/log hashes, exact top, tool version and timestamps. Reject stale targets, unsupported/truncated records, count disagreement, missing units and unresolved warnings. Repeat only affected processing for analysis, but verification of edited geometry requires fresh bound outputs.

CLEAN has zero waived and unwaived findings. VIOLATIONS, WAIVED, UNVERIFIED (unbound zero-result parse), INCOMPLETE and execution/provenance failures remain distinct. Waivers are exact approved run inputs; inherited/PCell ownership does not waive errors. Compare only matching policy/deck/dependency/waiver fingerprints. CLI exits: 0 CLEAN or preview; 2 VIOLATIONS/WAIVED; 3 unverified/incomplete/failure.

## User-specified CONOPC / density scope

Apply CONOPC or density waivers only when an actual user instruction exists in the current project configuration/session. Read scope, instruction and source from that project record; do not generalize another project's preferences into authorization for this project. Without waiver configuration, report the complete original deck and do not automatically ignore these rules.

Build a bounded waiver list from the rule text in the current deck: CONOPC missing-shape, shape, standalone-pattern and overlap checks; minimum/maximum metal density and associated density dummy-metal pattern checks. Preserve raw reports, rule names, original/flattened counts, the user's exact words and scope. Do not delete original records or disable rules in the foundry deck. In particular, do not blanket-ignore the `cont.*`, `mt1.*`, `mt2.*` or `tm.*` prefixes: contact/metal width, spacing, enclosure, via and connectivity errors still require repair.

Ignored items do not block repairs within the remaining explicitly authorized scope. Record incomplete density sidecar parsing and warnings directly related to ignored items separately; do not infer a density pass or treat them as a reason to add fill again. Waivers apply only to their corresponding scope and cannot suppress unrelated export, execution, unit, layer-mapping or connectivity problems. Report the remaining non-waived error count and the ignored CONOPC/density count at delivery. Even if the former is zero, use WAIVED / SCOPED_REPAIR_COMPLETE; do not claim complete foundry DRC CLEAN or geometric/electrical signoff closure.

## Repair invariants

Freeze complete symmetry scope, axis and net/pin/object mapping, including unmarked mates. Apply pair/self changes transactionally; compare actual metal/cuts, layers, widths/enclosures, access and matched/environment metrics. Preserve connected dual-sided same-net trunks. Do not delete groups, enlarge tolerances, swap nets or add cosmetic metal to pass.

Edit only authorized owned geometry. Device/PCell/well/ring/placement/pin changes need corresponding scope. Apply in a qualified same-cell transaction by default; clone to an absent destination only for initial working-layout creation or explicit staged/save-as requests. Verify complete readback, discard only this stage's unsaved changes on failure, and retain saved failing results. Recheck unchanged source and rerun the same DRC policy; unknown gates or missing adapters block live repair. DRC results do not establish LVS/PEX or analog performance.
