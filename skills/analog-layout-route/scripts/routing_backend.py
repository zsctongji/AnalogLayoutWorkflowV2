"""Access selection, topology routing and coupled guidance behind route-spec/v1."""
import copy
import math


def state(terminal):
    return (*terminal["xy_um"], terminal["route_layer"])


def via_boxes(via, x, y):
    g = via["geometry"]
    cut, spacing = g["cut_size_um"], g.get("cut_spacing_um", [0, 0])
    rows, columns = int(g.get("rows", 1)), int(g.get("columns", 1))
    if rows < 1 or columns < 1 or min(cut) <= 0 or not all(math.isfinite(float(v)) for v in cut + spacing):
        raise ValueError("invalid normalized via array")
    w = columns * cut[0] + (columns - 1) * spacing[0]
    h = rows * cut[1] + (rows - 1) * spacing[1]
    boxes = []
    for layer, key in ((via["lower"], "layer1_enclosure_um"), (via["upper"], "layer2_enclosure_um")):
        ex, ey = g[key]
        if min(ex, ey) < 0 or not all(math.isfinite(float(v)) for v in (ex, ey)):
            raise ValueError("invalid via enclosure")
        boxes.append((layer, [[x - w / 2 - ex, y - h / 2 - ey], [x + w / 2 + ex, y + h / 2 + ey]]))
    boxes.append((g["cut_layer"], [[x - w / 2, y - h / 2], [x + w / 2, y + h / 2]]))
    return boxes


def via_clear(via, x, y, obstacles, net, spacings, bounds):
    for layer, box in via_boxes(via, x, y):
        if any(box[0][k] < bounds[0][k] or box[1][k] > bounds[1][k] for k in (0, 1)):
            return False
        for obstacle in obstacles:
            if not obstacle.get("hard", True) or obstacle.get("layer") != layer or obstacle.get("net") == net:
                continue
            other, gap = obstacle["bbox_um"], spacings.get(layer, 0.0)
            if all(max(box[0][k] - gap, other[0][k]) < min(box[1][k] + gap, other[1][k]) - 1e-12 for k in (0, 1)):
                return False
    return True


def cost_regions(p, obstacles, net):
    result = []
    for obstacle in obstacles:
        if obstacle.get("hard", True) or obstacle.get("net") == net:
            continue
        if "cost_per_um" not in obstacle:
            raise p.SEARCH.PlanningError("INVALID_COST_REGION", "soft obstacle requires cost_per_um")
        result.append({**obstacle, "cost_per_um": p.SEARCH.nonnegative(obstacle["cost_per_um"], "cost_per_um"),
                       "crossing_factor": p.SEARCH.nonnegative(obstacle.get("crossing_factor", 0.25), "crossing_factor")})
    return result


