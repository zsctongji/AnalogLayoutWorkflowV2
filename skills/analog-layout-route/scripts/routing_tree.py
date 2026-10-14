"""Normalize same-net centerlines and prune redundant physical tree geometry."""
from collections import defaultdict


def on_edge(node, a, b):
    if node[2] != a[2] or a[2] != b[2]:
        return False
    return (a[0] == b[0] == node[0] and min(a[1],b[1]) <= node[1] <= max(a[1],b[1])
            or a[1] == b[1] == node[1] and min(a[0],b[0]) <= node[0] <= max(a[0],b[0]))


def graph_edges(paths, terminals):
    """Split at T/X junctions, overlaps, terminals and via landing vertices."""
    segments = [(a,b) for path in paths for a,b in zip(path,path[1:]) if a != b]
    vertices = set(terminals)
    vertices.update(n for segment in segments for n in segment)
    planar = [(a,b) for a,b in segments if a[2] == b[2]]
    for a,b in planar:
        for c,d in planar:
            if a[2] != c[2]: continue
            if a[1] == b[1] and c[0] == d[0]:
                cross = (c[0],a[1],a[2])
                if on_edge(cross,a,b) and on_edge(cross,c,d): vertices.add(cross)
    edges = set()
    for a,b in segments:
        if a[2] != b[2]:
            edges.add(tuple(sorted((a,b))))
            continue
        points = sorted(n for n in vertices if on_edge(n,a,b))
        edges.update(tuple(sorted((u,v))) for u,v in zip(points,points[1:]))
    return edges


def edge_length(edge):
    a,b = edge
    return abs(a[0]-b[0])+abs(a[1]-b[1])


def chains(edges, terminals):
    adjacency = defaultdict(set)
    for a,b in edges: adjacency[a].add(b); adjacency[b].add(a)
    visited, paths = set(), []
    # Keep electrical terminals and branching nodes as explicit breakpoints.
    breaks = {n for n,neighbors in adjacency.items() if len(neighbors) != 2} | set(terminals)
    for start in sorted(breaks):
        for neighbor in sorted(adjacency[start]):
            edge = tuple(sorted((start,neighbor)))
            if edge in visited: continue
            path = [start,neighbor]; visited.add(edge)
            while path[-1] not in breaks:
                node = path[-1]
                choices = sorted(n for n in adjacency[node] if tuple(sorted((node,n))) not in visited)
                if not choices: break
                nxt = choices[0]; visited.add(tuple(sorted((node,nxt)))); path.append(nxt)
            paths.append(path)
    return paths


def normalize_tree(paths, terminals, evaluate):
    """Only removes/reuses existing geometry; never invents shortcuts."""
    edges = graph_edges(paths, terminals)
    parents = {n:n for edge in edges for n in edge}
    if not set(terminals) <= set(parents):
        return paths, {"applied":False,"reason":"terminal has no physical edge"}
    def root(node):
        while parents[node] != node:
            parents[node] = parents[parents[node]]; node = parents[node]
        return node
    kept = set()
    for edge in sorted(edges, key=lambda e:(sum(evaluate(list(e)).values()),e)):
        a,b = edge
        ra,rb = root(a),root(b)
        if ra != rb:
            parents[ra] = rb; kept.add(edge)
    if len({root(n) for n in terminals}) != 1:
        return paths, {"applied":False,"reason":"disconnected input centerlines"}
    adjacency = defaultdict(set)
    for a,b in kept: adjacency[a].add(b); adjacency[b].add(a)
    pending = sorted(n for n in adjacency if len(adjacency[n]) == 1 and n not in terminals)
    while pending:
        n = pending.pop()
        if n in terminals or len(adjacency[n]) != 1: continue
        neighbor = next(iter(adjacency[n]))
        kept.discard(tuple(sorted((n,neighbor))))
        adjacency[n].remove(neighbor); adjacency[neighbor].remove(n)
        if neighbor not in terminals and len(adjacency[neighbor]) == 1: pending.append(neighbor)
    output = chains(kept, terminals)
    # Pruning can change the turn structure. Accept only non-increasing total
    # physical cost, including turns on resulting chains.
    original_cost = sum(sum(evaluate(path).values()) for path in paths)
    output_cost = sum(sum(evaluate(path).values()) for path in output)
    if output_cost > original_cost + 1e-9:
        return paths, {"applied":False,"reason":"normalization would increase routed cost"}
    primitive_length = sum(edge_length((a,b)) for path in paths for a,b in zip(path,path[1:]))
    return output, {
        "applied":True,
        "input_primitive_length_um":primitive_length,
        "input_unique_length_um":sum(edge_length(e) for e in sorted(edges)),
        "output_unique_length_um":sum(edge_length(e) for e in sorted(kept)),
        "duplicate_length_removed_um":primitive_length-sum(edge_length(e) for e in sorted(edges)),
        "cycle_or_stub_length_removed_um":sum(edge_length(e) for e in sorted(edges-kept)),
        "removed_edges":len(edges-kept),
    }
