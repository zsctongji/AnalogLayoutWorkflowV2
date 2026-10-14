# Strict-symmetry scope, generation and acceptance

## Establish electrically realizable scope first

In `symmetry-map.json`, bind source layout/netlist/access/profile hashes, common-axis provenance and each matching group's mode. Classify every net to route as pair, self, matched_only or justified ordinary/exception scope; do not omit matched nets to evade checks.

pair requires complete one-to-one physical-island mappings: instance/copy/finger, G/S/D/B roles, nets and legal access layers. Applying the mapping twice must return the original island. Nearest positions or equal dimensions alone cannot establish pairing. Axis-centered nodes of self map to themselves; other physical access islands map in pairs. Different nets cannot be shorted to create center connections.

Current-mirror reference, common-gate and output branches have different roles. Only part of their drain connections may be symmetric; whole nets such as net5 and OUT may not be interchangeable. Local matching scope must list exact endpoints/physical islands, all included route/via/reused metal and boundary interfaces. Remaining branches retain netlist correctness and participate in all connectivity checks. Existing templates/v1 has no generic branch-scope field: use project sidecars/adapter review, without invented parameters the compiler may ignore or local matching labeled whole-net pair PASS.

External ports are part of complete net paths. For user-specified nonmirrored single-ended ports, define the boundary and approval record for strict core symmetry + external-access exceptions. Do not ignore external wires and later claim whole-net symmetry. matched_only/exceptions do not receive strict-symmetry PASS.

## Generation and repair

### Full-net strategy coverage and trunk selection

Establish per-net strategies before selecting trunk coordinates. Do not derive exceptions backward from hardcoded left/right net placement. Project sidecar `symmetry-map.json` must cover all required_nets. For a net with a matched core and additional branches, split scopes while retaining complete whole-net connectivity checks.

For each net, record functional role, pair/self/matched_only/exception mode, core endpoints/physical islands, included route/via/reused-metal IDs, boundary branch points, selected collection/trunk strategy, candidate-comparison evidence and exception decisions. During planning before shape IDs exist, define scope through explicit endpoints and complete IDs after generation. A generic core-symmetric/periphery-excepted statement is insufficient.

- **Matched core**: generate by strict reflection and repair jointly from corresponding device escapes to designated core-boundary interfaces. Match layer sequences, lengths, widths, transition positions and branch points. Different whole-net loads do not justify demoting both entire nets to ordinary mode. Do not confuse current-mirror reference, common-gate and output branches.
- **Common-gate, bias and other common nets**: first evaluate axis-centered trunks with symmetric horizontal collection and equidistant two-sided trunks with actual same-net center connections. Select by actual ports, obstacles and sensitivity; do not mechanically route both alternatives. For asymmetric additional loads, preserve the symmetric core-collection scope and list extra connections separately. One extra branch does not justify side placement of the whole common net.
- **Single-ended outputs**: first evaluate axis-centered vertical trunks with corresponding collection from both sides. Prefer these when legal and within existing sensitive-net/parasitic budgets. Evaluate side alternatives if the axis is occupied, ports are unreachable or costs are materially unfavorable. Single-ended does not automatically mean right-side output; axis-centered trunks do not prove whole-net self-symmetry either. For user-specified side ports, separate core collection from boundary escapes without changing port requirements.
- **Additional-branch exceptions**: record actual netlist reasons, exact start/end islands/boundaries, geometry scope, unmirrored items and environment/parasitic risks. Nonequivalent net topologies may justify limited scopes but cannot exempt the entire drawing from checks. Changing adopted strict scope requires explicit user confirmation; unadopted candidate exceptions are proposed, not accepted.

Candidate comparisons must record actually evaluated axis-centered/two-sided/side alternatives, legality or specific obstacles, per-layer lengths/vias and sensitive-net costs. Without parasitic data, report geometric proxies and UNKNOWN only; do not invent benefits or relax budgets. Exhaustive track enumeration is unnecessary, but relevant preferred-alternative checks must precede side selection. Nonfunctional mirrored metal, dangling patches, duplicate vias and appearance-only meanders cannot establish symmetry.

`symmetry-audit.json` reports statuses/evidence separately for `matched_core`, `common_net_collection`, `single_ended_output_strategy`, `branch_exceptions` and `all_required_nets_accounted_for`. A passing output-strategy assessment does not prove output geometric self-symmetry; accepted exceptions do not mean exception geometry PASS. Describe overall results only as strict symmetry in designated cores with remaining scopes handled under listed strategies/exceptions. Claim complete left/right symmetry only when all geometric scopes actually verify with no asymmetric exceptions. Unclassified nets, omitted scopes, unevaluated side placement or unconfirmed scope demotion block materialization.

- For each group, jointly select M1 access islands, tracks, layer-transition sequences, via definitions/arrays, bus taps and ports. Reflect one side's template to generate the other; independent shortest paths with total-length compensation are insufficient.
- For every corresponding branch, compare paths from physical islands to the first branch point, first transition and subsequent trunk. Per-layer lengths/widths, bend positions, branch junctions and via types/counts/arrangements must correspond. Equal whole-net lengths cannot conceal local branch differences.
- Check the jointly feasible track domain on both sides. A DRC conflict on either side requires paired regeneration and rechecking every obstacle on the other side. Use opposite-direction via offsets to preserve reflection; do not add the same global offset to both sides.
- Include reused M1/contacts/vias in complete conductive unions and port paths, rather than comparing only new routes. Existing asymmetric geometry without modification authorization cannot be disguised with duplicate metal/contacts.
- Different collinear segmentation/shape counts are allowed, but actual same-layer/same-width conductor unions, end caps, landings, cut arrays and connection topology must correspond. For asymmetric via masters, prove correspondence of actual cuts/metal after legal orientation/transforms; equal via names alone are insufficient.
- Do not create nonfunctional dangling metal, one-sided meanders or extra vias for appearance. If paired detours exceed high-impedance/sensitive-net budgets, output conflicts and legal alternatives rather than silently relaxing budgets.

