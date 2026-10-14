# Executable runtime

Run only the actual stage required for this invocation. Read its executing skill and required references first. This document provides no universal writer that bypasses their checks.

## Checkpoint CLI

```text
python scripts/workflow_runtime.py init --config run-config.json --state workflow-state.json
python scripts/workflow_runtime.py next --state workflow-state.json --bindings fresh-bindings.json
python scripts/workflow_runtime.py check --state workflow-state.json
python scripts/workflow_runtime.py checkpoint --state workflow-state.json --stage STAGE --receipt receipt.json
```

The init config follows checkpoint.md fields and additionally supplies `requested_stages`. Stage order: discover/place/share/gate-access/ring/symmetry/macro-opt/route-intent/route-apply/drc/lvs/pex/postsim/performance-opt. Omitting the list defaults to LVS. Obtain `bindings` from fresh source/hierarchy/PDK/deck/current relevant results, rather than guessing hashes from manual status. Reverify historical state migrations item by item instead of relabeling in bulk.

`performance-opt` is an analysis/decision stage added explicitly on request. It depends on valid postsim and binds the current cellview/revision and immutable decision evidence. Completion verdicts are DECISION_READY, NO_ACTION or STOPPED, with separate performance status in the decision artifact. SPEC_PASS cannot replace a decision receipt. Adding a stage id does not establish a live adapter: without registration, run_stage still returns BLOCKED_CAPABILITY. Actual optimization returns to authorized qualified physical adapters, updates physical checkpoints and reruns affected DRC/LVS/PEX/postsim before a new decision. Do not hide CAD writes or skip checks inside this stage.

Receipts retain native validation.verdict. For CLOSED, DRC permits only CLEAN and LVS only VERIFIED_MATCH. SKIPPED requires skip_reason, skip_dependency_safe and actual applicability evidence. For share, SKIPPED also requires user_skip_authorization with source user, scope share and a nonempty actual user instruction explicitly requesting diffusion-share omission. Do not fabricate a user skip instruction from an automated judgment or general layout authorization. checkpoint rejects new records missing that authorization; check/next mark old unauthorized skips STALE and invalidate downstream dependencies. No feasible edges requires a completed NO_APPLICABLE_EDGES assessment result, rather than SKIPPED. Record readback_verified, output_cellview and output_revision; all verified records require valid immutable artifacts. Artifact paths default relative to the state directory and host defaults to local. Download remote files for verification or obtain a binding receipt from a qualified live checker; do not pretend a local check occurred.

DRC/LVS/PEX receipts additionally require `checked_cellview` equal to actual current. Equal geometry digests alone cannot bind another cell's report to the current target. Check native-report layout/source primaries rather than inferring them from wrapper configuration.

next does not write OA. It returns READY/blockers/requested-scope completion and invalidation reasons for every stage. DONE indexes stage-work completion rather than signoff. DRC VIOLATIONS may proceed to independent LVS, but PEX defaults to LVS VERIFIED_MATCH + DRC CLEAN at the same revision. Record exploratory_pex_authorization for explicit user acceptance; it still cannot override an incorrect DUT/LVS.

For LVS `REPORT_MATCH_UNVERIFIED`, permit only exploratory PEX with explicit acceptance of limitations. `exploratory_pex_authorization` must include `source: user`, `scope: pex`, actual `instruction`, current `revision` and `checked_cellview`. Same-revision `verification.lvs` must record an independent reference, an actual `CORRECT` report and the same cellview. Preserve original warnings and LVS status. Incorrect reports, missing independent references, old revisions or wrong targets still block extraction; exploratory authorization does not become signoff.

## Executable single-stage dispatch

```text
python scripts/run_stage.py --state workflow-state.json --registry registry.json --runs artifacts/runs
python scripts/run_stage.py --state workflow-state.json --registry registry.json --runs artifacts/runs --execute
```

The registry uses `schema: analog-layout-workflow.registry/v1`; each `stages` entry is `{script,script_sha256,python,python_sha256,code_dependencies:[{path,sha256}],mutating,qualification_evidence:[{path,sha256}],timeout_seconds}`. Register every import/remote-runner dependency affecting execution and pin the interpreter. Recheck after execution, not just the entry file. Register only fixed scripts with code review/live qualification, never arbitrary shell commands from user uploads or result files. Mutating stages require explicit targets/save modes: default `single-layout` reuses `save_policy.working_layout`, with the same target for every stage. Only explicit user `staged` requests require an absent destination for each new stage. See [save-policy.md](save-policy.md); legacy clone-only adapters cannot automatically choose archives for the user.

Script interface: `--handoff handoff.json --out stage-receipt.json`. handoff contains exact source/reference/target, constraints, bindings/dependencies, authorization and run_dir. After actual operations/checks, the child adapter outputs a receipt bound to `handoff_sha256`. Exit 0 without a receipt/readback/correct target does not advance status. Every run uses a new directory retaining commands/console/raw evidence. Child adapters do not hash a console still open for writing; the dispatcher binds final logs, commands and receipts after exit. A timeout does not prove CAD rollback; diagnose live state.

