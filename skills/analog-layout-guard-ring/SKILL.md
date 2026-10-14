---
name: analog-layout-guard-ring
description: Plan and create PDK-qualified guard rings per functional MOS module, including associated dummies, after verified placement and gate access.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

Follow [stage-writes.md](../analog-layout-workflow/references/stage-writes.md): planning and candidate checks do not write to CAD. Collect the complete stage object/shared-chain/move list, apply it in one batch at the end of the stage, save once, then perform independent readback. Reads must not implicitly commit pending writes. Reuse valid live qualification and unchanged evidence.


# Functional-module guard rings

Consume verified v2 placement, terminal access and declared sharing edges. Preserve device placement, matching and functional ring domains.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Plan

1. Check all enclosed MOS gate islands, including copies/dummies, using `scripts/check_gate_access.py` and [gate-access.md](references/gate-access.md). Poly→contact→accessible metal must already be realized and PDK-qualified. Missing/stale access blocks ring generation; reserve the full gate contact/landing/escape envelope. Reuse valid gate evidence only for the same geometry/revision.
2. Run `partition_modules.py`. Each differential pair, mirror, bias/output module gets its own ring with associated dummies, even when polarity/body/source nets match. Explicit module maps need complete unique MOS coverage. Resolve ambiguous ownership; do not merge modules to fit.
3. Read [reference-and-qualification.md](references/reference-and-qualification.md) for recipe/request/generator details. Establish LPPs, active/implant/metal continuity, contact pitch/enclosure, well/device/inter-ring clearance, tap distance and body tie from current PDK rules or a qualified generator. Reuse an unchanged qualified recipe. Inspect a manual reference only if requested or needed to qualify a missing recipe; reference layouts are project inputs rather than bundled rule sources.
4. P+ planning uses `plan_guard_ring.py --terminal-access ... --gate-review ...`. N+ remains a guided generator workflow with explicit nwell containment. Check all module envelopes together, pin access, corner/seam cuts, well fill and foreign geometry. Intentional source overlaps require declared same-module edges and contact/isolation evidence.

## Apply and verify

Apply to the current working layout by default; create a stage target only for an explicit user archive/save-as request. Prefer qualified PDK MPP/ROD generation; never synchronously invoke the interactive `leHiCreateGuardRing()` through bridge eval (known IPC blocking). The GUI shortcut is a manual alternative, not an automated prerequisite.

Read back unchanged device count/identity/parameters/transforms, closed rings, intended layers, all-side contacts, seam spacing, well clearance, gate access and no unintended shorts. Body ties require actual conductive connection to the intended net; labels alone do not connect rings. A cross-module shared edge or inadequate clearance is a placement conflict, not permission to merge rings or move devices.

Deliver module map, qualified recipe, ring plan and saved evidence. PREFLIGHT_ONLY/save success is not DRC/LVS closure; use the actual foundry checks before claiming completion of electrical isolation.

By default, do not add auxiliary `conopc` shapes for newly constructed contacts or guard rings. Enable them with `include_conopc: true` or `--include-conopc` in the corresponding generation script. Preserve shapes supplied by native vias/PCells, and verify actual cuts/landings and connectivity. Record the DRC impact of omitting conopc from the actual reports.
