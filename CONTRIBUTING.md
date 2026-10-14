# Contributing

Keep project-specific circuit identities, PDK rules and local tool/deck/model paths in external configuration. Preserve electrical intent, declared matching scope and revision binding. Do not copy historical coordinates, supplied waivers or PDK qualification into generic defaults.

Run these checks before submitting a change:

```bash
python scripts/check_repository.py --allow-modified
python scripts/run_tests.py
alflow doctor
alflow skills
```

The packaged source manifest is a snapshot. For a deliberate release, run `python scripts/update_manifest.py` after reviewing the changes; do not edit hashes solely to conceal an unexpected mismatch. Strict repository checks verify that snapshot, while `--allow-modified` permits normal development and still checks structure, metadata, links and exclusions.

A stage adapter must declare inputs, supported targets/objects, preconditions, transaction/save/readback behavior and receipt semantics. Code changes invalidate previous code-bound registration/qualification. Synthetic tests verify their stated invariants; they do not establish foundry closure or qualify live adapters.

Keep credentials, host identities, filled environments, proprietary PDK/deck/model files, native OA/GDS, PEX/PSF and actual project results outside version control. Use synthetic or authorized shareable inputs for regression cases. Preserve third-party authorship and licenses.

Bundled walkthroughs must be freshly authored synthetic offline examples with an `example.json` provenance declaration and end-to-end tests. Keep static acceptance contracts small; write generated candidates/reports to ignored output directories. Mark physical stages that were not executed as `NOT_RUN`, and never present a toy profile as process qualification. See the [worked example](examples/amp_compare_v4/README.md).
