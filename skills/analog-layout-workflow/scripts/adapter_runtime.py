"""One bounded clone/apply/readback transaction across qualified site backends.

No generic geometry legality solver. Verifiers are installed trusted code, not
PASS flags from a plan. Saved failures are retained and never reported rolled back.
"""
from __future__ import annotations
import copy
from workflow_runtime import digest,Invalid

GATES=('connectivity','pin_access','pdk_geometry','symmetry','protected','environment')
def verify_receipt(receipt,before,after):
    if receipt.get('before_sha256')!=digest(before) or receipt.get('after_sha256')!=digest(after):raise Invalid('Verifier binding mismatch')
    if any(receipt.get('checks',{}).get(k)!='PASS' for k in GATES):raise Invalid('Verifier FAIL/UNKNOWN')
    if not receipt.get('evidence'):raise Invalid('No verifier evidence')
def execute(plan,backend,verifier):
    required={'source','target','authorization','snapshot_sha256','edits','expected_after_sha256','capability'}
    if not required<=set(plan) or not plan['authorization']:raise Invalid('Incomplete authorized transaction')
    if plan['source']==plan['target']:raise Invalid('Source overwrite forbidden')
    backend.require(plan['capability'])
    before=backend.snapshot(plan['source'])
    if digest(before)!=plan['snapshot_sha256']:raise Invalid('Source drift')
    if backend.exists(plan['target']):raise Invalid('Target exists/open/locked')
    ids=[e['id'] for e in plan['edits']]
    if len(ids)!=len(set(ids)) or not set(ids)<=set(plan.get('authorized_ids',[])):raise Invalid('Duplicate/unauthorized edits')
    tx=None;saved=False
    try:
        tx=backend.begin_clone(plan['source'],plan['target'])
        if backend.read(tx)!=before:raise Invalid('Clone readback drift')
        if not callable(getattr(backend,'apply_batch',None)):raise Invalid('Stage writer must implement one apply_batch')
        backend.apply_batch(tx,plan['edits'])
        after=backend.read(tx)
        if digest(after)!=plan['expected_after_sha256']:raise Invalid('Complete readback differs from expected')
        evidence=verifier(before,after,plan);verify_receipt(evidence,before,after)
        if backend.snapshot(plan['source'])!=before:raise Invalid('Concurrent source drift')
        backend.commit(tx);saved=True
        target=backend.snapshot(plan['target'])
        if target!=after or backend.snapshot(plan['source'])!=before:raise Invalid('Saved/source readback drift')
        return dict(status='SAVED_LOCALLY_VERIFIED',target=plan['target'],saved_sha256=digest(target),verifier=evidence,signoff=False)
    except Exception as exc:
        # A save may succeed before close/readback fails; transport loss during
        # dbSave is ambiguous. Never purge that state as an unsaved transaction.
        save_state=tx.get('save_state','unsaved') if isinstance(tx,dict) else 'unsaved'
        if saved or save_state=='saved':raise Invalid('SAVED_NOT_CLOSED: '+str(exc)) from exc
        if save_state=='uncertain':raise Invalid('SAVE_STATE_UNKNOWN: retain target and inspect; '+str(exc)) from exc
        if tx is not None and not saved:
            try:
                rollback=backend.rollback(tx)
                if backend.snapshot(plan['source'])!=before:raise Invalid('Source changed during rollback')
            except Exception as rb:raise Invalid('ROLLBACK_FAILED: '+str(rb)+'; original: '+str(exc)) from rb
            raise Invalid('TRANSACTION_ABORTED: '+str(exc)+'; rollback='+str(rollback)) from exc
        raise

class MemoryBackend:
    """Fault-injection fixture only, never a production adapter."""
    def __init__(self,snapshot):self.views={'source':copy.deepcopy(snapshot)};self.tx=None;self.fail_at=None
    def require(self,capability):
        if capability not in {'rect-create','rect-replace'}:raise Invalid('Unsupported capability')
    def snapshot(self,target):return copy.deepcopy(self.views[target['cell']])
    def exists(self,target):return target['cell'] in self.views
    def begin_clone(self,source,target):self.tx=dict(cell=target['cell'],value=self.snapshot(source));return self.tx
    def read(self,tx):return copy.deepcopy(tx['value'])
    def apply(self,tx,edit):
        if self.fail_at==edit['id']:raise Invalid('injected apply fault')
        objs=tx['value']['objects'];old=next((o for o in objs if o['id']==edit['id']),None)
        if edit['op']=='replace':
            if old is None or digest(old)!=edit['before_sha256']:raise Invalid('Stale object')
            objs[objs.index(old)]=copy.deepcopy(edit['after'])
        elif edit['op']=='create':
            if old is not None:raise Invalid('Duplicate object')
            objs.append(copy.deepcopy(edit['after']))
        else:raise Invalid('Unsupported edit')
        objs.sort(key=lambda x:x['id'])
    def apply_batch(self,tx,edits):
        for edit in edits:self.apply(tx,edit)
    def commit(self,tx):self.views[tx['cell']]=copy.deepcopy(tx['value']);self.tx=None
    def rollback(self,tx):self.tx=None;return {'status':'DISCARDED_UNSAVED'}
