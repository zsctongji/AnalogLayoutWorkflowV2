# Joint symmetric solver contract

`scripts/symmetric_solver.py` is an offline end-to-end candidate solver using Python 3.10+ standard library and sibling `analog-layout-route`. It searches a finite rectilinear visibility graph; it is neither a native Virtuoso router nor a foundry/global-optimality solver. `PLANNED` means at least one complete candidate passed the represented geometry, intent and SVG gates. Every output remains `materializable=false`.

## Entry points

```text
python scripts/symmetric_solver.py --profile profile.json --access terminal-access.json --obstacles obstacles.json --request solve-request.json --out NEW_DIRECTORY
python ../analog-layout-workflow/scripts/configured_flow.py symmetric-route --project project.json --work candidate-directory
```

The standalone output directory must not exist. It writes `candidates.json`, `input-audit.json`, `symmetry-map.json`, `drc-rule-table.json`, `routing-review.md` and each accepted `candidate-N/{spec.json,intent.json,audit.json,preview.svg,svg-check.json,symmetry-audit.json,drc-preflight.json,direction-audit.json}`. These sidecars describe selected rectangular rules and retain pending native/foundry gates. Exit 0 indicates PLANNED; exit 2 indicates BLOCKED. A stopped budget may coexist with already audited candidates; inspect failures and statistics before interpreting the result. No tool, bridge or license is needed for offline search.

## Request

Schema `analog-layout-symmetric-route.solve-request/v1`:

- `target`: exact access target. `sources` must exactly equal `{profile_fingerprint,terminal_access_sha256,obstacles_sha256}`, using sibling `route_intent.digest` and current inputs. The obstacle source hashes are also checked.
- `axis`: `{coordinate: "x" | "y", value_um: finite number}`. Two times the axis must be on grid; a half-grid axis is legal because reflection preserves grid points. The axis is supplied from verified placement, never inferred from bounding boxes.
- `nets`: complete policies for every access net. Each has `net`, `net_class`, explicit `layers` and `widths_um`, and every `terminals` item `{instance,terminal,pin_island_id}` exactly once. Power/ground/high_current require `width_basis`; sensitive/high_impedance/differential/matched/feedback require `max_detour_ratio` or `max_bbox_excursion_um`. The joint audit enforces integer `max_bends` on primitive turns plus direction changes at adjacent-layer vias, including matching bend deltas. A same-position V-H-V stack conservatively counts two transitions. Verified exported metrics preserve this basis; the legacy intent builder alone counts primitive turns.
- `groups`: every whole net belongs to exactly one group. `pair` has `id,mode,first_net,second_net,pin_pairs`; its pin map is a complete bijection. `self` has `id,mode,net,pin_pairs`; the map partitions islands into reflection pairs or `[id,id]` fixed points. `ordinary` has `id,mode,net,reason`; this explicit asymmetric exception is still routed with Manhattan/metal/obstacle constraints. No scoped partial-net downgrade, transform override or missing-net fallback is accepted.
- `metal_levels`: optional PDK layer-to-actual-level map. Otherwise derive metal ordinal positions from the complete `layer_functions` stack sorted by rank. Rank 9/11/13 can mean levels 1/2/3; rank parity and layer-name suffixes are not metal levels. Explicit mappings must agree with available PDK stack evidence.
- `cut_rules`: cut layer to `{spacing_um,source,metric?}`; metric is `euclidean` (default) or `max_axis`. Same-net cuts are checked too. `cross_cut_rules`: `[{layers:[cutA,cutB],spacing_um,source,stacking_allowed?,metric?}]`. Stacking permission applies only to same-net, exactly concentric cuts; absent rules block rather than imply permission.
- `via_mirror_evidence`: via name to `{geometry_sha256,mirror_verified:true,source}`. The hash binds the exact profile `standard_geometry`; the source points to qualified PDK/readback evidence, not an agent guess. Normalized cut-array reflection is independently checked. Widths must contain complete perpendicular landing extents; direction-correct real landing stubs cover along-direction extents. Only adjacent actual metal levels are connected. Offsets/orientations outside the normalized adapter contract block.
- `local_access`: physical island id to `{region_um:[[x0,y0],[x1,y1]],max_length_um,source}` when M1 is used. Metal footprints must remain in sourced regions; final audit measures centreline union length per complete connected M1 component. Conservatively apply the smallest budget of its access anchors; primitive splitting and overlapping duplicate segments cannot evade it.
- `matching`: optional cross-net electrical matching contracts using the existing route-intent fields. A strict pair gets zero-delta geometry matching by default. Self symmetry and between-net matching are separate requirements; ABBA inputs must not be falsely mapped as mutually mirrored whole nets.
- `search`: positive integer budgets `max_expansions` (30000), `max_coordinates` per dimension (160), `max_vias_per_path` (12), `access_combinations` (12), `group_candidates` (3), `beam_width` (4), `max_orderings` (8), `top_k` (3).
- `costs`: nonnegative `via_cost_um` (2), `bend_cost_um` (one grid), `metal_area_weight` (0). Hard legality cannot be relaxed by changing costs. Soft rectangular obstacles need `hard:false,cost_per_um,source`; their intersected centreline length adds search cost.

