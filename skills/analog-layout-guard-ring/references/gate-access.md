# Gate contact prerequisite

This gate is required **before ring planning and generation**, for P+ and N+ rings and all adapters. Read the exact live source, not an old placement screenshot. Enumerate G pin islands for every selected MOS, including each m-copy and dummy. Do not infer contact completion from `gates_without_metal_access` alone: a poly-labelled pin may already reach a valid top-level contact, while a metal-labelled pin may lack verified gate continuity.

For every island require fresh evidence of:

- actual gate conductor → actual PDK contact cut → actual metal landing, with the schematic G net preserved;
- contact dimensions, enclosure, spacing, gate/source/drain isolation and grid checked against the active PDK;
- metal landing and a legal short local escape, including space for the next qualified via when needed, clear of the proposed ring;
- exact contact/landing object IDs and their full access/escape envelope, with a review artifact identifying the live geometry and rule checks. A planned PO1_M1 or a `connectGates` parameter value is not evaluated geometry evidence.

Multiple pin islands may belong to one proven continuous gate conductor. One existing contact may cover them all **only when the continuity evidence explicitly covers every island**. Do not force two contacts on opposite ends of a finger, duplicate existing contacts, or waive unmatched islands. Missing G access, unresolved net, poly-only/no-contact, stale evidence, or any failed legality check blocks generation. Do not use a boolean `gate_ready=true` as a substitute for the inventory.

## Inputs and checker

```text
python scripts/check_gate_access.py --intent placement-intent.json --terminal-access terminal-access.json --review gate-contact-review.json --source-lib LIB --source-cell CELL --source-view layout --instances M0 M1 --out gate-access-check.json
python scripts/plan_guard_ring.py --intent placement-intent.json --reference reference.json --request request.json --terminal-access terminal-access.json --gate-review gate-contact-review.json --out ring-plan.json
```

`terminal-access.json` uses `analog-layout-align.terminal-access/v1`. The review uses `analog-layout-guard-ring.gate-contact-review/v1` with:

- `target`: exact source `{lib,cell,view}`;
- `intent_sha256`, `terminal_access_sha256`: `check_gate_access.content_hash` (sorted compact JSON, ASCII escaping);
- `layout_snapshot_sha256`, `pdk_fingerprint`: nonempty provenance references; the live adapter must independently compare them with the current source/profile immediately before writing;
- `records`: each `{instance, net, covered_island_ids, contact_object_ids, metal_landing_object_ids, metal_layer, access_bbox_um, verification_source, continuity_verified, pdk_legality_verified, local_escape_verified}`. The three verification fields must be actual JSON `true`, backed by the named review. All ID lists are nonempty and unique. `access_bbox_um` encloses the complete contact, metal landing, poly extension and reserved legal local escape in world µm, not merely the contact center. `metal_layer` comes from the live PDK, not a hardcoded layer name.

The checker verifies source/hash binding, complete G inventory/net coverage and evidence completeness. It **does not** perform contact extraction or rule-deck qualification; evidence assertions must describe completed checks. It cannot turn fabricated/stale provenance into physical proof. The planner includes these access envelopes when sizing the ring. Guided adapters must do the same and check actual access-to-ring clearance on all relevant layers; PCell bbox clearance alone is insufficient.

When blocked, preserve a diagnostic report and return to an explicitly authorized placement/contact-access repair. This skill does not gain permission to repair gates from a request to create a guard ring. After repair, regenerate access, contact evidence and ring plan; never reuse the pre-repair hashes. This gate is not DRC/LVS signoff and does not certify full signal routing.