def configuration(p, profile, raw_obstacles, request, bounds, grid, preferred):
    net = request["net"]
    layers = request.get("layers") or [request.get("layer")]
    layers = list(dict.fromkeys(layers))
    rules = {r["layer"]: r for r in profile["routing_layers"]}
    if not layers or any(layer not in rules for layer in layers):
        raise p.SEARCH.PlanningError("UNKNOWN_LAYER", f"unknown net or routing layers {layers!r}")
    widths, spacings = {}, {}
    for layer in layers:
        minimum = p.unconditional_floor(rules[layer]["minimum_width_rules"], "minimum width")
        widths[layer] = float(request.get("widths_um", {}).get(layer, request.get("width_um", minimum)))
        if not math.isfinite(widths[layer]) or widths[layer] < minimum:
            raise p.SEARCH.PlanningError("ILLEGAL_WIDTH", f"width below {layer} minimum or nonfinite")
        spacings[layer] = p.unconditional_floor(rules[layer]["minimum_spacing_rules"], "minimum spacing")
        # Explicit normalized subset only; native conditional tables remain unknown.
        for rule in rules[layer].get("width_spacing_rules", []):
            if not rule.get("source"):
                raise p.SEARCH.PlanningError("RULE_SOURCE_MISSING", "width_spacing_rules requires source")
            p.SEARCH.nonnegative(rule["min_width_um"], "min_width_um")
            gap = p.SEARCH.nonnegative(rule["spacing_um"], "spacing_um")
            # Conservative for wider foreign wires: use the largest supplied gap.
            spacings[layer] = max(spacings[layer], gap)
    vias = p.via_catalog(profile)
    # Use the same deterministic definition in search and emitted geometry.
    selected = {}
    for via in vias:
        try:
            via_boxes(via, 0, 0)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise p.SEARCH.PlanningError("INVALID_VIA", f"invalid normalized via {via['name']}: {exc}")
        selected.setdefault(tuple(sorted((via["lower"], via["upper"]))), via)
    route_vias = list(selected.values())
    catalog = {v["name"]: v for v in vias}
    rects = {layer: p.expanded_obstacles(raw_obstacles, layer, net, widths[layer], spacings[layer], grid) for layer in layers}
    extra = []
    # Include via-envelope obstacle boundaries in the visibility graph.
    for via in route_vias:
        for layer, box in via_boxes(via, 0, 0):
            for ob in raw_obstacles:
                if ob.get("hard", True) and ob.get("layer") == layer and ob.get("net") != net:
                    b = ob["bbox_um"]; gap = spacings.get(layer, 0)
                    extra.extend(((p.snap_down(b[0][0] - box[1][0] - gap, grid), p.snap_down(b[0][1] - box[1][1] - gap, grid)),
                                  (p.snap_up(b[1][0] - box[0][0] + gap, grid), p.snap_up(b[1][1] - box[0][1] + gap, grid))))
    # Route-scale default: grid-only penalties become negligible on large nets.
    # Explicit bend_cost_um still takes precedence, including zero.
    default_bend = max(grid, min(widths[layer]+spacings[layer] for layer in layers))
    weights = (float(request.get("via_cost_um", 2.0)), float(request.get("bend_cost_um", default_bend)),
               float(request.get("off_direction_penalty", 0.25)))
    for value in weights: p.SEARCH.nonnegative(value, "routing cost")
    guides = request.get("guidance", [])
    weight = p.SEARCH.nonnegative(request.get("guide_weight", 1.0 if guides else 0.0), "guide_weight")
    regions = cost_regions(p, raw_obstacles, net)
    # Dimensionless routing policy, not a width/RC/EM model. Power networks
    # retain zero default area bias to preserve their explicit capacity plan.
    area_default = 0.0 if request.get("net_class") in ("power","ground","high_current","differential","matched") else 0.25
    area_weight = p.SEARCH.nonnegative(request.get("metal_area_weight",area_default),"metal_area_weight")
    reference_width = min(widths.values())
    layer_costs = {layer:area_weight*(width/reference_width-1) for layer,width in widths.items()}
    def evaluate(path):
        return p.SEARCH.evaluate_path(path, preferred, *weights, guides, weight, regions, layer_costs)
    def search(start, goals):
        return p.SEARCH.directional_astar(p, start, goals, rects, bounds,
            p.layer_adjacency(route_vias, layers), {start[:2], *(g[:2] for g in goals)}, grid, weights[0], preferred, weights[2], weights[1],
            guides, weight, regions,
            lambda x, y, name: via_clear(catalog[name], x, y, raw_obstacles, net, spacings, bounds), extra, layer_costs)
    return layers, widths, spacings, vias, route_vias, rects, search, evaluate


