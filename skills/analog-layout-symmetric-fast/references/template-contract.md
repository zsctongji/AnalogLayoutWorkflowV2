# Fast template compilation contract

Depends on sibling `analog-layout-route/scripts/route_intent.py` without copying/modifying that engine. Uses the Python 3.10+ standard library. Check interface compatibility before first use and run tests after upgrades.

## CLI

```text
python scripts/fast_route.py --profile profile.json --terminal-access terminal-access.json --request templates.json --out NEW_RUN
```

Request schema: `analog-layout-symmetric-fast.templates/v1`, with the following fields. The retained `mirror_spec.py` accepts the original `analog-layout-symmetric-route.templates/v1` only as a compatibility API; it does not enforce the new configuration/direction gate.

- `sources`: exactly `{profile_fingerprint, terminal_access_sha256, seed_sha256}`. Compute using original route_intent fingerprint/digest functions, not other skills' digests with different ASCII canonicalization.
- `axis`: `{coordinate:"x"|"y", value_um:number}`. x denotes a vertical line and y a horizontal line. Fix the original core axis; do not change it to simplify escapes.
- `seed_spec`: complete `analog-layout-route.spec/v1`, with required_nets containing every net to route, including nets on the mirrored side. routes/vias/contact_landings contain the complete first_net half-net for each pair; second_net geometry must be empty. Define self/ordinary nets completely in the seed. A one-point intent is insufficient: every actual physical island must reach the completed connectivity graph.
- `pairs`: `[{first_net,second_net,pin_pairs:[[first_island_id,second_island_id],...]}]`. Cover every island of both nets with one-to-one correspondence. The compiler verifies instance/terminal/net and selected coordinates against terminal-access, without guessing from neighboring finger counts. Seed access coordinates and their reflections must be measured candidate_centers of the corresponding islands.
- `self_nets`: explicit self-symmetric net list, disjoint from pairs; no automatic completion or shorting of sides. Compilation checks self-symmetry of represented segment unions by layer/width and via/contact centers directly, returning BLOCKED for asymmetry. Independent SVG gates and single-component checks remain required.
- `via_mirror_evidence`: qualified same-definition reflection-evidence/report paths keyed by via name and applicable to the current profile/layer stack/orientation. Presence is not proof; the agent must read supporting evidence. For asymmetric vias, copying names/positions is insufficient. Unverified contacts/vias cannot be mirrored. Check each definition in a stack and the complete stack.

All seed widths must be explicit and nonzero; do not rely on width=null to select minima automatically. net_constraints for each required_net require net_class; power/ground/high_current also require width_basis. Sensitive, high-impedance, differential, matched/feedback nets require directness budgets. Use engine-supported class names and adapt new classifications explicitly. Differential/matched nets require matching; pair compilation may add zero-geometric-difference constraints, while matched-only matching must be explicit in the seed.

Outputs: `route-spec.json`, `preflight-intent.json`, `template-result.json`. Even with TEMPLATE_PREFLIGHT_PASS, materializable is always false. Template generation does not check full-field obstacles, actual via envelopes/corners/conditional rules or environment; it is not a successful automatic-routing run.

The current compiler also does not identify device-local regions, cross-macro branches or cumulative M1 length budgets automatically. Therefore TEMPLATE_PREFLIGHT_PASS **does not establish compliance with the mandatory default routing hierarchy**. Callers must use the algorithm.md acceptance table and retain local regions/length budgets/results in the run directory. Do not add unsupported fields to the current strict schema or claim automatic implementation of these checks. Noncompliant M1 cross-array/cross-module drafts cannot enter materialization merely because compilation succeeds.

**Odd-metal vertical/even-metal horizontal directions are also an independent materialization gate.** Populate `seed_spec.preferred_directions` with verified PDK layer-name mappings to actual metal levels: M1 vertical, M2 horizontal, M3 vertical, and so on. Handle process conflicts according to the skill entry point. The fast entry point rejects unqualified reverse-direction segments using explicit actual metal levels. Retained direct compiler calls and the general validator still require the independent algorithm.md direction review before import. Do not alter PDK-profile rules to fit this mapping.

## Two helper functions

`doglegs(start,end,tracks_x,tracks_y)`: returns only bounded straight/L/U centerlines, removing zero-length segments and immediate reversals, sorted by length. No collision checking. Callers supply reasonable candidate tracks/stopping budgets and check actual widths/spacing on both sides.

