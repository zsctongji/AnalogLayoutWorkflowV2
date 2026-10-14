"""Fail-closed bindings for a trusted CAD-host export/Calibre adapter.

Receipts are adapter attestations, not cryptographic proof of tool semantics.
The core never manufactures a receipt or infers OA identity from a cell name.
"""
import hashlib
import json
import os
from pathlib import Path

def digest(path):
    p=Path(path)
    if not p.is_file():raise ValueError('missing bound input: '+str(p))
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def snapshot_files(paths):
    if not paths:raise ValueError('empty evidence file inventory')
    return {str(Path(p).resolve()):digest(p) for p in paths}

def unchanged(files):
    for p,h in files.items():
        if digest(p)!=h:raise ValueError('input changed during run: '+p)

def distinct_paths(inputs,outputs):
    ins=[Path(p).resolve() for p in inputs];outs=[Path(p).resolve() for p in outputs]
    for i,p in enumerate(outs):
        for q in ins+outs[:i]:
            if p==q or (p.exists() and q.exists() and os.path.samefile(str(p),str(q))):
                raise ValueError('input/output or output/output path collision: '+str(p))

def prepare(plan):
    c=plan['config'];b=c.get('binding',{})
    for key in ('metal_option','hierarchy_mode','result_limit','adapter_id'):
        if not isinstance(b.get(key),str) or not b[key].strip():raise ValueError('binding.'+key+' required')
    root=Path(plan['working_directory'])
    def paths(key):
        values=b.get(key)
        if not isinstance(values,list) or not values or not all(isinstance(x,str) and x for x in values):
            raise ValueError('binding.'+key+' requires a complete nonempty inventory')
        return [str((root/x).resolve()) for x in values]
    oa=snapshot_files(paths('oa_files'))
    deps=snapshot_files(paths('deck_dependencies'))
    inputs={x['path']:digest(x['path']) for x in plan['inputs'].values()}
    if 'layer_map' not in plan['inputs']:raise ValueError('explicit layer map required')
    receipts={k:str((root/b[k]).resolve()) for k in ('export_receipt','drc_receipt') if b.get(k)}
    if len(receipts)!=2:raise ValueError('two distinct receipt output paths required')
    outputs=list(plan['artifacts'].values())+list(receipts.values())
    outputs += [s[k] for s in plan['stages'] for k in ('stdout','stderr')]
    distinct_paths(list(oa)+list(deps)+list(inputs)+[plan['config_path']],outputs)
    if any(Path(p).exists() for p in outputs):raise ValueError('run outputs already exist; use a new iteration directory')
    return dict(oa=oa,dependencies=deps,inputs=inputs,receipts=receipts,
                config_sha256=plan['config_sha256'],policy={k:b[k] for k in ('metal_option','hierarchy_mode','result_limit','adapter_id')})

def verify_stage(plan,bound,stage,stream_hash=None):
    unchanged(bound['oa']);unchanged(bound['dependencies']);unchanged(bound['inputs'])
    if digest(plan['config_path'])!=bound['config_sha256']:raise ValueError('config drift')
    which='export_receipt' if stage=='streamout' else 'drc_receipt'
    p=Path(bound['receipts'][which]);r=json.loads(p.read_text(encoding='utf-8'))
    command=next(s for s in plan['stages'] if s['name']==stage)
    expected=dict(target=plan['config']['target'],config_sha256=plan['config_sha256'],
                  adapter_id=bound['policy']['adapter_id'],argv_sha256=fingerprint(command['argv']),
                  input_hashes=bound['inputs'],oa_hashes=bound['oa'],dependency_hashes=bound['dependencies'],
                  policy=bound['policy'])
    for k,v in expected.items():
        if r.get(k)!=v:raise ValueError('receipt mismatch '+stage+':'+k)
    if r.get('schema')!='analog-layout-drc.stage-receipt/v1' or r.get('stage')!=stage or r.get('completed') is not True:
        raise ValueError('incomplete stage receipt')
    if not all(isinstance(r.get(k),str) and r[k] for k in ('tool_version','interpreter_version')):
        raise ValueError('receipt lacks actual tool/interpreter versions')
    for k in ('stdout','stderr'):
        if r.get('log_hashes',{}).get(k)!=digest(command[k]):raise ValueError('log hash mismatch')
    artifacts=plan['artifacts']
    stream=Path(artifacts['stream'])
    if not stream.is_file() or stream.stat().st_size==0:raise ValueError('stream missing/empty')
    actual=digest(stream)
    if r.get('stream_path')!=str(stream.resolve()) or r.get('stream_sha256')!=actual:
        raise ValueError('receipt stream path/hash mismatch')
    if stage=='streamout':
        if r.get('saved_oa') is not True:raise ValueError('unsaved OA export')
        if r.get('oa_inventory_complete') is not True:raise ValueError('OA hierarchy inventory incomplete')
        if r.get('stream_format_validated') not in ('GDSII','OASIS'):raise ValueError('stream format not inspected by adapter')
    else:
        if stream_hash!=actual:raise ValueError('stream changed after export')
        if r.get('dependencies_complete') is not True:raise ValueError('include closure unverified')
        if r.get('result_limit_reached') is not False:raise ValueError('result limit reached/unknown')
        for k in ('summary','results'):
            if r.get('output_hashes',{}).get(k)!=digest(artifacts[k]):raise ValueError('result binding mismatch '+k)
    return dict(receipt_path=str(p),receipt_sha256=digest(p),stream_sha256=actual,tool_version=r['tool_version'])
