---
name: analog-layout-workflow
description: Coordinate the analog-layout skills from schematic placement through diffusion sharing, guard rings, symmetric macro optimization, routing, DRC/LVS and optional PEX. Use for multi-stage layout work, resuming a layout pipeline or selecting the next stage; not for starting a circuit-design pipeline or running every stage for a single-stage question.
---

# Analog layout workflow

Coordinate existing skills without copying their algorithms or treating saved layouts or passing candidates as completed signoff. Creating/modifying this skill does not authorize operations on a specific layout.

## Scope and startup

First establish the mode: `plan` (planning/candidates, no OA writes), `execute` (execute explicitly requested stages), `resume` (continue from a valid checkpoint), or `inspect` (read-only status/defect inspection). Record the start and stop points. Only a request to complete the entire layout workflow covers placement → routing → DRC/LVS; PEX/post-simulation requires an explicit user request. A request to continue does not expand confirmed scope.

Read existing workflow-state.json and the minimum relevant evidence. Without a state file, establish status from actual current OA data/reports; do not infer completed stages from cell names or windows. Ask only for information affecting the next step that cannot be obtained from the schematic, PDK or existing decisions: source/reference/target, save policy, matching topology/axis, module isolation, metal options, ports/currents or simulation definitions. Reuse confirmed choices without repeatedly asking.

Apply the unified save policy in [save-policy.md](references/save-policy.md). Unless the user explicitly requests stage archives, all layout stages continuously update the same confirmed `lib/cell/layout`, with batch save and readback at each stage end. Copy the complete source as needed only when first establishing the working target. Do not automatically create stage cells for a new stage, failed retry or legacy clone-only adapter. Use staged mode only for explicitly requested archives/Save As, recording the original request and naming. Preserve the source schematic, PDK and unrelated designs; do not delete historical scratch cells without authorization. For a single-stage request, do not run the entire chain.

## Project configuration and reusable entry points

For new or migrated projects, prefer `configured_flow.py` from [project-configuration.md](references/project-configuration.md). Put cellviews/environment/tests/waivers in project configuration, parameter types and layer roles in the PDK mapping, and arrangements/module order/net policies in separate configuration. Include configuration fingerprints in handoff evidence. Offline generation does not authorize CAD writes; retain actual readback and checks at each stage. Legacy scripts provide compatibility only; do not carry their cell names, tracks or user decisions into a new project.

Use `routing.backend: strict_symmetric` or `configured_flow.py symmetric-route` for strict automatic symmetric routing. Following [solver-contract.md](../analog-layout-symmetric-route/references/solver-contract.md), bind complete-net pair/self/ordinary exceptions, actual pin-island mappings, a fixed axis and independent PDK rules. The new solver jointly searches actions legal on both sides and enforces Manhattan routing with odd-metal vertical/even-metal horizontal directions. Historical general guided paired search and `mirror_spec.py` template mode remain compatibility interfaces and are not joint solving. Offline outputs still require the original route skill's live/import/DRC/LVS gates.

## Default dispatch graph

Follow [dispatch-efficiency.md](references/dispatch-efficiency.md) to control initial-placement time and rework: assemble topology, dummy ownership and audits of all device m copies before writing; reuse unchanged evidence and invalidate only affected dependencies; prepare the environment per connection lifecycle and time individual stages. Use automatic topology recognition and default common-axis ABBA for matching recognition and initial placement. Batch stage writes at stage end according to [stage-writes.md](references/stage-writes.md), retaining required independent readback.

```text
Saved schematic + PDK + complete device/net/module identities
  → align initial placement (place is an optional alternative/shared refinement engine; do not duplicate initial placement)
  → diffusion-share (assessment required; skip only at explicit user request)
  → gate-access: complete legal gate contacts/local M1 and read back
  → guard-ring: isolation by functional module, including associated dummies
  → macro-symmetry → macro-opt → symmetry/access rechecks
  → PDK profile + complete routing intent → controlled routing/external-port access
  → DRC + independent LVS → paired repairs → DRC/LVS/symmetry rechecks
  → [when explicitly requested] PEX → pre/post simulation under identical conditions → reports/curves
  → [when performance analysis/optimization is requested] performance-opt → optimization decision
      → [implementation authorized] minimum causal physical stage → DRC/LVS → PEX/post-simulation → next decision
```

Dispatch by actual dependencies rather than blindly following the graph. Do not send a layout with guard rings/routing to a PCell-only importer, or compact macros coupled by existing routing as free rigid bodies. Establish module boundaries before sharing to avoid cross-module source sharing that breaks separate rings. Record implementation and candidates separately. See [stage-contracts.md](references/stage-contracts.md) for detailed entry conditions, handoff evidence and rollback rules; read it before the first multi-stage dispatch.