Fix the common axis and require exact mutual coordinate mapping on the manufacturing grid. Axes at half-grid positions may produce legal mirrored coordinates, so check all reflected coordinates instead of requiring an integer-grid axis mechanically. Default geometric deviation is zero, allowing only numerical arithmetic error. Regenerate legal mirrored candidates if database quantization changes geometry; a one-grid displacement is not floating-point error.

## Acceptance artifacts and explicit boundaries

### Two-sided same-net trunks for highly matched nets

When different additional loads or current-mirror roles prevent whole-net pairing of two highly matched nets, permit and preferentially evaluate **independent two-sided collection for net A + independent two-sided collection for net B + cross-net matching of designated core branches**. Record this project policy after explicit user adoption. Global skills do not bind design-specific net names, coordinates, widths or PDK values.

- For each net n, plan one functional trunk on each side of common axis x=a at a−d_n and a+d_n, with d_n>0: two trunks total per net, not two per side. Legal layer changes/database segmentation may produce several shapes in one trunk; shape counts cannot replace topology checks.
- Within declared symmetric scope, same-net bilateral trunks use the same layers/widths and corresponding vertical extents, with mirrored taps, transitions and local access. Under odd-metal vertical/even-metal horizontal directions, use legal vertical layers such as actual M3 for trunks and legal horizontal layers such as M2 for same-net collection/connections. Conductors/legal vias form one net, rather than two dangling mirrored wires.
- Use separate isolated tracks/horizontal channels for the two nets. Do not overlap/short them on one layer to force d_A=d_B. Different axis distances may be necessary; independently quantify corresponding core-branch per-layer lengths, vias, metal area and nearby coupling-exposure differences. Equidistant left/right trunks do not automatically establish equal cross-net parasitics.
- Add a net to self_nets only when its complete physical islands, paths and ports verify as self-symmetric. For nonmirrored additional branches, specify self-symmetric core collection + additional-branch exceptions in sidecars; symmetric trunks alone do not give whole-net self PASS. Compare cross-net core matching branch by branch from corresponding islands to boundary interfaces, without fabricated whole-net pairs.
- Both trunks must collect actual device connections or have evidenced electrical functions. Do not add dangling mirrored wires, nonfunctional end extensions or duplicate contacts for appearance. Compare added length, vias, metal area and sensitive-node costs of the bilateral structure; do not add meanders to equalize total length. If DRC, access or adopted parasitic budgets cannot be met, report topology conflicts/alternatives without silently relaxing constraints.

Acceptance retains all of: per-net two-sided topology/actual connectivity, declared-scope self-symmetry, cross-net core matching, different-net isolation, additional-branch exceptions and added-parasitic risks. The template compiler does not generate bilateral trunks or infer these branch scopes automatically; callers must generate explicitly and complete these reviews.

Each stage's `symmetry-audit.json` records stage, target, common axis/provenance, input/actual-geometry hashes, groups/exceptions and check coverage. Record per group:

1. Complete physical-island/external-port correspondence and connectivity of every branch.
2. Per-layer metal-union reflection differences and unpaired shapes; widths, end extensions, local M1 and access layer sequences.
3. Per-branch/per-layer length differences; via/contact types, counts, coordinates, arrays, cuts and upper/lower-landing reflection residuals.
4. Actual center-interface connectivity of self nets and one conductive component per net; isolation between pair nets.
5. Foreign-net distance, parallel-exposure length, shields, crossings, wells/rings and fill differences near corresponding segments. State risks when environments cannot match, without false equal-parasitic claims.
6. Per-item PASS/FAIL/UNKNOWN/N/A, evidence locations, blockers and user-approved scope exceptions.

Any candidate geometry/access/via-parameter change invalidates old reports. Reconstruct independently from the actual saved database, rather than copying candidate reports. Unknown/failed geometry, mappings or connectivity in strict scope cannot be accepted. Report environment/electrical-parasitic conclusions separately; geometric PASS cannot replace PEX. Existing ordinary/exception scopes still require DRC, direction, net-integrity and sensitivity-budget compliance.

## Current automatic-check coverage

`mirror_spec.py` calls the original `svg_route_check.py` geometry-comparison functions to check compiled intent centerline unions by layer/purpose/width and via/contact centers/definitions directly. Coverage includes seed-declared self/pair groups. Asymmetric self nets are BLOCKED at compilation even when connected. All groups must follow the requested common axis, with tolerance at most `min(1e-9 µm, grid_um*1e-6)` for floating-point comparison only. Equivalent collinear unions with different segmentation may pass.

This early check omits complete conductor polygons, contact extensions, via overrides/arrays, reused live metal, arbitrary local-branch mappings and environment. Agents/adapters still complete these under the contract above. Template `materializable=false` remains unchanged; independent SVG gates and formal pre-materialization/readback checks remain required.