Contacts and PCell internals belong to the upstream local-access stage. An island must already expose a qualified allowed metal layer. Poly covered by metal is not a contact; missing access returns LOCAL_CONTACT_REQUIRED. Single-island pair/ordinary nets and singleton fixed-axis self nets require a sourced `terminal_escape` policy `{pin_island_id,layer,end_xy_um,source}` for a real intended pin escape. Paired escape destinations must be exact mirrors. Self escapes are routed/reflected as one connected net. No cosmetic loop is created to make a net appear routed.

Input obstacles use `analog-layout-route.obstacles/v1` with exact target/source hashes, positive bounds, and conservative rectangles containing real wire/PCell/ring/cut geometry. Unknown-net metal is foreign. Supplied evidence may be offline/incomplete, which remains visible in planning evidence; it never authorizes live import. Unsupported required topology such as a prescribed dual trunk or continuous power bus needs an explicit qualified extension or the reviewed template path, not a silently substituted generic tree.

## Search and validation

1. Enumerate mirrored on-grid physical access choices; corresponding nets have identical allowed layers and widths. Distinct pair nets must stay in separate half-planes: crossing the axis would short an exactly reflected pair.
2. Search layered nodes with hard odd-level vertical / even-level horizontal edges. Each action reserves its real swept metal or individual via cuts plus upper/lower landings **and its reflected counterpart**. Both static obstacles and previously committed groups/path vias participate in legality. No one-side result is committed first.
3. Connect multiple representative islands into a shared tree. A self net reflects its half-tree and searches a legal same-net axis bridge; fixed-axis accesses already joining both halves avoid an extra bridge. Half-grid bridges have on-grid endpoints. Multiple roots/frontiers, excluded previous edges and access combinations give bounded alternatives.
4. Keep bounded group candidates and reservation beams. On conflict restart with empty group reservations under rotated/reversed/permuted group orders. This is atomic whole-group rip-up/re-route; there is no unilateral mate edit. Search is deterministic for identical inputs.
5. Compact same-net/layer/width collinear interval unions while preserving the selected physical access layer; overlapping landing primitives do not inflate length/directness metrics. Reconstruct final geometry independently: hard directions, bounds, edge/cut/stack spacing, complete via landing coverage by wire union, exact conductor connectivity, complete reflected physical island selections, M1 locality, wire-union/cut reflection and matching. Reuse `mirror_spec.symmetry_preflight`, `route_intent` and SVG consistency checks. A failing candidate is never selected. Verified export refuses stale spec/audit/profile/access bindings.

Failure codes distinguish source/pin/policy errors, unknown PDK/access capability, NO_PATH_IN_GRAPH and BUDGET_EXHAUSTED. A finite visibility graph, bounded access/tree/landing alternatives and group order search are not an exhaustive search of every possible grid topology; neither failure proves physical UNSAT, and candidate cost is not a global optimum. Increase sourced search bounds or repair placement/access/constraints based on the reported cause.

The rectangular model uses square swept path caps and conservative sourced scalar spacing. Native polygon corners/caps, EOL/notch/min-area/PRL/voltage rules not represented here, full live obstructions, density, continuous bus capacity, IR/EM, environmental/parasitic symmetry and actual foundry DRC/LVS remain separate application gates. A passing synthetic example must never be used as a foundry rule source.

## Configured frontend

Use `routing.backend: "strict_symmetric"`; `routing.symmetry_solver` owns `axis,groups,search,costs,local_access`. PDK `routing_rules` owns `metal_levels,cut_rules,cross_cut_rules,via_mirror_evidence`. Existing per-net `layer_roles`/`widths_by_role_um` map through `pdk.layer_roles` before solving. Complete terminals and fresh hashes are generated from access, never copied from the previous request. General backend `search`, `symmetry_groups` and soft direction preferences must be migrated explicitly.

For example, a paired group is:

```json
{"backend":"strict_symmetric","symmetry_solver":{
  "axis":{"coordinate":"x","value_um":0},
  "groups":[{"id":"inputs","mode":"pair","first_net":"INP","second_net":"INN",
             "pin_pairs":[["left:G:0","right:G:0"]]}],
  "search":{"max_expansions":30000,"group_candidates":3,"top_k":2}
}}
```

This fragment is not a complete electrical/PDK request. Add every remaining net/group, net widths/directness and qualified rules. Do not derive the orbit map from instance-name similarities.
