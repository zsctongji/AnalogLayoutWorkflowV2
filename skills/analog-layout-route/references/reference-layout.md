# Reference layouts as routing evidence

Use only when the user authorizes a manual, legacy, or peer layout. Keep it read-only and record its exact library/cell/view plus extraction artifact/hash.

## Extract and qualify

Separate top-level routing paths/pathSegs, rectangles/polygons, vias, nets, widths, layer-purpose pairs, bbox, and placement from contacts, labels, annotations, and PCell-internal geometry. Report unassigned or ambiguous objects rather than guessing.

Summarize each net's circuit role, topology (local strap, trunk, center/bilateral bus, tree, ring, or escape), layer sequence/fractions, width classes, length, bends, vias, bbox excursion, and a placement-normalized baseline when available. Check required-net coverage, assigned-object coverage, device/PCell decomposition, schematic equivalence, and any DRC/LVS/PEX provenance.

Classify transfers:

- **Allowed evidence:** unambiguous topology, collection style, or layer policy for corresponding circuit roles.
- **Conditional:** widths, via arrays, loops, shielding, and returns pending present-PDK, current, noise, and IR/EM evidence.
- **Blocked without proof:** coordinates, pin-island IDs, raw length/via rankings across different placements, or matching geometry from a reference pair that fails target limits.

Fresh target `analog-layout-align.terminal-access/v1` remains authoritative. Different placement, multiplier expansion, PCell revision, or island grouping invalidates physical identities.

## Compare

Run `scripts/compare_reference_layout.py` with the target intent, fresh terminal access, reference summary, and route spec. It reports assignment coverage, layer fractions, target detour/off-direction/vias-per-terminal, power topology/width findings, and reference-pair self-consistency.

The tool suppresses raw length/via deltas unless `--placement-equivalent` is supplied after proving the exact placement transform and terminal correspondence. Prefer detour, transitions per terminal, off-direction ratio, branch/shared-trunk use, matching, current capacity, returns, and isolation.

Do not infer that a shorter supply tree beats a wider ring; compare IR/EM and returns. Review high off-direction or repeated-transition bias routes against center/bilateral/shared-bus collection. Preserve target matching when the reference pair is asymmetric.

Record which policies were adopted or rejected and why. A reference never substitutes for foundry DRC/LVS, PEX, EM/IR, or post-layout simulation.