| Stage | Responsible skill | Dispatch choice |
|---|---|---|
| Initial placement | [analog-layout-align](../analog-layout-align/SKILL.md) | Default; do not convert a user's common-axis requirement into common-centroid matching |
| Alternative placement/shared refinement | [analog-layout-place](../analog-layout-place/SKILL.md) | Do not duplicate ALIGN initial placement; invoke as required by the sharing skill |
| Shared active diffusion | [analog-layout-diffusion-share](../analog-layout-diffusion-share/SKILL.md) | Same net and functional module permit implementation, including central edges and chains; verify geometry and electrical connectivity after saving |
| Legal gate access | [analog-layout-local-access](../analog-layout-local-access/SKILL.md) | Add missing contacts and local escapes only; not global routing |
| Per-module guard rings | [analog-layout-guard-ring](../analog-layout-guard-ring/SKILL.md) | Do not generate before gate-access passes |
| Common-axis symmetry/compaction | [analog-layout-macro-symmetry](../analog-layout-macro-symmetry/SKILL.md), [analog-layout-macro-opt](../analog-layout-macro-opt/SKILL.md) | Preserve complete macros and reaudit the axis and actual geometry after optimization |
| PDK access and rules | [analog-pdk-profile](../analog-pdk-profile/SKILL.md) | Reuse valid fingerprints; does not replace the foundry deck |
| Default template routing | [analog-layout-symmetric-fast](../analog-layout-symmetric-fast/SKILL.md) | Default when no routing method is explicitly selected; verify the actual axis/map, configure complete templates, and reuse route validation/import |
| Joint symmetric search | [analog-layout-symmetric-route](../analog-layout-symmetric-route/SKILL.md) | Use when the user explicitly selects this skill or requests joint mirrored path search; do not run a second global planner |
| General/non-axis-symmetric routing | [analog-layout-route](../analog-layout-route/SKILL.md) | For matched nonmirrored structures or explicit user choice; do not fabricate mirror symmetry |
| Checks and repairs | [analog-layout-drc](../analog-layout-drc/SKILL.md), [analog-layout-lvs](../analog-layout-lvs/SKILL.md) | Check authorization is not repair authorization; recheck both after geometric repairs |
| Extraction/post-simulation | [analog-layout-pex](../analog-layout-pex/SKILL.md) | Independent LVS and binding checks; retain limitations from unclosed DRC |
| Performance iteration decisions | [analog-layout-iterate](../analog-layout-iterate/SKILL.md) | Invoke as needed after postsim; isolate parasitics and select candidates, then recheck/extract/simulate after bounded implementation |

`performance-opt` is an explicitly optional stage. The default layout flow does not automatically expand into performance optimization, and completing post-simulation does not authorize physical modifications. Analysis requests produce decisions only. When optimization implementation is already requested, reuse that authorization and return to the minimum causal stage within budget. Its checkpoint records decision completion rather than achieved performance. After physical revision changes, invalidate old checks, extraction, post-simulation and optimization decisions according to dependencies. Preserve immutable evidence for every iteration and record the best verified version. Retain the single-layout save policy and batch writes at the end of each physical stage.

## Routing method selection

Default to `analog-layout-symmetric-fast` / `backend: symmetric_fast` when the user has not selected a routing method. An explicit skill/backend or a clear request for joint mirrored search takes precedence. Explicit general routing uses `analog-layout-route`. Default selection does not invent an axis, pair map or exception: unavailable geometry or unsupported topology blocks the relevant route rather than silently changing methods. Fast and joint routes share existing validation/import and the same DRC/LVS requirements. Record the selected method and reason in the routing handoff; keep existing configured choices on resume.

## Dispatch invariants

- Default matching is common-axis (`common_axis`), with automatic recognition of equal-size differential pairs/current mirrors. For equal, even copy counts, use ABBA in each row. Enable `common_centroid` only for a matching group explicitly requested by the user; do not reuse a subskill's default common-centroid seed. Pass default policy and per-group exceptions to all stages. User-specified array arrangements apply only to their corresponding groups. Common-axis checks do not require equal two-dimensional centroids of the two devices.

- For explicit ABBA/BAAB requests, record `mode: explicit_pattern`, `pattern` and the actual user instruction in per-group matching_overrides. Sort by live coordinates to verify logical device identities, the x centers of copies of each device against the declared axis, and the declared same-identity mirror scope. A centered module bbox or reflected geometry from identical masters cannot replace this check. Internal AABB failure must return to that matching group for repair; macro translation cannot make it pass.

