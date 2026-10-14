# Native Virtuoso gate contacts

Apply the [unified save policy](../../analog-layout-workflow/references/save-policy.md) first: reuse the same working layout by default. New-target/absent-target procedures in this document apply only to initial target creation or explicitly requested staged archives/Save As. Legacy CLI clone restrictions are capability boundaries, not reasons to create stage archives automatically. In-place transactions still require saved-baseline checks, protected-object preservation and complete readback.

Users may create gate contacts directly with Virtuoso layout hotkeys. Automated operations also prefer the same native command or a documented corresponding via API. Use explicit rectangle generators for supplemental wiring or fallback situations within their capabilities.

## Live bindings and creation

Query the current binding through the bridge in read-only mode:

```lisp
hiGetBindKey("Layout" "<Key>o")
```

At this IC618 site, the query returned `leHiCreateVia()`, so pressing **O** in the layout window starts Create Via. This is a site observation; other sessions may have custom bindings. Do not modify user bindkeys. The bridge may invoke a confirmed native command to enter the same interactive function, with actual form operations through available UI tools. Use only verified APIs for batch database operations.

1. Reuse the authorized source, new target and save mode; operate in the exact target layout window.
2. Select the poly→M1 viaDef in the actual technology. This `ntc1132` site uses `PO1_M1`, with observed parameters: cut `0.45×0.45µm`, poly enclosure `0.25µm`, M1 enclosure `0.18µm`. Reread other PDKs/revisions instead of reusing these values.
3. Set the required single-cut/array configuration, orientation and position relative to the actual gate pin island. Ensure the lower landing connects to native gate poly, adding legal poly extensions when needed. The upper landing must connect continuously to a short M1 escape. Multiple cuts from one command do not prove connection to multiple disconnected gate islands.
4. Retain actual nets, functional modules, matching axes and declared pair mappings. Reuse legal existing gate contacts; hotkey use does not require rebuilding verified contacts.

## Noninteractive dispatcher entry point

`scripts/native_gate_adapter.py --handoff handoff.json --out receipt.json` calls built-in `dbCreateVia(cellview viaDef origin "R0")` through `NativeGateBackend`, without interactive forms or simulated keys. First obtain the actual viaDef using `techFindViaDefByName`. The currently verified profile is single-cut `PO1_M1` without overrides; its actual virtual master has three rectangles: cont, poly1 and mt1. Parameters and geometry must still be read at the site.

Register hashes of the entry point, interpreter, execution dependencies and live qualification in registry. `state.dispatch_inputs["gate-access"].native_gate_request` is `{path,sha256,host:"local"}`, with JSON containing bridge_env, source_snapshot_sha256, verified gate records and qualification-file references. The dispatcher passes corresponding stage inputs in `handoff.stage_inputs`. Reuse the authorized new target without overwriting the source layout.

The replacement adapter accepts verified contacts only. The original cut/poly/M1 shapes must exactly equal native-via expanded geometry layer by layer, with matching actual nets/owners. Preserve original poly stems, M1 escapes, devices, shared active diffusion and rings during planning; remove optional auxiliary shapes for the contact according to the user's conopc choice. After complete candidate checks, batch-create native vias, bind nets/stable root IDs and delete replaced custom shapes at stage end. Save once after full readback passes. Normalize computed floating-point centers to site coordinate precision, then check all expanded geometry without relaxing comparison tolerances. This entry point is not a new-contact planner for missing gate islands and does not support arbitrary via arrays/overrides.

Read back all actual primitives using `via~>viaHeader~>master~>shapes` and `dbTransformBBox`, and check actual via-root nets. Retain root and actual expanded-shape records; do not label primitives as independent top-level rectangles. On failure, undo only this stage's unsaved changes and verify restoration to the same working target's saved baseline. Unknown save status requires read-only diagnosis. Do not automatically switch to a new stage target; retain baseline scratch copies and follow agreed naming only for explicit staged mode.

## Readback and handoff

Native commands generate PDK-defined contact shapes, but actual placement still requires connectivity/spacing checks. Record stable semantic via-root ID, owner, viaDef, origin, orientation and override parameters, plus every actual expanded cut and upper/lower landing. Check grid, enclosure, foreign-net spacing, gate-poly continuity, M1 escapes and required symmetry from actual geometry. A via bbox or successful operation alone cannot establish these checks.

Current `local_access.py` and the workflow rectangle backend do not fully represent native vias. Native-via adapters must provide actual via/primitive readback and qualification evidence, or feed complete actual rectangular cuts/landings to an appropriate checker. Do not omit vias from snapshots or present native vias as top-level rectangles. Reference the current saved revision and actual checks when generating guard-ring gate-contact-review. For subsequent complete-macro movement, assign every via root to its macro and move it once, without translating generated shapes again.

Layouts with qualified existing contacts are not automatically modified when this skill's operating method changes. Record local verification and whole-circuit foundry DRC/LVS separately.