def enumerate_access_candidates(p, access, raw, layers, vias, grid, obstacles, net, widths, spacings, bounds, rects):
    resolved = p.resolve_terminal(access, raw, layers, vias, grid)
    instance = next(i for i in access["instances"] if i["name"] == raw["instance"])
    terminal = instance["terminals"][raw["terminal"]]
    if terminal.get("net") != net:
        raise p.SEARCH.PlanningError("WRONG_NET", "generated route spec failed authoritative route-intent preflight: terminal net mismatch")
    island = next(i for i in p.terminal_islands(raw["instance"], raw["terminal"], terminal) if i["id"] == resolved["pin_island_id"])
    centers = [raw["xy_um"]] if raw.get("xy_um") is not None else island["candidate_centers"]
    result = []
    if raw.get("route_layer") is not None and raw["route_layer"] not in layers:
        raise p.SEARCH.PlanningError("UNKNOWN_LAYER", "terminal route_layer is not an allowed net layer")
    for center in sorted({tuple(c) for c in centers}):
        for layer in layers:
            if raw.get("route_layer") is not None and raw["route_layer"] != layer:
                continue
            try:
                candidate = p.resolve_terminal(access, {**raw, "xy_um": list(center)}, [layer], vias, grid)
                landing_half = None
                if candidate["contact"]:
                    contact_via = next(v for v in vias if v["name"] == candidate["contact"]["via"])
                    target_box = dict(via_boxes(contact_via, 0, 0))[layer]
                    landing_half = (max(abs(target_box[0][0]), abs(target_box[1][0])),
                                    max(abs(target_box[0][1]), abs(target_box[1][1])))
                p.legalize_contact_escape(candidate, obstacles, net, widths[layer], spacings[layer], bounds, grid,
                                           landing_half)
            except ValueError:
                continue
            xy = candidate["xy_um"]
            if not all(bounds[0][k] <= xy[k] <= bounds[1][k] for k in (0, 1)) or p.point_blocked(xy, rects[layer]):
                continue
            if candidate["contact"]:
                via = next(v for v in vias if v["name"] == candidate["contact"]["via"])
                if not via_clear(via, *xy, obstacles, net, spacings, bounds): continue
                # Source extension clearance is checked with its full bounding rectangle.
                source = candidate["contact"]["source_layer"]
                boxes = dict(via_boxes(via, *xy)); landing = boxes[source]
                source_box = [[min(landing[0][k], center[k]) for k in (0, 1)],
                              [max(landing[1][k], center[k]) for k in (0, 1)]]
                blocked = any(ob.get("hard", True) and ob.get("layer") == source and ob.get("net") != net
                              and all(max(source_box[0][k], ob["bbox_um"][0][k]) < min(source_box[1][k], ob["bbox_um"][1][k]) for k in (0, 1))
                              for ob in obstacles)
                if blocked: continue
            clearance = min((max(x0 - xy[0], 0, xy[0] - x1) + max(y0 - xy[1], 0, xy[1] - y1)
                             for x0, y0, x1, y1 in rects[layer]), default=max(bounds[1][0] - bounds[0][0], grid))
            candidate["escape_clearance_um"] = clearance
            result.append(candidate)
    if not result:
        raise p.SEARCH.PlanningError("NO_LEGAL_ACCESS", f"no legal access for {resolved['pin_island_id']}")
    return result


def electrical_data(p, request, terminals):
    data = request.get("electrical")
    if data is None: return None
    if not str(data.get("source", "")).strip():
        raise p.SEARCH.PlanningError("ELECTRICAL_DATA_MISSING", "electrical current data requires source")
    ids = [t["pin_island_id"] for t in terminals]
    root = data.get("root_pin_island_id")
    current_map = data.get("sink_currents_a", {})
    if root not in ids or set(current_map) != set(ids) - {root}:
        raise p.SEARCH.PlanningError("ELECTRICAL_DATA_MISSING", "declare one root and a nonnegative current for every sink island")
    currents = [0.0 if i == root else p.SEARCH.nonnegative(current_map[i], "sink_current_a") for i in ids]
    epsilon = p.SEARCH.nonnegative(data.get("epsilon_a", 1e-9), "epsilon_a")
    if epsilon == 0: raise p.SEARCH.PlanningError("INVALID_CURRENT", "epsilon_a must be positive")
    return ids.index(root), currents, epsilon


