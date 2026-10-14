# Symmetric-routing handoff (guided adapter, not automatically completed by the script)

Generate `symmetry-routing-intent.json` and `symmetry-report.md` with format identifier `analog-layout-macro-symmetry.routing-intent/v1`. Bind source/snapshot/candidate/PDK-profile/terminal-access hashes, axis direction, coordinate and scope.

Required contents:

- `macro_roles`: self/pair/excluded with supporting basis; `device_pairs`: schematic identity, parameters, roles and reflected correspondence. Do not infer these solely from bboxes.
- `net_map`: a one-to-one involutive net mapping. Pair differential nets and handle common-source/supply nets as approved self-mappings. Empty strings cannot establish that unknown nets are the same net.
- `required_island_ids`: the complete physical-port inventory independently extracted from fresh terminal-access data. Multiple pin objects for one terminal cannot collapse into a single point. Every island must be paired, self-mapped or covered by an explicit asymmetry exception; do not silently omit ports with difficult gate access.
- `island_pairs`: instance/terminal/island IDs, nets, LPPs, actual global access polygons, candidate access points, selected points, same-layer reflection residuals, orthogonal offsets and escape directions for every port pair. Vertical-axis reflection swaps E/W and preserves N/S; horizontal-axis reflection swaps N/S and preserves E/W. All points must come from their actual islands, rather than fabricated arbitrary midpoints. A self-mapped island may contain mutually mirrored access points; it is not restricted to a center point.
- `channels`: geometry and layers of paired escape corridors, width/spacing/via basis and obstacle checks. Mapping same-layer access geometry does not prove a path through external obstacles; without channel evidence, remain pending.
- `routing_constraints`: sensitive-net topology, symmetric layer sequences/via stacks, length matching or tolerance sources, shared-net exceptions, supply and ring access. These are next-stage objectives, rather than implemented conclusions.
- `blockers` and `pending_checks`: itemized actual geometry, electrical roles, unequal access, unconnected ring supplies, unknown manufacturing rules and other issues.

Mark `SYMMETRY_HANDOFF_READY` only when in-scope geometric reflection, electrical mapping, complete island coverage, same-layer access and channel evidence all pass; this still guarantees neither routing reachability nor signoff. Otherwise use `BLOCKED_FOR_SYMMETRIC_ROUTING`. Common-axis candidates may be delivered for discussion, without a false symmetry-ready conclusion. Before integrating with analog-layout-route, read its current input contract and adapt explicitly; this file does not claim native route support for the new format.
