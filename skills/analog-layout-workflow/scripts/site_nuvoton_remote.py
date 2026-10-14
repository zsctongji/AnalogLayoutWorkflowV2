"""Read-only Nuvoton IC618/Calibre stage runner (Python 3.6+).

Native reports, file inventories and commands only; never grants signoff.
OA saved-state and evaluated hierarchy are supplied/checked by bridge adapter.
"""
import hashlib,json,os,re,subprocess,sys,time,struct
from pathlib import Path

PROJECT=CAL=IC=None  # Bound from the external qualified site profile in main().
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def write(p,x):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,indent=2)
def real8(b):
 return 0.0 if b==b'\0'*8 else (-1 if b[0]&128 else 1)*16.0**((b[0]&127)-64)*int.from_bytes(b[1:],'big')/2**56
def gds_validate(path,top):
 data=path.read_bytes();i=0;cells=[];refs=[];units=None;current=None;end=False;count=0
 while i<len(data):
  assert i+4<=len(data),'truncated GDS header'
  n,t,d=struct.unpack('>HBB',data[i:i+4]);assert n>=4 and n%2==0 and i+n<=len(data),'invalid GDS record'
  p=data[i+4:i+n];i+=n;count+=1
  if count==1:assert (t,d,n)==(0,2,6),'not GDSII'
  if t==3:
   assert len(p)==16 and units is None;units=[real8(p[:8]),real8(p[8:])];assert all(x>0 for x in units)
  if t==5:assert current is None;current=''
  if t==6:
   assert current=='';current=p.rstrip(b'\0').decode('ascii');assert current not in cells;cells.append(current)
  if t==18:assert current;refs.append([current,p.rstrip(b'\0').decode('ascii')])
  if t==7:assert current;current=None
  if t==4:
   assert current is None;tail=data[i:]
   assert not tail or (len(data)%2048==0 and len(tail)<2048 and not any(tail));end=True;break
 assert end and units and top in cells and not(set(r[1] for r in refs)-set(cells))
 assert top not in set(r[1] for r in refs)
 return dict(format='GDSII',primary=top,units=units,cells=cells,references=refs,record_count=count,scope='framing/units/hierarchy, not polygon equivalence')