def choose_access_topology(p, groups, request, search, evaluate):
    k = int(request.get("access_candidate_limit", 4))
    beam_width = int(request.get("access_beam_width", 16))
    frontier_limit = request.get("topology_frontier_limit", 4)
    share_tree = (request.get("shared_tree", True) and not request.get("electrical")
                  and request.get("net_class") not in ("differential","matched")
                  and request.get("target_length_um") is None)
    if k < 1 or beam_width < 1:
        raise p.SEARCH.PlanningError("INVALID_SEARCH_BUDGET", "access limits must be positive")
    def score(candidate, group_index):
        xy = candidate["xy_um"]
        distance = sum(min(abs(xy[0] - c["xy_um"][0]) + abs(xy[1] - c["xy_um"][1]) for c in group)
                       for i, group in enumerate(groups) if i != group_index)
        return (distance, -candidate["escape_clearance_um"], state(candidate))
    groups = [sorted(group, key=lambda c: score(c, i))[:k] for i, group in enumerate(groups)]
    cache = {}
    def cached_search(start, goals):
        key = (start, tuple(sorted(goals)))
        if key not in cache: cache[key] = search(start, goals)
        return cache[key]
    # With one legal access per physical island there is no access choice to
    # optimize.  Building a full topology for every growing prefix is cubic
    # duplicate work on large multi-finger nets; synthesize the final tree once.
    if all(len(group) == 1 for group in groups):
        selected = [group[0] for group in groups]
        electrical = electrical_data(p, request, selected)
        topology = p.SEARCH.synthesize_topology(
            [state(c) for c in selected], cached_search, evaluate, electrical,
            frontier_limit=frontier_limit, share_tree=share_tree,
        )
        return selected, topology, electrical
    beam = [(0, [])]
    for group in groups:
        trials = []
        for _, prefix in beam:
            for candidate in group:
                selected = prefix + [candidate]
                if len(selected) == 1:
                    trials.append((0, selected)); continue
                try:
                    topology = p.SEARCH.synthesize_topology([state(c) for c in selected], cached_search, evaluate,
                                                           frontier_limit=frontier_limit, share_tree=share_tree)
                except p.SEARCH.PlanningError as exc:
                    if exc.code != "TOPOLOGY_EDGE_BLOCKED":
                        raise
                    continue
                trials.append((sum(sum(evaluate(path).values()) for _, _, path in topology), selected))
        if not trials: raise p.SEARCH.PlanningError("TOPOLOGY_EDGE_BLOCKED", "no legal layered rectilinear path")
        beam = sorted(trials, key=lambda t: (t[0], tuple(state(c) for c in t[1])))[:beam_width]
    best = None
    for _, selected in beam:
        electrical = electrical_data(p, request, selected)
        topology = p.SEARCH.synthesize_topology([state(c) for c in selected], cached_search, evaluate, electrical,
                                               frontier_limit=frontier_limit, share_tree=share_tree)
        score_value = sum(sum(evaluate(path).values()) for _, _, path in topology)
        if electrical:
            parents = {child: parent for parent, child, _ in topology}
            lengths = {child: sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(path,path[1:]))
                       for _, child, path in topology}
            score_value = sum(lengths.values()) * electrical[2]
            for sink, current in enumerate(electrical[1]):
                node = sink
                while node in parents:
                    score_value += current * lengths[node]; node = parents[node]
        key = (score_value, tuple(state(c) for c in selected))
        if best is None or key < best[0]: best = (key, selected, topology, electrical)
    return best[1:]


