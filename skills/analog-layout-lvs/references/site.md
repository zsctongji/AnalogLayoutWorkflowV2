# Site-specific LVS integration

Supply current executable, independent schematic/config netlisting, layer map, foundry deck, process/metal options, device mapping and supply recognition through private site/project configuration. Validate the effective wrapper/include branches and actual execution logs; file extensions and similar names do not prove source identity or independence. Original PDK/deck files remain unchanged.

Export a fresh saved layout and independently netlist the schematic using the current site's supported flow. For Cadence analog netlisting, verify `CDS_Netlisting_Mode=Analog` where applicable, use an isolated `si.env`, and retain immutable inputs/commands/raw reports. Run-local overrides require an actual project basis; do not guess global power names or choose a modified deck by filename alone.

A report comparing source and layout from the same data is `INVALID_COMPARISON`, even if it says CORRECT. Preserve mapping/include/unused-device warnings. Stub models are allowed only with explicit foundry/device-map evidence. Inspect existing conditional SVDB/output declarations before adding wrapper directives. Report parsing or export/check evidence does not qualify OA mutation/rollback.

The bundled Nuvoton adapter retains its named capability boundary and requires an explicit external site profile. No historical run, captured cell or filled site profile is supplied by this repository. Another PDK needs its own reviewed adapter, rules and registration evidence.
