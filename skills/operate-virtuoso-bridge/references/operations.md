# Operations reference

## Windows commands

Run from the checkout:

```powershell
$vb = ".\.venv\Scripts\virtuoso-bridge.exe"
& $vb status
& $vb eval "1+2"
& $vb windows
& $vb snapshot
& $vb screenshot
& $vb load ".\path\script.il"
```

Prefer direct executables because `Activate.ps1` may be blocked. If activation is useful, limit the bypass to the current process:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Use ASCII quotes. PowerShell single quotes are convenient around SKILL containing double quotes.

## SKILL strings and symbols

Quote literal library, cell, and view names. An error such as `*Error* eval: unbound variable - analogLib` means SKILL parsed `analogLib` as a variable, not that the library is missing.

```skill
ddGetObj(analogLib)      ; wrong: reads an unbound variable
ddGetObj("analogLib")    ; correct: passes a library-name string
ddGetObj("analogLib" "res")
```

Use `'analogLib` only when an API explicitly expects a symbol. If `ddGetObj("analogLib")` returns `nil`, investigate library availability or `cds.lib`; do not diagnose an `unbound variable` error as a missing library.

## Python client

```python
from virtuoso_bridge import VirtuosoClient

client = VirtuosoClient.from_env()
ready = client.ensure_ready()
if not ready.ok:
    raise RuntimeError(ready.errors)

result = client.execute_skill("1+2")
if not result.ok:
    raise RuntimeError(result.errors)
print(result.output)
```

Pin an explicit env file when running outside the checkout or from a long-lived process:

```python
from virtuoso_bridge.env import set_runtime_env_file
set_runtime_env_file(r"C:\path\to\virtuoso-bridge-lite\.env")
```

## Active design query

```skill
let((cv)
  cv = geGetEditCellView()
  if(cv
    list(cv~>libName cv~>cellName cv~>viewName)
    nil
  )
)
```

Database objects exist only inside Virtuoso. Convert returned data to strings, numbers, or lists before expecting Python to consume it.

## Common states

```text
tunnel down, daemon unavailable  -> start bridge
tunnel running, daemon no response -> load generated setup in CIW
daemon user mismatch -> stop and investigate; do not override silently
connection refused after VM reboot -> verify ens33 IP and update .env
modal dialog blocks CIW -> inspect list-windows; dismiss only the identified dialog
Spectre NOT FOUND -> SKILL operations still work; configure Cadence environment only for simulation
```

## File boundaries

- `.il` uploaded by `load` executes in the VM's Virtuoso session.
- Files produced by SKILL or Maestro remain on the VM until downloaded.
- Stage local inputs before invoking remote tools.
- Verify existence, size, and expected content after transfers.