def route_net(p, profile, access, obstacles, request, bounds, grid, preferred):
    layers, widths, spacings, vias, route_vias, rects, search, evaluate = configuration(p, profile, obstacles, request, bounds, grid, preferred)
    raw_terminals = sorted(request.get("terminals", []), key=lambda t: (t["instance"], t["terminal"], t.get("pin_island_id", "")))
    if len(raw_terminals) < 2:
        raise p.SEARCH.PlanningError("MISSING_TERMINALS", "prototype requires at least two terminals")
    groups = [enumerate_access_candidates(p, access, t, layers, vias, grid, obstacles, request["net"], widths, spacings, bounds, rects) for t in raw_terminals]
    if request.get("max_bbox_excursion_um") is not None:
        margin = p.SEARCH.nonnegative(request["max_bbox_excursion_um"], "max_bbox_excursion_um")
        pins = [c["pin_xy_um"] for group in groups for c in group]
        local_bounds = [[max(bounds[0][k], min(xy[k] for xy in pins)-margin) for k in (0,1)],
                        [min(bounds[1][k], max(xy[k] for xy in pins)+margin) for k in (0,1)]]
        # All access candidates contribute to this conservative search window;
        # final selected-access directness is still checked by the intent builder.
        bounds = local_bounds
        layers, widths, spacings, vias, route_vias, rects, search, evaluate = configuration(
            p, profile, obstacles, request, bounds, grid, preferred)
    terminals, topology, electrical = choose_access_topology(p, groups, request, search, evaluate)
    net, routes, placed, contacts = request["net"], [], [], []
    lookup = {frozenset((v["lower"], v["upper"])): v["name"] for v in route_vias}
    paths = [path for _,_,path in topology]
    refinement = {"applied":False,"reason":"preserve electrical/matched/tuned topology or explicit opt-out"}
    if (request.get("shared_tree", True) and not electrical and request.get("net_class") not in ("differential","matched")
            and request.get("target_length_um") is None and len(terminals) > 2):
        paths, refinement = p.TREE.normalize_tree(paths, {state(t) for t in terminals}, evaluate)
    for edge_index, path in enumerate(paths):
        runs, transitions = p.split_layered_path(path)
        for run_index, (layer, points) in enumerate(runs):
            routes.append({"id": f"{net}_branch_{edge_index}_{run_index}", "net": net, "layer": layer,
                           "purpose": "drawing", "width_um": widths[layer], "points_um": points, "access": []})
        for x, y, lower, upper in transitions:
            name = lookup[frozenset((lower, upper))]
            if not any(v["via"] == name and v["xy_um"] == [x, y] for v in placed):
                placed.append({"id": f"{net}_via_{len(placed)}", "net": net, "via": name, "xy_um": [x, y]})
    length = sum(sum(abs(a[0]-b[0])+abs(a[1]-b[1])
                     for a,b in zip(r["points_um"],r["points_um"][1:])) for r in routes)
    target = request.get("target_length_um")
    if target is not None and float(target) > length + grid / 2:
        p.tune_route_length(routes, float(target) - length, obstacles, net, widths, spacings, bounds, grid)
    for index, terminal in enumerate(terminals):
        if terminal["contact"]:
            contacts.append({"id": f"{net}_contact_{index}", "net": net,
                **{key: terminal[key] for key in ("instance", "terminal", "pin_island_id", "pin_xy_um", "xy_um")},
                **terminal["contact"]})
        else:
            touching = [r for r in routes if r["layer"] == terminal["route_layer"] and p.segment_touches(r["points_um"], terminal["xy_um"])]
            if not touching:
                raise p.SEARCH.PlanningError("DISCONNECTED_COMPONENT", "direct terminal is not touched by a generated route")
            touching[0]["access"].append({key: terminal[key] for key in ("instance", "terminal", "pin_island_id", "xy_um")})
    parts = p.SEARCH.empty_cost()
    for route in routes:
        cost = evaluate([(*xy, route["layer"]) for xy in route["points_um"]])
        for key in parts: parts[key] += cost[key]
    parts["via_penalty"] = len(placed) * float(request.get("via_cost_um", 2.0))
    metrics = {"length_um": round(parts["wire_length_um"], 12), "bends": sum(max(0,len(r["points_um"])-2) for r in routes),
        "vias": len(placed), "layers": layers, "cost_breakdown": parts,
        "electrical_data_status": "provided" if electrical else "unavailable",
        "topology_method": "current_weighted_rooted_tree" if electrical else "bounded_cost_shared_tree" if refinement["applied"] else "bounded_cost_frontier",
        "tree_refinement":refinement,
        "effective_bend_cost_um":float(request.get("bend_cost_um",max(grid,min(widths[l]+spacings[l] for l in layers)))),
        "selected_access": [{key:t[key] for key in ("pin_island_id", "pin_xy_um", "xy_um", "route_layer", "escape_clearance_um")} for t in terminals],
        "topology_edges": [{"first": terminals[i]["pin_island_id"], "second": terminals[j]["pin_island_id"],
                            "path_start":list(path[0]), "path_end":list(path[-1]),
                            "role":"electrical_edge" if electrical else "construction_history"}
                           for i,j,path in topology]}
    terminal_points = [t["pin_xy_um"] for t in terminals]
    terminal_span = [max(xy[k] for xy in terminal_points)-min(xy[k] for xy in terminal_points) for k in (0,1)]
    unique = p.TREE.graph_edges([[(*xy,r["layer"]) for xy in r["points_um"]] for r in routes], set())
    unique_length = sum(p.TREE.edge_length(edge) for edge in sorted(unique))
    metrics["directness"] = {
        "terminal_span_um":terminal_span, "terminal_hpwl_um":sum(terminal_span),
        "unique_centerline_length_um":unique_length,
        "duplicate_centerline_length_um":max(0,parts["wire_length_um"]-unique_length),
        "length_over_hpwl":unique_length/sum(terminal_span) if sum(terminal_span) else None,
        "search_bounds_um":bounds,
        "basis":"HPWL is a connectivity lower bound, not an achievable optimum for every multi-terminal net"}
    metrics["drawn_wire_area_um2"] = sum(
        r["width_um"]*sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(r["points_um"],r["points_um"][1:]))
        for r in routes)
    metrics["width_policy"] = "Input/profile widths preserved; area cost selects among allowed layers, not narrower metal."
    if electrical:
        children = {i: [] for i in range(len(terminals))}
        for i,j,_ in topology: children[i].append(j)
        def current(i): return electrical[1][i] + sum(current(j) for j in children[i])
        for edge, (_,j,_) in zip(metrics["topology_edges"], topology): edge["current_a"] = current(j)
        metrics["electrical_source"] = request["electrical"]["source"]
    return routes, placed, contacts, metrics


