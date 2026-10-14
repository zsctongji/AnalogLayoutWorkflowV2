# Offline placement optimization

Use for automatic refinement of an already measured target-PDK v2 parent. This is a bounded
local search over rigid device groups; it is not a new ALIGN placer or a live database operation.
All coordinates are microns. Numeric rules below must come from caller evidence, not examples.

## Inputs and identity

The CLI accepts `--intent`, `--access`, `--request`, optional `--evidence`/`--feedback`, and a new
`--out` directory. It uses only the Python standard library. Python API:

```python
from placement_optimizer import optimize
from placement_geometry import digest
request = {
    "schema": "analog-layout-align.placement-optimization-request/v1",
    "target": access["target"],
    "parent_intent_sha256": digest(parent),
    "terminal_access_sha256": digest(access),
    "search": {"max_iterations": 5, "max_evaluations": 100, "top_k": 5,
               "priority": "balanced", "locked_instances": []},
    "constraints": {}
}
result = optimize(parent, access, request, evidence, feedback)
```

Hashes use SHA-256 of `json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)`
encoded as UTF-8 (default ASCII escaping). No timestamps affect search decisions or output.
The request target identifies the source snapshot, not permission to mutate it. Access schema
must be terminal-access/v1 with exactly the parent's instance set. Each instance's master,
origin, orientation and measured bbox must match the parent (bbox tolerance: one source grid).
The parent requires v2, positive explicit manufacturing grid, evaluated-PCell coordinate space,
complete inventory and source geometry. The optimizer rejects parameter/orientation changes.
Missing mapped terminals/islands block the included required nets, including bulk; the optimizer
does not infer internal ties. `required_nets` may explicitly restrict the evaluation scope.

## Planning evidence

`evidence.layers` maps exact layer names to:

| Field | Meaning |
|---|---|
| `source` | Required nonempty rule/profile/deck or reviewed project evidence reference |
| `width_um`, `spacing_um` | Required route width and spacing for this capacity estimate |
| `escape_length_um` | Required positive project-defined escape probe distance |
| `preferred_direction` | Optional `horizontal` or `vertical`; no implicit parity convention |
| `via_envelope_um` | Optional positive `[x_size, y_size]` envelope |
| `power_width_um` | Optional power-trunk width |
| `pair_spacing_um` | Optional within-pair spacing, otherwise the supplied spacing |

Top-level optional `profile_fingerprint` and `description` record provenance. This is a normalized
planning input, not a raw PDK profile; profile extraction/validation remains upstream. All rules
are estimates scoped to supplied widths/layers. Conditional DRC and full stacked-via geometry
are unmodeled. Unknown rules are never synthesized. Without rules, access remains `unknown`.

## Constraints

- `bounds_um`: fixed permissible placement/probe bbox.
- `required_nets`: nonempty subset of known nets; omitted means all mapped nets.
- `critical_net_weights`: known net -> nonnegative weight; unlisted nets are ordinary.
- `differential_nets`: explicit `[positive_net, negative_net]` pairs for HPWL comparison.
- `obstacles`: fixed snapshot obstacles with `id`, `bbox`, optional `layer`, `owner`, `basis`.
  Movable PCell bboxes are regenerated from each child; external obstacles stay fixed.
- `access_pairs`: explicit physical-island `first`/`second`, plus `axis_x_um` or `axis_instances`.
  The latter derives the mirror axis from the current bounding envelope of those instances.
  An island belongs to at most one pair. P0 supports x reflection only. This is a geometric
  proxy, not proof of environmental or electrical matching.
- `channel_demands`: `channel_id`, assigned `layer`, nonnegative integer `ordinary_nets`,
  `matched_pairs`, `power_trunks`. IDs are `first_instance|second_instance|across_axis`, where
  first is the lower coordinate box and axis 0 means a vertically oriented gap. Read IDs from
  baseline `channels`. Channels obstructed by a third PCell are excluded. Lost declared channels
  remain present with `overflow: null`; disappearance is not success. A child that loses a
  previously visible demanded channel is rejected with `DECLARED_CHANNEL_LOST` until the caller
  provides a revised demand mapping; it cannot improve by making the obligation unmeasurable.
- `sensitive_instances`, `noise_sources`, `heat_sources`: sources contain `instance` and optional
  nonnegative `weight` (default 1). Noise uses inverse Manhattan distance, regularized by the grid;
  thermal imbalance is the range of source exposures over sensitive instances. These are proxies.
- `boundary_connections`: `instance`, fixed `target_xy_um`, optional nonnegative `weight` for
  high-current escape distance estimates. This does not create/move pins.
- `preserve_core_axis`: defaults true for declared core macros.
- `centroid_tolerance_um`: explicit review tolerance; numerical default is 1e-8 microns.
  Exact-common-centroid labels still require equality at numerical precision; a larger tolerance
  only permits a candidate marked within tolerance, not an exact geometric claim.

Unsupported constraint keys fail rather than silently disappearing. Parameters, group membership,
dummy association, grid positions and electrical mappings are frozen against the root parent.

## Evaluation

