"""Offline fixed-axis row candidates and conservative polygon reflection audit."""
import argparse
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / 'analog-layout-macro-opt/scripts/macro_opt.py'
if not ENGINE.is_file():
    raise RuntimeError('Required sibling skill analog-layout-macro-opt is missing')
spec = importlib.util.spec_from_file_location('macro_opt_dependency', ENGINE)
opt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opt)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected finite number')
    return value


def canonical(points):
    pts = [tuple(round(number(v), 9) for v in p) for p in points]
    if any(len(p) != 2 for p in pts):
        raise ValueError('Expected XY polygon')
    if pts and pts[0] == pts[-1]:
        pts.pop()
    if len(set(pts)) < 3:
        raise ValueError('Degenerate polygon')
    variants = []
    for seq in (pts, pts[::-1]):
        variants.extend(tuple(seq[i:] + seq[:i]) for i in range(len(seq)))
    return min(variants)


def geometry_audit(snapshot, geometry, rows, deltas, k, axis):
    if geometry is None:
        return {'status': 'COAXIAL_ONLY', 'failures': ['MISSING_FLATTENED_GEOMETRY']}
    opt.check_keys(geometry, ['snapshot_sha256', 'evidence', 'source_figure_ids', 'figures', 'excluded_annotation_ids'])
    if geometry['snapshot_sha256'] != opt.digest(snapshot) or not geometry.get('evidence'):
        raise ValueError('Stale/missing geometry evidence')
    figures = geometry['figures']
    ids = [f['id'] for f in figures]
    expected = geometry['source_figure_ids']
    if len(ids) != len(set(ids)) or len(expected) != len(set(expected)) or set(ids) != set(expected):
        raise ValueError('Incomplete flattened figure inventory')
    objects = {o['id']: o for o in snapshot['objects']}
    excluded = geometry.get('excluded_annotation_ids', [])
    if len(excluded) != len(set(excluded)) or any(i not in objects or objects[i].get('kind') != 'label' for i in excluded):
        raise ValueError('Only explicitly classified annotation labels may be excluded')
    owners = {f['object_id'] for f in figures}
    if owners & set(excluded) or owners | set(excluded) != set(objects):
        raise ValueError('Incomplete geometry object coverage')
    by_macro = {m['id']: [] for m in snapshot['macros']}
    for f in figures:
        opt.check_keys(f, ['id', 'object_id', 'macro', 'lpp', 'points_um'])
        if f['macro'] != objects[f['object_id']]['macro'] or not isinstance(f['lpp'], list) or len(f['lpp']) != 2:
            raise ValueError('Invalid figure ownership/LPP')
        canonical(f['points_um'])
        by_macro[f['macro']].append(f)

    def signatures(name, reflect):
        result = Counter()
        for f in by_macro[name]:
            points = [[p[j] + deltas[name][j] for j in (0, 1)] for p in f['points_um']]
            if reflect:
                for p in points:
                    p[k] = 2 * axis - p[k]
            result[(tuple(f['lpp']), canonical(points))] += 1
        return result

    failures = []
    for row in rows:
        a, b = row[0], row[-1]
        left, right = signatures(a, True), signatures(b, False)
        if not left or not right:
            failures.append({'macros': row, 'reason': 'NO_PHYSICAL_GEOMETRY'})
        elif left != right:
            failures.append({'macros': row, 'unmatched_reflections': sum((left-right).values()),
                             'unmatched_targets': sum((right-left).values())})
    return {'status': 'GEOMETRY_ASYMMETRIC' if failures else 'REPRESENTED_GEOMETRY_SYMMETRIC',
            'failures': failures, 'scope': 'Polygon multiset on declared layers; no electrical or pin equivalence claim'}


