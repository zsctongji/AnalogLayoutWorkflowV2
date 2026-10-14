# Analog routing engineering practice

These are decision heuristics, not PDK rules. Schematic intent, measured current, project constraints, the active technology database, reliability rules, and foundry decks take precedence. Derive every numeric width, spacing, tolerance, and current limit from those sources.

## Hard invariants

- Every required net must cover all physical pin islands and form exactly one conductive component through same-layer overlap, legal vias/stacks, and contact landings.
- Review realized polygons, not only centerlines. Reject narrow necks, unfilled notches, slots, re-entrant pockets, immediate backtracking, and invalid elbow/T-junction unions.
- Check full via cuts and landing/enclosure envelopes against obstacles. Do not infer a needed diffusion contact from an access-layer label; inspect live PCell connectivity first. Do not stack adjacent-layer vias at one coordinate without explicit PDK/deck support.
- Route matched or differential branches as one coupled problem. Match access, layer sequence and per-layer length, width, bends, via types/counts, branching, and surrounding exposure; equal total length is insufficient.

## Planning policy

| Area | Decision rule |
|---|---|
| Directness | Start with the shortest electrically sound Manhattan topology. Report HPWL or another lower bound, detour, per-layer length, bends, branches, bbox excursion, and vias. Fix placement/access/topology before adding tuning. |
| Routing order | Establish power/ground capacity and returns, reserve sensitive/high-impedance/matched/feedback corridors, then ordinary signals. Document justified exceptions. |
| Layers | Prefer low layers for local access, middle layers for block trunks, and higher layers for long or high-current paths only with RC/via/congestion evidence. If the PDK is silent, odd-vertical/even-horizontal is a soft convention, never a DRC rule. |
| Width and vias | Size from current, voltage drop, resistance, EM/reliability, and parasitic budgets. Minimum width or via count is not an optimization goal by itself. |
| Power/ground | Compare tree, ring, star, or local branches by IR/EM, return continuity, shared impedance, and isolation. Avoid narrow serial feeds and verify guard/tap continuity at handoff. |
| Mirrors/bias | Keep common-gate and matched-source collection short, low resistance, and symmetric. Prefer center, bilateral, or symmetric buses over avoidable one-sided daisy chains. |
| Sensitive/high-Z/reference | Minimize length, metal area, branches, vias, and parallel aggressor exposure. Separate from clocks, switching, and large-swing outputs; preserve quiet returns. |
| Feedback/compensation/RF | Sense the intended node, keep the loop electrically short, and verify stability after PEX. RF needs its project-specific rule set. |
| Shielding | Use only a continuous, adequately stitched quiet return whose added capacitance is acceptable. |
| Congestion | Change access, topology, placement, or layer while charging added via/coupling cost. Return structurally asymmetric or unroutable placement to `analog-layout-align`. |

For pairs, prefer the shortest symmetric topology and minimal joint compensation in a quiet symmetric region. Require PEX to compare R, C, coupling, delay, and circuit performance.

## Required evidence

For each critical net record: class and intent; physical access/connectivity; total and per-layer length; directness, bends, branches, vias and widths; current/return-path basis; matching/environmental deltas; and unresolved DRC/LVS/ERC, reliability, PEX, or simulation checks. Ordinary nets may be summarized by class.
