# Expected and generated evidence

[expected.json](expected.json) is a small static acceptance contract. It contains
counts, complete net scope and explicit `NOT_RUN` signoff statuses. It is not a
DRC/LVS/PEX report.

Generated evidence belongs to the chosen ignored run directory:

| Artifact | Evidence |
|---|---|
| `work/plan/configuration-binding.json` | External configuration, source and copy bindings |
| `work/plan/placement-intent.json` | Complete copy placement, dummy ownership, ABBA and bbox checks |
| `inputs/route-anchors.json` | Synthetic physical terminal identities and derived bus positions |
| `inputs/generated-tracks.json` | Candidate and selected paired tracks for each physical pin orbit |
| `inputs/seed-spec.json` | Complete route/via/access geometry before template compilation |
| `work/routing/symmetric-fast/request.json` | Bound fast request, complete net scope and synthetic via evidence |
| `work/routing/symmetric-fast/intent.json` | Physical access coverage, connectivity, metrics and limits |
| `work/routing/symmetric-fast/svg-check.json` | Preview identity and represented symmetry consistency |
| `work/routing/symmetric-fast/direction-audit.json` | Actual metal-level odd/even direction gate |
| `reports/independent-geometry-audit.json` | Independent represented rectangles/cuts, landings and local M1 audit |
| `reports/result.json` and `reports/summary.md` | Actual offline outcome and all pending physical stages |

Generated data may contain absolute run paths as provenance; it is never bundled
as repository source. `BLOCKED` runs preserve their inputs and reason in
`reports/result.json`. Do not edit results to make a failed candidate pass.

The synthetic profile's readiness means it can drive this offline compiler; its
boundary fields explicitly deny foundry qualification and materialization.
Passing geometric audits applies only to represented synthetic geometry. Native
device obstructions, complete process rules and real performance remain unknown.
