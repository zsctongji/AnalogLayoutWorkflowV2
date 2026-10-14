"""Deterministic refinement proposals; no EDA calls or database mutations."""
from __future__ import annotations

from itertools import combinations
import math
from placement_geometry import center, digest, distance, envelope


FEEDBACK_CODES = {"NO_LEGAL_ACCESS", "CHANNEL_OVERFLOW", "TOPOLOGY_EDGE_BLOCKED",
                  "MATCHED_PAIR_ASYMMETRIC", "VIA_ENVELOPE_BLOCKED"}


def movement_units(intent):
    """Union overlapping groups/macros including their dummies into rigid units."""
    names = sorted(i["name"] for i in intent["instances"])
    owner = {n: n for n in names}
    def root(n):
        while owner[n] != n: n = owner[n]
        return n
    for record in [*intent.get("groups", []), *intent.get("macro_instances", [])]:
        members = {n for row in record.get("rows", []) for n in row}
        members.update(i["name"] for i in intent["instances"] if i.get("group") == record.get("name"))
        members.update(record.get("dummy_copies", []))
        if members - set(owner): raise ValueError("group/macro contains unknown instance")
        if members:
            first = min(members)
            for n in sorted(members): owner[root(n)] = root(first)
    result = {}
    for n in names: result.setdefault(root(n), []).append(n)
    return sorted(result.values())


def feedback_hints(feedback, parent, access, request):
    if not feedback: return []
    if feedback.get("schema") != "analog-layout-align.routeability-feedback/v1":
        raise ValueError("unsupported routeability feedback schema")
    if feedback.get("parent_intent_sha256") != digest(parent) or feedback.get("terminal_access_sha256") != digest(access):
        raise ValueError("stale routeability feedback hashes")
    if feedback.get("target") != request.get("target"):
        raise ValueError("routeability feedback target mismatch")
    known = {i["name"] for i in parent["instances"]}
    result = []
    for item in feedback.get("failures", []):
        if item.get("code") not in FEEDBACK_CODES: raise ValueError("unsupported feedback code")
        members = item.get("affected_instances", [])
        if not members or set(members)-known: raise ValueError("feedback must identify known affected instances")
        extra = item.get("required_extra_clearance_um", 0)
        if not isinstance(extra, (int, float)) or not math.isfinite(extra) or extra < 0:
            raise ValueError("invalid feedback clearance")
        result.append(item)
    return result