def plan(snapshot, request):
    opt.digest(request)
    opt.check_keys(request, ['schema', 'base_request', 'axis', 'orders', 'start_um', 'excluded_macros', 'geometry'])
    if request['schema'] != 'analog-layout-macro-symmetry.request/v1':
        raise ValueError('Unsupported symmetry schema')
    base = request['base_request']
    macros, objects, boxes, gaps = opt.prepare(snapshot, base)
    axis = request['axis']
    opt.check_keys(axis, ['coordinate', 'value_um', 'basis'])
    if axis['coordinate'] not in ('x', 'y') or not axis.get('basis'):
        raise ValueError('Invalid axis or missing provenance')
    k = 'xy'.index(axis['coordinate']); t = 1-k
    a = number(axis['value_um']); start = number(request['start_um'])
    grid = number(snapshot['grid_um'])
    excluded = request.get('excluded_macros', {})
    if not isinstance(excluded, dict) or not set(excluded) <= set(macros) or any(not v for v in excluded.values()):
        raise ValueError('Excluded macros need explicit reasons')
    if not set(excluded) <= set(base.get('locked', [])):
        raise ValueError('Excluded macros must be locked obstacles')
    orders = request['orders']
    if not isinstance(orders, list) or not orders:
        raise ValueError('Supply at least one row order')
    baseline = opt.evaluate(snapshot, base, boxes, gaps, {n:b[0] for n,b in boxes.items()})
    results = []
    for rows in orders:
        if not rows or any(not isinstance(row, list) or len(row) not in (1, 2) for row in rows):
            raise ValueError('Each row contains one self macro or two paired macros')
        names = [n for row in rows for n in row]
        if len(names) != len(set(names)) or set(names) != set(macros)-set(excluded):
            raise ValueError('Every in-scope macro must occur exactly once')
        offsets = {n:[opt.anchor(macros[n], boxes[n], j) for j in (0,1)] for n in macros}
        if any(not 0 <= offsets[n][j] <= boxes[n][1][j]-boxes[n][0][j] for n in macros for j in (0,1)):
            raise ValueError('Physical matching anchor must lie inside full macro envelope')
        pos = {n:list(b[0]) for n,b in boxes.items()}
        placed = []
        for row in rows:
            # Shared orthogonal matching-anchor coordinate. Prior rows constrain all pairs.
            q = max(start + offsets[n][t] for n in row)
            for n in row:
                for prev in placed:
                    end = pos[prev][t] + boxes[prev][1][t]-boxes[prev][0][t]
                    q = max(q, end + gaps[frozenset((prev,n))][t] + offsets[n][t])
            phase = boxes[row[0]][0][t] + offsets[row[0]][t]
            q = phase + math.ceil((q-phase)/grid - 1e-8)*grid
            if len(row) == 1:
                n = row[0]; pos[n][k] = a-offsets[n][k]
            else:
                left, right = row
                extent = boxes[left][1][k]-boxes[left][0][k]-offsets[left][k]
                distance = (extent + offsets[right][k] + gaps[frozenset(row)][k])/2
                # Snap outward using left origin phase; right phase checked independently.
                original_anchor = boxes[left][0][k] + offsets[left][k]
                left_anchor = original_anchor + math.floor((a-distance-original_anchor)/grid + 1e-8)*grid
                pos[left][k] = left_anchor-offsets[left][k]
                pos[right][k] = 2*a-left_anchor-offsets[right][k]
            for n in row:
                pos[n][t] = q-offsets[n][t]
            placed.extend(row)
        pos = {n:[round(v,9) for v in p] for n,p in pos.items()}
        metrics = opt.evaluate(snapshot, base, boxes, gaps, pos)
        audit = geometry_audit(snapshot, request.get('geometry'), rows, metrics['deltas_um'], k, a)
        candidate = {'id': opt.digest(pos)[:16], 'rows': rows, 'positions_um': pos, 'metrics': metrics,
                     'geometry_audit': audit, 'area_delta_um2': metrics['area_um2']-baseline['area_um2'],
                     'routing_status': 'PENDING_ELECTRICAL_PIN_AND_CHANNEL_AUDIT',
                     'object_moves': [{'object_id':o['id'], 'macro':o['macro'],
                                       'delta_um':metrics['deltas_um'][o['macro']],
                                       'payload_sha256':o['payload_sha256']} for o in objects.values()]}
        results.append(candidate)
    valid = [c for c in results if c['metrics']['valid']]
    valid.sort(key=lambda c:(c['geometry_audit']['status'] != 'REPRESENTED_GEOMETRY_SYMMETRIC', c['metrics']['area_um2']))
    return {'schema': 'analog-layout-macro-symmetry.candidates/v1', 'axis': axis,
            'snapshot_sha256':opt.digest(snapshot), 'request_sha256':opt.digest(request),
            'baseline':baseline, 'excluded_macros':excluded, 'candidates':valid,
            'rejected': [c for c in results if not c['metrics']['valid']], 'materialized':False,
            'status':'CANDIDATES_FOR_REVIEW' if valid else 'NO_VALID_CANDIDATE_FOR_SUPPLIED_ORDERS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot', 'request', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Choose a new output directory')
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8-sig'))
    request = json.loads(args.request.read_text(encoding='utf-8-sig'))
    result = plan(snapshot, request)
    args.out.mkdir(parents=True)
    (args.out/'candidates.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for i,c in enumerate(result['candidates'], 1):
        svg = opt.preview(snapshot,c)
        b = c['metrics']['bbox_um']; a = result['axis']['value_um']
        if result['axis']['coordinate'] == 'x':
            line = f'<line x1="{a}" x2="{a}" y1="{-b[1][1]}" y2="{-b[0][1]}"'
        else:
            line = f'<line x1="{b[0][0]}" x2="{b[1][0]}" y1="{-a}" y2="{-a}"'
        svg = svg.replace('</svg>', line+' stroke="red" stroke-width="0.15" stroke-dasharray="0.5 0.5"/></svg>')
        (args.out/f'candidate-{i}.svg').write_text(svg, encoding='utf-8')
    print(json.dumps({'status':result['status'], 'candidates':len(result['candidates'])}))


if __name__ == '__main__':
    main()
