# Installation

Use a source checkout and Python 3.11+. Install the frontend with `python -m pip install -e .`; use `.[dev,analysis]` to run all repository checks and offline suites. The optional analysis dependencies support parasitic kernels and report output. A frontend-only wheel does not embed the skill collection; use `ALFLOW_ROOT` to point it to a source checkout.

On Windows call `.venv/Scripts/python.exe` and `.venv/Scripts/alflow.exe` directly. On Linux/macOS use `.venv/bin/python` and `.venv/bin/alflow`. Shell activation is optional.

## Skill installation

`scripts/install_skills.py` installs the full sibling skill set into `~/.codex/skills` by default. Use `--dry-run` to inspect changes or `--destination PATH` for a separate directory. Conflicting existing distributed files block the entire preflight; use `--replace` to back up and replace those files. Backups are under the destination's `.analog-layout-flow-backups` directory. Unrelated user files are preserved; failed copies restore the overwritten distributed files.

After installation, use the agent application's normal skill refresh/discovery mechanism. The installer does not change model settings, application preferences or live EDA state.

## Bridge installation

Install `vendor/virtuoso-bridge-lite` in the same environment when actual Virtuoso access is needed. Keep its original license. Copy the connection field template into a private `local/bridge.env`, fill actual values, and configure the bridge using its supported environment-file interface. `alflow doctor` inspects local availability; it does not prove daemon/simulator readiness.

Before live operations follow [the bridge skill](../skills/operate-virtuoso-bridge/SKILL.md), including daemon status and a successful SKILL round trip. Simulator discovery, licenses, models and extraction qualification are separate checks.

## GitHub setup

The delivered directory is a local Git checkout on `main`. Review the source and license status, commit the desired files, create the intended remote repository, then set the actual remote URL and push. Filled configuration and generated artifacts remain ignored. No GitHub account, repository visibility or remote URL is assumed by this package.
