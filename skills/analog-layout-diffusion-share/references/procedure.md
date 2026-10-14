# Build and check shared diffusion

Start with a saved placement intent, authoritative terminal nets, functional module/dummy ownership and an authorized target. Preserve the source schematic.

## Eligibility

Same nonempty terminal net + same functional module is sufficient to select sharing. Include dummy boundaries, central left/right boundaries and source chains. Exclude different nets/modules; resolve unknown ownership. Different W/L/finger counts are not automatic exclusions and must not be resized to force sharing.

`inspect_pairs.py` exposes `sharing_eligible`, `module` and `eligibility_policy`. Its `requirements` are construction tasks or diagnostic concerns, not mandatory preimplementation electrical qualification. Cross-module and unknown-module candidates are ineligible. Inspect existing overlap during readback; a compulsory new fixture is unnecessary.

## Construct geometry

Read actual PCell active, terminal metal, contact cuts and legal parameters. Choose measured orientations and source-strip spacing. Coincide the intended contact/active area while retaining separate channels and drain/gate access. Bbox touching does not specify diffusion spacing.

Place all chain members at once. Each middle device has a single orientation, parameter set and origin while sharing opposite sides. Treat reflected edges together and retain the declared axis and dummy environment. Normally connect a source-compatible central edge between two previously shared halves.

Use `analog-layout-place.refinement-spec/v1` and `share_source_diffusion`. Set `evidence.eligibility_policy` to `same_net_same_module`; provide actual placements, module identity and measured source-contact arrays. Geometry values and cut coincidence are construction requirements. Under this policy the refiner does not require prior `terminal_continuity_verified`, `no_ds_short_verified`, `pair_probe_sha256` or `overlap_isolation_verified`. Leave them pending/false until checked; never manufacture evidence. Legacy strict operations remain readable for existing verified runs.

Save an authorized cellview using the established target policy. Preserve PCell parameter types and passive dimensions; do not modify PDK masters. S/D or D/D sharing requires a materializer supporting those actual terminal roles; do not rename S/D to bypass the S/S adapter.

## Check saved result

Read back parameters, transforms, actual active/contact/landing geometry and terminal islands. Inspect intended edges and other overlaps, and refresh access evidence. Check the applied complete chain/array for continuity, unintended shorts and unchanged recognition after saving. Reuse unchanged measurements; a separate pair fixture before construction is optional.

Report applied edges, cuts, central edges/chains, matching/dummy changes, area and status. Fix physical issues or record the precise unimplemented edge. DRC/LVS can follow at the requested stage; no signoff deck does not prohibit a clearly labeled unverified implementation. Never claim verification success from same-net eligibility alone.