def identifier(x):
 assert isinstance(x,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',x),'unsupported CAD identifier'
 return x
def inventory(cfg):
 roots=[PROJECT/cfg['target']['lib']/cfg['target']['cell'],PROJECT/cfg['reference']['lib']/cfg['reference']['cell'],PROJECT/cfg['site']['technology_library'],PROJECT/'Calibre/DRC',PROJECT/'Calibre/LVS']
 paths=[p for root in roots for p in root.rglob('*') if p.is_file() and '.cdslck' not in p.name]
 user_home=Path(cfg['site']['user_home']) if cfg['site'].get('user_home') else Path.home()
 paths += [p for p in [PROJECT/'cds.lib',PROJECT/'si.env',PROJECT/'.cdsinit',PROJECT/'.cdsenv',user_home/'.cdsinit',user_home/'.cdsenv',Path(__file__)] if p.is_file()]
 return {str(p.resolve()):sha(p) for p in sorted(set(paths))}
def main():
 global PROJECT,CAL,IC
 cfg=json.loads(Path(sys.argv[1]).read_text());assert cfg['schema']=='analog-layout-workflow.nuvoton-check/v1'
 site=cfg['site'];PROJECT=Path(site['project_root']);CAL=Path(site['calibre_root']);IC=Path(site['ic_root'])
 stage=cfg['stage'];assert stage in ('drc','lvs') and cfg['metal_option']==site['metal_option']
 for key in ('target','reference'):
  for f in ('lib','cell','view'):identifier(cfg[key][f])
 assert cfg['target']['view']=='layout' and cfg['reference']['view']=='schematic'
 assert cfg['master_libraries']==site['qualified_master_libraries'],'hierarchy profile not qualified'
 runname=identifier(cfg['run_name']);assert runname.startswith('codex_layout_p0_')
 root=PROJECT/runname;root.mkdir(exist_ok=False)
 env=dict(os.environ,CDS_Netlisting_Mode='Analog',CDSHOME=str(IC),CDS_INST_DIR=str(IC),CDS_AUTO_64BIT='ALL',CDS_LIC_FILE=site['cadence_license'],MGLS_LICENSE_FILE=site['mentor_license'],CALIBRE_HOME=str(CAL),MGC_HOME=str(CAL))
 before=inventory(cfg);write(root/'input-hashes.json',before);write(root/'run-config.json',cfg);rows=[]
 def run(name,args,cwd,timeout):
  start=time.time()
  with (root/(name+'.stdout.log')).open('xb') as out,(root/(name+'.stderr.log')).open('xb') as err:
   r=subprocess.run(args,cwd=str(cwd),env=env,stdout=out,stderr=err,timeout=timeout)
  row=dict(name=name,argv=args,cwd=str(cwd),returncode=r.returncode,start=start,end=time.time(),stdout_sha256=sha(root/(name+'.stdout.log')),stderr_sha256=sha(root/(name+'.stderr.log')))
  rows.append(row);write(root/(name+'.execution.json'),row);assert r.returncode==0,name+' execution failed'
 run('version',[str(CAL/'bin/calibre'),'-version'],root,60)
 gds=root/'layout.gds';deckpath=PROJECT/site[stage+'_deck']
 code=deckpath.read_text();plain=re.sub(r'//[^\n]*','',code)
 assert re.findall(r'(?im)^\s*#DEFINE\s+(TM_\w+)',plain)==[site['qualified_defines']['thickness']]
 assert re.search(r'(?im)^\s*#DEFINE\s+'+re.escape(site['qualified_defines']['top_metal'])+r'\s*$',plain)
 assert not re.search(r'(?im)^\s*#DEFINE\s+RC_DECK\b',plain),'PEX not requested'
 if stage=='drc':assert not re.search(r'(?im)^\s*(?:INCLUDE|#INCLUDE)\b',plain),'unqualified active DRC includes'
 changes={'LAYOUT PRIMARY':'"'+cfg['target']['cell']+'"','LAYOUT PATH':'"'+str(gds)+'"','LAYOUT SYSTEM':'GDSII'}
 if stage=='lvs':
  si=(PROJECT/'si.env').read_text()
  for key,value in {'simLibName':cfg['reference']['lib'],'simCellName':cfg['reference']['cell'],'simViewName':'schematic','hnlNetlistFileName':'source.sp'}.items():
   si,n=re.subn(r'^'+key+r'\s*=.*$',key+' = "'+value+'"',si,flags=re.M);assert n==1,(key,n)
  with (root/'si.env').open('x') as f:f.write(si)
  run('netlist',[str(IC/'bin/si'),str(root),'-batch','-command','netlist'],PROJECT,600)
  spice=(root/'source.sp').read_text();assert re.search(r'(?im)^\.subckt\s+'+re.escape(cfg['reference']['cell'])+r'\s',spice),'SPICE primary missing'
  changes.update({'SOURCE PRIMARY':'"'+cfg['reference']['cell']+'"','SOURCE PATH':'"'+str(root/'source.sp')+'"','SOURCE SYSTEM':'SPICE','LVS REPORT':'"'+str(root/'lvs.report')+'"','LVS REPORT MAXIMUM':'ALL'})
 else:
  changes.update({'DRC RESULTS DATABASE':'"'+str(root/'drc.results')+'" ASCII','DRC SUMMARY REPORT':'"'+str(root/'drc.summary')+'"','ERC RESULTS DATABASE':'"'+str(root/'erc.results')+'" ASCII','MASK RESULTS DATABASE':'"'+str(root/'mask.db')+'"'})
 for key,value in changes.items():
  pattern=r'^'+re.escape(key)+r'\s+(?!OPTION\b|MAXIMUM\b|UNITS\b)[^\n]*$'
  code,n=re.subn(pattern,key+' '+value,code,flags=re.M);assert n==1,(key,n)
 with (root/(stage+'.cal')).open('x') as f:f.write(code)
 write(root/'policy.json',dict(metal_option=cfg['metal_option'],hierarchy='hier',root_deck=str(deckpath),root_deck_sha256=sha(deckpath),wrapper_sha256=sha(root/(stage+'.cal')),changes=changes,RC_DECK=False,signoff=False,limitations=['Effective conditional/include closure and warnings still require site review.']))
 run('streamout',[str(IC/'bin/strmout'),'-library',cfg['target']['lib'],'-topCell',cfg['target']['cell'],'-view','layout','-strmFile',str(gds),'-layerMap',str(PROJECT/site['layer_map']),'-runDir',str(PROJECT),'-logFile',str(root/'stream.detail.log'),'-summaryFile',str(root/'stream.summary'),'-case','Preserve','-convertDot','node','-convertPcellPin','geometry'],PROJECT,600)
 write(root/'gds-validation.json',gds_validate(gds,cfg['target']['cell']));streamhash=sha(gds)
 assert inventory(cfg)==before,'source/PDK drift during export'
 run('calibre',[str(CAL/'bin/calibre'),'-'+stage,'-hier',str(root/(stage+'.cal'))],root,3600)
 assert sha(gds)==streamhash and inventory(cfg)==before,'bound inputs drift during check'
 write(root/'integrity.json',dict(unchanged=True,stream_sha256=streamhash,OA_and_PDK_unchanged=True))
 write(root/'commands.json',rows)
 outputs={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
 write(root/'output-hashes.json',outputs)
 print(json.dumps(dict(run_directory=str(root),stage=stage,completed=True,signoff=False)))
if __name__=='__main__':main()
