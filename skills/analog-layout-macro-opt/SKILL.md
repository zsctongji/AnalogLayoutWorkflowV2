---
name: analog-layout-macro-opt
description: Reduce post-ring layout area by rigidly translating complete functional macros under fixed symmetry, spacing and pin-access constraints. Includes bounded offline search and readback checks.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

Follow [stage-writes.md](../analog-layout-workflow/references/stage-writes.md): planning and candidate checks do not write to CAD. Collect the complete stage object/shared-chain/move list, apply it in one batch at the end of the stage, save once, then perform independent readback. Reads must not implicitly commit pending writes. Reuse valid live qualification and unchanged evidence.


# Macro area optimization

Use existing post-placement/share/ring evidence; do not rerun those stages when valid. A macro contains devices, dummies, shared active/cont, full ring/ROD/well, owned labels/pins/vias and local connections. Include passives in area.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Plan and search

Read [contract.md](references/contract.md) for snapshot/request schemas; additionally [gap-budget.md](references/gap-budget.md) when changing inter-module gaps.

1. Build/reuse a fresh complete post-ring object→macro inventory. Ownership must be unique; shared edges and whole rings cannot cross independently movable macros. Freeze units coupled by existing wires/shared wells/ROD, or resolve a rerouting/partition decision within user scope.
2. Preserve internal placement/orientation and the existing core axis. Declare self-axis/pair anchors, order, fixed macros and boundaries explicitly. Ring-bbox centering alone does not prove internal or electrical symmetry; do not invent mirror partners for passives/outputs.
3. Bind source hash, PDK-derived pair clearances, channel reservations, physical pin islands, sensitive-net span limits and bounded search budget in request.json. Avoid double-counting margins or imposing well spacing where inapplicable; unknown required rules block application.
4. Run `scripts/macro_opt.py --snapshot ... --request ... --out NEW_DIRECTORY`, or the workflow `configured_flow.py macro-opt` entrypoint with the project configuration. It uses rigid movement groups, ordered-stack compaction seeds and bounded beam search; rank feasible candidates by configured `objective_priority` (area then weighted HPWL if omitted). Review baseline, full envelope area/aspect, gap slack, pin-span/access and rejected constraints. Failure in budget is not proof of infeasibility; no improvement is valid.

For independently movable **unrouted** adjacent macros, read the full-envelope gap target from the current project circuit configuration. It is a planning target, not a PDK minimum or guaranteed via channel. Include rings/wells/contacts/local escapes, verify pair-specific rules/access, and synchronize pair_gaps with the corresponding order.gap_um. Keep larger demonstrated requirements. Do not carry a previous project's numeric target into a new design, shrink rings, or alter existing inter-module routing to force a target.

## Apply

Only live application needs [materialization.md](references/materialization.md) and the bridge. Use a qualified same-cell transaction by default; clone the whole cellview to an absent target only for initial working-layout creation or explicit staged/save-as requests. Qualify ROD transform semantics, then translate each owned object exactly once. Do not use a PCell-only importer, regenerate rings, rotate/reflect devices or break shared contacts.

Read back and run `verify_translation` on normalized snapshots: exact macro deltas, unchanged parameters/orientation/net/pin ownership, contact coincidence, ring closure, wells, passive dimensions and fresh access. Refresh downstream coordinates without calling projections measurements. Default saved status is MATERIALIZED_UNVERIFIED.

Output candidate metrics/preview/move manifests and one decision summary. Search models envelopes and pin spans, not RC/congestion/thermal/EM. Foundry DRC/LVS is required for signoff; [research.md](references/research.md) is optional background.

For cross-design search, request `objective_priority` may order `area_um2`, `weighted_hpwl_um`, and `aspect_ratio`; feasibility always ranks first. Omission preserves the existing area-first behavior. Module names/order/locks/gaps belong in project circuit constraints.
