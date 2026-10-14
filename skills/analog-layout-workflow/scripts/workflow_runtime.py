"""Revision-bound checkpoint validation and next-stage selection; no CAD writes."""
from __future__ import annotations
import argparse,copy,hashlib,json,os,tempfile
from pathlib import Path

SCHEMA='analog-layout-workflow.state/v1'
DEPS={'discover':[], 'place':['discover'], 'share':['place'], 'gate-access':['share'],
      'ring':['gate-access'], 'symmetry':['ring'], 'macro-opt':['symmetry'],
      'route-intent':['macro-opt'], 'route-apply':['route-intent'],
      'drc':['route-apply'], 'lvs':['route-apply'], 'pex':['drc','lvs'], 'postsim':['pex'],
      'performance-opt':['postsim']}
DONE={'LOCALLY_VERIFIED','CHECKED_WITH_LIMITATIONS','CLOSED','SKIPPED'}
class Invalid(ValueError):pass
def canonical(x):
    if isinstance(x,float) and x.is_integer():return int(x)
    if isinstance(x,list):return [canonical(v) for v in x]
    if isinstance(x,dict):return {k:canonical(v) for k,v in x.items()}
    return x
def digest(x):return hashlib.sha256(json.dumps(canonical(x),sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
def filehash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=p.name+'.',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(x,f,indent=2,ensure_ascii=False,allow_nan=False)
        os.replace(tmp,p)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()
def identity(x):
    if not isinstance(x,dict) or not all(isinstance(x.get(k),str) and x[k] for k in ('lib','cell','view')):raise Invalid('Exact cellview identity required')
def init(config):
    for k in ('source','reference','destination'):identity(config.get(k))
    if config['source']==config['destination']:raise Invalid('Destination must preserve source')
    stages=config.get('requested_stages',list(DEPS)[:11])
    if not stages or len(set(stages))!=len(stages) or any(s not in DEPS for s in stages):raise Invalid('Invalid requested stages')
    if not config.get('last_human_decision'):raise Invalid('Human scope decision missing')
    if not config.get('constraints') or not config.get('bindings'):raise Invalid('Constraints and revision/PDK bindings required')
    state=dict(schema=SCHEMA,run_id=config['run_id'],mode=config.get('mode','plan'),source=config['source'],reference=config['reference'],current=config['source'],destination=config['destination'],save_policy=config.get('save_policy'),last_human_decision=config['last_human_decision'],constraints=config['constraints'],bindings=config['bindings'],scope=stages,stages={},history=[])
    for field in ('dispatch_inputs','authorized_targets'):
        if field in config:state[field]=copy.deepcopy(config[field])
    return state
def token(record):return digest(record)
def share_skip_authorized(record):
    authorization=record.get('user_skip_authorization')
    return (isinstance(authorization,dict) and authorization.get('source')=='user'
            and authorization.get('scope')=='share'
            and isinstance(authorization.get('instruction'),str)
            and bool(authorization['instruction'].strip()))
def checked(state,base,bindings=None):
    if state.get('schema')!=SCHEMA:raise Invalid('Unsupported state schema')
    for k in ('source','reference','destination','current'):identity(state.get(k))
    if not isinstance(state.get('scope'),list) or len(set(state['scope']))!=len(state['scope']) or any(s not in DEPS for s in state['scope']):raise Invalid('Invalid scope')
    base=Path(base);results={};current=bindings if bindings is not None else state['bindings']
    artifact_hashes={}
    for sid in DEPS:
        r=state.get('stages',{}).get(sid)
        if not r:results[sid]=dict(status='NOT_STARTED',issues=[]);continue
        issues=[]
        if sid=='share' and r.get('status')=='SKIPPED' and not share_skip_authorized(r):
            issues.append('diffusion sharing skip requires explicit user instruction')
        for key,value in r.get('input_bindings',{}).items():
            if current.get(key)!=value:issues.append('changed binding: '+key)
        if r.get('constraints_sha256')!=digest(state['constraints']):issues.append('constraints changed')
        for dep in DEPS[sid]:
            actual=state['stages'].get(dep)
            if actual is None or r.get('dependency_tokens',{}).get(dep)!=token(actual):issues.append('changed/missing dependency: '+dep)
            if results.get(dep,{}).get('status') not in DONE:issues.append('dependency not verified: '+dep)
        for a in r.get('artifacts',[]):
            if a.get('host','local')!='local':issues.append('remote artifact requires downloaded receipt: '+a.get('path',''));continue
            p=Path(a['path']);p=p if p.is_absolute() else base/p
            key=p.resolve()
            if key not in artifact_hashes:artifact_hashes[key]=filehash(p) if p.is_file() else None
            if artifact_hashes[key]!=a.get('sha256') or artifact_hashes[key] is None:issues.append('missing/changed artifact: '+str(p))
        if r.get('status') in DONE and not r.get('artifacts'):issues.append('no immutable evidence')
        if sid=='performance-opt' and r.get('status') in DONE and r.get('validation',{}).get('verdict') not in {'DECISION_READY','NO_ACTION','STOPPED'}:
            issues.append('performance optimization needs a decision verdict, not a performance pass')
        if sid in {'drc','lvs','pex','performance-opt'} and r.get('status') in DONE:
            layout_revision=state.get('current_revision') or state.get('stages',{}).get('route-apply',{}).get('output_revision')
            if not layout_revision or r.get('output_revision')!=layout_revision:issues.append('result is not bound to current routed revision')
            if r.get('checked_cellview')!=state['current']:issues.append('result belongs to another/missing cellview identity')
        results[sid]=dict(status='STALE' if issues else r.get('status','NOT_STARTED'),issues=issues,verdict=r.get('validation',{}).get('verdict'))
    return results
def next_action(state,base,bindings=None):
    results=checked(state,base,bindings)
    for sid in DEPS:
        if sid not in state['scope']:continue
        if results[sid]['status'] in DONE:continue
        missing=[d for d in DEPS[sid] if results[d]['status'] not in DONE]
        if missing:return dict(status='BLOCKED_DEPENDENCY',stage=sid,missing=missing,stages=results)
        if state['mode']=='plan' and sid in {'route-apply','drc','lvs','pex','postsim'}:return dict(status='STOP_AT_PLAN_BOUNDARY',stage=sid,stages=results)
        if results[sid]['status']=='BLOCKED':return dict(status='BLOCKED',stage=sid,reason=state['stages'][sid].get('next_action'),stages=results)
        if sid=='pex':
            lv=state['stages']['lvs']['validation']['verdict'];dr=state['stages']['drc']['validation']['verdict']
            current_revision=state.get('current_revision') or state['stages']['route-apply'].get('output_revision')
            if not current_revision or state['stages']['lvs'].get('output_revision')!=current_revision or state['stages']['drc'].get('output_revision')!=current_revision:return dict(status='BLOCKED_REVISION_MISMATCH',stage=sid,stages=results)
            authorization=state.get('exploratory_pex_authorization')
            evidence=state.get('verification',{}).get('lvs',{})
            exploratory_match=(isinstance(authorization,dict)
                and authorization.get('source')=='user' and authorization.get('scope')=='pex'
                and isinstance(authorization.get('instruction'),str) and bool(authorization['instruction'].strip())
                and authorization.get('revision')==current_revision and authorization.get('checked_cellview')==state['current']
                and lv=='REPORT_MATCH_UNVERIFIED' and evidence.get('status')=='REPORT_MATCH_UNVERIFIED'
                and evidence.get('report_verdict')=='CORRECT' and evidence.get('independent_reference') is True
                and evidence.get('revision')==current_revision and evidence.get('checked_cellview')==state['current'])
            if lv!='VERIFIED_MATCH' and not exploratory_match:return dict(status='BLOCKED_LVS',stage=sid,stages=results)
            if dr!='CLEAN' and not state.get('exploratory_pex_authorization'):return dict(status='BLOCKED_DRC',stage=sid,stages=results)
        return dict(status='READY',stage=sid,reason=results[sid]['issues'],stages=results)
    dr=state['stages'].get('drc',{}).get('validation',{}).get('verdict')
    lv=state['stages'].get('lvs',{}).get('validation',{}).get('verdict')
    return dict(status='REQUESTED_STAGES_COMPLETE',physical_closure=dr=='CLEAN' and lv=='VERIFIED_MATCH' and state['stages']['drc'].get('status')=='CLOSED' and state['stages']['lvs'].get('status')=='CLOSED' and state['stages']['drc'].get('output_revision')==state['stages']['lvs'].get('output_revision'),stages=results)
def checkpoint(state,sid,receipt,base):
    if sid not in state['scope']:raise Invalid('Stage outside adopted scope')
    status=receipt.get('status');v=receipt.get('validation',{})
    if status not in DONE|{'CANDIDATE','MATERIALIZED_UNVERIFIED','BLOCKED'}:raise Invalid('Invalid status')
    if sid=='share' and status=='SKIPPED' and not share_skip_authorized(receipt):
        raise Invalid('Diffusion sharing cannot be skipped without explicit user instruction')
    valid=checked(state,base)
    if status in DONE and any(valid[d]['status'] not in DONE for d in DEPS[sid]):raise Invalid('Dependencies invalid')
    if status=='SKIPPED' and (not receipt.get('skip_reason') or receipt.get('skip_dependency_safe') is not True):raise Invalid('Skipped stage needs applicability evidence')
    if status in DONE and (not receipt.get('artifacts') or not v.get('verdict')):raise Invalid('Evidence and native verdict required')
    if status=='CLOSED' and sid=='drc' and v.get('verdict')!='CLEAN':raise Invalid('DRC closure must be CLEAN')
    if status=='CLOSED' and sid=='lvs' and v.get('verdict')!='VERIFIED_MATCH':raise Invalid('LVS closure must be verified independent match')
    if sid=='performance-opt' and status in DONE and v.get('verdict') not in {'DECISION_READY','NO_ACTION','STOPPED'}:
        raise Invalid('Performance optimization completion requires a decision verdict')
    if sid=='performance-opt' and receipt.get('output_cellview') and receipt['output_cellview']!=state['current']:
        raise Invalid('Performance decision cannot advance the physical layout target')
    if status in DONE and sid in {'route-apply','ring','gate-access'} and not receipt.get('readback_verified'):raise Invalid('Saved geometry readback required')
    if status in DONE and sid in {'drc','lvs','pex','performance-opt'}:
        current_revision=state.get('current_revision') or state.get('stages',{}).get('route-apply',{}).get('output_revision')
        if not current_revision or receipt.get('output_revision')!=current_revision:raise Invalid('Report revision is not current routed revision')
        if receipt.get('checked_cellview')!=state['current']:raise Invalid('Report cellview is not current routed target')
    record=copy.deepcopy(receipt)
    record.update(input_bindings=copy.deepcopy(state['bindings']),constraints_sha256=digest(state['constraints']),dependency_tokens={d:token(state['stages'][d]) for d in DEPS[sid]})
    child=copy.deepcopy(state);child['stages'][sid]=record
    if checked(child,base)[sid]['issues']:raise Invalid(str(checked(child,base)[sid]['issues']))
    if receipt.get('output_cellview') and receipt.get('readback_verified'):
        if not receipt.get('output_revision'):raise Invalid('Saved output revision missing')
        identity(receipt['output_cellview']);child['current']=receipt['output_cellview'];child['current_revision']=receipt['output_revision']
    child['history'].append(dict(stage=sid,record_sha256=token(record),previous_sha256=token(state['stages'][sid]) if sid in state['stages'] else None))
    return child
def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['init','next','check','checkpoint']);p.add_argument('--state',required=True);p.add_argument('--config');p.add_argument('--bindings');p.add_argument('--stage');p.add_argument('--receipt');p.add_argument('--out');a=p.parse_args()
    dest=Path(a.state)
    if a.command=='init':
        if dest.exists():raise Invalid('State exists')
        result=init(load(a.config));write(dest,result)
    elif a.command=='checkpoint':
        result=checkpoint(load(dest),a.stage,load(a.receipt),dest.parent);write(dest,result)
    else:
        s=load(dest);b=load(a.bindings) if a.bindings else None
        result=next_action(s,dest.parent,b) if a.command=='next' else checked(s,dest.parent,b)
    if a.out:write(a.out,result)
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
