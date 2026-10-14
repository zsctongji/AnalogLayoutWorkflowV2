# Marker ownership and diagnosis

## Evidence sequence

1. Bind the summary and result database to the exact target, deck/config fingerprint, and run timestamp.
2. Apply only explicit project/user waiver regexes. Preserve waived counts in the report.
3. Separate global counts, primary-cell markers, and generated/inherited cell results.
4. For every actionable marker, read its rule text, cell/hierarchy, polygon/bbox, and database units.
5. Query overlapping and nearby live shapes, vias, complete via landing metal, instances, and master/PCell geometry. Use net and route provenance tags when available.
6. Assign both an owner (`route-owned`, `placement-owned`, `PCell/inherited`, `pre-existing`, or `unknown`) and a cause before proposing a change.

## Cause classes

- Contact construction or enclosure
- Cross-net width/spacing/EOL/corner interaction
- Same-net notch, slot, re-entrant pocket, or width transition
- Via cut/enclosure, cut spacing, or forbidden stacked-via combination
- Active/poly/well/implant/tap/guard interaction
- Off-grid, malformed/non-simple polygon, stale result, or foreign geometry
- Density/OPC/antenna/reliability or another project-specific class

Do not infer a new diffusion contact from `thin`/active access alone; inspect whether the live PCell already provides connected source/drain landing metal. Do not infer via legality from origins or route centerlines; use the complete cut and landing envelopes.

## Repair and exit

Change only authorized owners. Read symmetric-repair.md before repair. For a matched structure, inspect and repair the mate even when only one side is marked, then recompute drawn matching metrics. Rerun the same DRC policy after saving. Waived findings remain WAIVED, never CLEAN; warnings/incomplete results still block closure.

## Executable mapping contract

`marker_geometry.py --report report.json --placements placements.json --snapshot snapshot.json --out NEW.json` performs explicit unit/orthogonal-transform mapping and bbox candidate queries. It does not infer a Calibre CN dialect or assign causal ownership automatically.

Snapshot: `target` and `objects`, each object containing stable `id`, `bbox_um` in top coordinates, `owner`, `net`, `layer`, `kind`, `provenance`. Include complete via cuts/landings, instance/master polygons and nearby objects needed for diagnosis. `route-owned` requires actual DB provenance (e.g. alrObjectId or a verified draftRouteId/manifest), not proximity or layer alone. A bbox intersection is only a candidate; inspect exact polygon interaction and rule before choosing the culprit.

Placements: `target`, `report_sha256` and `snapshot_sha256` using the module's canonical JSON digest; `dbu_per_um` must agree with the parsed result header; `transform_evidence` identifies the release-qualified RVE/bridge mapping evidence. `placements` is a list of:

- `marker_sha256`: canonical digest of the exact parsed marker, including raw CN.
- `instance_path`: complete root-to-leaf instance-name list (empty only for verified top-level geometry).
- `leaf_to_top_db_units`: one transform per level, applied leaf first. Each is `[a,b,c,d,tx,ty]`, meaning `(x',y')=(a*x+b*y+tx,c*x+d*y+ty)` in result DB units. Only unit orthogonal rotation/reflection is supported; divide by DBU-per-µm after composing. Path and transform order differ deliberately; the adapter must make both explicit.

Enumerate all verified occurrences for inherited markers; repeating a master cell name is not an instance path. Missing occurrence mapping stays UNRESOLVED. Unknown transforms, magnification, units or stale hashes must block edits. A successful transform is LOCATED_CAUSE_UNCLASSIFIED, not permission to edit and not evidence of DRC closure.