`placement_metrics.evaluate_placement(intent, access, constraints, evidence, parent)` projects
every physical island independently from the root live snapshot. It preserves candidates and layers;
no new contact center is invented. Access selection considers escape directions, foreign bbox
obstacles, via envelope fit, distance, first-turn/preferred-direction proxies and neighboring escape
competition. Explicit access pairs select candidates together. Missing candidates are hard failures;
geometrically blocked probes are soft risks that can drive refinement. Owner PCell internals are
excluded from bbox blocking, so `proxy_clear` never proves contact legality inside a PCell.

Channel capacity uses the gap across its long direction. For one layer, ordinary-track capacity is
`floor((gap-spacing)/(width+spacing))`, clamped at zero. Matching-pair width is
`2*width+pair_spacing`. Mixed demand sums ordinary, paired and power widths plus edge/interbundle
spacing together. Separate capacity numbers cannot be added. Unassigned layer/demand or unknown
power width produces `overflow: null`. Via-array fit checks the supplied envelope only.

Evaluation returns `status`, `hard_failures`, `metrics`, `soft_objectives`, `accesses`, `channels`,
`nets`, `matching`, `warnings` and `intent_sha256`. Optional metrics are null when evidence is absent.
Reported metrics include area/utilization, ordinary and weighted critical HPWL, median-star length,
differential HPWL delta, paired-access error, blocked/unknown access, via blockage, channel overflow,
unknown channels, critical-net bbox intersection proxy, and optional noise/thermal/boundary costs.
The crossing metric counts intersecting net envelopes; it is not a count of routed crossings.

## Search and outputs

`search.step_um` is an optional positive grid multiple, default one manufacturing grid. It is a
search increment, not a spacing rule. Bounds, step size and budgets should reflect the design scale.
`max_evaluations` counts attempted candidates (including rejected/revisited states) and the baseline.

Optional `search.macro_relocation_gap_um` enables coarse peripheral rigid-group
relocation around groups sharing explicitly weighted critical nets. See
[global-floorplan-review.md](global-floorplan-review.md) for selection and evidence
limits. Default ranking uses `unknown_declared_channels`, not the changing total
population of observed unknown gaps; `unknown_channels` remains diagnostic.

Group and macro memberships are unioned into rigid movement units, including dummy copies. Search
tries translations in four directions, directed overloaded-channel widening, feedback-prioritized
translation, and exchanges of equivalent ungrouped parallel copies. All children pass the existing
`refine()` function and a separate evaluator. Matched members must preserve relative geometry;
an unsupported internal group defect blocks baseline optimization and needs an explicit structural
refinement. All input identity, finite-value, grid and parameter checks run before selection.

`priority` is `matching`, `routeability`, `critical_hpwl`, `compactness`, or `balanced`. Optional
`objectives` is a nonempty list of supported minimization metric names. Area/utilization tradeoffs
are represented using area, not minimizing utilization. Hard-invalid candidates are removed,
dominated candidates removed, then lexicographic priority and deterministic identity break ties.
Known-to-unknown evidence regressions cannot dominate known candidates. Metric-equivalent layouts
share one representative, preferring the baseline; known evidence ranks before unknowns. Top-K bounds the retained
frontier; this is not exhaustive global Pareto enumeration. Equal objective vectors do not prolong
search. Stop reasons are iteration budget, evaluation budget or no improvement.

Output schema is `analog-layout-align.placement-candidates/v1`. It contains source hashes, target,
baseline, objectives, candidates, failures, history, ancestry, evaluation count and stop reason.
Candidate fields include `candidate_id`, `parent_id`, `generation`, v2 `intent`, `evaluation`,
`refinement_spec`, operations, geometric delta and metric delta. The root has ID `parent` and may
remain a finalist. Ancestry preserves intermediate parents even if they leave Top-K. IDs use geometry
hashes; outputs have `materialized: false`. CLI exports candidate JSON and SVG previews to a new
directory, plus the full candidates report. Generated previews require review; no SVG signoff is claimed.

## Routeability feedback

Optional feedback schema `analog-layout-align.routeability-feedback/v1` requires `target`,
`parent_intent_sha256`, `terminal_access_sha256`, and `failures`. Each failure has `code`,
`affected_instances`, optionally `required_extra_clearance_um`. Supported codes:
`NO_LEGAL_ACCESS`, `CHANNEL_OVERFLOW`, `TOPOLOGY_EDGE_BLOCKED`, `MATCHED_PAIR_ASYMMETRIC`,
`VIA_ENVELOPE_BLOCKED`. A caller adapts router results to this explicit format; raw router
failure reasons are not automatically assumed equivalent. Hash or target drift blocks the run.
Hints prioritize affected rigid units; supplied extra clearance enlarges the search step. Each child
is reevaluated independently, and a router rerun/live access extraction is still required to establish
that the original route failure was resolved. No router, bridge, subprocess or importer is invoked
by this adapter.

## Deferred capabilities

P1 orientation/abutment search, arbitrary-ratio common-centroid synthesis, resistor/capacitor
decomposition, detailed thermal/noise models and full router execution are not implemented.
The existing manual refinement interface remains available with its evidence requirements.
The optimizer does not resize devices or fix invalid parent geometry automatically.
