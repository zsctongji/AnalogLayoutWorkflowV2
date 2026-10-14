# External configuration and portable helpers

The default backend is `symmetric_fast`. Explicit `strict_symmetric` selects the joint solver; explicit `general` selects general routing. The default never converts solver groups/policies into templates or falls back to an independent/asymmetric planner. Missing template input produces `FAST_TEMPLATE_REQUIRED`.

## Standalone request

Use `analog-layout-symmetric-fast.templates/v1` with the compiler fields documented in [template-contract.md](template-contract.md), plus:

- `routing_policy.metal_levels`: actual PDK layer name → positive metal level, covering all routing layers; technology-rank parity and layer-name suffixes are not levels.
- `routing_policy.layer_roles`: project-independent role → actual PDK layer name. All referenced roles must exist in the level mapping.
- `routing_policy.local_direction_exceptions`: optional exact route-ID → `{source, reason, region_um, max_length_um}`. Only local level-1 reverse-direction access is eligible; the full route must fit its measured footprint region/length. These entries do not waive cumulative M1 or foundry checks.
- `ordinary_nets`: exact net-name → scoped reason for ordinary/matched-only/asymmetric portions. Together with `pairs` and `self_nets`, cover every access net exactly once. They do not receive strict mirror PASS.

All widths, absolute/relative coordinates, net identities, pair pin maps and per-run stopping budgets belong to project data. Keep `sources` bound to profile/access/seed hashes. Never modify a profile rule to make the direction policy pass.

## Helpers for finite template construction

`generated_tracks(profile, obstacles, points, axis, layer, width, limit)` returns a deterministic bounded candidate list using manufacturing grid, measured points, routing bounds and obstacle-edge clearance from sourced spacing. It accepts the shared obstacle format (`bounds_um`, `obstacles[].layer/bbox_um`). It does not certify two-sided reachability, cut spacing, via landings or full conditional legality. Include all supplied constraints in the full candidate review.

`layered_dogleg(profile, policy, prefix, net, points, horizontal_role, vertical_role, widths_by_role, via_name)` maps a straight/L/U skeleton to direction-correct layers and adds named adjacent transitions. It never invents a direct skip-layer via. Endpoint access tags, endpoint transitions, nonadjacent stacks and exact landing coverage must be completed before compiling the seed.

`mirror_spec.doglegs(start, end, tracks_x, tracks_y)` enumerates finite skeletons only. Feed generated or explicitly constrained tracks; do not store example tracks in the skill. `mirror_spec.horizontal_bus(...)` requires tap landings on the horizontal bus y, explicit widths and a qualified named transition. For other layer sequences, assemble mapped fragments instead. Neither helper replaces full connectivity/PDK checks.

## Configured workflow

In external `routing-policy.json`, choose `backend: symmetric_fast` (or omit backend) and put `axis`, `seed_spec`, `pairs`, `self_nets`, `ordinary_nets`, optional `via_mirror_evidence` and optional `local_direction_exceptions` in `fast_templates`. Keep `layer_roles` and `routing_rules.metal_levels`/`via_mirror_evidence` in the external PDK map. The seed target must match measured access and the project target; every required net must have a class/directness/current-width basis where applicable.

```text
python ../analog-layout-workflow/scripts/configured_flow.py symmetric-fast --project project.json --work candidate-dir
python ../analog-layout-workflow/scripts/configured_flow.py route --project project.json --work candidate-dir
```

Both use the default fast backend unless an explicit backend is configured for `route`. `symmetric-route` explicitly selects the joint solver; `symmetric-fast` explicitly selects templates. Fast artifacts go to `routing/symmetric-fast`; no command writes OA. Invalid/blocked reruns replace selected frontend artifacts with current BLOCKED evidence so an older successful template cannot remain selected. A standalone fast run requires a new output directory.