def reserve_geometry(p, profile, obstacles, routes, vias, request):
    net = request["net"]
    for route in routes:
        additions = p.path_obstacles(route["points_um"], route["layer"], net, route["width_um"], route["id"])
        obstacles.extend(additions)
        protection = request.get("protection")
        if protection:
            margin = p.SEARCH.nonnegative(protection["margin_um"], "protection.margin_um")
            penalty = p.SEARCH.nonnegative(protection["cost_per_um"], "protection.cost_per_um")
            for item, (a,b) in zip(additions, zip(route["points_um"], route["points_um"][1:])):
                box = item["bbox_um"]
                obstacles.append({**item, "id": item["id"] + "/protection", "hard": False,
                    "kind": request["net_class"], "cost_per_um": penalty,
                    "parallel_direction": "horizontal" if a[1] == b[1] else "vertical",
                    "bbox_um": [[box[0][0]-margin,box[0][1]-margin],[box[1][0]+margin,box[1][1]+margin]]})
    catalog = {v["name"]:v for v in p.via_catalog(profile)}
    for via in vias:
        for layer, box in via_boxes(catalog[via["via"]], *via["xy_um"]):
            obstacles.append({"id": via["id"] + "/" + layer, "layer": layer, "net": net, "hard": True, "bbox_um": box})


def transform_point(point, pair):
    x,y = point
    transform = pair.get("transform", "rotate_180" if pair["strategy"] == "rotate180_guided" else "mirror_x")
    if transform == "mirror_x": return [2*float(pair["axis_um"])-x, y]
    if transform == "mirror_y": return [x, 2*float(pair["axis_um"])-y]
    if transform == "rotate_180": return [2*float(pair["axis_x_um"])-x, 2*float(pair["axis_y_um"])-y]
    raise ValueError("unsupported symmetry transform")


