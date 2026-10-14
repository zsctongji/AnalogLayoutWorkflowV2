---
name: virtuoso-layout-practice
description: Inspect, plan, edit, and review Cadence Virtuoso IC layouts through virtuoso-bridge-lite using a project-aware checklist for floorplanning, routing, matching, pins, devices, verification, and area reduction. Use for applying these practices to a concrete Virtuoso cellview; not as a substitute for the active PDK, schematic intent, or foundry signoff decks.
---

# Virtuoso Layout Practice

Apply [references/layout-guidance.md](references/layout-guidance.md) through the installed `virtuoso-bridge-lite` workflow. Treat the active Virtuoso session and design database as live user state.

## Start with evidence

1. Locate the `virtuoso-bridge-lite` checkout containing `.env` and `.venv`.
2. Run `.\.venv\Scripts\virtuoso-bridge.exe status` before every Virtuoso operation.
3. Resolve the exact library, cell, view, PDK/process, metal stack, schematic source, and requested save behavior. If unclear, inspect with `windows`, `snapshot`, or read-only SKILL; never guess the frontmost cellview.
4. Read current geometry, connectivity, instances, pins, and parameters before proposing or making changes.
5. Identify applicable, unverifiable, and conflicting guidance. The current PDK, schematic, signoff deck, and verified project evidence win.

## Choose the operating mode

- **Review or explain:** inspect only; group findings as confirmed issue, likely issue, or unverified project rule.
- **Plan:** propose floorplan, placement, routing, matching, pin, and verification actions without modifying the design.
- **Edit:** make only the user-requested, explicitly scoped changes. Prefer bridge domain APIs when supported; use reviewed SKILL files for multi-form operations.
- **Verify:** rerun relevant extraction/connectivity checks and the project's DRC/LVS flow when available. Never claim signoff from visual inspection.

## Decision rules

- Treat numeric grids, layer names, enclosure values, legacy tools, and process labels in the reference as historical project knowledge. Confirm them from the active technology file, rule deck, verified cells, or user before use.
- Preserve schematic intent. After schematic changes, require a checked/saved source before layout reconciliation.
- Resolve connectivity before area optimization. Never shrink wires, contacts, vias, power paths, or ESD paths below verified requirements merely to save area.
- For matching, confirm the actual matching group, topology, orientation, surroundings, dummies, and routing parasitics; visual symmetry alone is insufficient.
- Keep power/ground, ESD, high-current devices, thin-oxide markers, and hierarchy pins conservative until project rules are confirmed.
- Preserve old layout versions when creating a revision; do not overwrite or delete prior cells unless explicitly requested.

## Mutation and verification

Before editing, report the resolved target and intended change. After editing:

1. Save only the intended target cellview.
2. Reread changed geometry, parameters, pins, and connectivity.
3. Run relevant project checks available through the bridge.
4. Report the exact target, changes, checks, failures or warnings, and unverified guidance.

Use the bridge for SKILL execution. Do not run SKILL from an SSH shell or expose the daemon outside its SSH tunnel.
