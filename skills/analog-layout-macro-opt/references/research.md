# Upstream research — 2026-09-26

Primary repositories/docs inspected before implementation; no upstream code copied or installed.

| Project | Observed mechanism | Adopted here | Not assumed |
|---|---|---|---|
| [ALIGN-public](https://github.com/ALIGN-analoglayout/ALIGN-public), [constraint docs](https://align-analoglayout.github.io/ALIGN-public/notes/const.html) | Hierarchical block assembly; SymmetricBlocks, Align, Order, Enclose, Spread | Functional macros and explicit, separately validated constraints | ALIGN mock-PDK geometry or its PCell-only importer is valid for a post-ring Virtuoso design |
| [MAGICAL](https://github.com/magical-eda/MAGICAL) | Separate constraint/placement/routing components; symmetry groups, paired/self-symmetric devices, net symmetry | Preserve groups and distinguish geometric symmetry from net/pin symmetry | Device symmetry alone certifies electrical matching; benchmark parameters are foundry rules |
| [OpenROAD Hier-RTLMP](https://github.com/The-OpenROAD-Project/OpenROAD/tree/master/src/mpl), [maintained README](https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD/master/src/mpl/README.md) | Hierarchical macro placement, per-macro halos, fences, area/wirelength objectives | Include ring/well outer envelope, explicit reservations, compare area and pin-span cost | Digital placer cost defaults or simulated-annealing weights transfer to analog |

MAGICAL links IdeaPlaceEx as a submodule at commit `a727c346648ad97512376f0b4277e11e16b79124`; direct submodule code retrieval was unavailable in this research pass. No claims about its implementation internals are used.

## Local integration decision

Revisited 2026-09-26: [ALIGN Order/Align documentation](https://align-analoglayout.github.io/ALIGN-public/notes/const.html) distinguishes ordering from alignment; [OpenROAD macro placement](https://openroad.readthedocs.io/en/latest/main/src/mpl/README.html) supports per-macro directional halos. Adopted here: retain order and physical axis constraints independently, audit directional pair-specific channel budgets, and add a whole-stack compaction proposal. No upstream numeric defaults or source code copied; the new standard-library proposal is not claimed to implement either upstream solver.

The existing ALIGN optimizer already translates rigid device groups, but its placement intent is PCell-oriented. After guard-ring generation, ownership expands to conductive shapes, well fill, ROD children, pins and local connections. Reusing only the old intent would leave these behind. This skill therefore introduces a complete post-ring object manifest and translation-only contract. It does not replace upstream dummy-orientation or contact-sharing logic.

The first engine is a deterministic bounded beam search with neighbor-edge anchors and affine movement groups, not a port of ALIGN/MAGICAL/OpenROAD and not a globally optimal MILP solver. Standard-library implementation avoids adding a solver dependency to the user's bridge environment. More advanced search can replace proposal generation without relaxing the invariant validator.
