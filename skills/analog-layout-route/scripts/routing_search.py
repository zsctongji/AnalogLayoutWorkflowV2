"""Deterministic routing search and topology primitives; no EDA side effects."""
import heapq
import math


class PlanningError(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


def nonnegative(value, name):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise PlanningError("INVALID_COST", f"{name} must be finite and nonnegative")
    return value


def empty_cost():
    return dict.fromkeys(("wire_length_um", "bend_penalty", "via_penalty",
                          "off_direction_penalty", "guide_deviation_cost", "sensitive_area_cost", "metal_area_penalty"), 0.0)


def overlap_length(a, b, box):
    (x0, y0), (x1, y1) = box
    if a[1] == b[1] and y0 < a[1] < y1:
        return max(0, min(max(a[0], b[0]), x1) - max(min(a[0], b[0]), x0))
    if a[0] == b[0] and x0 < a[0] < x1:
        return max(0, min(max(a[1], b[1]), y1) - max(min(a[1], b[1]), y0))
    return 0.0


def guide_distance(point, guides, layer):
    distances = []
    for guide in guides:
        if guide["layer"] != layer:
            continue
        for a, b in zip(guide["points_um"], guide["points_um"][1:]):
            distances.append(max(min(a[0], b[0]) - point[0], 0, point[0] - max(a[0], b[0]))
                             + max(min(a[1], b[1]) - point[1], 0, point[1] - max(a[1], b[1])))
    return min(distances) if distances else 0.0


def guide_integral(a, b, guides):
    """Exact integral of distance to the nearest same-layer guide segment.

    Each segment contributes a piecewise affine distance along a straight
    routing edge. Split at endpoint projections and pairwise intersections;
    this makes costs independent of collinear path compaction.
    """
    axis = 0 if a[1] == b[1] else 1
    other = 1 - axis
    lo, hi = sorted((a[axis], b[axis]))
    functions, knots = [], {lo, hi}
    for guide in guides:
        if guide["layer"] != a[2]: continue
        for p1,p2 in zip(guide["points_um"],guide["points_um"][1:]):
            left,right = sorted((p1[axis],p2[axis]))
            bottom,top = sorted((p1[other],p2[other]))
            offset = max(bottom-a[other],0,a[other]-top)
            functions.append((left,right,offset))
            knots.update(v for v in (left,right) if lo < v < hi)
    if not functions: return 0.0
    def value(f,t): return f[2]+max(f[0]-t,0,t-f[1])
    total = 0.0
    ordered = sorted(knots)
    for left,right in zip(ordered,ordered[1:]):
        if right == left: continue
        lines = []
        for f in functions:
            slope = (value(f,right)-value(f,left))/(right-left)
            lines.append((slope,value(f,left)-slope*left))
        cuts = {left,right}
        for i,(s1,c1) in enumerate(lines):
            for s2,c2 in lines[i+1:]:
                if abs(s1-s2) > 1e-12:
                    crossing = (c2-c1)/(s1-s2)
                    if left < crossing < right: cuts.add(crossing)
        cuts = sorted(cuts)
        for x,y in zip(cuts,cuts[1:]):
            total += (y-x)*(min(s*x+c for s,c in lines)+min(s*y+c for s,c in lines))/2
    return total


def edge_cost(a, b, incoming, preferred, via_cost, bend_cost, off_cost, guides, guide_weight, regions, layer_costs=None):
    cost = empty_cost()
    if a[2] != b[2]:
        cost["via_penalty"] = via_cost
        return cost, ""
    length = abs(a[0] - b[0]) + abs(a[1] - b[1])
    direction = "horizontal" if a[1] == b[1] else "vertical"
    cost["wire_length_um"] = length
    cost["metal_area_penalty"] = length * (layer_costs or {}).get(a[2],0.0)
    cost["bend_penalty"] = bend_cost if incoming and incoming != direction else 0.0
    cost["off_direction_penalty"] = length * off_cost if preferred.get(a[2]) not in (None, direction) else 0.0
    cost["guide_deviation_cost"] = guide_weight * guide_integral(a, b, guides)
    for region in regions:
        if region["layer"] == a[2]:
            penalty = region["cost_per_um"]
            if region.get("parallel_direction") not in (None, direction):
                penalty *= region.get("crossing_factor", 0.25)
            cost["sensitive_area_cost"] += overlap_length(a, b, region["bbox_um"]) * penalty
    return cost, direction


def evaluate_path(path, preferred, via_cost, bend_cost, off_cost, guides=(), guide_weight=0, regions=(), layer_costs=None):
    result, incoming = empty_cost(), ""
    for a, b in zip(path, path[1:]):
        cost, incoming = edge_cost(a, b, incoming, preferred, via_cost, bend_cost, off_cost, guides, guide_weight, regions, layer_costs)
        for key in result:
            result[key] += cost[key]
    return result


def directional_astar(p, start, goals, rects, bounds, adjacency, protected, grid,
                      via_cost, preferred=None, off_cost=0.25, bend_cost=0.0,
                      guides=(), guide_weight=0.0, regions=(), via_allowed=None, extra_points=(), layer_costs=None):
    preferred = preferred or {}
    via_cost = nonnegative(via_cost, "via_cost_um")
    bend_cost = nonnegative(bend_cost, "bend_cost_um")
    off_cost = nonnegative(off_cost, "off_direction_penalty")
    guide_weight = nonnegative(guide_weight, "guide_weight")
    layer_costs = {layer:nonnegative(value,"metal_area_penalty") for layer,value in (layer_costs or {}).items()}
    start = (p.snap(start[0], grid), p.snap(start[1], grid), start[2])
    goals = {(p.snap(x, grid), p.snap(y, grid), layer) for x, y, layer in goals}
    def inside(node):
        return bounds[0][0] <= node[0] <= bounds[1][0] and bounds[0][1] <= node[1] <= bounds[1][1]
    if not goals or not inside(start) or p.point_blocked(start[:2], rects[start[2]]):
        return None
    goals = {n for n in goals if inside(n) and not p.point_blocked(n[:2], rects[n[2]])}
    if not goals:
        return None
    xs = {p.snap_up(bounds[0][0], grid), p.snap_down(bounds[1][0], grid), start[0]}
    ys = {p.snap_up(bounds[0][1], grid), p.snap_down(bounds[1][1], grid), start[1]}
    for node in sorted(goals) + list(extra_points):
        xs.add(p.snap(node[0], grid)); ys.add(p.snap(node[1], grid))
    for layer_rects in rects.values():
        for x0, y0, x1, y1 in layer_rects:
            xs.update((x0, x1)); ys.update((y0, y1))
    for region in regions:
        (x0, y0), (x1, y1) = region["bbox_um"]
        xs.update((p.snap_down(x0, grid), p.snap_up(x1, grid)))
        ys.update((p.snap_down(y0, grid), p.snap_up(y1, grid)))
    for guide in guides:
        for x, y in guide["points_um"]:
            xs.add(p.snap(x, grid)); ys.add(p.snap(y, grid))
    xs = sorted(x for x in xs if bounds[0][0] <= x <= bounds[1][0])
    ys = sorted(y for y in ys if bounds[0][1] <= y <= bounds[1][1])
    xi, yi = {x: i for i, x in enumerate(xs)}, {y: i for i, y in enumerate(ys)}
    def heuristic(n):
        return min(abs(n[0] - g[0]) + abs(n[1] - g[1]) for g in goals)
    initial = (*start, "")
    distance, parent = {initial: 0.0}, {}
    queue = [(heuristic(start), 0.0, initial)]
    reached = None
    while queue:
        _, cost, state = heapq.heappop(queue)
        if cost != distance.get(state):
            continue
        x, y, layer, incoming = state
        node = state[:3]
        if node in goals:
            reached = state
            break
        neighbors = []
        for index in (xi[x] - 1, xi[x] + 1):
            if 0 <= index < len(xs): neighbors.append((xs[index], y, layer))
        for index in (yi[y] - 1, yi[y] + 1):
            if 0 <= index < len(ys): neighbors.append((x, ys[index], layer))
        for nxt in list(neighbors):
            if p.point_blocked(nxt[:2], rects[layer]) or not p.segment_clear(node[:2], nxt[:2], rects[layer]):
                neighbors.remove(nxt)
        if (x, y) not in protected:
            for other, via in adjacency.get(layer, []):
                if not p.point_blocked((x, y), rects[other]) and (via_allowed is None or via_allowed(x, y, via)):
                    neighbors.append((x, y, other))
        for nxt in sorted(set(neighbors)):
            parts, direction = edge_cost(node, nxt, incoming, preferred, via_cost, bend_cost, off_cost, guides, guide_weight, regions, layer_costs)
            new_state = (*nxt, direction)
            new_cost = cost + sum(parts.values())
            if new_cost + 1e-12 < distance.get(new_state, math.inf):
                distance[new_state] = new_cost
                parent[new_state] = state
                heapq.heappush(queue, (new_cost + heuristic(nxt), new_cost, new_state))
    if reached is None:
        return None
    path = [reached]
    while path[-1] != initial:
        path.append(parent[path[-1]])
    return [node[:3] for node in reversed(path)]


def tree_attachment_points(node, paths, reached_nodes):
    """Legal same-layer centerline vertices and orthogonal projections."""
    points = set(reached_nodes)
    for path in paths:
        points.update(path)
        for a, b in zip(path, path[1:]):
            if a[2] != b[2]:
                continue
            if a[0] == b[0]:
                points.add((a[0], min(max(node[1], min(a[1], b[1])), max(a[1], b[1])), a[2]))
            elif a[1] == b[1]:
                points.add((min(max(node[0], min(a[0], b[0])), max(a[0], b[0])), a[1], a[2]))
    return points


def synthesize_topology(nodes, search, cost, electrical=None, frontier_limit=4, share_tree=True):
    """Obstacle-aware metric MST, or sourced current-weighted rooted tree.

    Current mode minimizes a sum of root-to-sink route distances plus an
    epsilon-weighted tree length by deterministic local reparenting. It is an
    approximation, not the SAGERoute algorithm or a global Steiner optimum.
    """
    # Bounded actual-cost competition preserves the prior fast frontier mode
    # without accepting the first feasible but arbitrarily long detour.
    if not electrical:
        if not isinstance(frontier_limit, int) or isinstance(frontier_limit, bool) or frontier_limit < 1:
            raise PlanningError("INVALID_SEARCH_BUDGET", "topology_frontier_limit must be a positive integer")
        reached, result = {0}, []
        while len(reached) < len(nodes):
            frontier = []
            for child in sorted(set(range(len(nodes))) - reached):
                goals = (tree_attachment_points(nodes[child], [path for _,_,path in result], [nodes[i] for i in sorted(reached)])
                         if share_tree else {nodes[i] for i in sorted(reached)})
                lower = min(abs(nodes[child][0]-g[0])+abs(nodes[child][1]-g[1]) for g in goals)
                frontier.append((lower, child, goals))
            frontier.sort(key=lambda row: (row[0], row[1]))
            selected = None
            attempts = 0
            best_key = None
            for lower, child, goals in frontier:
                if selected is not None and (attempts >= frontier_limit or lower > best_key[0] + 1e-12):
                    break
                attempts += 1
                path = search(nodes[child], goals)
                if path is not None:
                    key = (sum(cost(path).values()), child, tuple(path))
                    if best_key is None or key < best_key:
                        parent = min(reached, key=lambda i: (abs(nodes[i][0]-path[-1][0])+abs(nodes[i][1]-path[-1][1]), i))
                        selected, best_key = (parent, child, path), key
            if selected is None:
                raise PlanningError("TOPOLOGY_EDGE_BLOCKED", "no legal layered rectilinear path")
            result.append(selected)
            reached.add(selected[1])
        return result

    edges = {}
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            path = search(nodes[i], {nodes[j]})
            if path is not None:
                edges[i, j] = (sum(cost(path).values()), path)
    reached, tree = {0}, []
    while len(reached) < len(nodes):
        choices = [(v[0], i, j) for (i, j), v in edges.items() if (i in reached) != (j in reached)]
        if not choices:
            raise PlanningError("TOPOLOGY_EDGE_BLOCKED", "no legal layered rectilinear path")
        _, i, j = min(choices)
        parent, child = (i, j) if i in reached else (j, i)
        tree.append((parent, child)); reached.add(child)
    if electrical:
        root, currents, epsilon = electrical
        lengths = {key:sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(path,path[1:]))
                   for key,(_,path) in edges.items()}
        adjacency = {i: [] for i in range(len(nodes))}
        for i, j in tree: adjacency[i].append(j); adjacency[j].append(i)
        parents, queue = {root: None}, [root]
        for i in queue:
            for j in sorted(adjacency[i]):
                if j not in parents: parents[j] = i; queue.append(j)
        def objective(par):
            value = 0.0
            for child, parent in par.items():
                if parent is not None: value += epsilon * lengths[tuple(sorted((child, parent)))]
                node, seen, length = child, set(), 0.0
                while par[node] is not None:
                    if node in seen: return math.inf
                    seen.add(node)
                    key = tuple(sorted((node, par[node])))
                    if key not in edges: return math.inf
                    length += lengths[key]; node = par[node]
                value += currents[child] * length
            return value
        # Finite, bounded coordinate descent. Never accept a worsening move.
        for _ in range(len(nodes) * 2):
            baseline, best = objective(parents), None
            for child in sorted(parents):
                if child == root: continue
                for parent in sorted(parents):
                    if parent == child or tuple(sorted((child, parent))) not in edges: continue
                    trial = dict(parents); trial[child] = parent
                    score = objective(trial)
                    if score + 1e-12 < baseline:
                        baseline, best = score, trial
            if best is None: break
            parents = best
        tree = sorted((parent, child) for child, parent in parents.items() if parent is not None)
    return [(i, j, edges[tuple(sorted((i, j)))][1]) for i, j in tree]
