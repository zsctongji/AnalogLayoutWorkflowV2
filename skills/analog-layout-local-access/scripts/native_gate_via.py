"""Native dbCreateVia stage backend and exact replacement verifier (rectangular PO1_M1)."""
from pathlib import Path
import sys,copy
S=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(S/'analog-layout-workflow/scripts'))
from virtuoso_adapter import VirtuosoBackend,q,pt
from workflow_runtime import digest,Invalid,filehash

class NativeGateBackend(VirtuosoBackend):
    def require(self,capability):
        if capability!='native-gate-via':raise Invalid('Unsupported native gate capability')
        proof=self.qualification or {}
        if proof.get('native_adapter_sha256')!=filehash(__file__) or proof.get('rectangle_base_sha256')!=filehash(S/'analog-layout-workflow/scripts/virtuoso_adapter.py'):
            raise Invalid('Native gate adapter qualification/code drift')
        if proof.get('site')!=self.ev('list(getHostName() getVersion())'):raise Invalid('Native gate site drift')
    def raw(self,allow_modified=False):
        raw=super().raw(allow_modified)
        raw.append(self.ev('''foreach(mapcar v p0Cv~>vias list(v~>p0ViaId v~>p0Owner v~>p0Instance v~>net~>name v~>viaHeader~>viaDefName v~>origin v~>orient v~>bBox v~>viaHeader~>overrideParams
          foreach(mapcar f v~>viaHeader~>master~>shapes list(f~>objType f~>lpp dbTransformBBox(f~>bBox list(v~>origin v~>orient 1.0)) f~>points f~>width))))'''))
        return raw
    def normalized(self,raw):
        result=super().normalized(raw[:5]);owned=[];foreign=[]
        for v in raw[5] or []:
            if not v[0]:foreign.append(v);continue
            if not v[1] or not v[2] or not v[3] or v[4]!='PO1_M1' or v[8]:raise Invalid('Unsupported native via identity/overrides')
            figures=[]
            for f in v[9] or []:
                if f[0]!='rect' or f[3] or f[4]:raise Invalid('Unsupported via primitive')
                figures.append(dict(kind=f[0],lpp=f[1],bbox_um=f[2]))
            owned.append(dict(id=v[0],owner=v[1],instance=v[2],net=v[3],via_def=v[4],origin_um=v[5],orientation=v[6],bbox_um=v[7],override_parameters=v[8],figures=sorted(figures,key=digest)))
        if len({v['id'] for v in owned})!=len(owned):raise Invalid('Duplicate native via IDs')
        result['native_vias']=sorted(owned,key=lambda v:v['id'])
        result['protected']['vias']=sorted(foreign,key=digest)
        return result
    def apply_batch(self,tx,edits):
        if tx is not self.tx or tx.get('batch_applied'):raise Invalid('Wrong/used native stage transaction')
        before={o['id']:o for o in tx['before']['objects']};seen=set();data=[]
        for e in edits:
            v=e['after'];ids=e['delete_ids']
            if e['op']!='native-via-replace' or e['id']!=v['id'] or v['via_def']!='PO1_M1' or v['orientation']!='R0':raise Invalid('Unsupported native operation')
            if not ids or len(ids)!=len(set(ids)) or seen.intersection(ids):raise Invalid('Overlapping native replacements')
            seen.update(ids)
            for ident in ids:
                old=before.get(ident)
                if old is None or digest(old)!=e['before_sha256'][ident] or old['owner']!=v['owner'] or old['net']!=v['net']:raise Invalid('Native replacement ownership/source drift')
            data.append('list('+q(v['id'])+' '+q(v['owner'])+' '+q(v['instance'])+' '+q(v['net'])+' '+pt(v['origin_um'])+' list('+' '.join(q(n) for n in ids)+'))')
        operations='list('+' '.join(data)+')'
        code='''let((ops vd index fs v n count)
          ops=OPERATIONS vd=techFindViaDefByName(techGetTechFile(p0Cv) "PO1_M1") unless(vd error("Missing PO1_M1"))
          index=makeTable('nativeGateObjects nil) count=0
          foreach(f p0Cv~>shapes when(f~>p0Id index[f~>p0Id]=cons(f index[f~>p0Id])))
          foreach(e ops foreach(ident nth(5 e) fs=index[ident] unless(length(fs)==1 && car(fs)~>p0Owner==cadr(e) && car(fs)~>net~>name==cadddr(e) error("Native gate replacement drift"))))
          foreach(e ops
            n=dbMakeNet(p0Cv cadddr(e)) v=dbCreateVia(p0Cv vd nth(4 e) "R0") unless(v error("Native via creation failed"))
            dbAddFigToNet(v n) dbReplaceProp(v "p0ViaId" "string" car(e)) dbReplaceProp(v "p0Owner" "string" cadr(e)) dbReplaceProp(v "p0Instance" "string" caddr(e))
            foreach(ident nth(5 e) dbDeleteObject(car(index[ident]))) count=count+1)
          count)'''.replace('OPERATIONS',operations)
        if self.ev(code)!=len(edits):raise Invalid('Incomplete native gate batch')
        tx['batch_applied']=True;tx['written'].update(e['id'] for e in edits)

