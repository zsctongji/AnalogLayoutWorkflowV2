# Reference and qualification

Select an exact reference cellview from the current project only when needed to qualify a missing recipe. Use `inspect_reference.py` with explicit `--env`, `--lib`, `--cell`, `--view` and `--out` arguments. Record current PDK identity and capture hash; no reference-layout data or project geometry is bundled. Read current shortcut bindings if using the GUI. Observed active/implant/well/metal/cut cross-sections are geometry evidence, not foundry legality.

The caller supplies a `analog-layout-guard-ring.request/v1` JSON. Example values below are illustrative **only**; use measured/qualified rules and actual instance identities before planning:

```json
{
  "schema": "analog-layout-guard-ring.request/v1",
  "source": {"lib": "mylib", "cell": "PLACED_CELL", "view": "layout"},
  "target": {"lib": "mylib", "cell": "NEW_GUARD_RING_CELL", "view": "layout"},
  "instance_names": ["M0", "M1"],
  "polarity": "p_substrate",
  "tie_net": "AVSS",
  "reference_ring_id": "reference_ring_0",
  "reference_qualified_for_pdk": true,
  "active_to_inner_edge_um": 1.0,
  "foreign_keepout_um": 0.5,
  "qualified_recipe": {"pdk_id": "ACTIVE_PDK_ID", "rule_source": "VERIFIED_RULE_OR_GENERATOR", "contact_pitch_um": 0.92, "corner_contact_inset_um": 1.2}
}
```

`reference_qualified_for_pdk=true` is a user/engineer assertion **only after** checking current technology, not an automatic conclusion from this skill. Record rule deck/generator provenance, rule version, PDK identity, and date in the run report. The recipe must also document the intended maximum tie/tap separation and metal strap width; the planner does not prove these. The numeric example above must not be adopted as a default.

Before the geometry request, resolve functional modules with `partition_modules.py`. Each request must select exactly one complete domain (functional module + polarity + body net), including associated dummies, and match its body tie. `modules` may supply the same reviewed explicit ownership list used by the partitioner. Common VSS/VDD is not permission to merge differential pairs and mirrors into one ring. Ring-to-ring collisions and shared diffusion crossing module boundaries are placement conflicts, not permission to silently combine domains.

`scripts/plan_guard_ring.py --intent ... --reference ... --request ... --terminal-access ... --gate-review ... --out ...` produces `analog-layout-guard-ring.plan/v1`. First satisfy [gate-access.md](gate-access.md): missing or unqualified realized gate contacts block the plan, and qualified gate-access/escape envelopes expand the enclosed extent. The planner also rejects cross-module or partial-domain selections, unresolved ALIGN bbox overlaps or missing instances, unsupported N+ auto-planning, unsupported reference cross-sections, unselected devices within the proposed envelope, unqualified contact pitch, or inadequate corner inset. It does **not** prove spacing to routed metal, wells outside PCell bboxes, terminals, other pre-existing guard rings, or foundry DRC/LVS. Inspect the actual layout for these before invoking the Virtuoso generator. The same gate applies to guided N+ or direct MPP/GUI construction; these are not bypass paths.

When using the GUI shortcut: use the authorized working target under the shared save policy; open the layout, activate the ring command, select the correct PDK ring/tap settings, enter the planned centerline rectangle, then read back the generated active/implant/well/metal/contact shapes. Do not assume the form's default ring polarity or tie net. If the GUI form cannot represent the qualified recipe or there is ambiguity about intended well containment, stop and request human review rather than substituting raw shapes.
