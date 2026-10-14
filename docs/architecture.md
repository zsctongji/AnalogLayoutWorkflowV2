# Architecture

The agent selects the requested stages and assembles verified inputs. Skills define contracts and failure handling. Python helpers construct and check candidates; site-qualified adapters perform native operations. Foundry tools provide independent physical/electrical reports. Saved layouts, candidate PASS and process-level closure are distinct evidence states.

## Stage map

| Stage | Canonical skill |
|---|---|
| Discovery and initial placement | `analog-layout-align` |
| Alternative placement/shared refinement | `analog-layout-place` |
| Shared diffusion | `analog-layout-diffusion-share` |
| Local contacts and access | `analog-layout-local-access` |
| Module guard rings | `analog-layout-guard-ring` |
| Common-axis macro alignment | `analog-layout-macro-symmetry` |
| Rigid macro compaction | `analog-layout-macro-opt` |
| Default mirrored templates | `analog-layout-symmetric-fast` |
| Explicit joint mirrored search | `analog-layout-symmetric-route` |
| General routing/shared intent and import | `analog-layout-route` |
| PDK extraction/profile checks | `analog-pdk-profile` |
| Foundry physical checks | `analog-layout-drc` |
| Independent electrical comparison | `analog-layout-lvs` |
| Extraction/post-layout measurements | `analog-layout-pex` |
| Optional physical performance iteration | `analog-layout-iterate` |
| Optional parasitic diagnosis | `analog-netlist-crawl` |
| Native bridge and layout practice | `operate-virtuoso-bridge`, `virtuoso-layout-practice` |
| Multi-stage orchestration | `analog-layout-workflow` |

`analog-pipeline` is retained as an existing analog-design entrypoint. Its broader circuit-design skills are outside this layout source bundle; ordinary layout questions do not start the full design pipeline.

## Single runtime source

`src/analog_layout_workflow` supplies the repository CLI. It loads the canonical checkpoint/dispatch runtime in `skills/analog-layout-workflow/scripts`, avoiding duplicated implementations. Skill helpers retain their relative sibling imports so the full installed skill set must remain together.

The checkpoint graph records requested scope, exact cellviews/revisions, dependency fingerprints and immutable stage artifacts. Changes invalidate downstream checks according to their causal dependencies. The default physical save policy updates one authorized working layout at the end of each stage; staged archives require an explicit request.

## Routing boundary

Default fast routing compiles complete measured finite templates and their exact reflected mates. Its track/layer helpers are configurable; template PASS is not full obstacle closure. Explicit joint routing performs bounded mirrored Manhattan search and independent represented-geometry audit. Explicit general routing uses its existing planner. All methods feed shared intent/SVG checks and a qualified importer; no second global planner rewrites an accepted mirrored candidate.

Neither offline branch grants OA materialization or foundry signoff. Native object geometry, conditional rules, full obstruction coverage, saved readback and actual DRC/LVS remain separate checks. Geometric symmetry alone does not establish equal parasitics.
