---
name: analog-layout-align
description: Plan and materialize ALIGN-style analog PCell placement with explicit m=1 copies, matching, live geometry and pin-access checks. Placement only; no routing or signoff.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Analog Layout ALIGN

Honor the requested matching topology: common-axis placement does not require common-centroid equality. Plan by default; apply when the user has requested implementation and the destination is resolved.

Follow [stage-writes.md](../analog-layout-workflow/references/stage-writes.md) for stage-end-only CAD writes.

## Configuration-driven reuse

For new designs, read sibling [project-configuration.md](../analog-layout-workflow/references/project-configuration.md). Use `configured_flow.py` for mapped device parameters, declarative rows/floorplan and policy-driven routing search. Retain actual matching/access/PDK and live-import gates; legacy defaults and project-specific helper patches are compatibility paths, not the cross-design interface.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Mode and references

- New placement: [pre-placement-checklist.md](references/pre-placement-checklist.md); use [reuse.md](references/reuse.md) for CLI commands and [contracts.md](references/contracts.md) when constructing artifacts.
- Existing-layout analysis: `scripts/analyze_placement.py`; load [global-floorplan-review.md](references/global-floorplan-review.md) only for global/routed floorplan review.
- Refinement: `refine_placement_intent.py`, then `project_intent_metrics.py`. Automatic candidate search additionally uses [optimization-contract.md](references/optimization-contract.md) and `placement_optimizer.py`.
- Apply/readback: `apply_placement_intent.py`, with `--verify-only` for an existing target. Read the relevant importer commands in reuse.md; no upstream rebuild if parent evidence remains valid.

## Placement rules

1. Use a checked/saved authoritative schematic, current PDK/grid and explicit G/S/D/B identities. `placement_flow.py` runs snapshot → build → place with `--flow_stop 3_pnr:place`. Recover complete hierarchical .pl results with `recover --work` only when scaled JSON is missing.
2. Expand m=N into N electrically parallel PCells preserving W/L/nf and setting m=1; never fold m into fingers. Validate device classification, mirror ratios and dummy associations. Ambiguous dummies stay unresolved.
3. Default matching is common-axis ABBA. `placement_flow.py build --matching common_axis` recognizes functional differential pairs and current mirrors from normalized dimensions/master and actual G/S/D/B topology. Equal even m-copy pairs use ABBA in every row, with mirrored left/right orientation; do not replace a two-copy differential pair with a diagonal seed. `--constraints <json>` carries the saved module_map/dummy_module_map. Ambiguous partners or unsupported copy decompositions must be resolved before writing, never truncated with zip. Use common-centroid topology only for the user's explicitly requested group. Ratio mirrors preserve their source ratios (supported 1:2:6 rows are CCC/BAB/CCC).
4. Use live `measure-pcells` → `legalize-pcells`, not mock-PDK coordinates. Measure evaluated master parameters, bboxes and all physical pin islands; snap to manufacturing grid. Validate parameter types: ntc1132 MOS w is string, fw/l/fingers numeric; cnl5 w/l are numeric SI. A mapping/parameter change invalidates related geometry/access evidence.
5. Preserve explicit matching, dummy context, critical spans, gate access and well/ring/channel reservations. For declared ABBA/BAAB, check the actual coordinate-sorted logical identities and each logical device's copy center on the declared axis; a centered macro or identical-master reflection does not establish logical matching. Area alone cannot override them. Every term~>pins island is required; candidate_centers is only a summary. Projection estimates do not replace measurement of changed PCells.
6. Keep circuit names, coordinates, thresholds and parameter substitutions in run inputs. Refinement selectors must resolve and preserve identity; reject unintended overlap, grid violations or unsupported geometry changes.

## Apply and handoff

For initial working-layout creation, at the skill stage end use an absent explicit target and one unsaved PCell transaction containing all copies and requested annotations; save once after all succeed. Planning/search is read-only in CAD; reuse measured variants. Read back the complete saved population. Do not use this importer on a post-ring/routed layout. On failure before save purge only the transaction; retain a saved failing draft for diagnosis.

Independently verify names/counts, masters, parameters, origins, orientation and evaluated bboxes (at most one manufacturing grid inside the outward-snapped envelope), no overlaps and no top-level electrical shapes/nets/terminals. Default annotations are one tagged nonconductive D/<net> label per MOS at its transformed D pin center. Annotation-only use must reject an open target or duplicate owned labels; labels do not establish connectivity.

Deliver intent, preview, measured access and readback evidence with unresolved items in the run summary. This stage establishes placement, not foundry DRC/LVS.
