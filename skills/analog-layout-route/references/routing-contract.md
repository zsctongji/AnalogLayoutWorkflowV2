# Routing contract

## Route spec (`analog-layout-route.spec/v1`)

```json
{
  "schema": "analog-layout-route.spec/v1",
  "target": {"lib": "designLib", "cell": "block", "view": "layout"},
  "required_nets": ["VINP", "VINN"],
  "routes": [{
    "id": "vinp_trunk", "net": "VINP", "layer": "metal-from-profile",
    "purpose": "drawing", "width_um": null,
    "points_um": [[10, 20], [15, 20], [15, 25]],
    "access": [{"instance": "M0", "terminal": "G", "pin_island_id": "M0:G:p0", "xy_um": [10, 20]}]
  }],
  "vias": [{"id": "vinp_gate", "net": "VINP", "via": "via-from-profile", "xy_um": [10, 20]}],
  "contact_landings": [{
    "id": "bias_gate_contact", "net": "BIAS", "instance": "M1", "terminal": "G",
    "pin_island_id": "M1:G:p0", "pin_xy_um": [30, 12],
    "source_layer": "poly-from-terminal-access", "via": "poly-to-metal-via-from-profile",
    "xy_um": [30, 13]
  }],
  "net_constraints": [{"net": "VINP", "net_class": "differential", "max_detour_ratio": 1.5, "max_bends": 6, "max_bbox_excursion_um": 2.0}],
  "matching": [{"first_net": "VINP", "second_net": "VINN", "max_length_delta_um": 0.1, "max_via_delta": 0, "max_per_layer_length_delta_um": 0.1, "max_bend_delta": 0, "max_via_type_delta": 0, "max_bbox_span_delta_um": 0.1}],
  "symmetry_groups": [
    {"id": "tail_self", "mode": "self", "net": "TAIL", "transform": "mirror_x", "axis_um": 50.0, "tolerance_um": 0.001},
    {"id": "input_pair_geometry", "mode": "pair", "first_net": "VINP", "second_net": "VINN", "transform": "mirror_y", "axis_um": 25.0, "tolerance_um": 0.001}
  ]
}
```

`required_nets` is the closure boundary: every listed net must have route geometry and every physical island on those nets must be covered. Planner exports must populate it from every requested net; this prevents a partial result from becoming reviewable merely because the omitted net never appeared in `routes`. `width_um: null` selects the maximum unconditional scalar minimum width only when the net's electrical sizing permits it. Coordinates are snapped to the manufacturing grid and the delta is reported. An access must name a real terminal and physical `pin_island_id` on the same net, use a candidate center from that island, and lie on its route. A legacy terminal without `pin_islands` is treated as one compatibility island.

`net_constraints` provides enforceable quality limits. `max_detour_ratio` compares routed length with terminal HPWL, `max_bends` limits geometric turns, and `max_bbox_excursion_um` limits how far the route leaves the terminal bounding box. These are review limits, not PDK values; derive them from circuit sensitivity and floorplan evidence. Power, ground, and high-current nets require an explicit width and `width_basis` in planner requests.

`contact_landings` is the only automatic poly-to-metal extension mechanism. Its named standard via must directly connect `source_layer` to a routing layer and expose normalized cut/enclosure geometry in the profile. `pin_xy_um` must be a candidate on the named island, and `xy_um` plus `pin_xy_um` must form a Manhattan extension. When `extension_bbox_um` is omitted, the builder derives an outward-grid-snapped rectangle that overlaps the pin access and encloses the via cut by the profile requirement; an explicit rectangle is validated by the same checks. The target-metal route must touch the contact center. This remains preflight evidence because arbitrary PCell obstructions are not modeled.

Generated `analog-layout-route.intent/v1` copies the profile fingerprint and source hashes, resolves rules, calculates metrics, and records boundaries. Do not edit it by hand; change the spec and rebuild.

`symmetry_groups` is optional because not every matched circuit has a simple geometric transform. Use it whenever the intended metal geometry must be self-mirrored or map one net onto another. `mode` is `self` with `net`, or `pair` with `first_net` and `second_net`. Supported transforms are `mirror_x` and `mirror_y` with `axis_um`, and `rotate_180` with `axis_x_um` plus `axis_y_um`. `tolerance_um` defaults to the manufacturing grid. Do not declare a geometric pair transform merely because two nets are electrically matched; common-centroid complements may instead be individually self-mirrored while their statistical matching is enforced by `matching`.

The builder constructs a conductive graph from same-layer metal overlap, route-to-via attachment, stacked vias sharing an intermediate layer, and contact landings. Every required net must have exactly one connected component. `physical_access_coverage.complete` and equal matched-net metrics are insufficient when route fragments are disconnected; `physical_connectivity.complete` is a separate hard gate. Older intents without this evidence must not be materialized or reused.

