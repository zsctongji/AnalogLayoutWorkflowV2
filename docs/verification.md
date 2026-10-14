# Verification

## Offline checks

`scripts/check_repository.py` checks source layout, skill frontmatter, maintained English Markdown, local documentation links, Python syntax, packaged provenance hashes and known private-data signatures. `--allow-modified` skips snapshot hashes while retaining the structural checks. The scan is scoped and does not prove absence of every possible secret.

`scripts/run_tests.py` runs repository and skill suites in isolated subprocesses because several legacy helpers share module names. Synthetic RC netlists under the parasitic parser's test fixtures are retained as unit-test inputs. No real circuit examples or historical simulation results are included.

GitHub Actions uses Windows/Linux and Python 3.11/3.12. It installs offline dependencies and runs repository checks, tests and read-only CLI inspection. CI does not connect to Virtuoso or execute Calibre/Spectre; successful CI is not native capability qualification or foundry closure.

## Live checks

The registry binds reviewed adapter/interpreter/dependency hashes and current site qualification. Empty templates register no capability. Stage receipts bind exact handoffs, saved revisions, input fingerprints, current results and independent readback. A successful process exit or database save without matching evidence does not advance the workflow.

Qualify native contact/PCell/ROD/via/port capabilities separately from generic rectangle transactions. Preserve unknown conditional-rule and unsupported-geometry results. DRC CLEAN and independent LVS VERIFIED_MATCH must refer to the same current saved revision before claiming physical/electrical closure. Exploratory extraction retains explicitly accepted limitations and does not manufacture signoff.

PEX/post-simulation additionally requires extracted DUT identity/ports, model/include closure, adopted corners/stimuli and valid metric definitions. Without limits, report measurements. Requalify changed adapter code and PDK/tool interfaces; do not reuse source-export hashes as live qualification.

## Packaged source provenance

`docs/source-manifest.json` lists every packaged source file except itself, with SHA-256 and a source category. It contains no absolute private source path. Vendored bridge license/attribution remain intact. Existing license status is preserved rather than assigning a new blanket license.
