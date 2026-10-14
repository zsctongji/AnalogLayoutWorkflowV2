---
name: analog-layout-place
description: Plan and refine analog PCell placement with explicit m=1 copies, live geometry, matching and PDK-probed source-sharing edges. Supports placement materialization, not routing or signoff.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Analog Layout Place

Placement/refinement engine used by diffusion sharing. Respect the user's common-axis/common-centroid choice; do not run both this skill and ALIGN merely to duplicate placement.

Follow [stage-writes.md](../analog-layout-workflow/references/stage-writes.md) for stage-end-only CAD writes.

## Configuration-driven reuse

For new designs, read sibling [project-configuration.md](../analog-layout-workflow/references/project-configuration.md). Use `configured_flow.py` for mapped device parameters, declarative rows/floorplan and policy-driven routing search. Retain actual matching/access/PDK and live-import gates; legacy defaults and project-specific helper patches are compatibility paths, not the cross-design interface.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Mode and references

- New placement: [pre-placement-checklist.md](references/pre-placement-checklist.md), `placement_flow.py`; commands in [reuse.md](references/reuse.md), artifact schemas in [contracts.md](references/contracts.md).
- Analyze: `analyze_placement.py`; [global-floorplan-review.md](references/global-floorplan-review.md) only for global/routed floorplans.
- Refine: `refine_placement_intent.py` accepts analog-layout-place.refinement-spec/v1 and legacy analog-layout-align.refinement-spec/v1; `project_intent_metrics.py` estimates child access.
- Search: [optimization-contract.md](references/optimization-contract.md) and `placement_optimizer.py` only when optimization is requested.
- Share source: [shared-source-diffusion.md](references/shared-source-diffusion.md) and analog-layout-diffusion-share for electrical candidacy/probes.
- Apply: `apply_placement_intent.py`; use `--verify-only` for read-only verification.

## Invariants and implementation

Use checked/saved schematic identity, PDK/grid and complete terminal mapping. Expand m=N into N m=1 copies, preserving W/L/nf and device identity. Never fold m into fingers. Default matching is common-axis ABBA for topology-identified differential pairs and equal mirrors with equal even m-copy counts. Every default row uses ABBA and mirrored left/right orientation. Use `build --matching common_axis --constraints <json>` to carry module/dummy maps; ambiguous partners and unsupported decomposition stop before writing without dropping copies. Common-centroid topology requires the user's explicit group choice. Supported ratio mirrors retain CCC/BAB/CCC (1:2:6).

Associate dummies only with a uniquely compatible group. Preserve rail-tied records if ALIGN prunes them. Run placement only (`--flow_stop 3_pnr:place`); `recover --work` is for missing scaled JSON with complete .pl files. A mock-generator limitation cannot justify changing nets or nf.

Measure live PCells and legalize bboxes/grid before use. Check evaluated parameters, not instance properties alone: ntc1132 MOS w string, fw/l/fingers numeric; cnl5 w/l numeric SI. Other PDKs need measured mappings. Preserve every physical pin island. Parameter/mapping changes require refreshed geometry/access; projected metrics remain estimates.

Source sharing requires same explicit S net, compatible kind/master and qualified PDK probe, facing S edges, continuous active, coincident actual cont cuts and D/S isolation. Opposite-side chains require identical complete placement/parameters for the middle MOS. Permit only declared source-region bbox overlaps at the measured depth. Different nets, missing evidence, same-side branching and device merging are rejected.

Keep project selectors/coordinates/policies in per-run inputs. Reject unresolved selectors, changed identities, illegal overlaps/grid or unmeasured changed geometry. Review matching, dummy context, spans, access and channels before area.

## Materialization

For initial working-layout creation, at the skill stage end use one unsaved PCell transaction in an absent destination; save only the full intended population. The importer cannot preserve arbitrary post-ring/routed geometry. Independently read back all names/masters/parameters/origins/orientations/bboxes; permit only qualified sharing overlaps. Actual saved source cont cuts need separate per-edge readback; generic bbox checks are insufficient.

Require no top-level electrical geometry/nets/terminals. Default one tagged D/<net> label per MOS is annotation only; annotation-only mode rejects open targets and duplicate labels. Failed unsaved transactions are purged; saved failing targets are retained. Deliver placement/access/sharing evidence and unresolved checks; only fresh foundry verification can establish electrical sharing or signoff.
