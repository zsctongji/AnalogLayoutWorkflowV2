"""Bridge handoff adapter for read-only Nuvoton DRC/LVS checks.

Tested profile only. Retains incomplete/warning states; no generic signoff badge.
"""
from pathlib import Path
import argparse,json,re,shlex,sys,time
from workflow_runtime import load,write,digest,filehash,identity,Invalid
from virtuoso_adapter import VirtuosoBackend,q

def read_reference(backend,reference):
 return backend.ev('let((cv result) cv=dbOpenCellViewByType('+q(reference['lib'])+' '+q(reference['cell'])+' '+q(reference['view'])+' "schematic" "r") unless(cv && !cv~>modified error("Missing/unsaved reference")) result=list(foreach(mapcar i cv~>instances list(i~>name i~>libName i~>cellName i~>viewName foreach(mapcar tm i~>instTerms list(tm~>name tm~>net~>name)) foreach(mapcar p i~>prop list(p~>name p~>valueType p~>value)))) foreach(mapcar tm cv~>terminals list(tm~>name tm~>net~>name tm~>direction))) dbClose(cv) result)')

def run(handoff,out):
 from virtuoso_bridge import VirtuosoClient
 from virtuoso_bridge.env import set_runtime_env_file
 h=load(handoff);stage=h['stage'];profile=h['constraints'].get('site_profile',{})
 if stage not in {'drc','lvs'} or profile.get('name')!='nuvoton1132-ic618-calibre2019':raise Invalid('Unqualified stage/site profile')
 if not profile.get('config'):raise Invalid('Explicit external site profile config required; repository has no qualified default')
 site_path=Path(profile['config'])
 site=load(site_path)
 if h['constraints'].get('metal_option')!=site['metal_option']:raise Invalid('Unsupported metal option')
 target=h['source'];reference=h['reference'];identity(target);identity(reference)
 if target['view']!='layout' or reference['view']!='schematic':raise Invalid('Wrong native views')
 if target==reference:raise Invalid('Independent schematic required')
 set_runtime_env_file(profile['bridge_env']);client=VirtuosoClient.from_env()
 skills=Path(__file__).resolve().parents[2];backend=VirtuosoBackend(client,skills)
 if backend.ev('1+2')!=3:raise Invalid('Bridge unavailable')
 before=backend.snapshot(target);revision=digest(before)
 if revision!=h['dependencies']['route-apply'].get('output_revision'):raise Invalid('Current saved geometry differs from routed checkpoint')
 masters=sorted({i[1] for i in before['protected']['instances']})
 if masters!=site['qualified_master_libraries']:raise Invalid('Unsupported evaluated layout hierarchy')
 schematic=read_reference(backend,reference)
 root=Path(out).resolve().parent;write(root/'native-before.json',before);write(root/'schematic-before.json',schematic)
 cfg=dict(schema='analog-layout-workflow.nuvoton-check/v1',stage=stage,target=target,reference=reference,metal_option=site['metal_option'],master_libraries=masters,site=site,run_name='codex_layout_p0_'+stage+'_'+str(time.time_ns()))
 remote='/tmp/'+cfg['run_name'];local_script=Path(__file__).with_name('site_nuvoton_remote.py')
 write(root/'remote-config.json',cfg)
 client.upload_file(local_script,remote+'.py');client.upload_file(root/'remote-config.json',remote+'.json')
 argv=[profile['remote_python'],remote+'.py',remote+'.json']
 result=client.ssh_runner.run_command(' '.join(shlex.quote(a) for a in argv),timeout=3600)
 write(root/'remote-execution.json',dict(argv=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,runner_sha256=filehash(local_script)))
 if result.returncode:raise Invalid('Remote native check failed: '+str(result.stdout)+' '+str(result.stderr))
 metadata=json.loads(result.stdout.strip().splitlines()[-1]);remote_dir=metadata['run_directory']
 client.download_file(remote_dir+'/output-hashes.json',root/'output-hashes.json')
 inventory=load(root/'output-hashes.json')
 raw=root/'raw'
 if raw.exists():raise Invalid('Raw evidence directory exists')
 # Transfer the immutable native run once; per-file SCP round trips are costly
 # for hierarchical SVDBs. Still verify every recorded file hash afterwards.
 transfer=client.download_file(remote_dir,raw,recursive=True,timeout=180)
 if not transfer.ok:raise Invalid('Native evidence transfer failed: '+str(transfer.errors))
 for name,sha in inventory.items():
  p=Path(name)
  if p.is_absolute() or '..' in p.parts:raise Invalid('Remote output path escape')
  dest=raw/p
  if dest.is_symlink() or not dest.is_file():raise Invalid('Missing/nonregular transferred evidence')
  if filehash(dest)!=sha:raise Invalid('Transferred output mismatch')
 if backend.snapshot(target)!=before:raise Invalid('OA changed during native check')
 if read_reference(backend,reference)!=schematic:raise Invalid('Schematic changed during native check')
 # Repeat schematic query through same independent reader, without netlisting
 # from layout-extracted data. Local OA file closure is recorded remotely.
 if stage=='drc':
  sys.path.insert(0,str(skills/'analog-layout-drc/scripts'))
  from calibre_drc import parse_artifacts
  analysis=parse_artifacts(raw/'drc.summary',raw/'drc.results',[])
  if analysis['primary_cell']!=target['cell']:raise Invalid('DRC primary mismatch')
  verdict=analysis['status']
 else:
  sys.path.insert(0,str(skills/'analog-layout-lvs/scripts'))
  from inspect_report import inspect
  analysis=inspect((raw/'lvs.report').read_text(encoding='utf-8'),(raw/'calibre.stdout.log').read_text(encoding='utf-8'))
  for label,expected in [('LAYOUT NAME',target['cell']),('SOURCE NAME',reference['cell'])]:
   primary=re.search(r"\('([^']+)'\)\s*$",analysis['metadata'].get(label) or '')
   if not primary or primary.group(1)!=expected:raise Invalid('LVS report primary mismatch: '+label)
  verdict=analysis['status']
 write(root/'native-analysis.json',analysis)
 # Parent dispatcher owns console/command logs and closes them only after this
 # child exits. Hash only immutable child evidence here.
 artifacts=[dict(path=str(p.resolve()),sha256=filehash(p),host='local') for p in root.rglob('*') if p.is_file() and p.name not in {Path(out).name,'console.log','command.json'}]
 receipt=dict(status='CHECKED_WITH_LIMITATIONS',handoff_sha256=digest(h),checked_cellview=target,output_revision=revision,readback_verified=True,validation=dict(verdict=verdict,native_execution_completed=True,physical_signoff=False),artifacts=artifacts,limitations=['Native check/export and revision binding tested; effective include closure, warning review and full OA-to-stream equivalence remain explicit limitations.'],next_action='Review native-analysis and raw evidence; never upgrade unverified/incomplete results to closure.')
 write(out,receipt)
 return receipt
def main():
 p=argparse.ArgumentParser();p.add_argument('--handoff',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 if Path(a.out).exists():raise Invalid('Receipt exists')
 print(json.dumps({k:v for k,v in run(a.handoff,a.out).items() if k!='artifacts'},indent=2))
if __name__=='__main__':main()
