# Site-owned bridge environment

Use the bundled bridge at `vendor/virtuoso-bridge-lite` or an explicitly configured compatible checkout. Install its dependencies in the chosen Python environment and keep filled connection settings in `local/bridge.env`. No host, user, project path or generated daemon path is bundled.

Resolve the current SSH host/user/ports, remote design workspace and Virtuoso version from site configuration. Use the bridge `status` command to obtain the current CIW setup path; temporary generated files may disappear after reboot. The bridge is ready only after daemon status is healthy and `eval "1+2"` returns `3`. Probe Spectre independently; a simulator-discovery failure does not prove the Virtuoso daemon failed.

On Windows use the executable in `.venv/Scripts`; on Linux use `.venv/bin`. The repository's `.env.template` describes unset fields. A filled bridge environment is a local project input, not a source-controlled artifact.
