# Global floorplan review

Use when reviewing an existing layout or when locally symmetric groups still produce
long connections, a stretched envelope, or extensive empty space.

- Read the exact live target without mutation. Reconcile its complete instance
  inventory, masters, orientations and bboxes with the source intent before using
  intent connectivity. The offline optimizer checks snapshot identity; the live
  closure summary alone is not a parameter or schematic-equivalence check.
- Separate all-PCell bbox, routed geometry bbox and active device area. Include
  capacitors/resistors and dummies in the envelope. Report bbox occupancy as a
  geometric proxy, not silicon utilization or a mandatory density target.
- Trace critical nets across functional groups. Attribute long spans to the actual
  terminal islands and group locations; do not call every long supply net critical.
  Passive/output arrays belong in the connectivity-driven floorplan, not
  automatically at the far right. The current legalizer's right-hand shelf is only
  an initial seed; it is not an optimized result.
- Preserve valid common centroids and dummies. Prefer moving whole peripheral
  groups before redesigning matched arrays, changing fingers, or sharing diffusion.
  Source sharing still needs its separate PDK evidence.
- A routed target may have top-level nets. Do not apply the placement-only
  zero-net criterion as a routed-layout error. Conversely, zero top-level terminals
  means hierarchy-facing pin completion remains unverified, not that nets are open.
- Missing bulk figures, well/tap/guard context and dummy-edge equivalence remain
  unknown without appropriate physical/PDK evidence. D/G/S symmetry is insufficient.

## Coarse-to-fine candidate search

The existing optimizer now accepts optional positive
`search.macro_relocation_gap_um`. Supply a reviewed planning gap and explicit
`constraints.critical_net_weights`; no automatic net-name/rail heuristics.
It tries four side-adjacency anchors around units sharing a positive-weight net,
then retains ordinary local translations. Coarse proposals move peripheral rigid
units only, preserve core macros, include owned dummies, and honor locks.
Grid snapping may slightly change the planning gap; it is not a spacing guarantee.
All candidates still pass the independent grid, overlap, identity, common-centroid,
access and declared-channel checks. Bounds/keepouts must be supplied when relevant.
These moves require rerouting: never translate devices beneath frozen existing wires.

Search ranks unknown channel evidence over a fixed obligation set:
`unknown_declared_channels` counts explicit channel demands with unknown capacity.
`unknown_channels` remains the count of all observed unknown gaps for reporting.
Its changing population must not implicitly reward spreading/removing adjacencies.
Known-to-unknown access/declared-demand regressions remain protected.

Compare candidates against the same baseline and pin-island model. Report unknown
access/capacity, increased net-envelope intersection, and omitted supplies explicitly.
A lower HPWL/area result is a candidate, not proof of routing, RC, bandwidth, DRC or LVS.
`GLOBAL FLOORPLAN REVIEW REQUIRED` is a screening result; its
`needs_refinement: null` means the decision needs circuit-specific review, not pass.
