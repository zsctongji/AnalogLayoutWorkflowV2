# RALF planner adapter contract

Use this contract only when automatic candidate generation is requested.  The
planner is a non-mutating stage before `analog-layout-route.spec/v1`; the
existing intent builder, review, guarded importer, and foundry verification
remain authoritative.

## Current implementation level

`scripts/route_planner.py` retains the stable artifact adapter boundary.
The implementation is split into `routing_search.py` (directional A*, costs,
topology), `routing_tree.py` (physical shared-tree normalization), and
`routing_backend.py` (access selection, geometry and guided pairs).
It performs bounded access beam search, actual-cost frontier tree generation,
optional sourced current-weighted rooted-tree optimization, normalized-via
envelope checks, contact escape, and conversion to the existing route spec.
The algorithms are independent implementations inspired by the routing
literature, not SAGERoute source code or the complete upstream RALF runtime.

It does not yet execute upstream RALF classes.  Those classes depend on
`MagicDie`, `global_pdk`, RALF `Net` objects, global obstacle state, and
`rtree`.  Do not describe this prototype as the complete upstream RALF router.

The current prototype supports multiple routing layers per net.  A terminal
island may connect directly or through one normalized profile via into a
routing layer.  If the projected contact is obstructed, the planner selects
the nearest Manhattan escape on an expanded-obstacle boundary.  Standalone
routing vias and contact landings are emitted into the existing route spec.

For a verified two-row, even-column common-centroid access pattern, the optional
`common_centroid_columns` strategy jointly synthesizes complementary contact
escapes, equal M1 landing stubs, equal-length M2 columns, and buses spanning
the complete union of escaped columns. It supports complete 2x2, 4x2, and larger 2N-by-2 terminal grids for each pair member. The generated pair must pass the whole-net conductive-component check; equal length and endpoint coverage alone are not acceptance criteria. This is a constrained topology generator, not a general
differential maze router.  Its numeric escape/stub/bus-clearance values must be
explicitly backed by reviewed layout evidence and the active profile.

Negotiated GCell planning, simultaneous pair wavefront search, shielding
synthesis, power/EM sizing, and Top-K output remain future capabilities.
Ordinary and guided strategies check normalized via landing/cut envelopes
against supplied obstacles and include envelope boundaries in the search graph.
The legacy common-centroid generator retains its existing clearance model.
Conditional cut spacing, stack legality and complete live geometry remain
foundry-verification obligations. Pair matching is
enforced by the authoritative builder; `target_length_um` can request an
obstacle-aware rectangular tuning segment only for non-paired routes and never
claims coupled pair routing.
Unsupported requests must return `BLOCKED`, not an approximate route.

## Obstacles (`analog-layout-route.obstacles/v1`)

```json
{
  "schema": "analog-layout-route.obstacles/v1",
  "target": {"lib": "designLib", "cell": "block", "view": "layout"},
  "sources": {
    "profile_fingerprint": "sha256-value",
    "terminal_access_sha256": "sha256-value",
    "placement_sha256": "optional-source-hash"
  },
  "bounds_um": [[0, 0], [100, 80]],
  "obstacles": [{
    "id": "M0/m1/0",
    "layer": "m1",
    "bbox_um": [[10, 20], [15, 25]],
    "kind": "pcell-internal",
    "owner": "M0",
    "net": null,
    "hard": true
  }]
}
```

Coordinates use microns and the exact target revision. A same-net obstacle
may be reused by that net. Foreign hard obstacles are expanded by
`route_width / 2 + spacing`. The spacing is the unconditional minimum, or
the conservative maximum of an explicitly supplied normalized
`routing_layers[].width_spacing_rules` table in the fingerprinted profile.
Each table entry requires `min_width_um`, `spacing_um`, and `source`.
The current implementation uses the maximum table spacing for all widths
to account conservatively for foreign-wire widths; it does not interpret
native conditional-rule tables.

A soft obstacle uses `hard:false` and must now supply finite nonnegative
`cost_per_um`; a legacy soft obstacle without cost is rejected rather than
silently ignored. Optional `parallel_direction` is horizontal or vertical;
perpendicular exposure is multiplied by `crossing_factor` (default 0.25).
Costs integrate the routed centerline length inside the region. They are
geometric proxies, not extracted coupling capacitance.

## Request (`analog-layout-route.plan-request/v1`)

