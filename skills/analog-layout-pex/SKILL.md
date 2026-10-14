---
name: analog-layout-pex
description: Extract revision-bound Calibre xRC parasitics and run Spectre post-layout simulation with verified DUT substitution and pre/post metric comparisons. Use for PEX, RC extraction and analog post-layout performance checks, not layout repair.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

# Analog Layout PEX / Post-Simulation

Operate on an explicit saved layout, independent schematic reference and testbench. Creating or inspecting a skill does not authorize extraction, simulation, layout edits or edits to an existing ADE session. A request to run PEX/post-simulation permits fresh run-local exports, testbench variants and results, not circuit/PDK changes.

## Execution economy

Select only the requested mode: configuration inspection, extraction, simulation or comparison. Reuse revision-bound LVS/PDK and prior completed extraction when all dependencies and options still match. Read [site.md](references/site.md) for the observed Nuvoton setup; read [measurements.md](references/measurements.md) when preparing or evaluating simulations. Use `operate-virtuoso-bridge` for live CAD access. Do not restart placement/routing or the full analog-design pipeline.

## Flow

1. Resolve layout/reference/testbench/DUT instance and actual saved state. Verify DUT electrical identity, not merely similar names; bind fresh hierarchy, PCells, tech/map, CDF/model includes and extraction/simulation settings by hashes. Reuse `analog-layout-lvs` evidence only for the exact revision. If LVS is unverified or DRC has deferred violations, an authorized exploratory run may proceed with explicit limitations; it is never signoff. A proven open/short/wrong DUT blocks performance interpretation.
2. Qualify the local xRC exporter/runner before using it. Work in a new directory. Preserve PDK originals; copy the LVS/xRC wrapper and modify only recorded run-local extraction directives. Resolve the capacitance/resistance technology include, active process options, unit declarations and include closure. Parameter `.xrc` files are not necessarily standalone decks. Preserve the independent schematic reference; never use extracted SPICE as the LVS source.
3. Execute the version-appropriate recorded extraction stages. Bind OA → stream → extraction DB → emitted netlist/includes, complete logs, commands/version/exit codes, policies and hashes. Confirm effective RC/Spectre settings, all expected ports/devices, parasitic scope and netlist dialect. RC means R+C, not L; do not infer coupling suppression, supply-net exclusion or aggressive reduction from that choice. Review coupling, reduction, grounding and exclusions explicitly. A file's existence or successful exit is insufficient for EXTRACTED_VALIDATED.
4. Independently export the accepted testbench and model/config include closure. Create a run-local variant replacing only the designated DUT, by resolved subckt and terminal order. Preserve external stimuli, bias, load, temperature and model sections. Check no duplicate device/parasitic definitions, recursive includes, stale DUT or dangling ports. Never regex-replace every occurrence of a similar cell name. No silent changes to OA/config/ADE; a distinct extracted view is created only if requested.
5. Probe the actual Spectre executable/version. Run DC operating point first, then only requested applicable analyses with saved signals and complete results. Use fresh private run directories and supported PSF/OCEAN exports; do not parse opaque Maestro databases by guessed schema. Review convergence, device/model/unsupported-parameter warnings and missing/truncated outputs before measuring. No foundry empty-stub LVS netlist is a simulation device model.
6. Compare with schematic simulations under identical conditions and measurement definitions. Missing baseline permits standalone characterization, not a fabricated degradation. Missing acceptance limits permit MEASURED, never PASS. A circuit labelled comparator is not automatically a valid small-signal amplifier. Report each requested metric separately with analysis, units, corner, bias/load, raw evidence and VALID/UNSUPPORTED/INCOMPLETE status.

## States and delivery

Keep extraction and simulation states separate: BLOCKED_CONFIGURATION, EXTRACTION_FAILED/INCOMPLETE, EXTRACTED_VALIDATED; SIMULATION_FAILED/INCOMPLETE, MEASURED, SPEC_PASS/SPEC_FAIL. SPEC_PASS requires all requested applicable metrics valid and explicit adopted limits met at the requested corners. Do not equate post-simulation completion with DRC/LVS/PEX signoff, or nominal deterministic offset with mismatch statistics.

Persist one compact manifest and summary plus immutable raw artifacts: target/reference/testbench revisions, DUT substitution map, original/run deck and dependencies, stream/netlist/model hashes, commands and completion logs, model+RC corner+temperature, analyses/definitions/limits, raw data and metric CSV/JSON, pre/post comparison and limitations. On failure retain evidence and stop at the causal stage; do not weaken extraction, models or measurement definitions to produce a pass.

`scripts/ac_metrics.py` evaluates normalized complex-transfer CSV (`frequency_hz,real,imag`). It reports sampled low-frequency gain, relative -3 dB bandwidth and descending unity crossings. Phase margin is calculated only with explicit `--loop-gain --feedback-sign-confirmed`. It does not parse PSF, validate a testbench or grant signoff. Do not treat its first frequency sample as measured DC gain or a missing crossing as zero.
