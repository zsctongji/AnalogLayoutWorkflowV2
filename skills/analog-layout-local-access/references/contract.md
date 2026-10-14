# Local-access v1 input/output

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

Input `analog-layout-local-access.request/v1`:

- `target`, `snapshot_sha256`, `pdk_fingerprint`, `grid_um`, `max_escape_um`: all must refer to the explicitly identified current run.
- `evidence`: a list of downloaded local files `{path,sha256}`, including the snapshot, PDK/profile and recipe qualification. The CLI recomputes every file hash; nonempty strings alone are insufficient.
- `islands`: each `{id,instance,terminal,net,layer,bbox_um}` represents an actual rectangular conductor, with terminal G/S/D/B and a `module`/owner. Unknown or empty nets are not allowed.
- `recipes`: key to `{lower_layer,upper_layer,cut_layer,cut_size_um:[w,h],lower_enclosure_um:[x,y],upper_enclosure_um:[x,y],width_um,spacing_um,cut_spacing_um,qualification_sha256}`. qualification_sha256 must match the sha256 of an actual file in evidence. The lower conductor connects directly to the island; obtain upper from the profile's M1 mapping instead of hardcoding layer names.
- `requests`: exactly one `{island_id,recipe,contact_xy_um,escape_xy_um}` per island, with coordinates selected by a joint matching/access policy. Existing contacts may supply `reuse:{contact_id,landing_id,lower_layer,upper_layer,cut_layer,cut_bbox_um,landing_bbox_um,continuity_evidence_sha256}`; the evidence sha256 must appear in evidence.
- For an existing complete escape, add `existing_escape:{id,net,layer,bbox_um}` to reuse. It must be actual continuous rectangular M1 that fully contains the requested escape. After verification, record reused_escape without creating duplicate metal. A single rectangular cut record cannot represent a complete contact array: represent every cut of a multi-cut island or use a qualified array verifier, and never substitute an array bbox for actual cuts.
- `obstacles`: all relevant rectangular conductors/cuts `{id,net,layer,bbox_um}`, retaining their actual nets. Unsupported foreign geometry must be an explicit run blocker, rather than silently removed from the list.
- `pairs`: `{left,right,axis_x_um,net_relation:pair|self}`, representing actual electrical mappings between the two islands. Both sides of self have the same net; pair refers to authoritatively paired distinct nets. Supply unpaired islands in an `exceptions` mapping `{island_id:reason}`. This defines an exact boundary and does not replace approval.
- `conditional_rules_status` must be `PASS` for SELECTED_RULES_PASS to be possible; otherwise use TEMPLATE_ONLY/UNKNOWN. This field must come from trusted site rule review, rather than permission entered by the agent itself.

CLI: `python scripts/local_access.py --request request.json --out absent-plan.json`. Outputs contain the original input digest, immutable evidence, per-island records, writable rectangle primitives, generation scope and blockers. All geometry uses top-level coordinates in µm.

The script does not output foundry CLEAN or gate-contact-review verified true. Generate the corresponding guard-ring schema only after the unified adapter/verifier has actually written and verified all islands/cuts/escapes. Preserve prototype classification and actual identity.
