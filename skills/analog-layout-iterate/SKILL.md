---
name: analog-layout-iterate
description: Analyze analog post-layout performance degradation, isolate parasitic causes, rank physical optimization candidates and coordinate bounded re-extraction/simulation iterations. Use for post-sim diagnosis or performance-driven layout optimization; not circuit sizing or initial layout.
---

# Analog Layout Iterate

Use post-simulation evidence bound to actual layout revisions to decide where to change, why, and how to assess benefits. Protect the electrical design by default; do not manufacture improvements by changing models, stimuli, dimensions or measurement definitions.

## Modes and boundaries

- `analyze`: for requested analysis/optimization decisions, verify existing data, run in-scope private diagnostic simulations when necessary, and output causes, candidates and next actions without OA writes.
- `optimize`: when the user has requested performance-optimization implementation, apply candidates and verify closure within that authorization. Reuse existing authorization without repeated confirmation each iteration. Deliver concrete candidates before asking about dimension/topology changes, altered matching requirements or expanded simulation conditions beyond the original layout-optimization scope.
- Creating/modifying this skill does not authorize execution or writes on the current design. Without a request for automatic optimization, completing post-simulation does not start iterations automatically.

Use the same confirmed working layout according to [save policy](../analog-layout-workflow/references/save-policy.md); create stage copies only on explicit user request. Original results and diagnostic files for each iteration may be saved independently and are not additional layouts. Batch-save CAD changes at the responsible physical stage's end, perform independent readback, and retain transaction/snapshot evidence needed to restore the best saved version.

## 1. Establish a comparable baseline

Through [analog-layout-pex](../analog-layout-pex/SKILL.md), check source electrical identity, target revision, independent LVS, RC extraction/DUT substitution, port order, models/corners, bias/load/stimuli/temperature and metric definitions. Different names with electrical equivalence may be supported by proof; identical names with different dimensions/nets are not comparable. Proven opens/shorts/wrong DUTs return to connectivity checks before performance interpretation.

Record schematic baseline, current complete PEX, raw data and revision hashes. Check DC operating points, branch currents, source voltage drops and device operating regions before evaluating dynamic metrics. Static output shift is not automatically input offset; open-loop phase is not phase margin; one TT result does not represent PVT or Monte Carlo.

Adopt existing user metric priorities, explicit limits and allowed degradation. Without specifications, report `MEASURED` and relative changes instead of inventing `SPEC_PASS`. `SPEC_PASS` requires every requested applicable metric to be valid and meet adopted limits/corners; do not omit missing measurements. Without input/output targets, similarity to the schematic does not automatically define the best operating point. Do not reduce all metrics to a weighted total score the user has not adopted.

## 2. Move from correlation to cause isolation

Use the parser and sparse R/C kernels in [analog-netlist-crawl](../analog-netlist-crawl/SKILL.md), and read applicable sections of [diagnosis and decisions](references/diagnosis-decision.md). Check effective R, terminal voltages and branch imbalance at access/common-source/current-mirror/supply paths first, then high-impedance-node C, coupling and critical time constants. Matching requires actual electrical-path checks; ABBA appearance cannot replace them.

Select the minimum diagnostic set for the main hypothesis: R-only, C-only, no-interconnect-parasitic variants preserving extracted device geometry, or per-net/branch idealization. Do not mechanically run every variant. All variants replace specified parasitics only in private simulation files, preserving intentional devices, capacitors, models and test conditions.

For flattening, renaming, node merging or netlist conversion, first prove that an unchanged complete PEX variant reproduces the original simulation. Check include closure, all device parameters, ports and node connectivity; equal device counts alone are insufficient. Record actual removed/shorted elements and nets for every variant without confusing grounded C with coupling C.

Draw conclusions only after diagnostic completion and valid operating points/data. Idealization benefits are sensitivity evidence, rather than predictions for manufacturable layouts. Some changes destroy existing error cancellation; individual benefits cannot be added.

## 3. Generate executable optimization decisions

Output a small set of physically justified candidates. For each, state evidence/confidence, target nets and actual owners/geometry, actions, preserved items, expected direction/side effects, invoked skill, validation metrics and acceptance/rejection conditions. Distinguish `OBSERVED`, `ISOLATION_SUPPORTED`, `HYPOTHESIS` and `PHYSICALLY_VERIFIED`.

Resolve electrical/manufacturing errors before improving critical specifications. Without hard specifications, compare Pareto tradeoffs using established primary metrics; do not silently accept significant tradeoffs. Distinguish improvement thresholds from numerical reproduction error. Without reliable thresholds, report changes without statistical-significance claims. Change placement/contacts/macros only when evidence points there; do not rerun all initial placement.

Hand routing/contact candidates to [local-access](../analog-layout-local-access/SKILL.md), [symmetric-route](../analog-layout-symmetric-route/SKILL.md) or [route](../analog-layout-route/SKILL.md), preserving original matching mappings and PDK conditions. Do not shorten wires by breaking well/ring isolation. Vias and upper/lower landings must be fully contained in corresponding connected metal shapes.

## 4. Bounded implementation and measured selection

`analyze` ends after the decision. Each `optimize` iteration applies one attributable candidate or an explicitly dependent joint candidate. Run local connectivity/access/electrical-matching readback, then recheck through [DRC](../analog-layout-drc/SKILL.md) and [LVS](../analog-layout-lvs/SKILL.md). Reuse existing explicit waivers without expanding them to pass. Invoke PEX for fresh extraction and post-simulation under identical conditions; judge actual improvement instead of substituting diagnostic idealization results.

Record initial baseline, current candidate and best verified version separately. Accepted candidates must pass current applicable checks and meet adopted specifications/degradation budgets. Restore rejected candidates through a capable transaction and verify by readback; failed saved versions cannot be the best version. If restoration is impossible, retain `SAVED_NOT_CLOSED`, stop further writes and report actual target status.

Prefer the user's budget. Without one, automatically implement at most 3 physical-candidate iterations, selecting diagnostic simulations per hypothesis and recording each budget in advance. End the iteration flow when specifications are met, candidates are exhausted, two consecutive iterations produce no meaningful improvement, the same cause fails again, budget is exhausted or out-of-scope actions are required. Infrastructure/convergence failures are not candidate performance degradation; diagnose failures before changing wires blindly.

## Dispatch and delivery

The layout dispatcher's optional `performance-opt` stage follows `postsim`. It is an analysis/decision checkpoint, not a universal CAD writer. Candidate execution returns to the minimum causal stage. Updated route/access evidence invalidates DRC/LVS/PEX/postsim and old decisions, then new results enter the next iteration. Do not register live writers for skill creation or unauthorized analysis.

Maintain one `optimization-decision.json` using fields in the diagnostic reference, with immutable original run evidence. Within a workflow, update only its human-readable summary and reference the decision. For standalone skill use, write one brief summary. Decision status is `DECISION_READY / NO_ACTION / STOPPED / BLOCKED`; separate performance status is `MEASURED / SPEC_PASS / SPEC_FAIL / INCOMPLETE`. Decision completion or budget exhaustion does not establish achieved performance.

Deliver the best verified layout/revision, baseline/best metrics, causal evidence, candidate acceptance/rejection records, whether the current target is the best version, applicable corners/waivers/unverified items, stop reason and next action.
