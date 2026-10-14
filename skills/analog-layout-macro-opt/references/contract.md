# Offline contract and algorithm

All coordinates are microns. `grid_um` is the measured manufacturing grid. Inputs and output are JSON; finite numeric values only. Run with Python 3.10+ (standard library, no SciPy or commercial solver). Keep per-run data outside the skill directory.

## Snapshot v1

`schema`: `analog-layout-macro-opt.snapshot/v1`.

- `source`: exact `{lib,cell,view}` and optionally saved revision identity.
- `evidence`: references/hashes of actual live capture, placement intent, saved sharing/contact check, ring inventory, terminal access and PDK profile. Presence is checked; truth and freshness must be established by the adapter and agent.
- `grid_um`: positive measured grid.
- `macros`: unique `{id, anchor_um?}`. Anchor is the original world-coordinate physical symmetry/matching anchor, a two-number point. Omitted means full-object envelope center. Never silently substitute an asymmetric ring's center for the active-array matching axis.
- `objects`: unique `{id, macro, bbox_um, payload_sha256, ...}` for **every** top-level physical object and PCell instance. `bbox_um` is the measured outer envelope, including widths/path extents. IDs must be stable semantic capture IDs, not persistent assumptions about session DB pointers. Use kind/LPP/owner/shape-signature and collision-safe occurrence mapping for anonymous shapes. Labels with zero-area boxes require an adapter-computed conservative nonzero display envelope; record its basis.
- `source_object_ids`: independently captured complete physical inventory. Exact equality with the objects list is required. Logical net/terminal records are additionally captured in payload/connection metadata, not disguised as zero-area rectangles.
- `payload_sha256`: hash of the translation-normalized complete object payload: object kind, LPP, points/vertices relative to its anchor, width, PCell master and typed/evaluated parameters, orientation, net/terminal and pin ownership, via/ROD membership and relevant properties. Not merely a bbox hash. Recompute independently from live target readback; copying old hashes is not verification.
- `protected_sets`: `{kind,object_ids}` for each whole ring/ROD complex and each shared edge/chain, including its devices and any top-level owning shapes. All members must have one owner. Include each dummy in its functional module. Independently reconcile ring inventory and sharing report so omitted protected sets cannot silently weaken checks.
- `cross_macro_connections`: `[]` only after checking for existing inter-macro conductive wires, vias, common well polygons and stretched ROD dependencies. Nonempty or absent blocks the optimizer. Intent nets connecting separate unrouted ports are not existing physical wires.

Derive macro envelopes from objects, not guessed dimensions. A capacitor's nwell and other generated geometry are already inside its measured PCell envelope. ROD parent/children may have overlapping envelopes; preserve ownership, but the materializer must not move a child twice.

## Request v1

`schema`: `analog-layout-macro-opt.request/v1`; `snapshot_sha256`: `digest(snapshot)` from the script (canonical sorted compact JSON, default ASCII escaping).

- `bounds_um`: allowed global rectangular search region. This is a user/project planning constraint, not a process rule. Negative coordinates are supported. Fixed external obstacles must be represented as complete locked macros.
- `pair_gaps`: exactly one `{macros:[a,b],x_um,y_um,basis}` for every unordered pair, including passives/obstacles. Values are required nonnegative envelope gaps. A valid pair must separate in x OR y by the relevant amount. Derive them conservatively from all applicable well/implant/active/routing rules and explicit escape/channel reservation. `basis` distinguishes foundry rule/profile from exploratory planning policy; neither supplied strings nor bbox checking certify DRC. Missing entries block; zero must be deliberate. Directional/nonrectangular/channel-topology rules need a reviewed adapter, not extra ignored keys.
- `align`: `[{axis:"x"|"y",macros:[...]}]`, equal physical anchors in the named coordinate; alignment does not itself prescribe order.
- `mirror`: `[{axis:"x"|"y",coordinate_um:number,pairs:[[a,b],...]}]`. Axis x means reflection about the vertical line x=coordinate; anchors have opposite equal offsets and equal y. Axis y is analogous. Line coordinates are fixed in v1. Translations only: no macro reflection is performed. The caller must establish reflected internal payload/pin equivalence if claiming full mirror symmetry. For a self-symmetric core stack use align; no fabricated partner or duplicated device.
- `order`: `[{axis,before,after,gap_um}]`, strict edge order with specified gap; independently enforce pair clearance too.
- `locked`: macro IDs whose absolute positions remain fixed.
- `nets`: optional `[{id,pins:[{island_id,macro,xy_um}],weight?,max_hpwl_um?}]`. Original world-coordinate access points must be selected from freshly measured physical pin islands; keep one selected point per required island. Default weight is 1. Hard max span is optional and circuit-specific; use baseline limits where regression is not permitted. All moved points translate with their owner. HPWL is not actual routed wirelength or parasitic delay. If omitted, HPWL is null, not zero quality risk; materialization requires separate access review.
- `search`: positive integers `max_evaluations,max_iterations,beam_width,top_k` and positive grid-multiple `step_um`. These are computational limits, not manufacturing numbers. Unknown request/constraint keys fail.

## Search

Before neighbor-step search, supported total orders receive forward/reverse whole-stack seeds; see `gap-budget.md` for eligibility and channel-budget review. Seeds consume the same evaluation budget and must pass the unchanged full validator. Output includes `ordered_compaction_seeds_evaluated`, `baseline_ordered_gap_audit`, and per-candidate `ordered_gap_audit`. These report axis-envelope slack, not layer-level DRC or routing feasibility.

Compile alignment and pair symmetry into affine movement components, separately for x/y. Propagate sign and offset relationships; conflicting cycles or locks block. Move a whole connected component with one root parameter. Source-phase grid snapping and the independent validator prevent half-grid/off-grid translations. Incompatible grid/symmetry returns no candidate rather than weakening equality.

Proposals include neighbor-envelope edge anchors, boundary anchors, coordinate alignment anchors and local steps. Beam states may be invalid during exploration; they are ranked by number of violations before area and weighted HPWL. Only independently validated complete layouts appear as output candidates. This is a bounded heuristic and can become trapped. It does not exhaust aspect ratios/topologies, optimize ring interiors, or guarantee a global optimum. Hard-valid baseline is retained as a fallback; no improvement is reported honestly. Fixed bounds and budgets control runtime.

CLI: `python scripts/macro_opt.py --snapshot macro-snapshot.json --request request.json --out new-run`

Output `candidates.json` has baseline metrics/failures, source/request hashes, status, evaluations, stop reason, rejected-check counts and up to Top-K valid candidates. Each candidate has all macro positions, deltas, full object moves with payload hashes, area delta and net HPWL. SVGs show **macro envelopes**, not a layer-accurate layout. Macro-envelope occupancy may exceed 1 for an invalid overlapping baseline; it is not active silicon utilization.

`verify_translation(source,target,candidate)` independently checks normalized IDs/count, move coverage, one delta per macro, translated bboxes and immutable payload hashes. The live adapter must also verify protected-set membership, terminal/net records, shape signatures, source/request hashes and candidate feasibility; the function is not a full OA/ROD or electrical verifier.