def make_plan(source,target,before,records,qualification):
    if before['native_vias']:raise Invalid('Use reviewed reuse logic for already-native gate source')
    objects={o['id']:o for o in before['objects']};after=copy.deepcopy(before);edits=[];removed=set();checks=[]
    for r in records:
        if r.get('reused_native'):continue
        ids=r['contact_object_ids']+r['metal_landing_object_ids']+[r['poly_id']]
        ids+=sorted(n for n in objects if n.startswith(r['instance']+'/G') and n.rsplit('/',1)[0]==r['contact_object_ids'][0].rsplit('/',1)[0] and '/opc' in n)
        cut=objects[r['contact_object_ids'][0]];point=[round(sum(p[a] for p in cut['bbox_um'])/2,9) for a in (0,1)]
        figures=[dict(kind='rect',lpp=lpp,bbox_um=[[round(point[a]+bb[k][a],9) for a in (0,1)] for k in (0,1)]) for _,lpp,bb,_ in qualification['local_figures']]
        expected=sorted((dict(kind='rect',lpp=objects[n]['lpp'],bbox_um=objects[n]['bbox_um']) for n in ids if objects[n]['lpp'][0]!='conopc'),key=digest)
        if digest(expected)!=digest(sorted(figures,key=digest)):raise Invalid('Native via differs from original contact geometry: '+r['instance'])
        if removed.intersection(ids):raise Invalid('Duplicate gate contact replacement')
        removed.update(ids)
        envelope=[[min(f['bbox_um'][0][a] for f in figures) for a in (0,1)],[max(f['bbox_um'][1][a] for f in figures) for a in (0,1)]]
        v=dict(id=r['contact_object_ids'][0]+'/native',owner=cut['owner'],instance=r['instance'],net=r['net'],via_def='PO1_M1',origin_um=point,orientation='R0',bbox_um=envelope,override_parameters=None,figures=sorted(figures,key=digest))
        edits.append(dict(id=v['id'],op='native-via-replace',delete_ids=ids,before_sha256={n:digest(objects[n]) for n in ids},after=v))
        checks.append(dict(instance=r['instance'],via_id=v['id'],net=v['net'],geometry_equal=True))
        after['native_vias'].append(v)
    after['objects']=[o for o in after['objects'] if o['id'] not in removed]
    after['native_vias'].sort(key=lambda v:v['id'])
    return dict(source=source,target=target,authorization=qualification.get('authorization',''),snapshot_sha256=digest(before),expected_after_sha256=digest(after),capability='native-gate-via',authorized_ids=[e['id'] for e in edits],edits=edits),after,checks

def verifier(before,after,plan):
    if digest(after)!=plan['expected_after_sha256']:raise Invalid('Native gate complete readback mismatch')
    if before['protected']!=after['protected']:raise Invalid('Devices/foreign geometry changed')
    return dict(before_sha256=digest(before),after_sha256=digest(after),checks={k:'PASS' for k in ('connectivity','pin_access','pdk_geometry','symmetry','protected','environment')},evidence=dict(basis='Exact expanded cont/poly1/mt1 equivalence to each previously verified contact; all stems, escapes, sharing and rings unchanged; actual via net read back',native_api='dbCreateVia',contacts=len(plan['edits']),scope='Local equivalence and via/net identity; no new whole-circuit foundry signoff'))
