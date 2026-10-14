# Reuse the PDK profile extractor

Use the Python environment that can import `virtuoso_bridge`.

```powershell
$python = "<analog-agents>\.venv\Scripts\python.exe"
$tool = "<skill-dir>\scripts\pdk_profile.py"
$profile = "<output-dir>\pdk-routing-profile.json"
$report = "<output-dir>\pdk-routing-profile.md"

& $python $tool extract --env <virtuoso-bridge\.env> `
  --lib <source-lib> --cell <source-cell> --view layout `
  --constraint-group foundry --out $profile --report $report

& $python $tool validate $profile
```

The named source cellview is used only to resolve its attached technology file and is opened read-only. The output directory should be local and excluded from public version control unless PDK sharing is authorized.

Agent example:

> Use analog-pdk-profile to extract the `foundry` constraint group from the technology database attached to `mylib/AMP/layout` in read-only mode, and output a PDK routing profile and coverage report without modifying the PDK or layout.

Before routing, validate again and copy the profile fingerprint into the routing intent. Regenerate rather than editing extracted numeric values by hand.
