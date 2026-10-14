---
name: analog-layout-symmetric-route
description: Search jointly legal mirrored Manhattan routes for complete paired or self-symmetric analog nets, with hard odd/even metal directions, sourced via geometry and bounded multi-net rerouting. Produce validated offline candidates and use existing live routing gates for application.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Symmetric Manhattan routing

Use a verified device-array axis and real net/pin mapping. When this joint-search skill is explicitly selected, automatic routing uses `scripts/symmetric_solver.py`; each wire/via action must be legal on both sides before A* accepts it. Candidate-only requests produce intent/preview; implementation uses the existing route validation/import chain.

The workflow defaults to sibling [analog-layout-symmetric-fast](../analog-layout-symmetric-fast/SKILL.md) when no routing method is selected. Keep the requested method; a fast-template failure does not authorize silent solver fallback.

## Configuration-driven reuse

For new designs, read sibling [project-configuration.md](../analog-layout-workflow/references/project-configuration.md). Use `configured_flow.py` for mapped device parameters, declarative rows/floorplan and policy-driven routing search. Retain actual matching/access/PDK and live-import gates; legacy defaults and project-specific helper patches are compatibility paths, not the cross-design interface.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Read by stage

- Automatic search: [solver-contract.md](references/solver-contract.md), then [symmetry-constraints.md](references/symmetry-constraints.md) for whole-net strategy.
- Legacy template compilation, only when explicitly selected: [template-contract.md](references/template-contract.md) and [algorithm.md](references/algorithm.md).
- Intent/application: sibling [routing-contract.md](../analog-layout-route/references/routing-contract.md).
- Geometry preflight/application: [drc-constraints.md](references/drc-constraints.md); bridge for live access and the original route importer contract. Reuse qualified unchanged profile/rules, refresh layout/access/obstacles when changed.
- Manual-reference comparison only when requested/needed: [reference-and-research.md](references/reference-and-research.md). Reference research is optional and is not repeated on every run.

## Retained hard rules

- **Access hierarchy:** every required G/S/D physical island uses a PDK-qualified contact/landing → short local M1 → legal via → higher-layer cross-array/module trunk. Include B/body/ring ties. Reuse proven existing conductors; poly covered by M1 is not a contact. Bound cumulative M1 length and local region per run; splitting a long route into short primitives does not qualify it as local.
- **Odd vertical/even horizontal:** map actual PDK metal levels, not layer IDs or technology rank numbers. The joint solver hard-rejects off-direction wires: M1 vertical local access, M2 horizontal, M3 vertical, and so on; turns use adjacent qualified vias. It has no soft direction relaxation or horizontal M1 exception. Measured legacy exceptions require the separately reviewed template path. PDK direction conflicts block. Existing PCell/ring interiors are not automatically rewritten.
- **Strict declared symmetry:** generate one side and reflect complete matched geometry about the device axis, including islands, stubs, widths, layers, branches, landings and actual cuts. Equal length/count alone is insufficient. Check both sides' obstacles and change them together; no tolerance expansion or scope deletion to pass.
- **Whole-net strategy:** every required net is classified. Pair = two nets with complete mirrored pin mapping; self = one connected self-symmetric net; matched_only = electrical matching without pointwise mirroring. Common gates/bias prefer axis or dual-side collection; single-ended output first evaluates an axis trunk; electrically unmatched branches get explicit scoped exceptions. Local PASS cannot prove global symmetry.
- **High-matching dual trunks:** when selected, each network has one left and one right trunk, electrically joined within that net; distinct nets remain isolated. Check within-net symmetry separately from between-net branch matching. No cosmetic duplicate metal or implicit topology downgrade.
- **Supplies:** continuous horizontal buses per power domain with short taps; sizes/via capacity follow current, IR/EM and PDK evidence. Labels/nearby endpoints do not establish continuity.
- **PDK geometry:** actual metal-edge width/spacing, notch/EOL/area/conditional rules; all same/different-net cuts including cross-level spacing/stacking; upper/lower enclosures and expanded landings versus neighbors. Unknown stacking legality is not permission. Mandatory relevant FAIL/UNKNOWN blocks application.

## Bounded workflow

1. Bind schematic, complete saved layout, terminal islands, PDK fingerprint and axis/net/pin map. Resolve missing legal contacts before materializable candidates. Preserve adopted scope and asymmetric exceptions.
2. Classify every whole net as pair, self or an explicitly reasoned ordinary exception. Bind all physical island orbits, widths, directness and power width basis. Supply capacity, continuous bus/dual-trunk topology and electrical matching requirements remain explicit project constraints; unsupported topology requests block rather than silently becoming ordinary trees.
3. Run `scripts/symmetric_solver.py` or configured `symmetric-route` with bounded joint A*, mirrored access combinations, multi-terminal trees, self-axis bridges, alternate edges, beam reservations and atomic group-order restart. Missing rules/map/access block; `BUDGET_EXHAUSTED` and `NO_PATH_IN_GRAPH` do not prove global infeasibility. Never fall back to independent mate routing. `mirror_spec.py` remains a legacy compiler and an independent centerline verifier.
4. Keep required machine outputs: input audit, symmetry-map, candidate spec/intent, preview/SVG check, rule table and stage-specific symmetry-audit/drc-preflight. Put human explanations once in routing-review.md; reference metrics instead of repeating tables. SELECTED_RULES_PASS is not foundry DRC.
5. Apply to the authorized working target under the save policy only after READY_FOR_REVIEW, SVG PASS and fresh live geometry/rule checks. Joint search outputs are always `materializable=false`; a rectangular offline audit does not qualify live polygon/conditional rules. Use the existing qualified transactional importer. Do not mutate placement/PCells/wells/rings/dummies/reference or pin definitions through routing.
6. Independently read saved geometry/terminals and repeat connectivity, direction and symmetry checks. Run actual DRC/LVS for routed closure; ERC/EM/IR/PEX/post-simulation are conditional on requested reliability/performance claims and available qualified flows, not mandatory for intent generation.

The compiler checks declared centerline unions and via/contact centers, not every live polygon/array/environment. Keep actual saved-geometry verification. Missing site capability limits implementation; no automatic fallback to arbitrary asymmetric routing. No PEX means no equal-parasitic claim.
