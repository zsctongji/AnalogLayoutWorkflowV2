# Controlled LVS repair

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

## Triage before editing

| Finding | Required causal evidence | Permitted bounded response |
|---|---|---|
| Self-comparison, wrong top, stale source, wrong map | Export/run provenance | Correct run-local config and re-export; no layout change |
| Missing/wrong port | Schematic terminal, extracted connected island, OA pin and label LPP | Create/replace pin on its proven conductor, correct port metadata; never merely relabel a wrong net |
| Open | One intended net split into independently extracted islands, mapped endpoints | Add short legal metal/via connection between those islands, reject other-net contact |
| Short | Two distinct source nets merged in extracted layout, mapped bridge geometry | Remove/trim/reroute the proven route-owned bridge, preserve all intended endpoint reachability |
| Missing/extra device | Hierarchical device map, m/nf/reduction/filter and source export audit | Diagnose first; never delete MOS/dummy to make counts agree |
| W/L/model/bulk discrepancy | CDF/export scale, actual PCell and foundry extraction map | Correct proven export mistake; resizing/replacing device or changing body topology requires separate approval and workflow |
| Soft connection/well/tap issue | PDK connectivity and actual body/ring network | Escalate protected well/implant/ring edits; same bbox or same type does not prove same net |

Normalize each discrepancy into a project record: ID/category, run/report hash, full source and layout paths, extracted net/device IDs, terminal roles, coordinate unit/transforms, candidate OA owners, and evidence establishing or refuting each cause. Unknown ownership, unsupported transforms or ambiguous correspondence blocks editing. Do not infer physical short/open solely from a net-name mismatch. Resolve invalid inputs first, then connectivity/ports, then residual properties. Keep policies unchanged between baseline and candidate comparisons.

## Plan and snapshot contract

`lvs_repair.py` is a Python API (`check(snapshot,plan)` and `execute(plan,adapter)`) plus a non-mutating preview CLI:

`python scripts/lvs_repair.py --snapshot snapshot.json --plan repair.json --output new-preview.json`

Snapshot fields:

- `target:{lib,cell,view}`, `objects` (complete normalized repair-scope inventory), `protected` (full device/placement/shared-active/ring/reference invariants or canonical digest records).
- Each object: `{id,owner,kind,net,metal,cuts}`; owner `route-owned` or `pin-owned`, kind `metal`, `via` or `pin`; each geometry entry `{layer,bbox_um:[[x0,y0],[x1,y1]]}` in top-level micrometres. All via cuts and enclosures must be included. Other immutable metadata is retained verbatim. Arbitrary polygons/curves are unsupported and must not be replaced with a bbox approximation.
- `slots`: reserved IDs for missing route/pin objects, containing the same identity keys but no geometry. These are evidence-derived repair candidates approved in the snapshot, NOT presumed objects in the OA DB. Existing IDs and slots cannot overlap.
- `groups:[{id,axis_x_um,net_pair:[leftNet,rightNet],pairs:[[leftID,rightID],...]}]`: distinct nets for differential pairs, equal nets for common-net dual sides; axis self-object maps to itself. Pairs may include a reserved missing mate. Complete scope mapping covers each existing object/slot exactly once in a group or approved exception.
- `exceptions:{id:{reason,approval,boundary}}`, `scope:{objectID:groupOrExceptionID}`. Freeze these in source evidence; the plan cannot remove a group, shift axis or grant itself an exception. Unrelated objects outside rectangular scope remain protected and are verified by the adapter.

Plan fields:

- `source`, distinct `target`, `snapshot_sha256`, `authorization` (record of actual user request, not manufactured approval), `authorized_ids`, `authorized_exceptions`.
- `baseline_sha256`, `reference_sha256`, `lvs_policy_sha256`, `drc_policy_sha256`: canonical evidence bundle digests. A source netlist hash must cover its include/config provenance, not only its root text.
- `findings:[{id,category,evidence,expected_delta}]`. Category is `open`, `short` or `port` in this engine. Evidence/expected_delta are nonempty structured records. They must identify authoritative terminal IDs, before-island membership, desired joined/separated terminal sets and protected relations; prose alone is not a verified graph delta.
- `edits:[{id,op,before_sha256,after,finding_ids}]`, op `create|replace|delete|verify`. `create` uses a reserved slot and null before hash; delete has null after; others bind full old object hash. `verify` explicitly includes an unchanged mate. A pin edit also needs `authorize_pin_edits:true` tied to user scope. Retain intended net IDs even when existing physical extraction is wrong: extracted connectivity is separate evidence, not an excuse to change intended net labels.

