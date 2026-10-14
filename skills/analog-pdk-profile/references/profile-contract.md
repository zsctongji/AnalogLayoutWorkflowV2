# PDK routing profile contract

Schema: `analog-pdk-profile/v1`.

The profile records:

- `source_target`: the exact library/cell/view used to resolve the technology database.
- `technology`: technology library, technology filename, timestamp, and selected constraint group.
- `fingerprint`: SHA-256 of canonical extracted technology identity, grid, layers, layer functions, LPPs, constraints, and vias. It excludes generation time, reports, and validation results.
- `manufacturing_grid_um`: grid returned by the attached technology file.
- `layers`, `layer_purposes`, and `layer_functions`: source inventories without guessed routing semantics.
- `constraints.rules`: constraint name, definition, layer tuple, raw value, condition parameters, and hard/soft marker.
- `routing_layers`: metal layers ordered by layer-function rank, with matching width and spacing rules retained as arrays.
- `vias`: source via definitions plus normalized standard cut/enclosure fields when their parameter list is complete.
- `coverage`: basic routing readiness, missing layer rules, missing adjacent-metal vias, and categories not established by this extractor.
- `validation`: structural errors and warnings at generation time.

## Router acceptance contract

A consumer must:

1. Recompute and match the fingerprint with `pdk_profile.py validate`.
2. Require `validation.structurally_valid=true`.
3. Require `coverage.basic_routing_ready=true` for automatic path generation.
4. Select an applicable rule by definition, layers, and condition parameters. It must not assume the first rule is universally applicable.
5. Refuse any route that needs an unknown layer, missing via, non-positive width/spacing, or an unverified special-context rule.
6. Record the profile fingerprint in every `routing-intent.json` so stale intents can be rejected.

The profile is a deterministic preflight interface. It is not a copy of the full foundry deck and does not establish DRC, LVS, density, antenna, reliability, or extraction correctness.
