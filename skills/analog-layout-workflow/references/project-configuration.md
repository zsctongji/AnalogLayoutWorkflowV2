# Configuration-driven placement and routing

Use `scripts/configured_flow.py` for a new or migrated design. It is an offline preparation/search entrypoint; it does not reroute an existing layout or grant import approval. Keep original revision-bound artifacts immutable. Reuse existing stage transaction/import and fresh live geometry checks for actual CAD operations.

## Configuration ownership

Project (`analog-layout-workflow.project/v1`): source/target cellviews, relative input paths, PDK/circuit/routing/site file references, simulation definitions and project-specific verification decisions. A waiver includes its scope and actual user instruction; this file is not a source of invented authorization.

PDK (`analog-layout-workflow.pdk-map/v1`): a device registry keyed by exact source master, device kind, target PCell master, canonical parameter to source/target name/type/scale mapping, and canonical electrical terminal names. `scale` converts parsed SI numbers into the target numeric PCell unit. Unregistered masters and unresolved numeric expressions block. `kind: ignore` is an explicit exclusion, not an inferred unsupported-device fallback. Keep layer roles and qualified contact/ring recipes here; recipe data alone does not qualify a live adapter.

Circuit (`analog-layout-workflow.circuit/v1`): either explicit modules or existing automatic topology discovery with module/dummy maps. Explicit module rows can name logical devices (copies consumed in index order) or exact copy IDs. Every expanded copy occurs once, and dummy membership must be complete. Matching mode is `common_axis` or `common_centroid`; ABBA/BAAB can be declared as `pattern`. Store special ratio rows here rather than patching helper functions.

Floorplan requires `order`, `device_gap_um` and `macro_gap_um`. `mode: stack` shares a vertical axis; optional `axis_x_um`, `origin_um` and `gap_after_um` control positions. `rows` and `explicit` support configured module arrangements with module-local matching axes. Multi-axis output is not authority for strict common-axis routing; the subsequent symmetry stage must establish its requested axis. These are deterministic floorplan options, not an ALIGN solver execution claim.

Routing (`analog-layout-workflow.routing-policy/v1`): exact network classifications, allowed layer roles, widths/basis, directness limits, coupled matching strategy/pin maps, symmetry groups, ordering and search costs. Terminal lists are generated from all actual pin islands. There are no fixed trunk coordinates in this path. When explicitly configured with `backend: general`, it invokes `route_planner.py` bounded A*/access-beam/shared-tree or guided pair search and then the route/SVG checks. Required paired mapping is never silently replaced by independent routing. Declared self-symmetry still must pass the generated-geometry gate; bounded search can return BLOCKED.

For strict automatic symmetry, select `backend: strict_symmetric` and put fixed `axis`, complete `groups`, search budgets/costs and M1 `local_access` in `routing.symmetry_solver`. Put actual `metal_levels`, sourced `cut_rules`/`cross_cut_rules` and hash-bound `via_mirror_evidence` in `pdk.routing_rules`. See [solver-contract.md](../../analog-layout-symmetric-route/references/solver-contract.md). `configured_route.py` dispatches to the joint solver, whose direction and mirrored geometry are hard constraints. General `search`, `symmetry_groups` and direction preferences must be explicitly migrated, not passed through or relaxed. The general backend remains compatible for ordinary/guided requests.

Site: tool/project/license/deck/map paths and supported metal/hierarchy configuration. `site_nuvoton_check.py` accepts the path as `constraints.site_profile.config`; its unchanged Nuvoton profile name/capability qualification still applies. No filled site JSON is packaged; provide an external site profile, and qualify any new PDK separately.

## Commands

```text
python scripts/configured_flow.py validate --project <project.json>
python scripts/configured_flow.py prepare --project <project.json> --work <candidate-dir>
python scripts/configured_flow.py place --project <project.json> --work <candidate-dir>
python scripts/configured_flow.py macro-opt --project <project.json> --work <candidate-dir>
python scripts/configured_flow.py route --project <project.json> --work <candidate-dir>
python scripts/configured_flow.py symmetric-route --project <project.json> --work <candidate-dir>
```

`prepare` writes copies/groups/parameter bindings, without measuring or placing in CAD. Use existing `measure-pcells` on that candidate directory when measurements are absent. The measurement/import scripts support the mapped `pcell_parameter_entries` and independently check evaluated types/values. `place` needs exact measured masters and geometry inputs; mapped evidence includes the PDK mapping hash and typed entries. Legacy geometry can only be reused for equivalent old parameter bindings. Mapping changes require new measurement.

All configuration fingerprints are recorded. `route` uses supplied obstacle evidence; without it, only conservative pin obstacles are generated and recorded as incomplete/offline. Generated candidates remain non-materializable until original live gates and qualified import complete. A failed planner/SVG candidate is not a saved layout or signoff result.

`symmetric-route` explicitly selects the strict backend; `route` also selects it when configured. Artifacts go to `routing/strict-symmetric`, including a complete independent geometry audit. A failed strict run overwrites this frontend's selected spec/intent/preview with hash-bound BLOCKED outputs, preventing stale success reuse. The standalone solver requires a new output directory. No command modifies OA or previously completed physical-layout evidence.

`macro-opt` reads `inputs.macro_snapshot` containing all measured macro objects, including rings and local access. `circuit.macro_optimization` holds the existing optimizer request fields: complete pair clearance bounds/basis, search bounds, alignment, mirror/order/lock constraints, pin-based net costs and `objective_priority`. The snapshot hash is generated, never copied from a previous run. Clearance evidence must be refreshed when geometry or PDK changes; no default zero gaps or inferred ring dimensions are introduced.

## Compatibility

Old CLI paths and Nuvoton qualifiers remain for prior runs. Their legacy defaults are not the preferred cross-design path. Do not copy project `build_route.py`, name-based ratio patches or simulation string replacements into a new design. Use configuration plus raw source/PDK/TB evidence, and retain explicit unsupported-capability states for ring/native-via/geometry cases outside qualified adapters.


## Default fast routing

Without an explicit routing method/backend, `route` selects `symmetric_fast`. Put project-specific measured templates in `routing.fast_templates`; keep actual `layer_roles` and `routing_rules.metal_levels` in the PDK map. Read [fast configuration](../../analog-layout-symmetric-fast/references/configuration.md). `symmetric-fast` forces this template backend, while `symmetric-route` forces the joint solver and `backend: general` preserves an explicit general-routing choice. Missing fast templates block; there is no implicit search fallback. Both backends retain offline-only candidates and shared live import/DRC/LVS gates.
