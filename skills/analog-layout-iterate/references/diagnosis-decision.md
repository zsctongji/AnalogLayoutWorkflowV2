# Parasitic diagnosis and optimization decisions

Select experiments by the main symptom. Do not generalize a historical design's net names, widths, tolerances or numerical values into standards for every design.

## Symptoms, experiments and actions

| Symptom | Priority checks/isolation | Candidates supported by evidence |
|---|---|---|
| DC output drift with similar gain/total current | Source/supply voltage drops, mirror branch currents and common-source effective R; per-net R idealization | Center feeding, equal-current paths, paired contacts/vias, local parallel paths/higher-layer routing |
| Reduced bandwidth/longer settling with stable DC | Grounded/coupling C at sensitive high-impedance nodes, C-only variants, per-net C removal, critical transients | Shorter sensitive paths, adjusted capacitor access, reduced long parallel coupling |
| Unequal behavior on the two input sides | Source/drain/gate access R/C on both sides, resistance matrices and terminal voltages under identical conditions; finite input-source impedance | Symmetric branching and actual access matching; avoid equal lengths with different layers/contacts |
| Worse high-frequency response/noise | Multifinger gate access R, actual RC poles/spectral density and corresponding definitions | PDK-legal multipoint gate access or parallel contacts; verify added C and geometry |
| Overall performance worsens after one net improves | Cancellation of supply/source/mirror errors and operating-point changes | Joint candidates and full-RC verification; do not directly add individual benefits |
| All metrics abnormal or simulation incomplete | DUT/models/includes/port mappings, extraction exclusions, convergence and disk/resources | Repair configuration/run integrity before physical layout changes |

Label R-kernel results separately for pin pairs, port-to-finger paths and clusters of shorted terminals; total summed R is not effective R. Effective R for shorted terminal clusters is not the voltage drop under actual distributed currents: verify against operating-point voltages/currents. Attribute polysilicon, diffusion, contact and metal resistance separately; mark unknown segment provenance as unknown. Accumulated path-centerline length is not a single driver-to-load path.

C totals must retain both endpoint nets, ground/supply/coupling classification and the duplicate-counting policy. The same coupling capacitor contributes to incident-C experiments on both nets, so benefits overlap and cannot be added. AC-grounding supplies is an analytical approximation under explicit conditions only; it cannot erase actual supply R.

## Diagnostic-variant integrity

Bind hashes of the original complete PEX, device definitions, helper includes, models, TB and results. Use a parser for the original dialect when converting netlists; preserve device terminal order, parameters, units and escaped names. An unchanged complete variant must reproduce baseline metrics within the original precision used to extract metrics; fix the converter first if it does not. Delete/short only entries in the parasitic inventory, never intrinsic/intentional devices or capacitors, and never shorten actual model parameters.

Do not replace missing measurements with zeros: mark missing crossings, failed analyses and missing noise bands separately. Output shift may support diagnosis, but VOUT/open-loop gain cannot independently define input offset. Closed-loop PM requires the actual loop and feedback polarity.

## Decision record

`optimization-decision.json` must include at least the following semantic fields. Record host and sha256 alongside path references, without forcing older skills to change their native schemas:

- `schema: analog-layout-iterate.decision/v1`, `mode`, actual user authorization/scope, iteration number and adopted budget.
- `identity`: electrical source/reference, layout cellview+revision, TB+DUT and model/RC/PDK bindings.
- `conditions`, `metric_definitions`, `adopted_limits`, metric priorities/degradation budgets; use null when no limits have been adopted.
- `baseline`, `current`, `best_verified`: revisions, raw/metrics references, applicable checks and limitations; whether the current target corresponds to the best version.
- `diagnostics`: changed parasitic scope for each variant, complete-variant reproduction proof, logs/completion/integrity, metrics, causal confidence and interactions.
- `candidates`: id, owner/net, action, preserved items, evidence, expected direction/risks, responsible skill, checks and acceptance conditions.
- `iterations`: actual candidates, before/after revisions, checks/post-simulation, acceptance/rejection with reasons and restoration results. Do not invent measurements for unimplemented candidates.
- `decision_status`, separate `performance_status`, `stop_reason`, `next_action` and remaining uncertainty.

Accept candidates based on measured full-RC performance under identical conditions. Without specifications, do not use a fixed recovery-to-95%-of-schematic threshold universally; obey an explicit user threshold when provided. Accept improvements in the primary metric only when degradation remains within adopted budgets. For significant undefined tradeoffs, retain the candidate for the user's decision.