See [dispatch-efficiency.md](dispatch-efficiency.md) for additional place input audits and reuse policy. state/config may provide `dispatch_inputs.place`, with schematic and placement_intent each represented as `{path,sha256,host: local}`. A candidate must exist before mutating execution; read-only planning requires only the schematic. Store matching and dummy ownership in constraints. Add verified input records before old runs enter place. run_stage returns BLOCKED_PREFLIGHT before starting the child adapter; other stages retain their interfaces. handoff adds dispatch_preflight and execution_policy. Record timings in command, stage checkpoint and performance.json; total adapter time does not establish network latency.

The dispatch runtime does not invent ALIGN, ring or foundry core implementations. Unregistered/unqualified stages explicitly return BLOCKED_CAPABILITY, without false success. Port existing run-specific adapters to this handoff interface individually and requalify after modifications. Replacing hardcoded cell names in old scripts does not establish general capability.

The native gate-access entry point is `analog-layout-local-access/scripts/native_gate_adapter.py`. After registering its site qualification, the dispatcher directly calls Virtuoso's built-in `dbCreateVia` to create actual poly→M1 vias. Per-stage `dispatch_inputs[stage]` passes to the fixed adapter as `handoff.stage_inputs`, and the adapter checks file hashes. Current support is equivalent-geometry native replacement of verified rectangular gate contacts; see [native-via.md](../../analog-layout-local-access/references/native-via.md) for inputs and boundaries. Native vias use dedicated snapshot/readback/backends; the generic rectangle backend's capabilities remain unchanged.

## Unified transaction interface

Default in-place transactions follow fresh saved snapshot→unsaved transaction on current working target→apply→full read→trusted verification→save→independent saved readback. Existing `adapter_runtime.execute(plan,backend,trusted_verifier)` is clone-only: fresh snapshot→absent clone→apply→full read→trusted verification→save→independent source/target readback. Use it only for initial working-target creation or explicit staged archives/Save As; do not claim in-place support. For single-layout, use/adapt a writer with corresponding live qualification; do not bypass limitations with stage copies. Existing DRC/LVS pure repair gates remain prerequisites.

`virtuoso_adapter.VirtuosoBackend` implements native snapshot, clone and p0Id/p0Owner-owned rectangle create/replace. Unidentified historical geometry is protected. It does not support PCell/ROD/native-via/pin mutation or changes to existing object owner/net/lpp. Actual cuts may be recipe-defined owned rectangles, verified by the local-access verifier; ordinary route repair cannot conceal contact scope.

Qualification binds adapter-code hashes, CAD host/version, capabilities and actual raw test evidence. Qualification establishes only the in-scope transaction mechanism. Callers still require trusted_verifier to supply bound actual reports for connectivity/pin_access/pdk_geometry/symmetry/protected/environment; UNKNOWN blocks saving. Without all verifiers, mechanism qualification is not qualification for complete controlled DRC/LVS repair closure.

For single-layout, rollback discards only this stage's unsaved transaction and verifies restoration to the same target's saved baseline. Clone-only/staged retains the unmodified baseline clone. Failures after saving remain SAVED_NOT_CLOSED, without a rollback claim. Deleting existing scratch data requires explicit cleanup authorization; runtime does not delete automatically or create stage copies for retries.

A transport interruption during `dbSave` is SAVE_STATE_UNKNOWN. Purge is forbidden; retain the target for read-only diagnosis. A successful save followed by a close failure is SAVED_NOT_CLOSED.

## Local read-only check profile

`site_nuvoton_check.py` accepts drc/lvs handoffs and checks an explicitly identified layout against an independent schematic under profile `nuvoton1132-ic618-calibre2019`. constraints supplies `metal_option: "3M + TM_8K"` and `site_profile:{name,bridge_env,remote_python}`. Layout evaluated masters currently support ntc1132 only; deeper hierarchy/other libraries require new qualification. Remote runner `site_nuvoton_remote.py` writes only new run directories, freezes OA/PDK/deck/map/si.env, retains GDS framing/hierarchy, independent SPICE, commands/logs/raw results and file hashes, and rechecks unchanged source/PDK.

Current qualification covers export/check/revision-binding mechanisms, rather than a complete foundry-closure adapter. Preserve native INCOMPLETE, REPORT_MATCH_UNVERIFIED and unreviewed warnings/include/equivalence limitations. Do not output CLEAN/VERIFIED_MATCH or use this as controlled-repair qualification. Check support does not register every PCell/ring/macro/router writer. Unregistered stages still return BLOCKED_CAPABILITY.

## Tests

`python -m unittest discover -s tests -v` covers stale files/dependencies, false closure, independent DRC/LVS, rollback on one-sided faults and local-access blockers for wrong nets/missing islands/mirroring/rules. MemoryBackend is a fault fixture only, never a live adapter.
