# amp_compare_v4: synthetic offline walkthrough

A runnable example of building layout scripts from external configuration and the
workflow contracts. The historical case inspired the `config / netlists / work /
reports` organization and functional module partition. All bundled devices,
geometry and rules are newly authored synthetic inputs. No historical design,
foundry file, native result or site credential is included.

## Run from a fresh checkout

Python 3.11 or newer is sufficient for the example itself. From the repository root:

```bash
python examples/amp_compare_v4/work/run_example.py
```

Results go to ignored `outputs/amp_compare_v4/`. Existing output directories are
refused, preserving the previous evidence. Choose a fresh location for each run:

```bash
python examples/amp_compare_v4/work/run_example.py --out outputs/amp_compare_v4_second
```

A successful run prints `OFFLINE_EXAMPLE_PASS`. Read the generated
`reports/result.json` and `reports/summary.md`; inspect `work/plan/placement.svg`
and `work/routing/symmetric-fast/preview.svg`. These are offline candidates.
Every result retains `materializable: false`.

## Inputs and script responsibilities

| File | Purpose |
|---|---|
| [project.json](config/project.json) | Source/target identities, input paths and separate configuration references |
| [pdk-map.json](config/pdk-map.json) | Typed parameter/terminal mapping, actual metal levels, layer roles and explicitly synthetic geometry/vias |
| [circuit.json](config/circuit.json) | Module ownership, dummy ownership, complete copy rows, orientations and common-axis floorplan |
| [routing-policy.json](config/routing-policy.json) | Topology, net classes, widths, local budgets, channel pitches and bounded track enumeration |
| [schematic.json](inputs/schematic.json) | Authoritative logical devices, parameters and connectivity |
| [synthetic-schematic.sp](netlists/synthetic-schematic.sp) | Human-readable connectivity illustration; toy models are intentionally undefined |
| [prepare_inputs.py](work/prepare_inputs.py) | Generate synthetic geometry/access and call reusable `configured_flow.prepare/place` |
| [build_route.py](work/build_route.py) | Derive pin orbits/tracks and assemble a **complete** `seed_spec` using shared fast-routing helpers |
| [run_example.py](work/run_example.py) | Sequence the offline stages and preserve PASS/BLOCKED evidence |
| [expected.json](reports/expected.json) | Small acceptance contract used by the end-to-end tests |

The logical fixture is a two-stage amplifier-like connectivity graph with 13
logical devices expanded into 29 `m=1` PCell copies, four MOS modules and a
compensation capacitor. It is not a sized or simulated amplifier design.

| Module | Active row order | Dummy owner |
|---|---|---|
| BIAS | NREF, NTAIL, NSINK, NSINK, NTAIL, NREF | ND_BIAS |
| INPUT | NIN, NIP, NIP, NIN (ABBA) | ND_INPUT |
| LOAD | PLOAD, PREF, PREF, PLOAD (ABBA) | PD_LOAD |
| OUTPUT | PDRIVE, PDRIVE in each of two rows | PD_OUTPUT |
| COMPENSATION | CCOMP | None |

Dummies occupy the ends of their configured MOS rows. `A/B` in the reusable
explicit-pattern checker follows the sorted active logical identities.

## How the routing script is assembled

1. Read placed rectangles and derive all D/G/S/B and capacitor metal pin islands.
   Add six virtual external-port islands, for 120 physical access obligations.
2. Confirm that every observed net is complete and self-reflected around the
   configured axis. ABBA gives each net its own self symmetry; VINP and VINN are
   **not** declared whole-net mirror mates. This example does not check cross-net
   electrical or parasitic matching.
3. Generate bounded vertical M1 escapes. Stagger their M2 fanout elevations by
   measured row position. Derive paired external M3 tracks from the current
   bounds and expanded keepout edges using `generated_tracks`.
4. Use `layered_dogleg` to map horizontal fanouts to the even metal role and
   vertical trunks to the odd role. Add explicit named M1/M2 and M2/M3 transitions,
   terminal tags and one continuous M2 bus per complete net.
5. Write `fast_templates.seed_spec` into the generated routing configuration and
   call `configured_flow.route`. Validate exact pin-island coverage, conductive
   connectivity, widths, direction, symmetry and annotated SVG consistency.
6. Reconstruct the represented metal/cut geometry with the independent symmetric
   audit helper. Check rectangle edge spacing, same/cross-level cuts, full via
   landing coverage, reflected cut arrays and cumulative local M1 budgets. This
   invokes the validator only, without running the joint A* solver.

All nine nets receive real connected geometry. Device/net/layer identities and
absolute tracks are absent from the route algorithm; they come from its inputs.
The generator is reusable within its documented self-symmetric external-fanout
topology. New topologies, richer obstacles, other device pin geometries or other
layer sequences require another recipe or the joint/general backend.

The external fanout is intentionally spacious to make contracts and transitions
easy to inspect. The supply widths and generous excursion limit are illustrative.
There is no IR/EM, coupling, parasitic or analog-performance qualification.

## Start here without previous conversation history

Read the [workflow skill](../../skills/analog-layout-workflow/SKILL.md),
[project configuration contract](../../skills/analog-layout-workflow/references/project-configuration.md),
[fast configuration](../../skills/analog-layout-symmetric-fast/references/configuration.md)
and [route-spec contract](../../skills/analog-layout-route/references/routing-contract.md).
Then run this example and inspect the generated seed, intent and audits before
writing a project adapter. Treat this implementation as a worked recipe, with
the shared contracts defining the required inputs and acceptance gates.

To exercise portable data changes, copy this example to a separate directory,
edit its configuration and run:

```bash
python examples/amp_compare_v4/work/run_example.py --example your-synthetic-copy --out outputs/changed-example
```

The runner expects the documented example directory structure. The tests cover
renamed devices/nets/PDK layers, a shifted axis, deterministic rebuilds and
rejection of missing mappings, incomplete policy or broken symmetry.

For a real project, keep filled site data outside version control. Replace the
synthetic geometry/profile/access with fresh measured inputs and qualify the
native diffusion, contact, ring, macro, import and verification adapters. Run
those physical stages before routing against the resulting complete live
obstacles. This script's synthetic snapshots cannot substitute for them.

## Physical stages

Diffusion sharing, native contacts, guard rings, complete-macro optimization,
live import, foundry DRC, independent LVS, PEX and post-simulation are all
`NOT_RUN`. This is a separate offline demonstration, not a workflow checkpoint
that permits those stages to be skipped. It produces no native layout or
simulation receipts. See [report boundaries](reports/README.md).
