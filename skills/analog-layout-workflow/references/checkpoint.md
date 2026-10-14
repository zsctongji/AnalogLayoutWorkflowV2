# Checkpoints and invalidation propagation

Place files in this design run's artifacts directory, rather than another project selected by an unrelated cwd. State the state-file path in the startup summary. On resume, the saved database and raw evidence are authoritative; state is only an index.

## Minimum structure

workflow-state.json uses `schema: analog-layout-workflow.state/v1` with these fields:

- `run_id`, `mode`, `scope` (start/stop/requested stages), `last_human_decision` (the user's semantic decision, not an internal approval token).
- `source`, `reference`, `current`, `destination`: explicit lib/cell/view and saved-revision fingerprints. Advance `current` only after save + readback.
- `save_policy`: defaults to `{mode: single-layout, working_layout: {lib,cell,view}}`. Use `staged` only for explicit user archive requests, recording `user_archive_request: {source: user, instruction: <original request>}` and stage targets. Save a new revision of the same working layout at each stage. Stage logs/hashes are not layout copies, and failed results are not final deliveries. See [save-policy.md](save-policy.md).
- `constraints`: matching topology, axis direction/coordinate/units, module/dummy map, fixed devices/exceptions, metal/PDK/profile fingerprint, gap/channel and port/supply constraints. Unknown values are null, without fabricated defaults.
- `stages`: indexed by stage id, with `status`, `skill`, `input_revision`, `output_revision`, `depends_on`, `artifacts` (path/sha256/type), `validation`, `limitations`, `next_action` for each entry. Preserve subskill verdicts; generic statuses are indexes and must not erase their semantics.
- `verification`: separate DRC, LVS, symmetry, connectivity, PEX and simulation, each bound to revision/policy/raw result. List waivers/deferrals separately.
- `next_stage`, `blocked_reason`, `summary_path`: update after each stage checkpoint, without duplicating state writes after every tool call.

Recommended index statuses: NOT_STARTED / CANDIDATE / MATERIALIZED_UNVERIFIED / LOCALLY_VERIFIED / CHECKED_WITH_LIMITATIONS / CLOSED / SKIPPED / BLOCKED / STALE. CLOSED requires the stage's corresponding strong evidence; local verification cannot impersonate foundry signoff. SKIPPED requires a reason, scope and evidence that downstream dependencies remain safe.

For diffusion-share, SKIPPED is permitted only at an explicit user request, retaining `user_skip_authorization: {source: user, scope: share, instruction: <actual user instruction>}`. Missing PDK probes/tools/rules remain CANDIDATE or BLOCKED. A complete assessment proving no feasible edges records an evaluated NO_APPLICABLE_EDGES result. On resume, invalidate old SKIPPED records without user authorization. Downstream geometric evidence may be retained but cannot continue as a checkpoint with satisfied dependencies.

Each artifact/database fingerprint records the generating tool/method, dependencies, units, coordinate system, hierarchy/top and saved status. A screenshot hash cannot replace a complete OA-hierarchy fingerprint. Identify the actual host for remote/local paths; a file hash cannot replace live-result binding. A run-local target clone requires identity verification/rebinding even with identical geometry; do not retitle old-run results as new-target results.

## Dispatch/resume algorithm

1. Restate the latest user decision and scope, and check source/current/target and save status without overwriting unsaved edits.
2. Check currently required artifact hashes and dependency/revision/PDK/policy bindings. Verify raw-result integrity under the responsible skill; unverifiable data is STALE/INCOMPLETE and cannot be used directly.
3. Within requested scope, select the earliest incomplete/invalid stage with valid dependencies. Reuse completed valid stages. Do not rerun an algorithm when coordinate/evidence updates suffice.
4. Pass a minimal handoff to the executing skill: exact source/target, valid input fingerprints/paths, immutable constraints, this step's action/mode, required output evidence and unresolved items.
5. Return updated status and next action; do not execute beyond the authorized stop. Report specific BLOCKED causes for unmet dependencies instead of hiding them with default names or templates.

## Change propagation

| Change | Required invalidation/update | Usually retained |
|---|---|---|
| Source electrical identity/W/L/m/nf or PCell serializer/master | Affected place/share/access/ring/macro/route, DRC/LVS/PEX/postsim | Independent module evidence with no dependency, after reuse verification |
| Legal sharing/local-contact changes | Affected access, ring envelopes, macro snapshots, route, DRC/LVS/PEX | Unchanged instance parameters and schematic |
| Ring/well/body-tie changes | Macro geometry/access, route/isolation, DRC/LVS/PEX | Schematic and facts about unchanged shared edges; rebind final signoff |
| Complete-macro rigid translation | Actual snapshot/terminal coordinates/obstacles, route, foundry checks/PEX | Internal parameters/local topology; retain contact/ring-structure evidence only after readback |
| Route/pin/via geometry/net changes | Connectivity/actual symmetry, DRC/LVS/PEX/postsim | Internal place/share/ring layout if unchanged and confirmed by readback |
| Axis/matching scope changes | All dependent matching/symmetry/route/repair audits; upstream placement when needed | Electrical schematic identity; axis changes are not automatically authorized |
| Deck/metal/PDK conditions/waiver changes | Corresponding rule checks/run results and genuinely dependent physical stages | Device identities with unchanged parameters |
| TB/models/measurement definitions only | Baseline/postsim and metrics; invalidate PEX if extraction dependencies change | Unchanged layout/LVS/RC netlist when extraction corner is unchanged |
| Post-simulation result/revision/metric-definition changes | performance-opt decisions; reevaluate generated but unapplied candidates | Original iteration evidence; do not relabel old decisions as current |
| Explanatory text/nonexported annotations only | Verify no actual stream/label/connectivity effect; rebind changed revision | Facts proven unchanged by canonical geometry/terminal comparison |

If source-layout drift is found, do not continue writing to old intermediate versions. Diagnose differences first and preserve original results. Reuse saves repeated work, not fresh readback, strong verification or user decisions.
