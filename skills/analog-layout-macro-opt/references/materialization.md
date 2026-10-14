# Guided Virtuoso adapter: extract, clone, translate, read back

This version has no generic live mutation CLI. Use `operate-virtuoso-bridge` for live operations. Load `virtuoso-layout-practice` only when broader layout review is needed beyond this adapter contract. Never pass a post-ring source to the PCell-only importer or rebuild from pre-ring JSON. Reuse unchanged source evidence, while checking freshness before copying and independently reading back after save.

## Capture

1. Confirm bridge health, target cellview identity and absence of unsaved source edits. Read saved source PCells, evaluated parameters, shape points/bboxes/widths/LPPs, nets, terminals, pin figures, vias and ROD parent/child/dependency relationships.
2. Reconcile upstream logical module ownership, explicit dummy associations, saved source-sharing edges and ring names/properties. The closure artifacts are evidence, not permission to infer that every object within a bbox belongs to the module.
3. Produce complete source object IDs and normalized payloads before reducing to optimizer envelopes. Group all PCell shapes through their instance; top-level ring paths/cuts/fill/labels/ports require explicit owners. A pin figure is a shape owned by a terminal, not a second shape to move independently. Keep non-geometric connectivity records in a sidecar with the source hash.
4. Any straddling wire, common fill/well, boundary pin with unresolved movement policy or ambiguous ROD dependency blocks independent macro motion. Ask for scoped rerouting or freezing; do not cut wires, delete geometry or merge module rings implicitly. An unrelated fixed object can be a locked obstacle macro.

## Applying one selected candidate

- Require an explicit apply request and the exact working lib/cell/view. Under the default single-layout policy, re-read the saved baseline and apply through a qualified same-cell transaction; reject stale candidates or unrelated unsaved edits. A new absent target is required only for initial working-layout creation or explicit staged/save-as requests; preserve its source immutable.
- In single-layout mode preserve the complete existing cellview; in explicitly staged mode use the bridge's verified design-level copy operation, preserving connectivity and PCells. Check the full baseline or copied objects/counts before translating. Do not clone through a lossy GDS route or recreate parameters from strings.
- Qualify in scratch whether moving a ROD root propagates to subpaths/cuts/terminal figures and how their IDs map. Reuse that qualification for the same CAD version, generator/ROD structure and adapter; repeat only when these change. Never guess `dbMoveFig` on every root and child, which can double-transform contacts. Unknown semantics blocks application.
- Apply each macro's single translation to exactly its complete object set. Use a visit/accounting ledger for every root, propagated child and independent object. Preserve parameters, orientations, net names and terminal attachments. The sharing skill's world-coordinate contact evidence and ring centerlines must be translated by the same delta in a new child artifact; never overwrite original evidence or label the projection as new measurement.
- Before save, compare new geometry to expected rigid transforms and rerun macro feasibility. On pre-save failure purge only the unsaved target transaction; on post-save verification failure retain the current working view for diagnosis. Do not switch to new stage views, replace another design, or delete user's objects as recovery.

## Acceptance

Read the saved target independently: same instance/master/parameter/orientation sets, same shape counts/types/LPP/net ownership, one delta per macro, ROD ring closed and complete, coincident source contacts unchanged, no new gate/drain intrusion, unchanged passive dimensions, continuous intended well fill and no foreign well collisions. Ensure pin/term figures were moved exactly once and inter-ring supply status remains explicit. Run the normalized `verify_translation` helper plus project-specific geometry checks.

Re-extract terminal islands and macro pin access; compare sensitive net spans, differential access topology, escape channels and supply port accessibility. Translation preserves internal shared diffusion and common centroids algebraically, but changes inter-module well-edge, noise/thermal and routing environment. Do not claim electrical matching from unchanged internal geometry.

Update child placement intent origins/bboxes/macros, shared-contact world coordinates, ring inventory, pin-access artifact and all provenance hashes together. Keep the full post-ring manifest authoritative; do not use the placement-only zero-net/zero-shape criterion after rings exist. Run actual DRC/LVS/PEX as appropriate. Report `MATERIALIZED_UNVERIFIED` until these checks are actually completed.
