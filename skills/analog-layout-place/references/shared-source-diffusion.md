# Same-net source diffusion sharing

Default policy: `same_net_same_module`. Same nonempty net and same functional module authorize implementation, including central edges and chains. Use `evidence.eligibility_policy: same_net_same_module`; require measured construction geometry/contact coincidence, but perform continuity, no-short and overlap-isolation checks after saving. Do not require a prior pair fixture, probe hash or electrical verification booleans. Pending checks must remain pending. The strict prequalification fields below describe legacy operations without this policy; they are not prerequisites under the default simplified policy.

Use this mode only for adjacent MOS instances whose `S` terminals are explicitly on the same net. Sharing is a PDK-backed PCell abutment with coincident source contact cuts that preserves both device identities. A device may share one source edge on each side in a chain; it never rewrites the schematic or treats touching bboxes as electrical proof.

## Required evidence

- same `nmos` or `pmos` kind and the same PCell master;
- exact source-net equality from the placement intent;
- a live-PDK pair probe or equivalent project-qualified source for orientations, abutment parameters, evaluated origins, and bboxes;
- the active PDK fingerprint;
- the content hash of the pair-probe artifact;
- verified shared-source continuity and verified absence of unintended source-to-drain or drain-to-drain shorts;
- nonempty, cut-for-cut coincident world-coordinate source contact arrays on the same PDK contact layer, plus contact landing metal and enclosure checks;
- confirmation that wells, taps, implants, contacts, matching environment, and later terminal access remain valid.

Do not infer `leftAbut`, `rightAbut`, `connectSD`, orientation, or pitch values. Put measured values in the per-run refinement spec.

Run `scripts/shared_source_candidates.py --intent <placement-intent.json> --out <candidates.json>` first. It reports pairs with the same S net, MOS kind, and PCell master, but labels every result `REQUIRES_PDK_PAIR_PROBE`; discovery alone never authorizes abutment.

## Refinement operation

Use schema `analog-layout-place.refinement-spec/v1`. The values below show structure, not PDK recommendations:

```json
{
  "op": "share_source_diffusion",
  "id": "source_pair_0",
  "instances": ["M0__M0", "M1__M0"],
  "net": "VSS",
  "axis": "x",
  "placements": [
    {"name": "M0__M0", "origin": [0, 0], "orientation": "R0", "bbox": [[0, 0], [1, 2]], "pcell_parameters": {"rightAbut": "measured-value"}, "pcell_parameter_types": {"rightAbut": "string"}},
    {"name": "M1__M0", "origin": [0.5, 0], "orientation": "MY", "bbox": [[0.5, 0], [1.5, 2]], "pcell_parameters": {"leftAbut": "measured-value"}, "pcell_parameter_types": {"leftAbut": "string"}}
  ],
  "evidence": {
    "source": "live PDK pair probe artifact",
    "pdk_fingerprint": "sha256:...",
    "pair_probe_sha256": "sha256:...",
    "abutment_geometry_verified": true,
    "terminal_continuity_verified": true,
    "no_ds_short_verified": true,
    "source_contact_overlap_verified": true,
    "contact_layer": "PDK contact/drawing LPP",
    "source_contacts_um": {"M0__M0": [[[0.6, 0.4], [0.7, 0.5]]], "M1__M0": [[[0.6, 0.4], [0.7, 0.5]]]},
    "expected_bbox_overlap_um": 0.5,
    "overlap_isolation_verified": true
  }
}
```

The coordinates above illustrate JSON shape only; never copy them into a design. The operation rejects missing/duplicate instances, different S nets, different kinds/masters, unsourced evidence, wrong edge spacing, missing or split contact arrays, and contact cuts outside either instance bbox. A PDK probe may establish `expected_bbox_overlap_um` for the intended shared source region. Require `overlap_isolation_verified=true` after inspecting gate/drain/isolation geometry. One instance may join at most one edge per physical side, with a consistent full placement and PCell parameter set across both operations. Other positive-area bbox overlaps remain forbidden; materialized readback must show precisely the declared edge overlaps and measured depth.

## Closure

Require `validation.shared_diffusion_complete == true`, remeasure changed PCells, materialize only into a new authorized view, and verify parameters, orientations, bboxes, and **actual saved cont cuts** by readback. The generic placement importer does not currently read contact figures; extract them separately from Virtuoso for every shared edge and compare to the probe arrays. Then run foundry DRC, LVS, extraction, and relevant matching/current checks. Downstream routing must consume freshly extracted physical pin islands because source access geometry may change.