def generate_candidates(intent, evaluation, request, hints):
    settings = request.get("search", {})
    grid = intent["coordinate_contract"]["manufacturing_grid"]
    # Default is a search step, not a PDK spacing rule.
    step = settings.get("step_um", grid)
    if not isinstance(step, (int, float)) or not math.isfinite(step) or step <= 0 or abs(step/grid-round(step/grid)) > 1e-7:
        raise ValueError("step_um must be positive and on grid")
    records = {i["name"]: i for i in intent["instances"]}
    locked = set(settings.get("locked_instances", []))
    if locked-set(records): raise ValueError("unknown locked instance")
    units = movement_units(intent)
    unit_for = {n: u for u in units for n in u}
    proposals = []
    def add(names, dx, dy, reason, priority):
        if locked.intersection(names) or (dx == 0 and dy == 0): return
        proposals.append({"priority": priority, "reason": reason, "affected_instances": names,
                          "spec": {"schema": "analog-layout-align.refinement-spec/v1",
                                   "metadata": {"reason": reason}, "operations": [{"op": "translate",
                                       "selector": {"names": names}, "dx": dx, "dy": dy}]}})
    # Coarse topology moves escape the microscopic-step/right-shelf local minimum.
    # Caller supplies a planning gap, not a fabricated PDK spacing rule.
    gap = settings.get("macro_relocation_gap_um")
    if gap is not None:
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap <= 0:
            raise ValueError("macro_relocation_gap_um must be finite and positive")
        gap = math.ceil(gap / grid) * grid
        weights = request.get("constraints", {}).get("critical_net_weights", {})
        core = set(intent.get("floorplan", {}).get("core_macros", []))
        for unit in units:
            if any(records[n].get("group") in core for n in unit):
                continue  # preserve core floorplan; move peripheral units only
            own_nets = {net for n in unit for net in records[n].get("terminals", {}).values()}
            bb = envelope([records[n]["bbox"] for n in unit])
            for anchor in units:
                if anchor == unit: continue
                anchor_nets = {net for n in anchor for net in records[n].get("terminals", {}).values()}
                shared = sorted(net for net in own_nets & anchor_nets if weights.get(net, 0) > 0)
                if not shared: continue
                ab = envelope([records[n]["bbox"] for n in anchor])
                bc, ac = center(bb), center(ab)
                offsets = [(ab[0][0]-gap-bb[1][0], ac[1]-bc[1]),
                           (ab[1][0]+gap-bb[0][0], ac[1]-bc[1]),
                           (ac[0]-bc[0], ab[0][1]-gap-bb[1][1]),
                           (ac[0]-bc[0], ab[1][1]+gap-bb[0][1])]
                for dx, dy in offsets:
                    add(unit, round(dx/grid)*grid, round(dy/grid)*grid,
                        "critical-net macro relocation: " + ",".join(shared), 2)
    # Capacity deficit gives directed expansion proposals, preserving each rigid group.
    for ch in evaluation.get("channels", []):
        if ch.get("overflow") is not True: continue
        a, b = ch["members"]
        if unit_for[a] == unit_for[b]: continue
        move = max(step, math.ceil((ch["required_width_um"]-ch["width_um"])/grid)*grid)
        axis = ch["across_axis"]
        add(unit_for[a], -move if axis == 0 else 0, -move if axis == 1 else 0, "expand overloaded channel "+ch["channel_id"], 0)
        add(unit_for[b], move if axis == 0 else 0, move if axis == 1 else 0, "expand overloaded channel "+ch["channel_id"], 0)
    blocked = {r["instance"] for r in evaluation.get("accesses", []) if r["access_risk"] == "blocked"}
    hinted = {n for h in hints for n in h["affected_instances"]}
    for unit in units:
        priority = 1 if blocked.intersection(unit) or hinted.intersection(unit) else 3
        reason = "pin-escape/route-feedback refinement" if priority == 1 else "rigid-unit local search"
        local_step = max([step]+[math.ceil(h.get("required_extra_clearance_um", 0)/grid)*grid for h in hints if set(h["affected_instances"]).intersection(unit)])
        for dx, dy in ((local_step, 0), (-local_step, 0), (0, local_step), (0, -local_step)):
            add(unit, dx, dy, reason, priority)
    # Equivalent standalone parallel copies can exchange slots without changing identities.
    singletons = [u[0] for u in units if len(u) == 1 and not locked.intersection(u)]
    for a, b in combinations(singletons, 2):
        x, y = records[a], records[b]
        if any(x.get(k) != y.get(k) for k in ("logical_device", "pcell_master", "pcell_parameters", "terminals", "orientation")):
            continue
        if x.get("group") or y.get("group"): continue
        delta = [y["origin"][k]-x["origin"][k] for k in (0, 1)]
        proposals.append({"priority": 4, "reason": "exchange equivalent parallel copies", "affected_instances": [a, b],
                          "spec": {"schema": "analog-layout-align.refinement-spec/v1", "operations": [
                              {"op": "translate", "selector": {"names": [a]}, "dx": delta[0], "dy": delta[1]},
                              {"op": "translate", "selector": {"names": [b]}, "dx": -delta[0], "dy": -delta[1]}]}})
    unique = {}
    for p in sorted(proposals, key=lambda p: (p["priority"], p["reason"], digest(p["spec"]))):
        unique.setdefault(digest(p["spec"]["operations"]), p)
    return list(unique.values())
