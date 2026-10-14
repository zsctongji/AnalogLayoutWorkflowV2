# Configuration and PDK adaptation

The workflow uses separate external project, PDK, circuit, routing and site configurations. Their primary contracts are [project configuration](../skills/analog-layout-workflow/references/project-configuration.md), [fast routing configuration](../skills/analog-layout-symmetric-fast/references/configuration.md) and [joint solver configuration](../skills/analog-layout-symmetric-route/references/solver-contract.md).

| Configuration | Responsibility |
|---|---|
| Project | Source/target identities, relative input paths, config references, simulation definitions and actual project decisions |
| PDK | Source/PCell device mapping, parameter names/types/units, terminal mapping, layer roles/actual levels, qualified contact/ring/via data |
| Circuit | Complete modules/dummies, matching modes, row arrangements and placement/macro constraints |
| Routing | Net classes, widths/current basis, directness/matching/topology, actual axis/pin maps and selected backend |
| Site/registry | Tools, licenses, maps/decks/models, bridge environment, adapter/interpreter/dependency hashes and current qualification |

`config/site.template.json` is unqualified and contains placeholders. `config/registry.template.json` registers no stages. The templates are structural starting points, not circuit examples or execution authority. Keep filled configuration and PDK measurements outside tracked source, usually under ignored `local/` or a separate project directory.

## Routing

No selected method defaults to `symmetric_fast`. It requires `routing.fast_templates` with a complete measured seed, axis and whole-net classifications. `strict_symmetric` uses `routing.symmetry_solver` with complete groups, search budgets and sourced local-access/PDK rules. `general` explicitly selects the general planner. Do not pass one backend's options through another or silently fall back after failure.

The configured frontend is `skills/analog-layout-workflow/scripts/configured_flow.py`. Its `validate`, `prepare`, `place`, `macro-opt`, `route`, `symmetric-fast` and `symmetric-route` commands generate offline artifacts only. Full contracts describe their required inputs and status semantics; no bundled design input is provided.

## Changing PDK

Rebuild parameter/master and terminal mappings, measure evaluated PCell variants, extract a fresh routing profile, and qualify diffusion-sharing boundaries, contacts, via geometry/stacks and guard rings. Bind layer roles to verified actual metal levels; rank parity and name suffixes are not levels. Resolve conflicts between PDK direction requirements and the odd-vertical/even-horizontal policy without changing the PDK evidence to force a pass.

Configure and verify independent export, DRC/LVS, extraction and model/testbench interfaces. Test native creation/readback/save behavior on authorized small cells before registering complete stages. The named Nuvoton check adapter is retained with its specific scope; an external path mapping does not qualify another process or writer. The repository deliberately supplies no filled legacy site profile and requires `site_profile.config`.
