# Controlled, symmetry-preserving repair

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

Use this only for user-authorized repair, never for analysis-only requests. `symmetric_repair.py` is a Python API with a pure `check(snapshot, plan)` gate and `execute(plan, adapter)` transaction protocol. No concrete Virtuoso writer or automatic repair search is installed by this update. Missing site adapter or any unknown verification gate means stop; never bypass the gate with direct SKILL writes.

## Non-negotiable symmetry boundary

One Calibre marker does not define the edit scope. Start from the full, hash-bound layout symmetry inventory, including unmarked mates, actual metal and via-cut geometry, common-axis constraints and functional branch boundaries. Preserve net identities and matched device roles. A pair group maps two different nets; self maps one net. Dual-sided same-net collection is not a whole-net pair relationship between two different nets.

Repair both corresponding objects together, even if one side was initially legal. If a mate is absent, moving it would create another violation, or it lies outside authorized scope, return a conflict rather than make a one-sided edit. Actual metal/cut layer, geometry, width/enclosure and positions must reflect about the frozen axis. Equal total length or via count is insufficient. Do not add dummy metal, delete a symmetry group, enlarge tolerance, swap nets, split a long illegal move into short edits or silently downgrade matching scope.

Asymmetric reference/output/additional branches must have a source-snapshot exception with reason, approval and exact boundary. Even approved exceptions do not waive DRC or the surrounding matched core. For matched-only groups, explicitly retain the branch endpoint mapping and comparative metrics in the site verifier; the rectangle mirror gate is not a substitute for branch matching, RC or environment checks.

## Snapshot and plan

The snapshot contains:

- exact `target: {lib,cell,view}`;
- full in-scope `objects` with unique stable `id`, `owner`, `net`, `kind`, and `metal`/`cuts` lists. Each geometric element is `{layer,bbox_um:[[x0,y0],[x1,y1]]}` in top-level µm. Include actual via arrays/landing rectangles, not just origin and nominal type;
- `symmetry_groups`: `{id,mode:"pair"|"self",axis_x_um,object_pairs:[[left_id,right_id],...]}`; pair additionally has `net_pair:[left_net,right_net]`. A self-mirrored axis object may map to itself;
- `scope_by_object`: every object ID → exactly its group ID or exception ID;
- `exceptions`: exception ID → `{reason,approval,boundary}`.

The plan contains canonical `snapshot_sha256`, exact `source`, a distinct new `target`, recorded `authorization`, `authorized_object_ids`, optional `authorized_exceptions`, `drc_policy_sha256`, and `edits:[{id,before_sha256,after}]`. `after` is the complete normalized object. The current kernel only updates existing route-owned objects; it rejects creation/deletion, net/identity/owner/kind changes and non-route geometry. A separate authorized workflow is required for device/guard/pin/placement changes.

The pure gate rejects stale plans, incomplete scope inventories, duplicate edits/mates, one-sided edits, unknown exceptions, net changes and post-edit mirror mismatches. It uses fixed nanometre-fraction numeric normalization (1e-9 µm), not a tunable design tolerance. Current geometry comparison requires matching rectangular partitions; equivalent differently partitioned polygons may be conservatively rejected. General polygon-union checking is not implemented; unsupported geometry must not be simplified into a false PASS.

## Trusted adapter protocol

`execute` invokes these adapter methods in order:

1. `snapshot(source)` obtains a fresh, full normalized snapshot. `exists(target)` must reject any existing destination, open editor or conflicting lock.
2. `begin_clone(source,target)` creates an isolated transaction without changing the source. `read(transaction)` must reproduce the complete source inventory and constraints before editing.
3. `apply(transaction, edit)` changes only the authorized object. All edits in a pair/self group belong to this one transaction.
4. `read(transaction)` must equal the expected full after-inventory, not just the edited IDs; unchanged objects and the symmetry/exception inventory must remain unchanged.
5. `verify(transaction,before,after)` must actually check connectivity, pin_access, pdk_geometry, matched_metrics and environment. Return those keys as PASS only with retained measured evidence and reports; also bind `before_sha256` and `after_sha256`. UNKNOWN or FAIL blocks commit. This site verifier must check both sides' new-old/new-new geometry, same-net and cross-level cut spacing, full enclosures, direction, short local M1, branch lengths/widths/vias and neighbor exposure. No PEX means no claim of equal parasitics.
6. `commit(transaction)` saves only the new target; an exception before successful commit calls `rollback(transaction)` for the entire group. The adapter must implement reliable recovery and must not mutate the original source.
7. `snapshot(target)` independently reopens saved data and compares it; `snapshot(source)` confirms the source is unchanged.
8. `rerun_drc(target)` runs the bound runner with unchanged DRC policy and returns `policy_sha256` and `saved_snapshot_sha256` as well as runner results. Only CLEAN with bound provenance and no integrity issues closes the DRC loop. WAIVED/incomplete/nonzero results yield SAVED_NOT_CLOSED. Retain the new saved draft for diagnosis; do not pretend it was rolled back after commit.

Adapters are trusted code reviewed for the active CAD version, not boolean success flags supplied by the repair plan. Store their implementation identity and evidence in the run. This core does not infer topology ownership or implement a PDK rule solver. One invocation performs one bounded transaction; repeated repairs require fresh markers/snapshots and renewed plans. Stop on failed verification, no progress or a symmetry/PDK conflict; do not retry indefinitely.

## Regression obligations

At minimum test: only-left marker with paired repair; missing mate; one-sided edit rejected; unequal widths/layers/cut arrays rejected; same-net self pair; axis object; immutable asymmetric exceptions; protected PCell/guard/pin refusal; clone/readback drift; failure rolls back both sides; saved readback mismatch; changed DRC policy; changed source; unbound/waived rerun cannot close. Synthetic adapter tests are not live Virtuoso/Calibre qualification.
