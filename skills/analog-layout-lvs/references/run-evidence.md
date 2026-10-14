# Evidence required for a verified LVS result

Persist an evidence manifest alongside immutable raw artifacts. Missing data is unknown, not a default pass. Do not accept booleans such as `verified: true` as substitutes for artifacts.

Record:

- Run ID, UTC start/end, remote host, working directory, tool version, exact command and exit code.
- Layout and reference library/cell/view/config, resolved paths, hierarchy revisions/hashes before export and after run. Detect mid-run edits. A top-file-only hash is insufficient for referenced PCells/cells.
- Stream export command/settings, layer map and its SHA256, top cell, units, log, stream SHA256, and independent inspection of top/hierarchy/geometry/labels.
- SPICE exporter settings, view/stop lists, authoritative source revision, CDF/device mappings, include dependency paths and SHA256, output SHA256, top subckt and terminal order. Do not substitute the extracted layout netlist.
- Original deck and transitive INCLUDE dependencies with SHA256, active conditionals/options, run-local wrapper and any explicit changes. Include search paths/environment dependencies matter. A text search for DEFINE is not a complete preprocessor.
- Layout extraction transcript/database and compare transcript; resolved paths, file identity (including aliases) and hashes on the execution host; prove layout input originated in stream extraction.
- Full report, all hierarchical results, extraction/ERC artifacts, raw hashes, no unexamined report caps or truncation; completion and exit status must agree. Timestamps alone do not establish provenance.
- Warning review records with exact evidence, impact, reviewer rationale; blackbox/exclusion/filter/reduction/tolerance scope and any required user approval. Unknown or severe warnings block verified match.

Verified match requires all of the above to agree with the exact target, independent inputs, full hierarchy success, and no unresolved validity issue. Classify accepted limitations separately. If a report only exposes extracted SPICE for its layout name, bind that SPICE to the stream extraction log/database before accepting it; never assume `.sp` necessarily means an invalid run.

Do not automatically accept identical content hashes as proof of self-comparison when genuinely independent extractions can be evidenced. Conversely, different hashes do not prove independence. The observed same-data warning and identical resolved input object are hard failures for layout-vs-schematic verification.
