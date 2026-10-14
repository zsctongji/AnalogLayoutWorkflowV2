# Design references (reviewed 2026-09-27)

- [Netgen source](https://github.com/RTimothyEdwards/netgen/blob/master/tcltk/netgen.tcl.in): comparison reporting includes structured JSON conversion. Adopt structured discrepancy/evidence records rather than treating a console success word as sufficient. Do not replace the foundry Calibre deck with Netgen or claim Netgen automatically repairs Virtuoso geometry.
- [KLayout repository](https://github.com/KLayout/klayout) and [LVS database documentation](https://klayout.org/downloads/master/doc-qt4/manual/lvs_io.html): an LVS database combines extracted layout connectivity, reference netlist and object cross-reference. Adopt explicit circuit/net/device/pin mapping before geometry edits; a nearby marker is not causal ownership.
- Existing `analog-layout-drc/references/symmetric-repair.md` and `scripts/symmetric_repair.py`: adopt new-target transactions, full readback and frozen symmetry scopes. Reuse its rectangle/cut geometry primitives. LVS additionally needs controlled creation/deletion, an expected connectivity delta and both LVS/DRC rechecks; the DRC update-only controller is not reused as an LVS repair engine.

These are architectural inspirations, not copied routing algorithms or proven site adapters. No project is installed and no proprietary PDK is redistributed.