```json
{
  "schema": "analog-layout-route.plan-request/v1",
  "target": {"lib": "designLib", "cell": "block", "view": "layout"},
  "sources": {
    "profile_fingerprint": "sha256-value",
    "terminal_access_sha256": "sha256-value",
    "obstacles_sha256": "sha256-value"
  },
  "nets": [{
    "net": "VINP",
    "layers": ["m1", "m2"],
    "widths_um": {"m1": 0.4, "m2": 0.5},
    "net_class": "differential",
    "max_detour_ratio": 1.5,
    "max_bends": 6,
    "max_bbox_excursion_um": 2.0,
    "via_cost_um": 2.0,
    "terminals": [
      {"instance": "M0", "terminal": "G", "pin_island_id": "M0:G:p0"},
      {"instance": "M1", "terminal": "G", "pin_island_id": "M1:G:p0"}
    ]
  }],
  "matching": [{
    "first_net": "VINN",
    "second_net": "VINP",
    "max_length_delta_um": 0.1,
    "max_via_delta": 0,
    "strategy": "common_centroid_columns",
    "contact_layer": "m1",
    "bus_layer": "m2",
    "contact_escape_um": 0.8,
    "landing_stub_um": 0.6,
    "bus_clearance_um": 2.325
  }],
  "symmetry_groups": [{
    "id": "vinp_self_mirror", "mode": "self", "net": "VINP",
    "transform": "mirror_x", "axis_um": 50.0, "tolerance_um": 0.001
  }],
  "reserve_matched_pairs_first": true
}
```

Every net requires an explicit `net_class`; use `ordinary` deliberately rather than relying on a default. List every required physical pin island explicitly. Omitted widths use each
layer's maximum unconditional scalar minimum width only for ordinary nets whose electrical basis permits it. Power, ground, and high-current nets must provide explicit widths and a non-empty `width_basis`. Sensitive, high-impedance, differential, matched, and feedback nets must provide either `max_detour_ratio` or `max_bbox_excursion_um`. The legacy singular
`layer` and scalar `width_um` fields remain accepted. `target_length_um` is an
explicit request for non-matched nets only, not a value the planner may invent. It is forbidden on either member of a matching rule because single-sided trombone compensation does not preserve layer, bend, via, or coupling symmetry.

`differential` and `matched` nets must appear in exactly one matching rule.
Supported strategies are `common_centroid_columns`, `mirror_guided`,
`rotate180_guided`, and `partial_mirror_guided`. The common-centroid
parameters remain unchanged. Guided strategies require explicit `pin_pairs`
and transform coordinates as described below. Missing/unsupported strategies
return `BLOCKED`; the planner never falls back to uncoupled searches.

When any matching rule is present, `reserve_matched_pairs_first` must be true. With it, constrained matched-pair geometry is
reserved before ordinary nets.  If later nets cannot route, return `BLOCKED`;
do not silently discard pair spacing.  A caller may iterate global routing or
compose the reviewed pair into an already validated surrounding route spec,
but the complete composition must pass the authoritative builder again.

The planner copies optional `symmetry_groups` unchanged into the route spec
and intent for the annotated SVG gate. Declaring a group alone does not
activate guided generation: select a matching strategy explicitly.
Guidance permits local obstacle detours within matching budgets; a separate
strict geometric symmetry group can still reject those detours at the SVG gate.

`scripts/prepare_planner_inputs.py` can create a conservative offline snapshot
from terminal-access data.  It includes foreign-net routing-layer pin figures,
but explicitly marks arbitrary PCell bodies, existing routes, top-level
shapes, and conditional rules as absent.  Such a snapshot is suitable for
planner development and review only; refresh it from the live target before
materialization.

The planner copies obstacle coverage into `planning_evidence`. If `live_snapshot` is false, a reviewed route spec must add `offline_obstacle_review` with `reviewed_live_target: true` and a non-empty evidence basis before validation permits materialization. This is not a waiver for foundry DRC.

Layer direction is a soft search cost. Actual code precedence is request
`preferred_directions`, then profile `preferred_direction`, then the numeric
layer-name suffix convention (odd vertical, even horizontal). This preference
does not authorize overriding a foundry hard rule. `off_direction_penalty`
biases A* without forbidding necessary segments. The common-centroid template
may override this preference; the intent reports off-preference length.

## Optional algorithm configuration

Net-level values override request-level values for:

| Field | Default | Meaning |
|---|---|---|
| `bend_cost_um` | max(grid, minimum width+spacing across allowed layers) | Planar turn cost; via resets direction; common-centroid legacy template retains grid default |
| `via_cost_um` | 2.0 | Cost per routing via, excluding terminal contacts |
| `off_direction_penalty` | 0.25 | Additional cost per off-direction unit length |
| `access_candidate_limit` | 4 | Retained candidate locations/layers per island |
| `access_beam_width` | 16 | Retained joint access assignments per expansion |
| `topology_frontier_limit` | 4 | Actual-cost frontier trials before accepting a feasible branch |
| `shared_tree` | true | Reuse existing line interiors and normalize unconstrained ordinary tree geometry |
| `metal_area_weight` | 0.25; zero for power/ground/high-current/matched/differential | Soft bias against wider allowed layers; never reduces the requested width |