If terminal-access reports an intended D/G/S/B terminal in `missing_master_terminals` and its net is required, the builder blocks the intent. A `terminal_waivers` entry may clear one obligation only when it names the instance and terminal and records both a reason and concrete evidence, such as verified PCell internal body tie connectivity. A missing pin shape, naming mismatch, or assumption about substrate connection is not evidence.

`preferred_directions` is an optional layer map using `horizontal` or `vertical`. When omitted, the checker uses an explicit PDK preferred direction when available, otherwise the documented odd/even metal convention. The intent records horizontal, vertical, and off-preference length per layer. Deviations are review warnings, never DRC claims; matched topology may justify them but must still remain connected and environmentally balanced.

Route centerlines must not double back or form a short U-shaped pocket. More importantly, review the realized union of same-net path polygons at every elbow, T-junction, overlap, bus tap, and tuning structure. Do not accept an unfilled inside-corner notch, concave recess, narrow slot, or re-entrant pocket. Use a PDK-legal same-net corner/junction fill or change the topology, and apply identical corner treatment to matched routes. The current route-spec schema has no generic fill-polygon primitive, so any required fill must be represented and reviewed through the controlled materialization workflow rather than assumed from centerline geometry.

**Via containment is a separate hard geometry gate:** the actual lower and upper via metal landing polygons (including the full array/enclosure) must lie entirely inside their respective same-net wire contours. Exclude the via's own landing shapes from the enclosing wire union; otherwise the test is tautological. A via center or cut inside the wire is insufficient. Reject protruding pads/tabs, corner shoulders and new notches even when the contact is electrically continuous and cut enclosure is legal. At a straight wire use adequate transverse width and actual axial endpoint extension; at a bend/T/crossing use the realized conductor union. Prefer extending the existing segment, widening a legal matched segment uniformly, or moving the via into an existing sufficiently wide region. Do not add an isolated cosmetic landing solely to relabel the protrusion as a wire. Preserve PDK via/enclosure definitions; recheck foreign spacing, cut/stacking, connectivity, symmetry and matching after every correction. For native PCell access that cannot meet this geometry preference without changing the device, record the exact limitation instead of silently changing PCell dimensions or claiming containment PASS. Emit per-via/per-layer uncovered geometry in a hash-bound pre-import and saved-readback sidecar; the existing centerline/SVG compiler does not enforce this gate. Use [`scripts/via_containment.py`](../scripts/via_containment.py) on verified rectangular decompositions; `check(wires, vias)` reports uncovered regions per via/layer. Include actual path endpoint coordinates/extensions and exclude each tested via landing from the wire input. For paths whose native extension attributes are ineffective, extend the endpoint coordinates and qualify the actual bounding boxes before saving. Unsupported polygon decomposition remains UNKNOWN.

The checker covers profile identity/readiness, target, required-net closure, one conductive component per required net, routing layer-purpose pairs, minimum width, Manhattan/grid geometry, complete physical pin-island coverage, named via transitions, poly/contact source enclosure, route attachment, conservative same-layer cross-net spacing, declared directness limits, preferred-direction metrics, and pair total/per-layer length, bends, route/access counts, via type/count, and route-bbox-span matching. Both named pair members must have route geometry. It does not polygonize path joins, prove environmental coupling symmetry, prove the absence of concave notches/re-entrant pockets, or infer that an access-layer candidate needs a new contact when a live PCell already contains connected landing metal. It also does not cover arbitrary PCell obstruction geometry, full via landing envelopes, forbidden stacked-via combinations, conditional/EOL/notch rules, density, antenna, EM, substrate coupling, extraction, DRC, or LVS. Close routing boundaries with live database inspection, then hand the saved target and evidence to `analog-layout-drc`.

## Annotated SVG check (`analog-layout-route.svg-check/v1`)

The preview generator emits `analog-layout-route.preview/v1` SVG. The root records the intent SHA-256 and coordinate transform. Every route polyline, via rectangle, and contact circle records its object ID, net, layer or via definition, and other identity fields. Run `scripts/svg_route_check.py` immediately after intent/preview generation.

The SVG checker inversely maps rendered coordinates into microns, requires one matching SVG element for every intent route/via/contact, rejects missing, extra, duplicated, relabeled, stale-hash, or geometrically changed elements, confirms every intent `matching` result is passing, and applies every declared `symmetry_groups` transform to route unions plus via/contact point sets. The output records target, intent fingerprint, SVG fingerprint, counts, matched-pair results, symmetry-group results, errors, warnings, and the review boundary.

A passing SVG check is required for materialization. Supply it with `apply_routing_intent.py --svg-check <svg-check.json>`; the importer rejects a non-PASS result, a target mismatch, an intent-hash mismatch, missing SVG fingerprint, or reported errors. `--verify-only` may omit the artifact because it only rereads already materialized database geometry.

SVG checking is deliberately independent but not authoritative for electrical connectivity. A preview can be geometrically symmetric while carrying an electrical open, wrong net, illegal enclosure, or unmatched parasitic environment. Require all three relevant gates: structured intent connectivity/matching, annotated SVG structure/symmetry, and Virtuoso database readback, followed by foundry verification.
