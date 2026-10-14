# Reuse the placement-only workflow

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

Use the same Python environment that can import `virtuoso_bridge`. Run the bridge CLI `status` first and require `[daemon] OK` plus a successful `eval "1+2"` round trip.

## Produce a target-PDK placement intent

```powershell
$flow = "<skill-dir>\scripts\placement_flow.py"
$python = "<analog-agents>\.venv\Scripts\python.exe"
$work = "<output-dir>"

& $python $flow snapshot --work $work --lib <source-lib> --cell <source-cell>
& $python $flow build --work $work --top <source-cell>
```

At this point, inspect `plan/intent.json`, `plan/device-copies.json`, `plan/copy-groups.json`, and `plan/dummy-associations.json`. Correct classification before continuing.

ALIGN is optional evidence for relative planning and must stop after placement:

```powershell
& <align-python> $flow place --work $work --align-repo <ALIGN-repo> --python <align-python> --pdk <mock-pdk>
```

If the mock generator cannot represent an otherwise valid ratioed unit group, retain that limitation in `align-status.md`; do not change device dimensions, fingers, or nets to make the mock run pass.

Measure the actual PCells and produce the authoritative target-PDK v2 intent:

```powershell
& $python $flow measure-pcells --work $work --probe-lib <source-lib> --probe-cell <source-cell>
& $python $flow legalize-pcells --work $work --device-gap 0.5 --macro-gap 5.0
```

The gaps are planning inputs, not foundry rules. Review `plan/placement-intent.json`, `plan/placement.svg`, and all validation fields before writing Virtuoso.

## Materialize a new Virtuoso layout

The user must name the destination. It must not exist.

```powershell
$apply = "<skill-dir>\scripts\apply_placement_intent.py"
$intent = "$work\plan\placement-intent.json"
$report = "$work\plan\virtuoso-placement-verification.json"

& $python $apply $intent --env <virtuoso-bridge\.env> `
  --lib <target-lib> --cell <new-target-cell> --view layout --report $report
```

The command creates PCells and annotations in one unsaved transaction with one save at the end of the placement skill. It creates PCells plus non-electrical `D/<net>` annotations by default, saves the new view, and immediately performs readback. It fails if the target already exists or if instance identity, master, origin, orientation, bbox, annotation, overlap, or placement-only top-level counts do not pass. Add `--no-annotate-drains` only when an annotation-free target is explicitly required.

To audit an already created view without changing it:

```powershell
& $python $apply $intent --env <virtuoso-bridge\.env> `
  --lib <target-lib> --cell <target-cell> --view layout --report $report --verify-only
```

The explicit form of the default annotated import is:

```powershell
& $python $apply $intent --env <virtuoso-bridge\.env> `
  --lib <target-lib> --cell <new-target-cell> --view layout --report $report `
  --annotate-drains
```

To add them to an existing, unannotated placement that passes readback:

```powershell
& $python $apply $intent --env <virtuoso-bridge\.env> `
  --lib <target-lib> --cell <target-cell> --view layout --report $report `
  --annotate-only
```

The target must not be open in a layout window. The annotation mode creates one tagged label per MOS at the transformed PCell D-pin center. It does not create connectivity. Default `--verify-only` expects the labels. Use `--verify-only --no-annotate-drains` for a deliberately unannotated target.

## Close and refine an existing placement

Extract real pin access without modifying the layout:

```powershell
$analyze = "<skill-dir>\scripts\analyze_placement.py"
$closure = "<output-dir>\closure"

& $python $analyze $intent --env <virtuoso-bridge\.env> `
  --lib <target-lib> --cell <target-cell> --view layout --out $closure
```

Review `terminal-access.json`, `placement-closure.json`, and `net-routability-report.md`. If structural refinement is justified, write a per-run `refinement-spec.json`; keep all circuit names, coordinates, revision names, and parameter choices in that file. Apply it deterministically:

For routing, consume `nets[].physical_accesses` or `instances[].terminals[].pin_islands`, not only the compatibility field `selected_center`. Every physical island on a net included in a routing intent must be named by `pin_island_id` or covered by a validated contact landing.

```powershell
$refine = "<skill-dir>\scripts\refine_placement_intent.py"
$child = "<output-dir>\placement-intent-refined.json"
$delta = "<output-dir>\intent-delta.json"

& $python $refine $intent <refinement-spec.json> $child --delta $delta
```

Project the measured parent pin figures onto the child placement before creating a new view:

```powershell
$project = "<skill-dir>\scripts\project_intent_metrics.py"

& $python $project "$closure\terminal-access.json" $intent $child `
  "<output-dir>\pin-access-projection.json" --spec <refinement-spec.json>
```

For manual refinement the agent authors the spec from closure evidence. For automatic offline
search use the optimizer below. A projected improvement is not a Virtuoso result. Measure any
changed PCell geometry, materialize only to a user-named new view, then rerun readback and placement closure.

## Optimize a measured placement offline

Read [optimization-contract.md](optimization-contract.md) and prepare the hash-bound request
and sourced per-layer planning rules. This command needs only Python's standard library;
it does not require a bridge environment or run the live readiness commands above.

```powershell
& <python> <skill-dir>\scripts\placement_optimizer.py `
  --intent <parent-v2.json> --access <terminal-access.json> `
  --request <optimization-request.json> --evidence <planning-rules.json> `
  --feedback <routeability-feedback.json> --out <new-output-directory>
```

`--evidence` and `--feedback` are optional. Missing evidence produces unknown capacity/access
results. The output directory must not exist. Review `placement-candidates.json`, its baseline,
failures and ancestry, and the exported candidate JSON/SVG pairs. The unchanged baseline may
remain on the Pareto frontier. A selected child requires a new live readback before its projected
access can be consumed as authoritative routing input. The command never calls a router/importer.

## Agent conversation examples

Planning only:

> Use analog-layout-place to generate a placement plan with explicit m copies from mylib/AMP/schematic; measure actual PCell bboxes and output placement-intent.json without modifying Virtuoso.

Materialize after reviewing the intent:

> Use analog-layout-place to map `<absolute-path>/placement-intent.json` to the newly created mylib/AMP_layoutV2/layout; place PCells only, do not route or overwrite an existing view, and verify by readback after saving.

Audit only:

> Use analog-layout-place in verify-only mode to check that mylib/AMP_layoutV2/layout matches `<absolute-path>/placement-intent.json`, without modifying the layout.

Read-only closure and proposed refinement:

> Use analog-layout-place for read-only placement closure on mylib/AMP_layoutV2/layout; if adjustment is needed, generate a declarative refinement-spec, a new placement intent, an intent delta and a pin-access projection without modifying the layout.

## Completion boundary

Placement is complete only when the report passes and records zero top-level electrical shapes, nets, and terminals. In annotated mode, the only permitted top-level shapes are tagged `D/<net>` labels on the requested annotation LPP. Wells, guard rings, dummy ties, routing, pins, DRC, LVS, and PEX are later stages and must not be implied by this result.
