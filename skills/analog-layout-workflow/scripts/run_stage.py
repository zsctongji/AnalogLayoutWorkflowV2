"""Execute exactly one hash-pinned installed stage adapter, then validate receipt.

Registry entries are reviewed site code, not a free-form shell command in a plan.
Each adapter consumes handoff.json and must emit stage-receipt.json in its run dir.
"""
from __future__ import annotations
import argparse,json,subprocess,time
from pathlib import Path
from workflow_runtime import load,write,filehash,digest,next_action,checkpoint,Invalid
from dispatch_preflight import placement_preflight, matching_policy

def run_stage(state_path,registry_path,runs,execute=False):
    dispatch_started=time.perf_counter()
    state_path=Path(state_path);registry_path=Path(registry_path)
    state=load(state_path);registry=load(registry_path)
    if registry.get('schema')!='analog-layout-workflow.registry/v1':raise Invalid('Unknown adapter registry')
    action=next_action(state,state_path.parent)
    if action['status']!='READY':return action
    stage=action['stage'];entry=registry.get('stages',{}).get(stage)
    if not entry:return dict(status='BLOCKED_CAPABILITY',stage=stage,reason='No installed stage adapter')
    script=Path(entry['script']);script=script if script.is_absolute() else registry_path.parent/script
    if not script.is_file() or filehash(script)!=entry.get('script_sha256'):raise Invalid('Stage adapter changed')
    python=Path(entry['python'])
    if not python.is_file():raise Invalid('Interpreter unavailable')
    pinned={script.resolve():filehash(script)}
    if entry.get('python_sha256'):
        if filehash(python)!=entry['python_sha256']:raise Invalid('Interpreter changed')
        pinned[python.resolve()]=entry['python_sha256']
    for a in entry.get('qualification_evidence',[])+entry.get('code_dependencies',[]):
        p=Path(a['path']);p=p if p.is_absolute() else registry_path.parent/p
        if not p.is_file() or filehash(p)!=a['sha256']:raise Invalid('Adapter qualification evidence changed')
        pinned[p.resolve()]=a['sha256']
    if entry.get('mutating'):
        if state['mode'] not in {'execute','resume'} or not entry.get('qualification_evidence'):raise Invalid('Write capability not qualified/authorized')
        targets=state.get('authorized_targets',{})
        if stage not in targets:raise Invalid('Exact destination for stage missing')
    preflight=None
    if stage=='place':
        try:preflight=placement_preflight(state,state_path.parent,bool(entry.get('mutating')))
        except Invalid as error:return dict(status='BLOCKED_PREFLIGHT',stage=stage,reason=str(error))
        for a in preflight['artifacts']:pinned[Path(a['path'])]=a['sha256']
    preview=dict(status='PREVIEW',stage=stage,script=str(script),script_sha256=filehash(script),state_sha256=digest(state),mutating=bool(entry.get('mutating')))
    if not execute:return preview
    run=Path(runs)/f'{state["run_id"]}-{stage}-{time.time_ns()}'
    run.mkdir(parents=True,exist_ok=False)
    handoff=dict(stage=stage,state_sha256=digest(state),source=state['current'],reference=state['reference'],target=state.get('authorized_targets',{}).get(stage),constraints=state['constraints'],bindings=state['bindings'],dependencies={s:state['stages'][s] for s in __import__('workflow_runtime').DEPS[stage]},mode=state['mode'],authorization=state['last_human_decision'],run_dir=str(run.resolve()),
                 execution_policy={'reuse_valid_dependency_evidence':True,'rerun_only_changed_inputs':True,'preserve_required_fresh_live_readback':True,'cad_write_boundary':'stage_end_only','planning_read_only':True,'apply_batch_once':True,'save_once':True,'include_conopc':state['constraints'].get('include_conopc',False)},dispatch_preflight=preflight,matching_policy=matching_policy(state))
    handoff['stage_inputs']=state.get('dispatch_inputs',{}).get(stage,{})
    write(run/'handoff.json',handoff)
    argv=[str(python),str(script),'--handoff',str((run/'handoff.json').resolve()),'--out',str((run/'stage-receipt.json').resolve())]
    started=time.time()
    validation_seconds=time.perf_counter()-dispatch_started
    execution_started=time.perf_counter()
    try:
        with (run/'console.log').open('w',encoding='utf-8') as log:
            proc=subprocess.run(argv,cwd=registry_path.parent,stdout=log,stderr=subprocess.STDOUT,timeout=entry.get('timeout_seconds',60),shell=False)
        command=dict(argv=argv,start=started,end=time.time(),exit_code=proc.returncode,script_sha256=filehash(script),
                     timing_seconds={'dispatch_preparation':validation_seconds,'adapter_execution':time.perf_counter()-execution_started})
    except subprocess.TimeoutExpired:
        write(run/'command.json',dict(argv=argv,start=started,end=time.time(),status='TIMEOUT',timing_seconds={'dispatch_preparation':validation_seconds,'adapter_execution':time.perf_counter()-execution_started}))
        return dict(status='EXECUTION_INCOMPLETE',stage=stage,run=str(run),warning='Inspect any live transaction; timeout is not rollback')
    write(run/'command.json',command)
    receipt_started=time.perf_counter()
    if any(not p.is_file() or filehash(p)!=sha for p,sha in pinned.items()):raise Invalid('Adapter code/dependency changed during run; retain outputs, do not checkpoint')
    if proc.returncode!=0:return dict(status='EXECUTION_FAILED',stage=stage,run=str(run))
    receipt_path=run/'stage-receipt.json'
    if not receipt_path.is_file():return dict(status='INCOMPLETE_NO_RECEIPT',stage=stage,run=str(run))
    receipt=load(receipt_path)
    if receipt.get('handoff_sha256')!=digest(handoff):raise Invalid('Stage receipt belongs to another handoff')
    if entry.get('mutating') and receipt.get('output_cellview')!=handoff['target']:raise Invalid('Wrong saved target')
    # Only dispatcher phases are measured here; never infer network/CAD time.
    receipt['dispatcher_timing_seconds']=dict(command['timing_seconds'],receipt_validation=time.perf_counter()-receipt_started)
    if preflight:
        receipt.setdefault('artifacts',[]).extend(preflight['artifacts'])
    # The dispatcher closes these logs after the child exits. Child receipts
    # must not pre-hash the still-changing console. Bind final execution here.
    receipt.setdefault('artifacts',[])
    for p in [run/'command.json',run/'console.log',receipt_path]:
        receipt['artifacts'].append(dict(path=str(p.resolve()),sha256=filehash(p),host='local'))
    # Relative artifact paths are local to the isolated child run.
    for a in receipt.get('artifacts',[]):
        p=Path(a['path']);a['path']=str(p if p.is_absolute() else (run/p).resolve())
    checkpoint_started=time.perf_counter()
    result=checkpoint(state,stage,receipt,state_path.parent)
    if digest(load(state_path))!=digest(state):raise Invalid('Concurrent checkpoint changed; do not overwrite')
    write(state_path,result)
    timing=dict(receipt['dispatcher_timing_seconds'],checkpoint=time.perf_counter()-checkpoint_started,total=time.perf_counter()-dispatch_started)
    write(run/'performance.json',dict(stage=stage,timing_seconds=timing,scope='Dispatcher timing; adapter time includes CAD/IPC/network and is not decomposed'))
    return dict(status='CHECKPOINTED',stage=stage,run=str(run),timing_seconds=timing,next=next_action(result,state_path.parent))
def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--registry',required=True);p.add_argument('--runs',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args()
    print(json.dumps(run_stage(a.state,a.registry,a.runs,a.execute),indent=2,ensure_ascii=False))
if __name__=='__main__':main()
