# Analog Layout Flow

A reusable skill-based workflow for analog IC placement, contacts, guard rings, routing, physical checks and optional post-layout analysis. It combines agent planning with deterministic Python helpers and site-qualified Virtuoso, Calibre and Spectre adapters.

The repository contains workflow source, contracts, synthetic tests and a vendored Virtuoso bridge. Circuit examples, historical results, native design databases, filled site configuration and foundry files are excluded.

## Workflow

```mermaid
flowchart LR
    S[Saved schematic and PDK] --> P[Placement]
    P --> D[Shared diffusion]
    D --> A[Local contacts and access]
    A --> G[Guard rings]
    G --> M[Macro symmetry and compaction]
    M --> R[Routing]
    R --> V[DRC and independent LVS]
    V --> X[Optional PEX and post-simulation]
    X --> I[Optional performance iteration]
```

Each physical stage uses the authorized working layout, saves at stage end and independently reads back the saved result. Offline candidates and local checks remain distinct from foundry closure. Live capability is specific to the adapter, tool versions and PDK that have actually been qualified.

## Quick start

Python 3.11 or newer is required. From the repository root:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv/Scripts/python.exe -m pip install -e ".[dev,analysis]"
.venv/Scripts/alflow.exe doctor
.venv/Scripts/alflow.exe skills
.venv/Scripts/python.exe scripts/check_repository.py
.venv/Scripts/python.exe scripts/run_tests.py
```

Linux/macOS:

```bash
.venv/bin/python -m pip install -e ".[dev,analysis]"
.venv/bin/alflow doctor
.venv/bin/alflow skills
.venv/bin/python scripts/check_repository.py
.venv/bin/python scripts/run_tests.py
```

`python scripts/alflow.py doctor` also works directly from the checkout. These commands do not contact CAD. Use an editable checkout; a frontend-only wheel needs `ALFLOW_ROOT` pointing to the checkout to discover its skills.

## Routing selection

| Request | Skill | Backend |
|---|---|---|
| No routing method selected | [Fast symmetric templates](skills/analog-layout-symmetric-fast/SKILL.md) | `symmetric_fast` |
| Explicit joint mirrored path search | [Joint symmetric router](skills/analog-layout-symmetric-route/SKILL.md) | `strict_symmetric` |
| Explicit general routing | [General route and shared validation](skills/analog-layout-route/SKILL.md) | `general` |

Explicit choices take precedence. Fast routing uses complete measured straight/L/U/bus templates and exact mirror expansion; the joint backend searches both sides' legality together. Neither a missing template nor a failed search silently changes the backend. Both reuse the routing intent, SVG and qualified application gates.

## Repository layout

```text
skills/                         Workflow skills, helper scripts and synthetic tests
src/analog_layout_workflow/      Offline CLI frontend
scripts/                        Skill installer, repository checks and test runner
tests/                          Frontend and installation tests
config/                         Unfilled registry and site templates
docs/                           Installation, architecture, configuration and verification
vendor/virtuoso-bridge-lite/     Bridge source with its original license
.github/                        Offline CI and contribution templates
```

The canonical stage runtime lives in `skills/analog-layout-workflow/scripts`; the frontend uses it directly. No duplicate runtime copy is maintained under `src`.

## Install the skills

```bash
python scripts/install_skills.py --dry-run
python scripts/install_skills.py
```

The default destination is `~/.codex/skills`. Existing identical files are reused. Conflicting files block the installation before writing; `--replace` explicitly backs up and replaces distributed files while preserving unrelated local files. Use `--destination` for a separate local skill directory. See [installation](docs/installation.md).

## Configure EDA and a PDK

Install the bridge only for live operations:

```bash
python -m pip install -e vendor/virtuoso-bridge-lite
```

Create private settings under `local/` from `.env.template` and `config/`. Supply the actual project, device/parameter mappings, layer stack, native contact/ring recipes, tools, decks and models. An empty registry grants no execution capability. See [configuration](docs/configuration.md) and [verification](docs/verification.md).

The bundled Nuvoton check adapter retains a specific capability boundary and requires an external site profile. It is not a universal PDK adapter. Configuration portability does not establish live writer, DRC/LVS or extraction qualification.

## Development and publishing

See [CONTRIBUTING.md](CONTRIBUTING.md). GitHub Actions runs offline checks and tests on Windows/Linux with Python 3.11/3.12; it never invokes proprietary EDA software. [The source manifest](docs/source-manifest.json) records the packaged file hashes and origins.

To publish this local checkout, create the intended GitHub repository and add its actual URL as the Git remote. This source bundle does not create or push a remote repository. Preserve [license status](LICENSE.md) and [third-party notices](THIRD_PARTY_NOTICES.md); no new project-wide open-source license is assigned by packaging.