All costs must be finite and nonnegative; search limits must be positive.
Candidate screening ranks terminal-distance estimates, escape clearance and
deterministic geometric ties. Beam ranking uses actual obstacle-aware routes,
including bends, direction and via envelopes. Explicit terminal `xy_um`
remains binding. Optional terminal `route_layer` constrains the chosen access
layer to an allowed net layer. All physical islands remain required.

Ordinary topology uses bounded actual-cost frontier growth, not an exact MST.
Each unconnected terminal searches to existing tree vertices and orthogonal
projections onto same-layer segments. Rank feasible branches by complete
search cost, rather than accepting the first Manhattan-nearest connection.
The frontier limit bounds trials after a feasible branch is found; blocked
early trials do not prevent trying the remaining frontier. A Manhattan lower
bound can terminate ranking early when no remaining branch can beat the best.
Sorted instance/terminal/island identities preserve terminal-order invariance.

For unconstrained nets with more than two terminals, normalize the constructed
physical graph: split same-layer crossings/overlaps/T-junctions and via landings,
deduplicate edges, remove cycles, and prune leaves that are not selected access
points. Reconstruct degree-two chains and accept only non-increasing physical
cost including bends. This adds no geometry across obstacles and preserves
every selected terminal. Different-layer crossings do not imply connectivity.
The authoritative intent builder still checks actual metal connectivity.

Do not run generic shared-tree/pruning on electrical-current trees, matched
networks or explicit target-length routes: their current allocation, coupled
structure or length intent must be preserved. Existing saved layouts are not
pruned by this algorithm. Explicit `shared_tree:false` disables interior reuse
and normalization; `topology_frontier_limit:1` gives a faster first-feasible
control mode. It is not a byte-for-byte replay of earlier releases.

When `max_bbox_excursion_um` is supplied, constrain search to the union of
candidate pin bounds plus that margin, intersected with the global boundary.
After access selection the authoritative builder still checks the exact chosen
geometry. No placement, terminal or cell boundary is silently moved.

Area penalty per segment is
`metal_area_weight * (layer_width / minimum_allowed_width - 1) * length`.
This is a geometry/congestion preference, not a capacitance, resistance or EM
model. A wider layer remains available when needed. Explicit width and
electrical constraints prevail. Set the weight to zero to disable this bias.
The previous odd-vertical/even-horizontal preference remains configurable.

Metrics count emitted primitives; `directness.unique_centerline_length_um`
also unions same-layer collinear intervals (not polygon area). Compare it
with terminal HPWL to distinguish placement span from extra routing.
Candidate pruning can miss a feasible or better access combination; increase
budgets or revise placement/access when appropriate.

To use sourced current weighting, supply on a net:

```json
{
  "electrical": {
    "source": "saved schematic simulation artifact and operating point",
    "root_pin_island_id": "A:G:p0",
    "sink_currents_a": {"B:G:p0": 0.002},
    "epsilon_a": 1e-9
  }
}
```

Exactly one root and nonnegative current for every other requested physical
island are required. Do not duplicate a terminal's total current onto every
finger: the source must justify the per-island allocation. Rooted MST
reparenting minimizes current-weighted root-to-sink geometric length plus
epsilon times total tree-edge length, with bounded strict improvements.
This is a single-source static current model, not signed multi-source or
time-varying current analysis. Report branch current sums and evidence source.
Missing `electrical` produces `electrical_data_status:unavailable` without
inventing currents; incomplete supplied evidence blocks. Current weighting
does not size wire/via geometry or establish IR/EM closure.

For dynamic protection, supply a net-level `protection` object:
`{"margin_um": 2.0, "cost_per_um": 5.0}`.
These illustrative numbers are search policy, not PDK recommendations.
After routing that net, its segments produce parallel-sensitive soft regions
for later nets. The mechanism accepts every declared net class, including
high-impedance, sensitive, differential, feedback and switching/output
networks. Declare switching nets with the existing `output` class and
protection/circuit evidence rather than adding an unsupported class.
No protection distance or coupling budget is inferred from class alone.
Explicit input soft regions allow protection before any geometry is committed.

## Guided matching

Example matching-rule extension (numeric tolerances require circuit evidence):

