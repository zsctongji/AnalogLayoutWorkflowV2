# Inputs, algorithm and capability boundaries

First read the sibling `analog-layout-macro-opt/references/contract.md`. Use its v1 snapshot unchanged; object payload hashes must cover complete content, rather than only bboxes. All quantities use µm. Physical matching anchors must be explicit and justified; the default bbox center applies only to macros for which equivalence of the two has been established.

## symmetry request/v1

```json
{
  "schema": "analog-layout-macro-symmetry.request/v1",
  "base_request": {"schema": "analog-layout-macro-opt.request/v1"},
  "axis": {"coordinate": "x", "value_um": 0, "basis": "existing core axis, measured capture reference"},
  "start_um": 0,
  "orders": [[["core1"], ["core2"], ["left", "right"]]],
  "excluded_macros": {}
}
```

The example `base_request` is a positional placeholder. Replace it with a complete macro-opt request: snapshot hash, bounds, all pair_gaps/basis, existing align/mirror/order/locked constraints, critical-net pins/span limits and valid search fields. The script uses prepare/evaluate from that request without running beam search, so search budgets do not affect this skill's results. Do not use the example directly as a valid request.

`orders` is a list of candidate row orders. Each row contains one self-symmetric macro or two qualified mirrored macros (left/right or bottom/top). Every in-scope macro must appear exactly once. Explain every out-of-scope object in `excluded_macros` and lock it in base_request.locked; these objects still participate in spacing, area and obstacle checks. Peripheral exemptions invalidate a claim of whole-layout axis symmetry.

`start_um` is the orthogonal lower bound for each row's leading edge, rather than the other coordinate of the symmetry axis. Algorithm: compact sequentially along the common axis, considering the complete bboxes of all earlier rows and pair gaps; align the orthogonal components of physical anchors within each row and place paired anchors at equal distances from the common axis. Apply grid-realizable translations only, without changing orientation. Conflicts with existing locks/order/bounds/span constraints return rejected; do not silently discard constraints. The algorithm does not search arbitrary topologies around fixed obstacles; explicitly supply alternative row orders/start values in the request. It does not guarantee optimality, and an empty candidate set does not prove infeasibility.

Output candidates.json contains the axis, original hashes, baseline, coordinates/full-object move list for each candidate, complete dimension/area changes, net spans and errors. The SVG shows macro outlines only, rather than actual layer geometry. Candidate `metrics.valid` means only that existing geometric planning constraints passed; inspect `geometry_audit` and routing_status separately.

## Optional geometry field

Bind snapshot_sha256 and nonempty `evidence` to actual flattened captures and check records. `source_figure_ids` is the complete flattened figure-ID inventory obtained independently from the database.

`figures` entries:

```json
{"id":"unique-flat-figure", "object_id":"parent-instance-or-shape-id", "macro":"core1", "lpp":["metal1","drawing"], "points_um":[[0,0],[1,0],[1,1],[0,1]]}
```

All points use source-layout world coordinates. Expand actual PCell layer geometry under the corresponding instance, including vias and contacts. Convert ring paths reliably into actual finite-width polygons instead of supplying centerlines or bboxes. Compound shapes and shapes with holes require a validated, consistent polygon decomposition. Without a reliable adapter, omit geometry and report UNKNOWN. The script handles simple polygons only; do not force unsupported curves/holes into this representation.

`excluded_annotation_ids` may exclude nonphysical annotations explicitly marked `kind: label` in the snapshot; they remain in the move list. All other objects require figure coverage. The adapter must verify object-to-figure completeness item by item against evaluated masters and the raw inventory. Complete fields are not live evidence. Do not exclude electrical pins, wells or missing layers as annotations.

The reflection audit compares multisets of LPP + polygons normalized by vertex cycle, including reversed vertex order. Coordinates only remove floating-point tails to nine decimal places; artificially increasing tolerance is forbidden. Preserve duplicate-figure counts. Equivalent geometry with different segmentation may conservatively fail and require additional union review. The script does not compare nets/device roles; supplement it according to routing-handoff.md. A geometric pass does not automatically yield READY. An agent must still review all source/master/flatten evidence for freshness, completeness and trustworthy provenance.

## Verification and materialization

Run `python -m unittest discover -s tests -v`. Tests use synthetic data and do not establish PDK qualification or live testing of the current V8. The script does not connect to EDA. For materialization, follow the macro-opt skill's materialization guidance, preserve the complete post-ring cellview and all logical associations, and reread actual geometry to verify the axis and pin islands.
