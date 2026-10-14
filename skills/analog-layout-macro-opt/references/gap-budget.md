# Pair-specific whitespace and channel budgets

Read when optimizing inter-module whitespace. A source layout's gap is an observation, not automatically a hard process constraint. Preserve explicitly user-adopted reservations; distinguish those from an earlier adapter's unqualified default. A request to optimize whitespace permits revisiting the latter, not discarding real routing requirements.

For each ordered neighbor pair, record a sidecar `gap-budget.json` bound to the live snapshot and rule sources:

- Measured complete macro-envelope gap and relevant facing layer edges, including rings, implant, well fill and local pin escapes.
- Applicable rule, device/voltage/domain context, numeric minimum and provenance. Well-to-well spacing applies only when two relevant wells are present; a well facing a substrate tap/device requires its own clearance rule. Unknown contexts remain blocked, not silently zero.
- Convert layer-edge constraints to required envelope gap by subtracting measured inset margins already inside the two envelopes. Clamp to zero; round UP to the manufacturing grid. Do not shrink/rebuild rings or omit labels/passives to improve reported area.
- A separate routing reservation: layer, track count, conductor/via landing width, edge clearance, access direction and purpose. One-dimensional channel width is `sum(track_widths) + sum(intertrack_spaces) + edge_clearances`; use landing widths when vias must fit. Different-layer overlap needs a reviewed access plan. This is a planning capacity model, not router closure or process spacing.
- Use the maximum of applicable physical clearance, routing reservation and other adopted isolation margins. Synchronize `pair_gaps` and `order.gap_um`; a stale larger order gap must not silently defeat a reviewed smaller pair gap. Keep x/y budgets independent.

Report old gap, new gap, reclaimed gap, limiting rule/reservation and unverified conditions. Compare a source-constraint baseline against the revised budget so an improvement is not misattributed solely to search quality. After translation remeasure actual layer-edge distances, protected geometry and terminal access. If needed trunks/landings no longer fit, reject or restore channel space; never claim routability solely from a smaller HPWL.

## Ordered-stack candidate generation

### User-selected 1.5 µm vertical candidate

For placement-only adjacent stacks, evaluate a 1.5 µm complete-envelope vertical gap before retaining earlier generic 2.34/3 µm channel allowances. Record `requested_vertical_gap_um: 1.5` in the sidecar as user planning policy, not a foundry rule. Keep this sidecar field out of the strict request schema.

Do not assume the whole inter-module gap must contain a complete via landing plus two edge reservations. Review the actual access topology: legal landings may remain inside owned macro regions or use external side channels and higher-metal trunks, subject to PDK and symmetry checks. Conversely, do not assume those alternatives exist merely to justify 1.5 µm. If unresolved, retain a draft candidate with the access limitation, not a materialization-ready claim.

When physical clearance and reviewed access permit 1.5 µm, set the applicable pair's `y_um` and vertical order's `gap_um` to 1.5, rounded outward to the manufacturing grid. Preserve x budgets and all other pairs unless separately reviewed. For reviewed horizontal adjacency, the same 1.5 µm target may be used in pair_gaps.x_um and horizontal order.gap_um; record requested_horizontal_gap_um in the sidecar. Each direction uses the maximum of the 1.5 µm target, applicable physical clearance and required routing/access reservation, rounded outward to grid. When a verified requirement exceeds 1.5 µm, use that requirement and report the limiting layer/rule or access obligation. The adopted 1.5 µm target does not authorize smaller gaps by default. Keep the old-budget baseline and report changed assumptions alongside the area comparison.

For a total acyclic order whose movement components on the compacted axis are independent, the engine adds forward/reverse stack proposals. It propagates pair/order separation through all predecessors, preserves fixed positions, snaps outward on the source-phase grid, and moves an entire stack in one candidate. Coupled-axis components and ambiguous/partial orders fall back to beam search. All proposals pass the same full validator (bounds, locks, symmetry, pair gaps and pin spans), count against the same evaluation budget, and never replace a valid baseline with an invalid candidate. This is a conservative constraint-graph-inspired proposal, not an LP global-optimum claim.

`ordered_gap_audit` reports conservative axis slack; another axis may satisfy pair separation in a general non-stack topology. Positive slack is not automatically recoverable when locks, spans, other neighbors or routing reservations bind.
