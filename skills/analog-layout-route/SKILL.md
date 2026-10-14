---
name: analog-layout-route
description: Plan, validate, review, and optionally materialize PDK-aware analog routing from analog-pdk-profile and analog-layout-align terminal-access artifacts. Use for route planning, access/connectivity closure, matched routing, reference-layout comparison, or controlled Virtuoso routing. It does not replace foundry DRC/LVS or silently edit a cellview.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Analog Layout Route

Produce a reviewable routing intent before any Virtuoso write. Authority order is: connectivity and PDK/reliability rules, circuit intent, matching/symmetry, sensitive-node isolation, RC/current capability, then congestion and area. Foundry decks remain signoff authority.

## Configuration-driven reuse

For new designs, read sibling [project-configuration.md](../analog-layout-workflow/references/project-configuration.md). Use `configured_flow.py` for mapped device parameters, declarative rows/floorplan and policy-driven routing search. Retain actual matching/access/PDK and live-import gates; legacy defaults and project-specific helper patches are compatibility paths, not the cross-design interface.

Workflow default routing uses sibling [analog-layout-symmetric-fast](../analog-layout-symmetric-fast/SKILL.md) and `backend: symmetric_fast`, unless the user explicitly selects another method. This skill supplies shared validation/import and explicitly selected general routing. For explicitly selected joint common-axis routing, dispatch configured `backend: strict_symmetric` to sibling [analog-layout-symmetric-route](../analog-layout-symmetric-route/SKILL.md). Its joint solver hard-checks both reflected actions and actual-level directions; this skill supplies the shared intent/SVG/application gates. General guided pair search is still available, but does not establish pointwise mirror legality during search. Do not run a second global planner over an accepted joint candidate or independently repair its mate.

## Inputs and references

Require matching targets and fresh provenance for:

- `analog-pdk-profile/v1` with a valid fingerprint and routing readiness;
- `analog-layout-align.terminal-access/v1` from the exact placed revision;
- `analog-layout-route.spec/v1` with every routed net in `required_nets` and an explicit `net_class`.

Read only the detail needed for the current mode:

- [routing-contract.md](references/routing-contract.md): route-spec, intent, matching, connectivity, contact, and SVG contracts.
- [routing-practice.md](references/routing-practice.md): topology, ordering, width, layer, via, shielding, and analog tradeoffs.
- [planner-contract.md](references/planner-contract.md): automatic candidate generation with `route_planner.py`.
- [reference-layout.md](references/reference-layout.md): user-authorized manual or legacy reference layouts.
- [routing-checklist.md](references/routing-checklist.md): evidence gates before routing, before materialization, and after readback.

Never copy numeric rules from examples.

## Workflow

1. Validate profile readiness/fingerprint and require exact target agreement among profile context, terminal access, and route spec. Stop on stale identity, missing required terminals, or unsupported rules.
2. Classify and plan each net using `routing-practice.md`. Cover every required physical `pin_island_id`; use profile-backed `contact_landings` for poly-only access. Require one conductive component per required net—endpoint coverage alone is insufficient.
3. For automatic search, use `route_planner.py` under `planner-contract.md`. A candidate is not authoritative; bounded search failure is not proof of global unroutability. Matched/differential nets require one explicit matching rule and supported coupled strategy, never independent routes plus one-sided length tuning.
   Review terminal span separately from excess route length, and examine shared-tree/duplicate metrics plus per-layer width and area. The ordinary planner compares actual frontier costs, reuses existing tree interiors, and prunes redundant generated geometry; current-driven, matched and explicit-length topologies retain their specialized constraints. Use the documented frontier budget and area/bend weights when balancing quality and runtime.
4. Optionally compact reviewed redundant fragments with `compact_route_spec.py`. It only merges equal-width, same-net/layer/purpose collinear Manhattan intervals and exact duplicate vias. Rebuild against fresh terminal access afterward.
5. Build the intent and annotated preview:

```powershell
<python> scripts/route_intent.py build `
  --profile <profile.json> --terminal-access <terminal-access.json> `
  --spec <route-spec.json> --out <intent.json> `
  --report <report.md> --preview <preview.svg>

<python> scripts/svg_route_check.py `
  --intent <intent.json> --svg <preview.svg> `
  --out <svg-check.json> --report <svg-check.md>
```

6. Require intent `decision.status == "READY_FOR_REVIEW"`, SVG status `PASS`, complete physical access, one component per required net, and all declared matching/symmetry limits passing. Preserve warnings and unresolved conditional rules.
7. Review live-target obstacles, realized joints, current/IR/EM basis, return paths, critical-net directness, and matched access/layer/via/environment evidence through checklist Gate 2. Every via's complete lower/upper metal landing must be contained in the corresponding same-net wire contour, without protruding tabs or corner shoulders; use actual path end extensions, widths and unions, not a centerline/cut-only test. Offline obstacle snapshots may generate candidates but cannot authorize materialization.
8. Materialize into the already confirmed working cellview by default; do not ask for a new stage destination. Only an explicit user archive/save-as request selects a different target. Use a qualified same-cell transaction with the passing hash-matched SVG artifact, `operate-virtuoso-bridge`, and `virtuoso-layout-practice`; `apply_routing_intent.py` may be used only within its verified capabilities. Reject drift, discard only this stage's unsaved partial work, save only complete work, and read back object identities, nets, geometry, and counts.
9. Complete checklist Gate 3, then hand the exact saved target, hashes, PDK fingerprint, object IDs, readback, and matching evidence to `analog-layout-drc`. Continue with applicable LVS/ERC/antenna/EM, PEX, and post-layout simulation; do not call intent, SVG, or visual review signoff.

Validate an existing intent with:

```powershell
<python> scripts/route_intent.py validate --profile <profile.json> --intent <intent.json>
```

## Reference-layout mode

Keep an authorized reference cellview read-only. Run `compare_reference_layout.py` before transferring a policy. Raw length/via comparisons stay disabled unless exact placement transformation and terminal correspondence are proven. Never transfer pair geometry from a reference that fails the target matching limits; supply widths, loops, and via arrays remain conditional on current, IR/EM, and current-PDK evidence.

## Modification boundary

- Intent generation, comparison, and verification-only readback are non-mutating.
- Do not change placement, PCells, devices, wells, taps, guard rings, or pins without separate authorization.
- Never infer the target from the frontmost window or route into a merely open revision.
- Refuse materialization while the exact target is open in Layout Editor; use a closed, explicitly prepared revision so unsaved edits cannot be purged or overwritten.
- Abort without saving on target, technology, terminal-access, placement, hash, or partial-creation drift.
- Internal device connectivity is not hierarchy-ready completion when external nets lack an authorized boundary/pin plan.
