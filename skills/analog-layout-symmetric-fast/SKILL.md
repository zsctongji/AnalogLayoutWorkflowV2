---
name: analog-layout-symmetric-fast
description: Generate axis-mirrored Manhattan routing with bounded straight/L/U and bus templates using measured pin islands and external PDK/project policies. Default workflow routing strategy when the user has not selected another method; reuse shared routing checks and qualified import.
---

# Fast symmetric template routing

Use this skill by default for workflow routing when no method is explicitly selected. Preserve an explicit choice of `analog-layout-symmetric-route` (joint solver) or `analog-layout-route` (general routing). The default does not invent a symmetry axis or electrical correspondence: missing geometry/maps block the affected template; a non-axis circuit needs an explicitly classified ordinary/matched-only scope or a general-routing choice.

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): update the authorized working layout and save/read back once per physical stage. A request to modify this skill is not a request to operate a live layout.

## Read by task

- Template planning: [algorithm.md](references/algorithm.md), [symmetry-constraints.md](references/symmetry-constraints.md).
- Configuration or generation: [configuration.md](references/configuration.md), [template-contract.md](references/template-contract.md).
- Geometry review or application: [drc-constraints.md](references/drc-constraints.md), sibling [routing-contract.md](../analog-layout-route/references/routing-contract.md).
- Reference comparison only when requested: [reference-and-research.md](references/reference-and-research.md).

## Reusable configuration

Keep cellview/device/net identities, exact axis/pin maps, widths, local-access regions/budgets, topology and candidate limits in project files. Keep actual layer names/levels, role mappings, technology identity and via definitions/qualification in PDK data. No built-in circuit names, absolute tracks, universal micron lengths, supply currents or layer-name parsing. `generated_tracks` derives a finite candidate set from current pins, routing bounds and expanded obstacle edges. `layered_dogleg` assigns horizontal/vertical primitives to configured roles and rejects an invented direct nonadjacent via. Explicit tracks remain legitimate project constraints.

## Required behavior

1. Bind the complete saved layout/schematic/access/profile and verified axis. Resolve missing native contacts upstream; do not modify PCell parameters, devices, wells, rings, dummies or net identities through routing.
2. Cover every access net exactly once as a complete paired net, self-symmetric net, or reasoned ordinary/matched-only exception. Paired physical islands require a complete bijection; self nets need real same-net center connectivity. Include supplies, body/ring ties and external ports.
3. Configure finite topology/track/access alternatives. Use `scripts/fast_route.py` to compile each complete seed and reflect its mate atomically. This is template enumeration, not A*, beam/tree maze search or an independent mate router. Record the configured attempt budget; exhaustion is `NO_VALID_TEMPLATE_IN_BUDGET`, not proof of physical infeasibility. Do not silently switch to another backend.
4. Apply odd-metal vertical/even-metal horizontal directions using verified actual levels. Short horizontal M1 exceptions need exact route IDs, sourced local regions and length limits; they cannot override hard PDK directions or evade cumulative-component checks by splitting primitives. The fast entry point enforces its represented direction gate. The original compatibility compiler alone does not.
5. Reuse route_intent and SVG gates. Retain a rule table and actual metal-edge, per-cut, stack, upper/lower landing, obstacle and cumulative-local-access evidence. Unknown relevant rules block application. Template PASS remains `materializable=false`; it is not foundry DRC or complete obstacle closure.
6. Apply only through the qualified transaction/import chain with fresh live checks. Independently read saved geometry, ports, connectivity, actual directions and complete mirrored objects. Run foundry DRC and independent LVS for routed closure. PEX is required for equal-parasitic/performance claims.

Supply widths/via capacity require current/IR/EM evidence. Continuous buses and adopted dual-trunk topologies must remain continuous and connected within each net. Shared/general route machinery supplies validation/application only: do not run a second global planner on an accepted fast template. Reuse unchanged upstream evidence and consolidate explanations in one routing-review.md.
