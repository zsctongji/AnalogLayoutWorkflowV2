# Analog routing checklist

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

At each gate, mark applicable items `pass`, `fail`, `unknown`, or `not-applicable`, with evidence, rule source, and owner. A legacy convention or visual impression is not PDK evidence.

## Gate 1: pre-route

- **Identity and freshness:** Saved schematic, exact target revision, terminal-access hash, PDK fingerprint/readiness, and unchanged device/connectivity state agree.
- **Closure boundary:** Every requested net has an explicit `net_class`, every physical D/G/S/B/body/hierarchy access island is inventoried, and any missing-master-terminal waiver has verified PCell/internal-tie evidence.
- **Electrical plan:** Record routing order, current/voltage-drop/parasitic/EM basis, return paths, width/via policy, sensitive regions, matching groups, and special mirror/bias/feedback/ESD structures.
- **Capacity and obstacles:** Use live geometry to assess device, implant/well/guard, existing-route, via-envelope, and sensitive-region keepouts plus channel/pin-escape capacity. Return structurally unroutable or strongly asymmetric placement to `analog-layout-align`.
- **Hierarchy:** Declare required boundary access, pin order/layer/direction, supply/body exposure, and keepouts. Do not silently create or move pins.
- **Reference layout, when authorized:** Record its exact read-only source, extraction/hash, required-net and assigned-object coverage, equivalence/signoff boundary, transferred policies, and coordinate reuse. Without placement equivalence, do not rank raw length/via count. Reject unmatched reference-pair geometry; treat supply width/loops/via arrays as conditional on current-PDK and IR/EM evidence.
- **Revision safety:** Name the destination and planned save behavior; do not target an open or inferred cellview.

## Gate 2: reviewed intent

- **Connectivity:** Every required island is covered and each required net is one conductive component across routes, vias/stacks, and contact landings. Check D/G/S/B identity and legal source/drain sharing.
- **Geometry quality:** For critical nets, verify HPWL/directness, detour, bbox excursion, per-layer length, branches, bends, layer changes, widths, and vias against declared limits. Inspect realized elbow, T-junction, tap, overlap, width transition, and contact polygons for necks/notches/EOL/min-area risks.
- **Matched networks:** One supported coupled strategy and passing limits cover total/per-layer length, bends, route/access counts, via type/count, and expected bbox span. Manually review access, topology, width, corner treatment, branching, shielding, crossings, fill, and aggressor exposure.
- **Circuit structures:** Review power/ground capacity and returns; mirror/bias collection; sensitive/high-Z/reference/feedback/compensation isolation; ESD continuity; and legal PCell/contact/via access using `routing-practice.md`.
- **Annotated SVG:** `svg_route_check.py` passes with the current target/intent hash, complete object counts/geometry, matching results, and declared symmetry groups. SVG evidence does not replace connectivity, live obstacles, polygon review, or foundry checks.
- **Integration status:** Boundary routes reach declared access. If external nets lack a pin plan, report internal routing complete but integration incomplete.

## Gate 3: materialized readback

- **Identity:** Saved target, technology/placement/intent/SVG hashes, object IDs, nets, layers, widths, points, contact extensions, counts, and component counts match the reviewed intent.
- **Physical closure:** Highlight every net and inspect endpoints, junctions, materialized polygons, via landings/enclosures, device crossings, labels, and manufacturing purposes. Re-run foundry notch/EOL/min-area and related checks.
- **Matching and reliability:** Recompute geometry from readback; run appropriate PEX pair comparison, voltage drop, current density/EM, via-current, return-path, and post-layout performance checks.
- **Handoff:** Send exact target and evidence to `analog-layout-drc`, then continue applicable LVS/ERC/antenna/reliability, PEX, and simulation. Preserve the prior revision unless the user explicitly authorized controlled existing-view edits.

## Blocking policy

Before materialization, block on failed or unknown identity/freshness, readiness, required access/connectivity, supported layer/via legality, matched constraints, critical geometry, or live-obstacle reconciliation. After materialization, retain failed work for diagnosis but never overwrite the prior revision or claim completion.
