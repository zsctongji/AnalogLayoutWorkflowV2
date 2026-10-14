# Explicit multiplier-copy placement artifact contract

The work directory is an explicit command-line argument. The driver creates:

- `plan/schematic.json`: schematic-only bridge snapshot.
- `plan/intent.json`: inferred pairs, roles, dummies, and placement policy.
- `plan/align/<cell>.sp`: ALIGN input containing one MOS instance per multiplier copy, each with preserved `W/L/nf` and `m=1`.
- `plan/align/<cell>.const.json`: `GroupBlocks` and exact ABBA/common-centroid generator constraints.
- `plan/device-copies.json`: source logical device to explicit `m=1` PCell-copy mapping.
- `plan/copy-groups.json`: matching/array membership and requested rows.
- `plan/dummy-associations.json`: deterministic dummy-family to active-group association and unresolved cases.
- `plan/pcell-geometry.json`: live Virtuoso evaluated PCell bbox, manufacturing grid, and exact parameters used; the probe cellview must not be saved.
- `plan/align-run/`: raw ALIGN placement-only run.
- `plan/placement.json`: normalized or `.pl`-recovered hierarchical placement.
- `plan/placement-intent.json`: directly consumable PCell intent: library/cell/layout view, parameters, terminals, explicit identity, group, actual row/column, orientation, and hierarchical/relative anchors.
- `plan/pcell-floorplan.json`: target-PDK macro and instance bboxes after grid snapping and overlap legalization.
- `plan/placement.svg`: technology-neutral explicit-copy preview.
- `plan/summary.md`: matching patterns and any degraded fallbacks.
- A caller-selected readback report such as `plan/virtuoso-placement-verification.json`: persisted target, top-level object counts, all readback PCell instances, bbox deltas, overlap results, and mismatches.

For read-only placement closure and refinement, the tools additionally create:

- `terminal-access.json`: full live PCell D/G/S figure inventory, transformed access centers, one `pin_islands` record per Cadence pin object, selected access per physical island, net-level `physical_accesses`, estimates, channels, symmetry, and findings. A routed net is not physically closed until every required island is covered.
- `placement-closure.json`: compact closure result without the per-instance figure payload.
- `net-routability-report.md`: human-readable placement-only routability assessment.
- `refinement-spec.json`: per-run, circuit-specific declarative input with preferred schema `analog-layout-place.refinement-spec/v1`; the cloned engine also accepts `analog-layout-align.refinement-spec/v1` for compatibility.
- A child placement intent plus `intent-delta.json`: deterministic result and before/after audit trail.
- `pin-access-projection.json`: parent live access transformed through the child placement, with schema `analog-layout-align.pin-access-projection/v1`.

Automatic offline optimization adds `analog-layout-align.placement-optimization-request/v1`,
`analog-layout-align.placement-candidates/v1`, and optional
`analog-layout-align.routeability-feedback/v1`; see [optimization-contract.md](optimization-contract.md)
for exact fields and evidence boundaries. Candidate exports remain the existing v2 placement
intent and refinement-spec/v1. Each candidate includes a unified evaluation, parent ID,
operations, delta, and source hashes. `READY_FOR_REVIEW` means offline candidate review only.

The projection/v1 output additionally retains `projected_pin_islands` and `source_hashes`.
`net_metrics[].terminal_count` counts logical instance terminals and
`physical_access_count` counts independent pin islands. Changed PCells require an explicit
measured `pin_templates` mapping before projecting access. A template-derived island ID is
projection metadata and must be replaced by live readback before routing.

`shared_diffusion_groups` is optional placement metadata produced by the
`share_source_diffusion` refinement operation. Each group names exactly two
same-kind, same-master MOS instances whose `S` terminals map to the declared
same net, the abutment axis, and sourced PDK evidence. Their evaluated PCell
bboxes must meet at the PDK-probed edge spacing with positive orthogonal overlap;
a declared source-region bbox overlap is permitted only when its contact-cut coincidence and
gate/drain isolation are evidenced and independently checked at readback. This preserves both device identities; it does not
establish LVS connectivity. Live readback, DRC, LVS, and extraction remain required.

An exact two-device pattern must contain `m` copies of each source device and give both logical devices the same row/column centroid. `nf` remains a parameter of every copy and is not expanded by this flow. Copy indices are interchangeable among electrically parallel instances; when recovering `.pl`, assign indices deterministically by physical slot while classify device identity from terminal connectivity.

The intent is complete when `unexpected_missing_instances` is empty. Rail-tied dummy copies pruned by ALIGN are legal only in `deferred_instances`; a downstream Virtuoso placer must add them at array edges and legalize them with the active PDK. A dummy with an explicit same-net S terminal may subsequently be considered for source sharing, subject to the same PDK/contact checks as active MOS copies.

For PCell legalization, completeness requires every explicit copy placed, every dummy family uniquely associated, no PCell bbox overlap, and the declared matching coordinates to agree (x for common_axis; x/y for common_centroid). Legacy and configured stack layouts require a common core x-axis. Configured rows/explicit layouts may use module-local axes; they record core_axis_x=null when no common axis exists. Strict common-axis routing must then wait for the symmetry stage to establish its axis. Supplied geometry replay is offline evidence; actual materialization requires live measurement/readback. These checks do not imply DRC or LVS signoff.

The refinement spec supports generic selectors by explicit names, macro, group, logical device, kind, or placement role. Supported operations are `translate`, `place`, `set_parameters`, `update_group`, `update_macro`, and `share_source_diffusion`. Project-specific names and coordinates belong only in this input artifact. `set_parameters` must be accompanied by explicit placements containing evaluated bboxes unless `geometry_unchanged=true` is asserted. Source sharing requires measured edge placements and coincident source-contact arrays under the evidence contract in [shared-source-diffusion.md](shared-source-diffusion.md). A middle MOS may join a left and right edge with identical placement/parameters. Parent and child instance identity sets must remain equal.

`pin_templates` is an optional mapping from a child instance to a parent live instance whose measured master-local pin figures are valid for projection. It is evidence supplied by the caller, not an inferred electrical equivalence. Projected HPWL and differential balance are preflight metrics, not live readback or signoff.

Absolute dimensions remain mock-PDK dependent until `measure-pcells` and `legalize-pcells` produce the v2 target-PDK intent. Only a validated v2 intent may be passed to `apply_placement_intent.py`.

The importer is a separate, explicitly authorized mutation boundary. It requires a new destination view and rejects an existing one. A successful placement-only readback has the expected instance count and identities, correct PCell masters/origins/orientations, evaluated bboxes within one manufacturing grid of the planning envelopes, no unexpected positive-area bbox overlaps, and zero top-level electrical shapes, nets, and terminals. PDK-probed shared-source edges may have only their explicitly declared isolated source-region overlaps, at the measured depth. PCell-internal geometry is expected and is not counted as top-level routing. Contact-cut readback is a separate mandatory check for diffusion-share closure.

The importer does not create connectivity. `terminals` in the placement intent remain annotations for later routing and LVS mapping; they are not layout nets or pins at this stage.

Drain annotations are enabled by default and have text `D/<net>` plus properties `alaKind`, `alaInstance`, `alaTerminal`, and `alaNet`. The default LPP is `annotate/drawing`. Readback must find exactly one tagged label for every MOS intent record, on the requested LPP and at the center of the transformed PCell D pin. These labels are the only permitted top-level shapes in annotated placement-only mode; top-level nets and terminals remain empty. `--no-annotate-drains` is the explicit opt-out.
