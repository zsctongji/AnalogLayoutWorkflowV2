"""Conservative Calibre text-report triage, never signoff or an OA writer."""
import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path


def field(text, name):
    m = re.search(r'^\s*' + re.escape(name) + r':\s*(.*?)\s*$', text, re.M)
    return m.group(1) if m else None


def input_path(value):
    if not value:
        return None
    value = re.sub(r"\s+\('[^']*'\)\s*$", '', value).strip().strip('"')
    return posixpath.normpath(value.replace('\\', '/'))


def inspect(text, log=None):
    metadata = {k: field(text, k) for k in
                ('LAYOUT NAME', 'SOURCE NAME', 'RULE FILE', 'CREATION TIME',
                 'CURRENT DIRECTORY', 'CALIBRE VERSION')}
    combined = text + '\n' + (log or '')
    warnings = [line.strip() for line in combined.splitlines()
                if re.search(r'\b(?:warning|fatal|error)\s*:', line, re.I)]
    reasons = []
    layout = input_path(metadata['LAYOUT NAME'])
    source = input_path(metadata['SOURCE NAME'])
    cwd = metadata['CURRENT DIRECTORY']
    if cwd:
        layout = posixpath.normpath(posixpath.join(cwd, layout)) if layout else None
        source = posixpath.normpath(posixpath.join(cwd, source)) if source else None
    same = bool(layout and source and layout == source)
    same_warning = bool(re.search(r'source\s+and\s+layout\s+refer\s+to\s+the\s+same\s+data', combined, re.I))
    # Restrict banner parsing to overall section, not arbitrary occurrences in warnings.
    overall = re.search(r'OVERALL COMPARISON RESULTS(.*?)(?:\n\s*-{5,}|INITIAL NUMBERS|CELL SUMMARY|\Z)', text, re.S)
    banner = overall.group(1) if overall else ''
    correct = bool(re.search(r'\bCORRECT\b', banner))
    incorrect = bool(re.search(r'\bINCORRECT\b', banner))
    complete = all(re.search(pattern, text, re.M) for pattern in
                   (r'^\s*SUMMARY\s*$', r'^Total CPU Time:', r'^Total Elapsed Time:'))
    known_header = bool(re.search(r'L\s+V\s+S\s+R\s+E\s+P\s+O\s+R\s+T', text))
    fatal = bool(re.search(r'\bFATAL\s*:|license checkout failed|segmentation fault|\bABORTED\b', combined, re.I))
    log_correct = bool(re.search(r'LVS completed\.\s+CORRECT\.', log or '', re.I))
    log_incorrect = bool(re.search(r'LVS completed\.\s+INCORRECT\.', log or '', re.I))
    log_conflict = (correct and log_incorrect) or (incorrect and log_correct)
    capped = bool(re.search(r'(?:report|results?)\s+(?:was\s+|were\s+)?truncated|maximum\s+(?:number\s+of\s+)?(?:results|errors)\s+(?:reached|exceeded)', combined, re.I))
    if same or same_warning:
        status = 'INVALID_COMPARISON'
        reasons.append('Same-data warning or identical reported input paths; independent layout/schematic comparison not established.')
    elif fatal:
        status = 'EXECUTION_FAILED'
        reasons.append('Fatal/aborted execution evidence found.')
    elif not known_header or not complete or correct == incorrect or log_conflict:
        status = 'INCOMPLETE'
        reasons.append('Unsupported/incomplete report or contradictory comparison evidence.')
    elif incorrect:
        status = 'REPORT_MISMATCH'
    else:
        status = 'REPORT_MATCH_UNVERIFIED'
    if capped:
        reasons.append('Result truncation detected; discrepancy inventory is incomplete.')
        if status == 'REPORT_MATCH_UNVERIFIED':
            status = 'INCOMPLETE'
    if log is None:
        reasons.append('Execution transcript and exit status not provided.')
    elif not (log_correct or log_incorrect):
        reasons.append('Transcript has no recognized compare completion line.')
    reasons.append('OA/export/deck/result provenance, hierarchy and warning review require separate evidence.')
    categories = [name for name in ('INCORRECT NETS', 'INCORRECT PORTS', 'INCORRECT INSTANCES', 'PROPERTY ERRORS')
                  if re.search(r'^\s*' + name + r'\s*$', text, re.M)]
    return {'status': status, 'verified_match': False, 'metadata': metadata,
            'reported_inputs': {'layout': layout, 'source': source},
            'report_footer_present': bool(complete), 'result_cap_detected': capped,
            'discrepancy_sections': categories, 'warning_error_lines': warnings,
            'reasons': reasons}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    p.add_argument('--log', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    raw = args.report.read_bytes()
    log_raw = args.log.read_bytes() if args.log else None
    result = inspect(raw.decode('utf-8', errors='replace'),
                     log_raw.decode('utf-8', errors='replace') if log_raw is not None else None)
    result['report_sha256'] = hashlib.sha256(raw).hexdigest()
    result['log_sha256'] = hashlib.sha256(log_raw).hexdigest() if log_raw is not None else None
    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        # Never overwrite a previous evidence file.
        with args.output.open('x', encoding='utf-8') as f:
            f.write(output + '\n')
    print(output)


if __name__ == '__main__':
    main()