The pure gate checks identity, authorization coverage, immutable fields, protected snapshot, pair coverage and final exact-partition rectangle/cut symmetry. It does NOT solve connectivity or DRC. A preview `PLAN_VALIDATED` is not approval to write. Equivalent differently partitioned polygons may conservatively fail. The adapter returns objects sorted by stable ID after edits. Consumed creation slots disappear; deleted objects become identity-only absent slots so the frozen group/scope inventory remains intact. A later repair needs a newly bound plan, not reuse of the previous baseline.

## Trusted site adapter

Adapter code must be reviewed for the current CAD/PDK, with implementation hash retained. Do not accept plan-supplied PASS flags or bypass with ad-hoc SKILL. Read `operate-virtuoso-bridge` for live access and `analog-layout-drc` for the actual DRC run.

1. `snapshot(source)` returns fresh full normalized scope and protected state. `validate_baseline(plan,snapshot)` returns a receipt bound to the snapshot and all four plan fingerprints, with status `BOUND_MISMATCH` and evidence references. It must check real immutable files, independent extraction, complete results and causal ownership. Unknown warnings impacting extraction block geometry repair. `exists(target)` includes library/path aliases, editor buffers and locks.
2. `begin_clone(source,target)` creates isolated target/transaction without changing source, and either returns a handle or cleans partial creation on failure. `read(tx)` returns full snapshot. `apply(tx,edit)` resolves actual OA objects by stable path/geometry identity; no ID substring search. Duplicate writes and stale originals fail.
3. `verify(tx,before,after,plan)` actually checks expected graph delta and absence of unintended shorts/opens, G/D/S/B and port reachability, PDK legality, pin access, frozen symmetry, matched metrics and environment. It returns `checks` PASS for `expected_delta`, `no_unintended_connectivity`, `pdk_geometry`, `pin_access`, `matched_metrics`, `environment`, plus before/after hashes and evidence references. PDK directions remain those of the routing handoff (e.g. odd vertical/even horizontal), not a new LVS-specific rule. No PEX means no claim of matched parasitics.
4. `commit(tx)` saves only target; `rollback(tx)` must recover the entire target transaction after precommit/commit exceptions (including partial saves) without touching source. A transaction cannot be qualified until this behavior is tested. A postcommit validation failure retains target with `SAVED_NOT_CLOSED`, not a false rollback claim.
5. Independently `snapshot(target)` and source-readback after save. `rerun_lvs(target)` and `rerun_drc(target)` use fresh outputs and return status, `saved_snapshot_sha256`, `policy_sha256`, `integrity_issues`, `evidence`, `bound:true`; LVS also returns `reference_sha256`. `bound` is an adapter result backed by checked artifacts, not sufficient user-authored evidence. New top/output paths are run identity, not changes to the normalized electrical/DRC policy.
6. Full saved/source readback after reruns detects concurrent drift. Only `VERIFIED_MATCH` + `CLEAN` with unchanged reference/policies and complete evidence returns `REPAIR_CLOSED`. Otherwise retain the draft as `SAVED_NOT_CLOSED`; report whether failures are residual, regressed or unverified. Baseline DRC violations/waivers cannot be hidden: improved LVS may be delivered as partial progress but never joint closure.

One transaction is the default bound. For subsequent iterations use a fresh snapshot/run and explicit continuing scope; stop on failed gate, no progress, new unintended connectivity, source drift or a repeated root cause. A lower aggregate discrepancy count is not proof that the targeted fault was repaired. Do not silently retry by loosening matching or relaxing symmetry.

## Qualification boundary

The included simulated adapter tests exercise gates, paired operations, readback, rollback and dual-verifier closure. They do not implement or qualify a generic Virtuoso writer. Before first live use, test the site adapter in a user-authorized scratch cell with deliberately introduced open/short/pin faults; verify original unchanged, correct paired repair, full rollback and bound Calibre results. Until then output a plan and the exact missing capability, not a claim that the layout was repaired.
