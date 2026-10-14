# Optional reference comparison and primary sources

Use only a reference explicitly provided or selected for the current project. Record its exact cellview, saved revision, capture path/hash and read-only inspection scope in the project run, never in this reusable skill. Resolve names against the current library rather than assuming a previous project's naming or a local user's filesystem path.

Separate ordinary routing from PCell contacts, rings, annotations and labels before comparing layers or H/V counts. Net properties or visual resemblance do not prove continuity, full-net symmetry, DRC/LVS, or equivalence to the current target. Derive dimensions/tracks from current geometry and PDK rules; reference coordinates are examples, not defaults. Unavailable captures cannot support renewed inspection claims and do not prevent unrelated template compilation.

Optional primary-source background:

- [MAGICAL anaroute](https://github.com/baloneymath/anaroute): inspect its actual interfaces if comparing symmetry-aware routing inputs.
- [ALIGN](https://github.com/ALIGN-analoglayout/ALIGN-public) and [constraint documentation](https://align-analoglayout.github.io/ALIGN-public/notes/const.html): consult when establishing electrical pin correspondence and placement/routing handoffs.
- [AnalogDetailedRouter](https://github.com/ALIGN-analoglayout/AnalogDetailedRouter): optional detailed-routing background, not a dependency or local-PDK qualification.

This skill retains the route spec/intent, complete-island connectivity and SVG/readback chain while generating bounded straight/L/U/bus templates with exact mirror expansion. It does not install/run these external solvers, reproduce their algorithms, or obtain foundry signoff from reference layouts. Research is optional and is not repeated on every run.
