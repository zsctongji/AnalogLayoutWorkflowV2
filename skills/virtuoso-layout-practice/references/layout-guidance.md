# Layout guidance distilled from the supplied experience summary

This is historical engineering guidance, not a foundry rule deck. Confirm process-specific values, layer names, and check flows against the active PDK and project before applying them.

## Before layout

- Confirm the snap grid. The source associates 0.08, 0.06, and 0.05 processes with grids of 0.1, 0.05, and 0.025 respectively; treat these mappings as unverified project conventions.
- Do not start a cell name with a digit when the legacy DRACULA flow is in use.
- Decide pin exit directions and positions before placement.
- Analyze the schematic and group MOS devices that implement the same function.
- Plan the preferred direction of each metal layer. Keep gate orientation consistent where practical.

## Placement, devices, and hierarchy

- After a schematic edit, check and save it before reconciling layout.
- Place devices from a rough floorplan, then route. Compare device count, type, dimensions, and extracted parameters with the schematic.
- Return each completed cell to the project's expected origin convention.
- When a lower-level cell has supplies such as `vssx`, `vddx`, `vssb`, or `vddb` that are not connected by the parent, expose and connect required pins according to the hierarchy plan. Prefer resolving this in the lower-level cell.
- Leave routing channels when placing subcells; avoid forcing later routes across devices.
- Keep useful lower-level pins and labels orderly for reuse.
- Place capacitors after the main placement and routing plan is stable, using remaining space only if matching and parasitic requirements allow it.
- Confirm every device terminal is connected and parallel MOS source/drain sharing matches the schematic topology.
- Keep unrelated MOS thin-oxide or marker regions separate when the PDK requires it. Confirm thin-oxide devices have required implant or marker layers.

## Routing, contacts, pins, and labels

- Prefer an upper metal for external pins when stack, current, EM, and integration constraints permit it.
- Bring required external routes to the cell boundary and reserve access space.
- Avoid unnecessarily long routes; use connectivity highlighting to find merge and shortening opportunities.
- Do not route across a MOS channel unless the PDK and circuit constraints permit it.
- Ensure route junctions overlap correctly. Inspect them at high zoom and respect minimum width at overlapping metal segments.
- The source recommends at least two contacts or vias in ordinary cases and fewer for very small MOS devices; override this with PDK, current density, resistance, EM, reliability, and geometry.
- The source says a metal via may fit among diffusion contacts; use only when legal in the active rule deck.
- The source warns against contacting both ends of a polysilicon segment to metal; confirm the intended reason and current PDK rule before treating it as a prohibition.
- Keep internal core power/ground distinct from ESD power/ground where the architecture requires separation.
- Do not break an ESD connection when rerouting; avoid changing its metal layer without an explicit, verified current/ESD plan.
- Use sufficiently wide, low-resistance metal for power MOS pins; broad coverage may be appropriate but must pass density, slotting, EM, and DRC constraints.
- Keep metal dummy orientation consistent with preferred metal direction when the fill methodology requires it.
- Use the project's manufacturing-recognized label purpose. The source says `y0` is not recognized in GDS and top-metal pin names should use `text2` with identical pin/text names in its legacy DRAC flow; verify stream-out and LVS/DRC mappings first.
- Treat `Text2` and `y0` as check or annotation layers unless the active layer map says otherwise.
- Use integer pass-window dimensions for pads only if required by pad or assembly rules.

## Matching and passive devices

- Matching means equalizing the relevant fabrication environment, not merely drawing symmetry.
- Choose horizontal, vertical, centroid/common-centroid, interdigitated, or another pattern from the actual matching requirement. The source favors center matching, especially for larger groups.
- Do not relax matching for small devices without sensitivity analysis or project precedent.
- For four or more matched devices, seek local and global environmental symmetry, including orientation, neighbors, dummies, edge effects, wells, gradients, and routing.
- Do not assume an amplifier device must match the current source below it; derive groups from circuit intent.
- Keep capacitor top- and bottom-plate voltage distribution and routing balanced. Avoid extreme aspect ratios unless the PDK/model permits them.
- For resistor arrays larger than two elements, use dummies when required. The source records an `NPIM` extension of 0.55 µm beyond `EPOLY2` at the outer resistor; treat this as project-specific and unverified.
- For a legacy resistor-dummy LVS issue, the source suggests moving `nimp` and `RPdummy` to the outermost real resistor without covering the dummy. Apply only after confirming device-recognition and LVS rules.
- The source mentions paralleling resistors; confirm value, matching, voltage, current, noise, and area consequences.

## Verification and error finding

- Compare device count and dimensions against the schematic, then compare extracted parameters.
- Check every terminal and junction, especially supply nets such as `VSSX` and `VDDX`.
- Highlight nets with the available command (called `SHOTS` in the source) to trace breaks, accidental branches, and inefficient routes. Identify the current tool equivalent rather than assuming this command exists.
- Run the project-approved DRC and LVS/extraction flow. The source recommends DRACULA instead of DIVA for large cells; treat this as legacy guidance.
- A clean visual review is not signoff. Report the actual deck, run target, results, and remaining waivers.

## Area reduction

Optimize only after correctness and critical electrical constraints are established.

- Rework floorplan and routing channels first; area is driven by devices, spacing, and routing space.
- Use space above resistors for routing and below wide power rails for devices only when legal and electrically acceptable.
- A longer resistor shape may reduce area for some targets, but verify aspect-ratio limits, matching, contacts, parasitics, and model validity.
- Use minimum legal wire width only where current, EM, IR drop, reliability, noise, and via access allow it; width need not automatically equal contact-array width.
- When producing a smaller revision, preserve the previous layout. Consider lower-level-to-parent interconnect and floorplanning before altering device geometry or verified cells.

## Review output

Report each applicable item as **Pass**, **Issue**, **Needs confirmation**, or **Not applicable**, with concise evidence. Prioritize correctness/connectivity, PDK legality, power/ESD reliability, matching, pin accessibility, verification, and only then area.
