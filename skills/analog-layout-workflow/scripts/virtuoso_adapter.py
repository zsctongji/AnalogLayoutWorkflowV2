"""Concrete bridge backend: exact native snapshot and owned rectangle transactions.

Does not edit PCells/ROD/vias/pins or certify PDK legality. Qualification must
bind this implementation, site and capability; an installed file is not a permit.
"""
from __future__ import annotations
import json,sys,hashlib,copy,math
from pathlib import Path
from workflow_runtime import digest,Invalid,identity

def q(s):return json.dumps(s,ensure_ascii=True)
def pt(p):return 'list('+ ' '.join(repr(float(x)) for x in p)+')'
def bbox(b):return 'list('+pt(b[0])+' '+pt(b[1])+')'
class VirtuosoBackend:
    def __init__(self,client,skills_root,qualification=None):
        self.client=client;self.qualification=qualification;self.tx=None
        sys.path.insert(0,str(Path(skills_root)/'analog-layout-guard-ring/scripts'))
        from inspect_reference import parse_lisp
        self.parse=parse_lisp
    def ev(self,code):
        r=self.client.execute_skill('progn('+code+')')
        if not r.ok:raise Invalid(str(r.errors)+' '+str(r.output))
        return self.parse(r.output)
    def require(self,capability):
        if capability not in ('rect-create','rect-replace'):raise Invalid('Unsupported native operation')
        qual=self.qualification or {}
        if qual.get('adapter_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest() or capability not in qual.get('capabilities',[]):raise Invalid('Missing matching live qualification')
        if qual.get('site')!=self.ev('list(getHostName() getVersion())'):raise Invalid('Qualification site/version drift')
    def select(self,target,mode='r'):
        identity(target)
        self.ev('p0Cv=dbOpenCellViewByType('+q(target['lib'])+' '+q(target['cell'])+' '+q(target['view'])+' "maskLayout" '+q(mode)+') unless(p0Cv error("No explicit cellview")) t')
    def raw(self,allow_modified=False):
        if not allow_modified and self.ev('p0Cv~>modified'):raise Invalid('Unsaved source')
        return self.ev('''list(
        foreach(mapcar i p0Cv~>instances list(i~>name i~>libName i~>cellName i~>viewName i~>xy i~>orient i~>bBox
          foreach(mapcar p i~>master~>parameters~>value list(p~>name p~>valueType p~>value))
          foreach(mapcar tm i~>master~>terminals list(tm~>name foreach(mapcar p tm~>pins foreach(mapcar f p~>figs list(f~>objType f~>lpp dbTransformBBox(f~>bBox i~>transform))))))
          foreach(mapcar f i~>master~>shapes list(f~>objType f~>lpp dbTransformBBox(f~>bBox i~>transform) f~>points f~>width f~>theLabel))))
        foreach(mapcar f p0Cv~>shapes list(f~>objType f~>lpp f~>bBox f~>points f~>width f~>net~>name f~>theLabel f~>origin f~>p0Id f~>p0Owner f~>draftRouteId f~>otaId))
        foreach(mapcar v p0Cv~>vias list(v~>viaHeader~>viaDefName v~>origin v~>orient v~>bBox v~>viaHeader~>overrideParams))
        foreach(mapcar tm p0Cv~>terminals list(tm~>name tm~>net~>name tm~>direction foreach(mapcar p tm~>pins foreach(mapcar f p~>figs list(f~>objType f~>lpp f~>bBox f~>p0Id f~>draftRouteId f~>otaId)))))
        techGetMfgGridResolution(techGetTechFile(p0Cv)))''')
    def normalized(self,raw):
        objects=[];protected=[]
        for f in raw[1] or []:
            if f[8]:
                if f[0]!='rect' or not f[9]:raise Invalid('Managed nonrect/unowned shape')
                objects.append(dict(id=f[8],owner=f[9],net=f[5],kind='rect',lpp=f[1],bbox_um=f[2]))
            else:protected.append(f)
        if len({o['id'] for o in objects})!=len(objects):raise Invalid('Duplicate managed IDs')
        canonical=lambda a:sorted(a or [],key=lambda x:json.dumps(x,sort_keys=True))
        return dict(objects=sorted(objects,key=lambda x:x['id']),protected=dict(instances=canonical(raw[0]),shapes=canonical(protected),vias=canonical(raw[2]),terminals=canonical(raw[3]),grid_um=raw[4]))
    def snapshot(self,target):
        old=self.tx
        self.select(target)
        result=self.normalized(self.raw())
        if old:self.select(old['target'],'a')
        return result
    def exists(self,target):
        identity(target)
        # Reject a cell as well as its view, avoiding overwriting another design.
        return bool(self.ev('if(ddGetObj('+q(target['lib'])+' '+q(target['cell'])+') t nil)'))
    def begin_clone(self,source,target):
        if self.tx:raise Invalid('Adapter transaction already active')
        if self.exists(target):raise Invalid('Destination exists')
        self.select(source)
        before=self.normalized(self.raw())
        self.ev('foreach(w hiGetWindowList() when(w~>cellView && w~>cellView~>libName=='+q(target['lib'])+' && w~>cellView~>cellName=='+q(target['cell'])+' error("Destination editor open"))) let((d) d=dbCopyCellView(p0Cv '+q(target['lib'])+' '+q(target['cell'])+' '+q(target['view'])+' nil) unless(d error("Clone failed")) dbClose(d)) t')
        self.tx=dict(source=source,target=target,before=before,written=set())
        self.select(target,'a');return self.tx
    def read(self,tx):
        if tx is not self.tx:raise Invalid('Wrong transaction')
        self.select(tx['target'],'a');return self.normalized(self.raw(True))
    def apply(self,tx,edit):
        # Compatibility entrypoint; production stage runtime calls apply_batch once.
        return self.apply_batch(tx,[edit])
    def apply_batch(self,tx,edits):
        if tx is not self.tx or tx.get('batch_applied'):
            raise Invalid('Wrong transaction or stage batch already applied')
        current={o['id']:o for o in tx['before']['objects']}
        planned=[]; ids=set()
        grid=tx['before']['protected'].get('grid_um')
        for edit in edits:
            ident=edit['id'];new=edit['after'];old=current.get(ident)
            if ident in ids or ident in tx['written']:raise Invalid('Duplicate operation')
            ids.add(ident)
            if new['id']!=ident or new['kind']!='rect' or not new['owner'] or not new['net']:
                raise Invalid('Unsupported/new identity')
            if edit['op']=='replace':
                if old is None or digest(old)!=edit['before_sha256'] or any(old[k]!=new[k] for k in ('id','kind','net','owner','lpp')):
                    raise Invalid('Stale/protected identity')
            elif edit['op']=='create':
                if old is not None:raise Invalid('Existing managed object')
            else:raise Invalid('Operation not implemented')
            bb=new['bbox_um'];lpp=new['lpp']
            if len(lpp)!=2 or not all(isinstance(s,str) and s for s in lpp):raise Invalid('Invalid LPP')
            if len(bb)!=2 or any(len(p)!=2 for p in bb) or any(not math.isfinite(float(v)) for p in bb for v in p) or any(bb[0][a]>=bb[1][a] for a in (0,1)):
                raise Invalid('Invalid rectangle geometry')
            if grid and any(abs(v/grid-round(v/grid))>1e-6 for p in bb for v in p):
                raise Invalid('Off-grid rectangle')
            planned.append(edit)
        # Compact data list plus one native loop; precheck all identities before any mutation.
        records='list('+' '.join('list('+q(e['op'])+' '+q(e['id'])+' '+q(e['after']['owner'])+' '+q(e['after']['net'])+' list('+q(e['after']['lpp'][0])+' '+q(e['after']['lpp'][1])+') '+bbox(e['after']['bbox_um'])+')' for e in planned)+')'
        if planned:
            code='let((ops index f n fs count)\n              ops=RECORDS index=makeTable(\'p0BatchObjects nil) count=0\n              foreach(shape p0Cv~>shapes when(shape~>p0Id index[shape~>p0Id]=cons(shape index[shape~>p0Id])))\n              foreach(e ops\n                fs=index[cadr(e)]\n                if(car(e)=="replace"\n                  unless(length(fs)==1 && car(fs)~>objType=="rect" && car(fs)~>p0Owner==caddr(e) && car(fs)~>net~>name==cadddr(e) && car(fs)~>lpp==nth(4 e) error("Native batch identity drift"))\n                  when(fs error("Native batch create already exists"))))\n              foreach(e ops\n                if(car(e)=="replace"\n                  car(index[cadr(e)])~>bBox=nth(5 e)\n                  progn(n=dbMakeNet(p0Cv cadddr(e)) f=dbCreateRect(p0Cv nth(4 e) nth(5 e)) unless(f error("Rectangle failed"))\n                    dbAddFigToNet(f n) dbReplaceProp(f "p0Id" "string" cadr(e)) dbReplaceProp(f "p0Owner" "string" caddr(e))))\n                count=count+1)\n              count)'
            count=self.ev(code.replace('RECORDS',records))
            if count!=len(planned):raise Invalid('Incomplete native batch; discard unsaved transaction')
        tx['written'].update(ids);tx['batch_applied']=True
        tx['mutation_batch_count']=1 if planned else 0
    def commit(self,tx):
        self.select(tx['target'],'a')
        tx['save_state']='uncertain'
        if not self.ev('dbSave(p0Cv)'):
            tx['save_state']='unsaved';raise Invalid('Save failed')
        tx['save_state']='saved'
        self.ev('dbClose(p0Cv) p0Cv=nil t');self.tx=None
    def rollback(self,tx):
        if tx.get('save_state','unsaved')!='unsaved':raise Invalid('Saved/uncertain target cannot be purged as rollback')
        self.select(tx['target'],'a');self.ev('dbPurge(p0Cv) p0Cv=nil t');self.tx=None
        if self.snapshot(tx['target'])!=tx['before']:raise Invalid('Rollback clone differs from baseline')
        return dict(status='DISCARDED_ALL_UNSAVED_EDITS',retained_baseline_clone=tx['target'])