`doglegs` returns no layer assignment or vias; an entire L/U cannot be assigned directly to one layer. Callers must assign straight segments by direction, add legal profile vias at corners and recheck complete connectivity/matching. The helper does not perform this conversion.

`horizontal_bus(prefix,net,m1,trunk_layer,width_m1,width_trunk,via,taps,y,x_range)`: outputs routes/vias fragments. Each tap is `{access:{instance,terminal,pin_island_id,xy_um},landing_xy_um}`. A single nonzero short H/V segment runs from actual M1 access to landing, followed by one explicit named via to trunk layer and a continuous horizontal bus. No automatic poly contact or arbitrary multilevel via stack support: manually generate legal seed geometry or use the original skill's controlled contact_landings adapter. m1 is an actual profile layer name, not an assumed literal M1. Length limits, track selection and current-width adjustment are not automatic; upstream budgets/downstream checks own them.

The retained bus helper requires every landing to have the same y coordinate as its horizontal bus. A vertical branch on the horizontal trunk layer is rejected. Use mapped `layered_dogleg` fragments and qualified transitions for additional branches.

## Required validation chain

The compiler checks only explicit pairs/self_nets. It does not recognize common-gate/bias/single-ended outputs or compare axis-centered/side trunks automatically. Thus all declared groups may PASS while asymmetric whole-layout trunks remain omitted. Callers must first perform **full-net strategy coverage and trunk selection** in symmetry-constraints.md, covering required_nets individually in project sidecars and listing local-branch exceptions separately. Do not add unsupported fields to strict templates/v1 or describe agent/adapter reviews as compiler-enforced. Adapters constructing route-spec directly without template compilation must also perform this gate.

Perform full-scope/readback review under `symmetry-constraints.md`. Compilation output adds `symmetry_preflight`, which must PASS for TEMPLATE_PREFLIGHT_PASS. Inconsistent common axes, exceeded numerical tolerance or self/pair geometry mismatch block. Coverage is limited to represented centerline unions and via/contact centers, rather than all live conductors/arrays/port paths. Use independent `symmetry-audit.json` sidecars without adding unsupported branch fields to strict templates/v1.

All stages must also follow `drc-constraints.md`. `drc-rule-table.json` and per-stage `drc-preflight.json` are independent sidecars, not new template-request fields. Template `materializable=false` remains unchanged. Existing scripts do not parse decks or complete individual-cut/conditional-spacing checks automatically; neither `TEMPLATE_PREFLIGHT_PASS` nor error-free general intent alone permits import. Agents/adapters complete and review these reports; do not claim the current importer automatically reads these sidecars.

1. Jointly check complete live obstacles and shorts, spacing and enclosure among newly generated routes/vias on both sides. For failures, modify template parameters and regenerate completely; do not patch mates locally and break reflection.
2. Rebuild with the existing route_intent CLI from profile/access/spec, producing hashed formal intent/report/preview and requiring READY_FOR_REVIEW. Preserve compiler-added offline-obstacle markers. Only after actual live review, record reviewed_live_target and specific evidence in planning_evidence under the original contract.
3. Run svg_route_check and require PASS. It checks pair/self geometry; compiler/intent status alone is insufficient. Special self/matched-only cases may fail here and cannot be waived as merely display issues.
4. Gate 2 reviews live obstacles, actual corners, width changes, via envelopes/stacks, supply/ring access, ports/environment. Only after completion may import of the user-authorized new revision proceed.
5. Follow original importer readback and foundry verification; do not send template-script results directly to dbCreatePath.

Example: mutually mirrored nets may automatically expand to strictly identical geometry. If ABBA positive/negative inputs are each self-symmetric, do not provide fabricated pair pin_maps. Select matching objectives first, then plan self+matching and still check per-layer lengths/vias/environment. Ask for explicit user adoption if that choice changes the objective.


## Configuration and helper API

Read [configuration.md](configuration.md) for required `routing_policy`, full-net classifications, generated tracks, role-based layer assignment, and the configured workflow backend. Physical coordinates in a supplied seed are project data, not skill defaults. Local M1 cumulative regions/budgets, full via landing/cut/conditional-rule checks and live readback remain separate required evidence; the new direction gate does not certify them.
