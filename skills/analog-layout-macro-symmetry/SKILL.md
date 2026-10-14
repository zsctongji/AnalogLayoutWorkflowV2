---
name: analog-layout-macro-symmetry
description: Align intact analog macros to a common symmetry axis, verify reflected geometry and pin mapping, and prepare symmetric-routing candidates.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

Follow [stage-writes.md](../analog-layout-workflow/references/stage-writes.md): planning and candidate checks do not write to CAD. Collect the complete stage object/shared-chain/move list, apply it in one batch at the end of the stage, save once, then perform independent readback. Reads must not implicitly commit pending writes. Reuse valid live qualification and unchanged evidence.


# Macro symmetry

Organize intact post-ring macros around the selected common axis; symmetry precedes area. Honor candidate-only requests.

## Execution economy

Use only the requested mode and its references; a question does not start the workflow. Reuse already-read instructions and revision-bound evidence. Recheck changed dependencies and obtain fresh live readback before writing; do not rerun upstream stages just because another skill starts. Existing user choices and authorized destinations carry forward. Keep required machine artifacts, but consolidate human explanations into one run summary. Load the bridge only for live CAD operations; research and historical examples are optional. Run signoff checks when requested or required for the claimed completion state, not for every offline candidate.

## Planning

Read [contract.md](references/contract.md) and the sibling [macro snapshot contract](../analog-layout-macro-opt/references/contract.md) when preparing inputs. Reuse existing valid complete snapshots.

1. Reconcile all devices, dummies, shared contacts, rings, wells, shapes, vias, pins and ROD ownership. Cross-macro routing/shared wells/ROD dependencies must be frozen or resolved before moving blocks.
2. Keep the existing core axis unless the user changes it. Use actual internal device axes, not ring bboxes. Specify axis direction/coordinate, self-symmetric macros, functional mirror pairs, fixed blocks, order, clearances and escape/span budgets. No fake counterparts or automatic reference/output device exchange.
3. `scripts/symmetry_plan.py --snapshot ... --request ... --out NEW_DIRECTORY` generates rigid-translation candidates for supplied row orders. x=a means a vertical axis; y=a means horizontal. Grid/half-grid conflicts and unknown process gaps remain explicit.
4. Audit represented actual per-layer geometry, not just envelopes. Missing complete flattened PCell/ring/cont/well/metal polygons yields COAXIAL_ONLY; supported geometry passing reflection yields REPRESENTED_GEOMETRY_SYMMETRIC. Unsupported partitions/shapes require qualified union checking, not relaxed tolerance.
5. For routing handoff read [routing-handoff.md](references/routing-handoff.md): verify involutive device/net mappings, every physical pin island, same-layer access and mirrored escape space. ABBA/common-centroid/rotational symmetry alone does not prove electrical mirror symmetry.
6. Rank symmetry validity, routing readiness, then area. Explicitly report peripheral exceptions; core-only evidence cannot establish global symmetry. Internal failures return to the affected placement/share/ring step; this planner does not rebuild or reflect PCells.

## Application and limits

Live application uses the bridge and sibling [materialization.md](../analog-layout-macro-opt/references/materialization.md). Use the current working layout in a qualified same-cell transaction; clone the entire cellview into an absent target only for initial working-layout creation or explicit staged/save-as requests. Translate every object once and read back transforms, contact coincidence, rings, wells, ports and actual axes. Refresh geometry/access evidence and downstream coordinates. The script itself has no Virtuoso writer; unverified saved results remain MATERIALIZED_UNVERIFIED.

Requires sibling macro-opt API and Python 3.10+. Preserve signoff status separately; geometry symmetry does not prove equal parasitics or LVS/DRC. [research.md](references/research.md) is background, not a runtime prerequisite.
