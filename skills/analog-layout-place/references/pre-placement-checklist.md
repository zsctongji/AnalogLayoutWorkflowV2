# Placement readiness and acceptance

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

Use once for a new placement; for refinement review only affected items plus global invariants. Reuse checks bound to unchanged source/PDK/parameters. Record pass/fail/unknown/not-applicable and evidence in the existing run summary or structured input; no separate duplicate checklist report is required.

## Required before materialization

- **Source and destination:** checked/saved schematic revision, complete inventory and exact absent destination with valid project/Cadence name. Verify save status through available evidence; ask only when it cannot be established. Preserve existing user choices. Do not implicitly overwrite revisions or shift hierarchy origins.
- **Technology:** authoritative manufacturing grid (UI snap separately if relevant), current PDK/device flavor, typed evaluated PCell parameters/bboxes. Never infer rules from process nicknames.
- **Electrical equivalence:** G/S/D/B mapping, master, W/L/nf and m-copy expansion. Resolve unexplained differences; finger-count/width changes are circuit changes, not ordinary compaction.
- **Matching:** selected topology, explicit copies/ratios, functional groups and dummy ownership. Check corresponding orientations, device/bulk equivalence, edge/dummy/well context and terminal access. Require centroid equality only for common-centroid groups; common-axis/mirror groups use their actual declared axes. Label interdigitated/fallback patterns accurately.
- **Physical access:** every required pin island, intended boundary/pin order, layer direction, keepouts and realistic contact/via/power/ring/tap escape space. Bbox non-overlap alone does not prove routability.
- **Abutment:** explicit terminal identity and qualified PDK support. Same-source sharing needs equal S nets, compatible kind/master, measured edge parameters, continuous active/coincident contacts and D/S isolation. Never merge devices or reinterpret terminals to save area.

## Review only circuit-relevant risks

Protect critical/high-impedance adjacency and sensitive-net spans; compare differential-chain axes and positive/negative access topology. Preserve ratio-mirror reference balance and edge context. For actual noisy/high-current/thermal blocks, check sensitive-node separation, supply/output escape, substrate paths and matched thermal exposure. Do not invent absent circuit categories or fixed risk weights.

Use current PDK requirements for wells/taps/rings, isolation and layout-dependent effects. Reject compaction that breaks adopted matching, removes required dummies, blocks access or violates those requirements. For resistor/capacitor arrays preserve unit/plate/terminal matching; unsupported decomposition stays an explicit limitation.

## Handoff

Deliver source/PDK identity, placement/access evidence, groups/axis/dummies, reservations, origin policy and unresolved items. Detailed device construction belongs to qualified PCells/PDK rules. Routing, body ties, pins, DRC/LVS and requested PEX/EM/IR/performance checks are downstream tasks, not additional placement loops. A placement-only result must not claim they passed.
