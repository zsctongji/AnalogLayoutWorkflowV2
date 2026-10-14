---
name: analog-pdk-profile
description: Extract and validate a local Cadence Virtuoso technology database into a provenance-rich analog routing profile. Use before PDK-aware layout routing or when inspecting manufacturing grid, routing layers, width/spacing constraints, and via definitions. It is read-only and does not replace foundry DRC/LVS decks.
---

# Analog PDK Profile

Create a local, machine-readable PDK routing profile from the technology database attached to an explicitly named Virtuoso cellview. Keep the extractor generic; store technology-specific names and numeric rules only in generated run artifacts.

## Workflow

1. Use `operate-virtuoso-bridge` to confirm `[daemon] OK` and an `eval "1+2"` result of `3`.
2. Resolve an exact source library/cell/layout view and constraint group. Never infer the frontmost window or silently choose a PDK.
3. Run `scripts/pdk_profile.py extract` with explicit `--lib`, `--cell`, `--view`, `--constraint-group`, `--out`, and `--report` arguments.
4. Review the generated profile identity, fingerprint, rule coverage, missing adjacent-metal vias, warnings, and unknown signoff categories.
5. Run `scripts/pdk_profile.py validate` immediately before a downstream router consumes the profile. Reject a changed fingerprint, invalid schema, non-positive geometry, missing basic routing rules, or unknown layer references.
6. Regenerate the profile when the technology library timestamp, constraint group, or extracted fingerprint changes.

The extraction is read-only. It opens the named cellview in read mode, reads its attached technology file, and closes the view. It must not write the technology library, cellview, PDK files, or foundry decks.

## Consumer boundary

A future `analog-layout-route` may consume only profiles whose `validation.structurally_valid` and `coverage.basic_routing_ready` fields are true and whose fingerprint passes revalidation. It must still treat every extracted rule as preflight evidence, not foundry signoff.

- Prefer routing layers identified by the technology database layer-function table.
- Preserve every constraint's source group, condition parameters, and raw value; do not collapse conditional rules into one universal minimum.
- Use normalized via geometry only when the standard via parameter list is complete. Preserve the raw parameter list for audit.
- Treat preferred direction, EOL/notch rules, density, antenna, high-voltage context, electromigration, and other unextracted categories as unknown unless separately verified.
- Keep generated PDK profiles local unless the user confirms they may be shared. Foundry licensing and confidentiality rules remain authoritative.
- Always run the project's original DRC/LVS decks after routing. Do not claim that a profile is complete or signoff-equivalent.

Read [references/profile-contract.md](references/profile-contract.md) when implementing a consumer, and [references/reuse.md](references/reuse.md) for command examples.

## Failure handling

- If the target cellview cannot be opened or has no technology file, stop without emitting a valid profile.
- If the requested constraint group is absent, report the available groups and require an explicit choice.
- If a routing layer lacks scalar positive `minWidth` or `minSpacing`, mark basic routing coverage false.
- If adjacent routing layers have no normalized via definition, mark the gap explicitly; never invent a via.
- If extraction succeeds but coverage is incomplete, retain the profile for diagnosis and prohibit automatic routing from treating it as ready.