- Maintain one authoritative dataset for the source schematic, device dimensions/m/nf/nets, matching topology, actual core axis and module/dummy identities. Resolve parameter-mapping or identity conflicts first; layout labels do not replace connectivity.
- Same-S-net active–dummy/dummy–dummy edges may be sharing candidates; different or missing S nets cannot share, and independent guard-ring modules cannot share across boundaries. Preserve legal actual cont overlap and independent D/G/B.
- Macros include devices, dummies, shared active/cont, complete rings/wells/ROD, local wires/vias/ports; do not move devices alone. Read complete-macro-envelope clearance targets from the current circuit configuration. Actual spacing is the maximum of the configured target, applicable process isolation and required access space; retain the basis for each pair. Unconfigured targets must not inherit numerical values from other projects.
- Matched cores require strict reflection. Prefer axis-centered or connected two-sided collection for common nets; evaluate an axis-centered trunk first for single-ended outputs, with explicit exceptions for noncorresponding branches. Two-sided trunks must belong to the same net and be connected. Odd-metal vertical/even-metal horizontal directions use actual metal levels. Follow routing-skill requirements for PDK conditional rules, via spacing/stacking and legal local-M1 exceptions.
- Include external ports, supply and body-ring connectivity in complete closure; completed internal wires do not establish circuit completion. Bias values such as 200 µA cannot automatically serve as maximum supply current.
- Unknown adapter capabilities, PDK rules or actual geometry block corresponding writes. Candidate/blocker evidence may be output, without unsupported pass conclusions. Do not modify the original PDK library.

`share` must not be skipped as an optional optimization, for missing PDK probes/adapters, or to prioritize gate contacts. `SKIPPED` is allowed only at an explicit user request to skip diffusion sharing. The receipt must retain the actual user instruction in `user_skip_authorization` (`source: user`, `scope: share`, `instruction`). Existing unauthorized skip records become invalid on resume and block downstream gate-access/ring stages. With no candidates or feasible edges, complete applicability assessment and supply `NO_APPLICABLE_EDGES` evidence. Unknown conditions remain candidate/blocked and cannot be treated as no feasible edges.

Auxiliary conopc for newly constructed contacts/guard rings is optional by default (`include_conopc: false`) and may be omitted at user request. Native-via/PCell process geometry is generated by the PDK; do not delete or alter it without authorization. Determine conopc rule compliance from actual foundry reports; an omission policy does not establish DRC CLEAN. Read project waivers only from actual user instructions in current project configuration, and bind specific rules and revisions according to [DRC scope](../analog-layout-drc/SKILL.md#user-specified-conopc--density-scope). Generic skill text provides no waiver authorization.

## Each handoff and resume

Read the responsible skill's complete SKILL.md and the references required for the mode before acting; preserve its status terms and adapter limitations. Load operate-virtuoso-bridge only for live CAD operations. Reuse previously read upstream instructions and unchanged evidence; do not repeat GitHub/reference-layout research at every stage or run the entire circuit-design pipeline.

Write one checkpoint at stage end: actual input/output revisions, evidence paths/hashes, technical conditions, local-verification/signoff status, unresolved items and next action. Read [checkpoint.md](references/checkpoint.md) when creating or resuming a checkpoint for state format and invalidation propagation. File existence does not establish valid evidence; check relevant fingerprints and save status before resuming.

During execution/resume, use `workflow_runtime.py` from [runtime.md](references/runtime.md) to validate and select stages. `run_stage.py` runs only registered hash-pinned adapters; missing site qualification is an explicit blocker. The shared transaction interface is `adapter_runtime.py`, with the bridge owned-rectangle backend in `virtuoso_adapter.py`. Leave unsupported PCell/ROD/via/pin operations to qualified adapters in the original skills. Code creation and passing unit tests do not qualify all live stages.

Return failures to the minimum causal stage: repair adapters/export/rule bindings before considering geometry. Controlled repairs save a new revision, read back and check actual mirrored objects and connectivity. Every iteration requires new evidence and explainable progress. Stop and request direction for repeated identical causes, drift or actions beyond authorization. Do not retry indefinitely, relax tolerances or suppress devices to manufacture a pass.

## Final delivery

Maintain one human-readable workflow-summary.md and one workflow-state.json, referencing required machine evidence/raw logs from substages without duplicating complete reports. Summarize the final cellview, completed/skipped/blocked stages, area, axis/symmetry exceptions, connectivity, DRC/LVS and optional PEX metrics. Mark deferred/waived/incomplete results.

Claim geometric/electrical check closure only with complete DRC CLEAN + independent LVS VERIFIED_MATCH for the same current saved revision. This does not automatically establish reliability/performance signoff. List original violations, approved waivers and deferred items separately. Sharing/guard rings initially permit local verification only; upgrade corresponding verification status after final foundry evidence passes. Without specification thresholds, PEX reports MEASURED only; open-loop transfer phase is not phase margin.