```json
{
  "first_net": "N",
  "second_net": "P",
  "strategy": "mirror_guided",
  "transform": "mirror_x",
  "axis_um": 0.0,
  "pin_pairs": [["N0:G:p0", "P0:G:p0"], ["N1:G:p0", "P1:G:p0"]],
  "guide_weight": 1.0,
  "max_length_delta_um": 0.1,
  "max_via_delta": 0,
  "max_per_layer_length_delta_um": 0.1,
  "max_bend_delta": 0
}
```

Full mirror/rotation requires one-to-one correspondence covering both nets.
Partial mirror permits a declared subset, while every unmapped island still
must connect. Transform `mirror_x` or `mirror_y` needs `axis_um`;
`rotate_180` needs `axis_x_um` and `axis_y_um`. The rotation strategy defaults
to rotate_180; mirror strategies default to mirror_x.

The coupled transaction filters reference access by legal transformed
counterpart candidates, routes the reference, selects the corresponding
counterpart access/layer, reserves the reference metal/via envelopes, and
routes the second net with positive guidance weight. It then runs the
authoritative pair connectivity/matching check before exposing either net.
No single-sided length tuning or zero-weight guidance is accepted.
This bounded reference-first strategy does not retry every possible first
branch when the second fails. Partial symmetry guides the full transformed
reference tree, with correspondence constraints on the declared subset.

Guide cost is the integral of distance to the nearest same-layer guide
segment, multiplied by `guide_weight` (inverse-micron units for a micron
equivalent cost). Exact piecewise-linear integration preserves cost under
collinear compaction. A missing guide on a layer has zero attraction;
the final per-layer matching constraints remain mandatory.
Environmental parasitic equality is explicitly unknown until PEX.

## Candidates (`analog-layout-route.plan-candidates/v1`)

The result records hashes of all authoritative inputs and, when supplied,
fingerprints the upstream RALF routing sources.  A successful result contains
`candidate_001.route_spec`, which is directly consumable by
`route_intent.py build`.  A failed result has status `BLOCKED`, no candidates,
and structured per-net failure records.

Every candidate route spec contains `required_nets` copied from the complete request. The authoritative builder blocks missing route geometry or uncovered physical islands, so a partial plan cannot pass by omission.

Additional candidate metrics include `selected_access`, `topology_edges`,
`topology_method`, `electrical_data_status`, optional branch `current_a`,
and per-net `cost_breakdown`. Candidate cost equals the sum of
`wire_length_um`, `bend_penalty`, `via_penalty`,
`off_direction_penalty`, `guide_deviation_cost`, `sensitive_area_cost`,
and `metal_area_penalty`.
New metrics include `effective_bend_cost_um`, `drawn_wire_area_um2`,
`tree_refinement` (duplicates/cycle/stub reduction and application status),
and `directness` (terminal span, HPWL, unique/duplicate centerline length,
length/HPWL ratio and search bounds). HPWL is only a lower bound; ratios above
one are not by themselves violations. For shared trees, `topology_edges`
is construction history with actual path start/end, not a final terminal-only
graph. Electrical mode retains its directed current edges.
The common-centroid legacy template reports its existing geometry metrics
and length/bend/via/off-direction costs; it does not run the new soft-region search.
Reported cost is recomputed from emitted primitives (deduplicated routing
vias), so it can differ from the sum of topology-edge search costs.

Failures retain `reason` and add `code`, such as `NO_LEGAL_ACCESS`,
`TOPOLOGY_EDGE_BLOCKED`, `SYMMETRY_UNSATISFIABLE`, `INVALID_VIA`,
`UNKNOWN_LAYER`, `ELECTRICAL_DATA_MISSING`, or `PREFLIGHT_FAILED`.
Source identity/hash errors retain the existing fail-fast ValueError behavior.
`rule_coverage` and warnings explicitly mark PRL, EOL, conditional cut
spacing, minimum area, stacked-via legality and environmental parasitics as
unknown. Do not interpret planner success as closure of those categories.

Never materialize a candidate directly.  Export it, rebuild an intent with the
authoritative inputs, require `READY_FOR_REVIEW`, review it, and only then use
the guarded importer after explicit user authorization.

## Commands

```powershell
<python> scripts/route_planner.py plan `
  --profile <profile.json> --terminal-access <terminal-access.json> `
  --obstacles <obstacles.json> --request <request.json> `
  --ralf-root <IIC-RALF> --out <candidates.json>

<python> scripts/route_planner.py export `
  --candidates <candidates.json> --candidate-id candidate_001 `
  --out <route-spec.json>
```
