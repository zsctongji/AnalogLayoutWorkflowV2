"""Fail-closed inventory/evidence gate; not a contact extractor or DRC engine."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def ids(value):
    return (isinstance(value, list) and bool(value) and all(nonempty(v) for v in value)
            and len(set(value)) == len(value))


def valid_box(box):
    return (isinstance(box, list) and len(box) == 2
            and all(isinstance(p, list) and len(p) == 2 for p in box)
            and all(type(v) in (int, float) and math.isfinite(v) for p in box for v in p)
            and all(box[1][k] > box[0][k] for k in (0, 1)))


def check_gate_access(intent, access, review, source, names):
    failures = []
    envelopes = []
    required = {}
    if not access or not review:
        return {'status': 'BLOCKED_GATE_ACCESS', 'failures': ['Missing fresh terminal access or gate-contact review'], 'access_envelopes_um': []}
    if (access.get('schema') != 'analog-layout-align.terminal-access/v1'
            or review.get('schema') != 'analog-layout-guard-ring.gate-contact-review/v1'):
        failures.append('Unsupported gate evidence schema')
    if not source or access.get('target') != source or review.get('target') != source:
        failures.append('Gate evidence source target mismatch')
    if review.get('intent_sha256') != content_hash(intent) or review.get('terminal_access_sha256') != content_hash(access):
        failures.append('Stale gate evidence hash')
    for key in ('layout_snapshot_sha256', 'pdk_fingerprint'):
        if not nonempty(review.get(key)):
            failures.append('Missing '+key)
    items = {i['name']: i for i in intent['instances']}
    measured = {i['name']: i for i in access.get('instances', [])}
    if len(measured) != len(access.get('instances', [])):
        failures.append('Duplicate measured instance')
    if not ids(names):
        failures.append('Invalid selected instance inventory')
    for name in names:
        item, live = items.get(name), measured.get(name)
        if not item or not live or item.get('kind') not in ('nmos', 'pmos'):
            failures.append(f'{name}: missing MOS gate inventory')
            continue
        if live.get('bbox') != item.get('bbox') or ('orientation' in item and live.get('orientation') != item['orientation']):
            failures.append(f'{name}: measured placement differs from intent')
        gate = live.get('terminals', {}).get('G', {})
        net = item.get('terminals', {}).get('G')
        islands = gate.get('pin_islands', [])
        if not nonempty(net) or gate.get('net') != net or not islands:
            failures.append(f'{name}: missing gate net/islands')
        for island in islands:
            ident = island.get('id')
            if not nonempty(ident) or not island.get('figures') or ident in required:
                failures.append(f'{name}: missing/duplicate gate island geometry')
            else:
                required[ident] = (name, net)
    covered = set()
    records = review.get('records', [])
    if not isinstance(records, list):
        records = []
        failures.append('Invalid contact records')
    for record in records:
        if not isinstance(record, dict):
            failures.append('Invalid contact record')
            continue
        name = record.get('instance')
        if name not in names:
            continue  # A whole-layout review can be reused for one complete domain.
        island_ids = record.get('covered_island_ids')
        if not ids(island_ids):
            failures.append(f'{name}: empty/duplicate covered island IDs')
            continue
        valid = True
        for key in ('contact_object_ids', 'metal_landing_object_ids'):
            if not ids(record.get(key)):
                failures.append(f'{name}: missing actual {key}')
                valid = False
        for key in ('metal_layer', 'verification_source'):
            if not nonempty(record.get(key)):
                failures.append(f'{name}: missing {key}')
                valid = False
        for key in ('continuity_verified', 'pdk_legality_verified', 'local_escape_verified'):
            if record.get(key) is not True:
                failures.append(f'{name}: unverified {key}')
                valid = False
        if not valid_box(record.get('access_bbox_um')):
            failures.append(f'{name}: invalid access/escape envelope')
            valid = False
        for ident in island_ids:
            if required.get(ident) != (name, record.get('net')):
                failures.append(f'{name}: wrong-net/unknown gate island {ident}')
                valid = False
        if valid:
            covered.update(island_ids)
            envelopes.append(record['access_bbox_um'])
    for ident in sorted(set(required)-covered):
        failures.append(f'{ident}: no qualified realized gate contact/metal access (poly-only or unknown)')
    return {'status': 'BLOCKED_GATE_ACCESS' if failures else 'GATE_ACCESS_EVIDENCE_COMPLETE',
            'failures': failures, 'required_island_count': len(required), 'covered_island_count': len(covered),
            'access_envelopes_um': envelopes, 'review_sha256': content_hash(review),
            'boundary': 'Evidence completeness only; live continuity, PDK qualification and ring-clearance review remain adapter responsibilities'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('intent', 'terminal-access', 'review', 'out'):
        parser.add_argument('--'+key, type=Path, required=True)
    for key in ('source-lib', 'source-cell', 'source-view'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--instances', nargs='+', required=True)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    result = check_gate_access(read(args.intent), read(args.terminal_access), read(args.review),
                              {'lib': args.source_lib, 'cell': args.source_cell, 'view': args.source_view}, args.instances)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(result['status'])
    return 0 if not result['failures'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
