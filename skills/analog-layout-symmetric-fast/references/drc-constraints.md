# DRC rule constraints and evidence contract

Read before selecting tracks, widths, vias or landing points. Applies to candidate generation, pre-materialization review and post-save readback; it does not replace foundry DRC. This document specifies checks for agents/project adapters, **not a claim that mirror_spec.py implements them**.

## 1. Rule sources and applicability

Create `drc-rule-table.json` in the run directory. Record target, process/PDK version, metal-thickness option, manufacturing grid, profile fingerprint, deck files/version/content hashes, rule IDs/locations, units and applicable layer pairs/conditions. State implementation methods (rectangle distance, polygon checks, actual deck, etc.) and coverage boundaries for every rule.

Obtain rules from the current foundry deck, corresponding design-rule manual and verified tech/via definitions. Resolve discrepancies by checking process options/conditions before selecting values; do not silently choose a smaller value. Manual reference layouts, historical successes and previous-run values cannot replace current rules. Do not alter profiles to hide violations. Wide-wire/PRL, EOL, same-net exceptions, array scale, redundant cuts, high voltage and pad-only stacking permissions are conditional rules, not one unconditional global minimum.

Assess applicability of at least these rule families individually:

| Rule family | Checked objects |
|---|---|
| min-width, min-area, grid | All new metal, local escapes, landings, port shapes and narrow necks in unions |
| metal spacing | Wire–wire, wire–landing, landing–landing and edge spacing to existing PCells/guard rings/routes |
| width/PRL, EOL, notch | Wide-wire parallel regions, endpoint neighborhoods, inner U corners, T junctions and same-net notches |
| cut size / cut spacing | CONT and each via level: dimensions, cut spacing within/between arrays, including same-net cuts |
| cross-cut / stacking | Spacing between cut layers, projected overlap, allowed cascades/forbidden stacks and contextual exceptions |
| enclosure / extension | Upper/lower conductor coverage of each cut, directional end enclosure, legal landings and access |

`N/A` requires an explanation that corresponding geometry/context is absent; unread or unimplementable rules are not N/A. Rules applicable to new geometry but not parsed/checked are `UNKNOWN` and cannot count as passes. List full-chip/signoff items such as density, antenna and complete reliability separately as pending; do not present local preflight as complete DRC.

## 2. Measure actual geometry

1. Capture complete live conductors, cuts and obstacles: actual PCells, rings, old routes/vias, top-level ports and legal local contacts. Treat unknown nets as foreign; device bboxes or pin centerlines are insufficient.
2. Generate conductors from actual pathStyle, end extensions and corners; do not assume endpoints extend outward by half the width. Use actual conductor unions for width changes, U/T junctions and same-net connections. Probe unknown polygon/end-cap behavior or use the actual deck, rather than passing approximate geometry.
3. Expand standard vias into individual cuts and upper/lower metal using actual row/column counts, cutSize, cutSpacing, originOffset, enclosure, orientation and overrides. Identical via names do not establish equal array/enclosure parameters; reread parameters after saving.
   Also check complete via containment: all upper/lower landing geometry must lie inside actual corresponding same-net route outlines, with no protrusions at endpoints, corners or T junctions. Include actual metal enclosure in envelopes, not just cuts. Exclude via-supplied landings from route unions used to prove containment; a landing cannot prove its own containment. Extend route ends from actual endpoint coordinates and beginExt/endExt. If property writes are ineffective, extend endpoint coordinates and confirm by readback, widen the complete route legally or move landing points, applying changes jointly. Do not conceal protrusions with isolated patches or alter PDK via enclosures to shrink vias. After saving, output uncovered regions per via/layer; failures block this geometry gate.
4. Cover new–existing and new–new interactions, including both sides and cross-combinations near self-symmetry axes. Explicit checked-scope evidence may be retained for unchanged existing internal geometry, but interactions with new geometry cannot be excluded.

For parallel straight wires with overlapping projections, centerline track separation is at least `w1/2 + S_applicable + w2/2`. This is for proposal generation only. Measure endpoint/corner/diagonal minimum distances and PRL/EOL conditions using the deck's distance definitions. Do not universally substitute center distance, Manhattan distance or Euclidean distance for the specified metric.

For arrays, cut pitch = cut dimension + cut edge spacing, separately in x/y; pitch is not edge clearance. Check cuts between different via instances even on the same net. For exact overlap with existing cuts, prefer proving reuse of the same legal contact/via instead of duplicating it. Overlap on different nets is an immediate short, not a merge opportunity.

## 3. Layer transitions are not automatically legal

M1→M2→M3 geometric connectivity does not establish permission for V12/V23 at the same coordinate. Check cross-level spacing/stacking limits for every actual cut-layer combination. If stacking is forbidden, offset landing points and connect on an intermediate layer respecting odd-metal vertical/even-metal horizontal directions, then recheck both cut types, landings, wire spacing and matching. Array expansion/offset also requires every applicable interaction with nearby CONT/other vias.

Check enclosure/access using conductor unions proven to be same-net and geometrically connected. Nearby labels or cut centers on wires do not establish conduction. Actual standard-via upper/lower metal may contribute to enclosure; legal existing enclosure need not be expanded mechanically. Expanded landings affect neighbor spacing, so recheck all interactions. Current capacity/EM sizing is an independent constraint: minimum DRC cut counts do not establish supply-current capacity.

## 4. Joint selection and stopping conditions

Include widths, applicable spacing, complete via envelopes and end requirements in bounded track/landing candidate budgets first. Both sides share the legal candidate set. After actual conflicts, change tracks, offset vias or transition legally as a pair, never one side alone. Recompute all adjacency relations, connectivity, per-layer length/via matching and sensitive-net budgets after changes.

Exhausted bounded candidates return `NO_VALID_TEMPLATE_IN_BUDGET`; missing rule/live-geometry evidence returns a not-ready status. Do not disable spacing, skip same-net cuts, reduce widths, permit forbidden stacking or relax symmetry to pass. Ordinary user acceptance of appearance exceptions cannot legalize PDK violations. Record any formal foundry waiver explicitly without claiming absence of violations.

## 5. Per-stage check records

`drc-preflight.json` is a project sidecar; **do not add it to existing strict template/route-spec schemas**. Suggested fields:

- `stage`: candidate / pre_import / saved_readback.
- `target`, `intent_sha256`, `layout_snapshot_sha256`, `rule_table_sha256`, `profile_fingerprint`; after saving, also record actual geometry-readback hashes.
- `checks`: rule_id, object/route/via/cut IDs, net, layer pairs, bboxes/positions, actual parameters/conditions, measured/required values, units/distance definitions, margins, PASS/FAIL/UNKNOWN/N/A and evidence locations.
- `coverage`: included new/existing metal, cuts and pin/ring/PCell obstacles; unrepresentable geometry and uncovered rules.
- `blocking_failures`, `blocking_unknowns`, `pending_signoff`, `status`.

Record `SELECTED_RULES_PASS` only when every required check affecting current geometry has evidence of a pass or justified N/A, without blockers. Candidate-geometry changes, via-parameter changes, grid snapping, target drift or rule changes invalidate old reports. Recompute independently after saving; changing a projected report's stage does not make it readback evidence.

Materialization requires all of: formal intent/SVG gates, direction/local-access gates, this DRC preflight, user authorization and target protection. Only actual foundry-deck runs on saved layouts may report foundry DRC clean. Neither this rule table nor rectangle preflight replaces them.