def route_coupled_pair(p, profile, access, obstacles, first, second, pair, bounds, grid, preferred):
    """A coupled transaction: reference route -> transformed guide -> counterpart.

    Explicit island correspondence is mandatory. Any matching failure blocks
    the entire transaction; neither branch is committed independently.
    """
    mapping = pair.get("pin_pairs", [])
    first_ids = {t.get("pin_island_id") for t in first["terminals"]}
    second_ids = {t.get("pin_island_id") for t in second["terminals"]}
    if not mapping or any(len(m) != 2 for m in mapping):
        raise p.SEARCH.PlanningError("INVALID_PAIR_MAPPING", "guided pair requires pin_pairs of island IDs")
    left, right = [m[0] for m in mapping], [m[1] for m in mapping]
    if len(set(left)) != len(left) or len(set(right)) != len(right) or not set(left) <= first_ids or not set(right) <= second_ids:
        raise p.SEARCH.PlanningError("INVALID_PAIR_MAPPING", "pin_pairs must be one-to-one and name real requested islands")
    partial = pair["strategy"] == "partial_mirror_guided"
    if not partial and (set(left) != first_ids or set(right) != second_ids):
        raise p.SEARCH.PlanningError("INVALID_PAIR_MAPPING", "full symmetry requires correspondence for every island")
    # Restrict reference candidates to those with a legal transformed counterpart.
    local_access = copy.deepcopy(access)
    islands = {island["id"]:island for instance in local_access["instances"] for name,t in instance["terminals"].items()
               for island in p.terminal_islands(instance["name"],name,t)}
    tolerance = float(pair.get("access_tolerance_um", grid/2))
    tolerance = p.SEARCH.nonnegative(tolerance, "access_tolerance_um")
    legal_candidates = {}
    for net_request in (first, second):
        layers,widths,spacings,vias,_,rects,_,_ = configuration(
            p,profile,obstacles,net_request,bounds,grid,preferred)
        for raw in net_request["terminals"]:
            legal_candidates[raw["pin_island_id"]] = enumerate_access_candidates(
                p,local_access,raw,layers,vias,grid,obstacles,net_request["net"],widths,spacings,bounds,rects)
    for a,b in mapping:
        matches = [candidate["pin_xy_um"] for candidate in legal_candidates[a] if any(
            candidate["route_layer"] == other["route_layer"] and
            max(abs(v-w) for v,w in zip(transform_point(candidate["pin_xy_um"],pair), other["pin_xy_um"])) <= tolerance
            for other in legal_candidates[b])]
        if not matches: raise p.SEARCH.PlanningError("SYMMETRY_UNSATISFIABLE", f"no paired access for {a}/{b}")
        islands[a]["candidate_centers"] = matches
        islands[a]["selected_center"] = matches[0]
    r1,v1,c1,m1 = route_net(p,profile,local_access,obstacles,first,bounds,grid,preferred)
    selected = {t["pin_island_id"]:t for t in m1["selected_access"]}
    second_request = copy.deepcopy(second)
    for a,b in mapping:
        desired = transform_point(selected[a]["pin_xy_um"],pair)
        counterpart = min((c for c in legal_candidates[b] if c["route_layer"] == selected[a]["route_layer"]),
                          key=lambda c: sum(abs(v-w) for v,w in zip(c["pin_xy_um"],desired)))
        center = counterpart["pin_xy_um"]
        for terminal in second_request["terminals"]:
            if terminal["pin_island_id"] == b:
                terminal["xy_um"] = center
                terminal["route_layer"] = counterpart["route_layer"]
    second_request["guidance"] = [{"layer":r["layer"], "points_um":[transform_point(xy,pair) for xy in r["points_um"]]} for r in r1]
    second_request["guide_weight"] = p.SEARCH.nonnegative(pair.get("guide_weight",1.0), "guide_weight")
    if second_request["guide_weight"] <= 0:
        raise p.SEARCH.PlanningError("INVALID_GUIDANCE", "coupled guidance weight must be positive")
    local_obstacles = copy.deepcopy(obstacles)
    reserve_geometry(p,profile,local_obstacles,r1,v1+c1,first)
    r2,v2,c2,m2 = route_net(p,profile,local_access,local_obstacles,second_request,bounds,grid,preferred)
    spec = {"schema":p.ROUTE.SPEC_SCHEMA,"target":access["target"],"required_nets":[first["net"],second["net"]],
            "routes":r1+r2,"vias":v1+v2,"contact_landings":c1+c2,"matching":[pair]}
    checked = p.ROUTE.build(profile,access,spec)
    if checked["decision"]["status"] != "READY_FOR_REVIEW":
        raise p.SEARCH.PlanningError("SYMMETRY_UNSATISFIABLE", "guided pair failed authoritative matching/connectivity: " + "; ".join(checked["validation"]["errors"]))
    for m in (m1,m2):
        m["paired_topology"] = True
        m["coupled_strategy"] = pair["strategy"]
        m["environmental_symmetry_status"] = "unknown_requires_PEX"
    m2["guidance"] = second_request["guidance"]
    return r1+r2,v1+v2,c1+c2,{first["net"]:m1,second["net"]:m2}
