---
name: analog-layout-diffusion-share
description: Implement shared MOS diffusion for terminals on the same net within the same functional module, including dummies and multi-device chains. Check actual geometry and connectivity after implementation.
---

Follow [save-policy.md](../analog-layout-workflow/references/save-policy.md): by default, every stage updates the same working `lib/cell/layout`, with save and readback at the end of each stage. Create stage-specific targets only when the user explicitly requests staged archives or Save As. Legacy clone-only/absent-target limitations do not authorize automatic archives; retain candidates and report a capability blocker when no qualified in-place transaction is available.

Follow [stage-writes.md](../analog-layout-workflow/references/stage-writes.md): planning and candidate checks do not write to CAD. Collect the complete stage object/shared-chain/move list, apply it in one batch at the end of the stage, save once, then perform independent readback. Reads must not implicitly commit pending writes. Reuse valid live qualification and unchanged evidence.


# Analog diffusion sharing

Use the saved schematic and current placement to implement shared diffusion. Read [procedure.md](references/procedure.md) when planning or applying geometry.

## Sharing rule

**Terminals on the same nonempty net and in the same functional module may share diffusion.** Modules include a differential pair, current mirror, bias mirror or output stage and its associated dummies. Different modules remain separate even when they share a supply net.

Apply this rule to adjacent devices, the central boundary between left/right halves, and multi-device chains. Do not stop at disjoint pairs or omit a central edge because a middle device already shares on its other side. Dummy finger counts or dimensions need not equal active-device dimensions; preserve the schematic dimensions and nets.

The default eligibility policy is `same_net_same_module`. Do not require a separate Calibre pair fixture, prequalified overlap-isolation booleans, or foundry DRC/LVS before implementing an eligible edge. Same-net/module eligibility authorizes construction; it does not constitute a verification result.

## Implementation and checks

1. Resolve terminal nets and module ownership. `scripts/inspect_pairs.py` inventories same-source MOS pairs and marks same-module pairs `SHARE_ELIGIBLE`. Resolve unknown ownership; do not infer it from a common supply.
2. Use live PCell geometry to choose orientation and spacing that merge the intended diffusion/contact region. Keep PDK-supported parameters, identities, W/L/fingers, m=1 copies and matching. Same net alone does not determine spacing or permit arbitrary overlap through another terminal.
3. Place an entire chain with one consistent placement/parameter set per middle device. Preserve the matching axis and balanced dummy environment. Include eligible central edges.
4. Save to the authorized target. Read back actual shared active/contact/landing geometry, dimensions and changed terminal islands. Check continuity, unintended shorts and device recognition on the resulting geometry; repair if needed. Reuse unchanged measurements; run DRC/LVS for the requested completion level.

Use `analog-layout-place.refinement-spec/v1` with `evidence.eligibility_policy: same_net_same_module`. Preimplementation electrical checks may remain pending; never set verification fields true to satisfy an older adapter. The current refiner supports S/S sharing. Other same-net diffusion terminals need a compatible materializer preserving terminal identity.

Keep run artifacts and one workflow summary. Report `MATERIALIZED_UNVERIFIED` until requested checks close; reserve `VERIFIED_SHARED_DIFFUSION` for actual saved geometry with foundry DRC/LVS evidence. Candidate planning requires no signoff run. Skip sharing only when explicitly requested; missing prequalification is not a reason to skip or block construction.
