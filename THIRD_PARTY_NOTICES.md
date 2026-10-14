# Source and third-party notices

The workflow skills are a source export of the local analog layout skill collection, including the fast mirrored-template backend and joint symmetric search backend. Repository maintenance adds a small CLI, installer, validation scripts, documentation and CI configuration. File origins and packaged hashes are recorded in [docs/source-manifest.json](docs/source-manifest.json).

The vendored `virtuoso-bridge-lite` component retains its original MIT license and copyright attribution to its original authors. Its upstream source and license are preserved; it is not claimed as original workflow implementation.

ALIGN, MAGICAL and other routing/design projects may be referenced by skill documentation as research background. A skill named ALIGN-style placement does not establish that ALIGN-public is installed, bundled or executed. Referencing a project does not import its code, license or process qualification. Preserve any additional attribution when introducing third-party code in future changes.

The repository does not contain proprietary EDA tools, foundry decks, device model libraries, captured reference layouts or actual circuit examples. Small synthetic RC fixture files are retained only for parser/kernel regression tests.
