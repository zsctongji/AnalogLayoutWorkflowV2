import copy,json,sys,tempfile,unittest,hashlib
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workflow_runtime import *
from adapter_runtime import execute,MemoryBackend,GATES
from run_stage import run_stage
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'analog-layout-local-access/scripts'))
from local_access import compile_request

def cell(name):return dict(lib='test',cell=name,view='layout')
class StateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);(self.base/'evidence').write_text('real evidence')
  self.art=[dict(path='evidence',sha256=filehash(self.base/'evidence'))]
  self.s=init(dict(run_id='test',mode='execute',source=cell('source'),reference=cell('schematic'),destination=cell('final'),constraints={'axis':0},bindings={'source':'saved-A','pdk':'pdk-A'},last_human_decision='test isolated flow'))
 def tearDown(self):self.tmp.cleanup()
 def done(self,sid,**kw):
  r=dict(status='LOCALLY_VERIFIED',artifacts=self.art,validation={'verdict':'LOCAL_PASS'},output_revision='saved-A',readback_verified=True,checked_cellview=self.s['current']);r.update(kw);self.s=checkpoint(self.s,sid,r,self.base)
 def chain(self):
  for sid in list(DEPS)[:9]:self.done(sid)
 def test_resume(self):
  self.done('discover');self.done('place');self.assertEqual(next_action(self.s,self.base)['stage'],'share')
 def test_file_drift(self):
  self.done('discover');(self.base/'evidence').write_text('drift');self.assertEqual(next_action(self.s,self.base)['stage'],'discover')
 def test_dependency_changed(self):
  self.done('discover');self.done('place');self.done('discover',limitations=['new warning']);self.assertEqual(checked(self.s,self.base)['place']['status'],'STALE')
 def test_scope_no_upstream_autorun(self):
  self.s['scope']=['pex'];self.assertEqual(next_action(self.s,self.base)['status'],'BLOCKED_DEPENDENCY')
 def test_no_waived_clean(self):
  self.chain()
  with self.assertRaises(Invalid):self.done('drc',status='CLOSED',validation={'verdict':'WAIVED'})
 def test_checks_run_independently(self):
  self.chain();self.done('drc',status='CHECKED_WITH_LIMITATIONS',validation={'verdict':'VIOLATIONS'});self.assertEqual(next_action(self.s,self.base)['stage'],'lvs')
 def test_no_wrong_revision_closure(self):
  self.chain()
  with self.assertRaises(Invalid):self.done('drc',status='CLOSED',validation={'verdict':'CLEAN'},output_revision='old-A')
 def test_old_matching_pair_rejected(self):
  self.chain();self.done('drc',status='CLOSED',validation={'verdict':'CLEAN'});self.done('lvs',status='CLOSED',validation={'verdict':'VERIFIED_MATCH'})
  self.s['stages']['route-apply']['output_revision']='new-B';self.s['scope'].append('pex')
  self.assertNotEqual(next_action(self.s,self.base).get('stage'),'pex')
 def test_numeric_hash_stability(self):self.assertEqual(digest({'x':1}),digest({'x':1.0}))
 def test_identical_geometry_different_target_rejected(self):
  self.chain()
  with self.assertRaisesRegex(Invalid,'cellview'):self.done('drc',checked_cellview=cell('another-cell'))
 def test_pex_blocked_drc(self):
  self.chain();self.done('drc',validation={'verdict':'VIOLATIONS'});self.done('lvs',validation={'verdict':'VERIFIED_MATCH'});self.s['scope'].append('pex');self.assertEqual(next_action(self.s,self.base)['status'],'BLOCKED_DRC')
 def test_exploratory_pex_requires_bound_correct_report_and_user(self):
  self.chain();self.done('drc',validation={'verdict':'VIOLATIONS'});self.done('lvs',validation={'verdict':'REPORT_MATCH_UNVERIFIED'});self.s['scope'].append('pex')
  self.s['verification']={'lvs':dict(status='REPORT_MATCH_UNVERIFIED',report_verdict='CORRECT',independent_reference=True,revision='saved-A',checked_cellview=self.s['current'])}
  self.assertEqual(next_action(self.s,self.base)['status'],'BLOCKED_LVS')
  self.s['exploratory_pex_authorization']=dict(source='user',scope='pex',instruction='Accept limitations and run exploratory PEX',revision='saved-A',checked_cellview=self.s['current'])
  self.assertEqual(next_action(self.s,self.base)['status'],'READY')
  valid=copy.deepcopy(self.s)
  for field,value in [('report_verdict','INCORRECT'),('revision','old'),('independent_reference',False),('checked_cellview',cell('other'))]:
   with self.subTest(field=field):
    self.s=copy.deepcopy(valid);self.s['verification']['lvs'][field]=value;self.assertEqual(next_action(self.s,self.base)['status'],'BLOCKED_LVS')
  self.s=copy.deepcopy(valid);self.s['exploratory_pex_authorization']['source']='agent';self.assertEqual(next_action(self.s,self.base)['status'],'BLOCKED_LVS')
 def test_plan_not_mutating(self):
  self.chain();self.s['mode']='plan';self.assertEqual(next_action(self.s,self.base)['status'],'STOP_AT_PLAN_BOUNDARY')
 def test_skip_requires_reason(self):
  self.done('discover');self.done('place')
  with self.assertRaises(Invalid):self.done('share',status='SKIPPED')
 def test_share_skip_requires_explicit_user(self):
  self.done('discover');self.done('place')
  with self.assertRaisesRegex(Invalid,'explicit user'):
   self.done('share',status='SKIPPED',skip_reason='No probe yet',skip_dependency_safe=True)
 def test_share_skip_accepts_explicit_user(self):
  self.done('discover');self.done('place')
  self.done('share',status='SKIPPED',skip_reason='User explicitly requested skipping',skip_dependency_safe=True,
            user_skip_authorization={'source':'user','scope':'share','instruction':'Skip diffusion sharing for this run.'})
  self.assertEqual(next_action(self.s,self.base)['stage'],'gate-access')
 def test_share_skip_rejects_bad_authorization(self):
  self.done('discover');self.done('place')
  for authorization in ({'source':'agent','scope':'share','instruction':'Skip'},
                        {'source':'user','scope':'ring','instruction':'Skip'},
                        {'source':'user','scope':'share','instruction':'  '},
                        {'source':'user','scope':'share','instruction':True}):
   with self.subTest(authorization=authorization),self.assertRaises(Invalid):
    self.done('share',status='SKIPPED',skip_reason='Skip',skip_dependency_safe=True,user_skip_authorization=authorization)
 def test_legacy_share_skip_blocks_downstream(self):
  self.done('discover');self.done('place');self.done('share');self.done('gate-access')
  # Simulate a historical, fully hash-bound skip lacking explicit user authorization.
  record=self.s['stages']['share'];record.update(status='SKIPPED',skip_reason='Optional optimization',skip_dependency_safe=True)
  self.s['stages']['gate-access']['dependency_tokens']['share']=token(record)
  results=checked(self.s,self.base)
  self.assertEqual(results['share']['status'],'STALE')
  self.assertEqual(results['gate-access']['status'],'STALE')
  self.assertEqual(next_action(self.s,self.base)['stage'],'share')
 def test_completed_no_applicable_edges_is_assessed(self):
  self.done('discover');self.done('place')
  self.done('share',validation={'verdict':'NO_APPLICABLE_EDGES'})
  self.assertEqual(next_action(self.s,self.base)['stage'],'gate-access')
 def test_hash_same_artifact_once_per_check(self):
  self.done('discover');self.done('place');self.done('share')
  with patch('workflow_runtime.filehash',wraps=filehash) as hashed:
   self.assertEqual(checked(self.s,self.base)['share']['status'],'LOCALLY_VERIFIED')
   self.assertEqual(hashed.call_count,1)
  (self.base/'evidence').write_text('changed after first check')
  self.assertEqual(checked(self.s,self.base)['discover']['status'],'STALE')

class AdapterTests(unittest.TestCase):
 def setUp(self):
  self.before={'objects':[],'protected':{'devices':'immutable'}};self.backend=MemoryBackend(self.before)
  a=dict(id='L',owner='route-owned',net='N',kind='rect',lpp=['M1','drawing'],bbox_um=[[-2,0],[-1,1]])
  b=dict(a,id='R',bbox_um=[[1,0],[2,1]])
  self.after=dict(self.before,objects=[a,b]);self.plan=dict(source=cell('source'),target=cell('new'),authorization='paired test',snapshot_sha256=digest(self.before),expected_after_sha256=digest(self.after),capability='rect-create',authorized_ids=['L','R'],edits=[dict(id=o['id'],op='create',after=o) for o in [a,b]])
 def verifier(self,b,a,p):
  self.assertEqual(a,self.after);self.assertEqual(b['protected'],a['protected'])
  return dict(before_sha256=digest(b),after_sha256=digest(a),checks={k:'PASS' for k in GATES},evidence=['measured fixture'])
 def test_pair_save(self):self.assertEqual(execute(self.plan,self.backend,self.verifier)['status'],'SAVED_LOCALLY_VERIFIED');self.assertEqual(self.backend.views['source'],self.before)
 def test_one_side_failure_rolls_back(self):
  self.backend.fail_at='R'
  with self.assertRaisesRegex(Invalid,'TRANSACTION_ABORTED'):execute(self.plan,self.backend,self.verifier)
  self.assertNotIn('new',self.backend.views);self.assertIsNone(self.backend.tx)
 def test_unknown_gate_rollback(self):
  def bad(b,a,p):r=self.verifier(b,a,p);r['checks']['symmetry']='UNKNOWN';return r
  with self.assertRaises(Invalid):execute(self.plan,self.backend,bad)
  self.assertNotIn('new',self.backend.views)
 def test_source_drift(self):
  self.backend.views['source']['protected']['devices']='changed'
  with self.assertRaisesRegex(Invalid,'Source drift'):execute(self.plan,self.backend,self.verifier)
 def test_existing_target(self):
  self.backend.views['new']={}
  with self.assertRaises(Invalid):execute(self.plan,self.backend,self.verifier)
 def test_incomplete_readback(self):
  self.plan['expected_after_sha256']='wrong'
  with self.assertRaises(Invalid):execute(self.plan,self.backend,self.verifier)
 def test_protected_edit_detected(self):
  self.after['protected']={'devices':'changed'}
  with self.assertRaises(Invalid):execute(self.plan,self.backend,self.verifier)
 def test_close_failure_after_save_not_rollback(self):
  original=self.backend.commit
  def fail(tx):original(tx);tx['save_state']='saved';raise Invalid('close failed')
  self.backend.commit=fail
  with self.assertRaisesRegex(Invalid,'SAVED_NOT_CLOSED'):execute(self.plan,self.backend,self.verifier)
  self.assertIn('new',self.backend.views)
 def test_ambiguous_save_not_rollback(self):
  def fail(tx):tx['save_state']='uncertain';raise Invalid('transport lost')
  self.backend.commit=fail
  with self.assertRaisesRegex(Invalid,'SAVE_STATE_UNKNOWN'):execute(self.plan,self.backend,self.verifier)
  self.assertIsNotNone(self.backend.tx)

class AccessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);(self.base/'rules').write_text('fixture only not a foundry rule');sha=filehash(self.base/'rules')
  rec=dict(lower_layer='PO',upper_layer='M1',cut_layer='CONT',cut_size_um=[.2,.2],lower_enclosure_um=[.1,.1],upper_enclosure_um=[.1,.1],width_um=.4,spacing_um=.2,cut_spacing_um=.2,qualification_sha256=sha)
  self.req=dict(schema='analog-layout-local-access.request/v1',target=cell('fixture'),snapshot_sha256=sha,pdk_fingerprint=sha,grid_um=.1,max_escape_um=2,evidence=[dict(path='rules',sha256=sha)],recipes={'gate':rec},islands=[dict(id='L:G:0',instance='L',terminal='G',net='INN',layer='PO',bbox_um=[[-2,-1],[-1,1]],module='pair'),dict(id='R:G:0',instance='R',terminal='G',net='INP',layer='PO',bbox_um=[[1,-1],[2,1]],module='pair')],requests=[dict(island_id='L:G:0',recipe='gate',contact_xy_um=[-1.5,0],escape_xy_um=[-1.5,-.5]),dict(island_id='R:G:0',recipe='gate',contact_xy_um=[1.5,0],escape_xy_um=[1.5,-.5])],obstacles=[],pairs=[dict(left='L:G:0',right='R:G:0',axis_x_um=0,net_relation='pair')],exceptions={},conditional_rules_status='PASS')
 def tearDown(self):self.tmp.cleanup()
 def test_contact_pair(self):self.assertEqual(compile_request(self.req,self.base)['status'],'SELECTED_RULES_PASS')
 def test_missing_island(self):
  self.req['requests'].pop()
  with self.assertRaises(ValueError):compile_request(self.req,self.base)
 def test_wrong_net_pair(self):
  self.req['islands'][1]['net']='INN'
  with self.assertRaises(ValueError):compile_request(self.req,self.base)
 def test_one_side_escape(self):
  self.req['requests'][1]['escape_xy_um']=[1.5,-.6];self.assertEqual(compile_request(self.req,self.base)['status'],'BLOCKED')
 def test_foreign_short(self):
  self.req['obstacles']=[dict(id='bad',net='OUT',layer='M1',bbox_um=[[-1.6,-.3],[-1.4,-.1]])];self.assertEqual(compile_request(self.req,self.base)['status'],'BLOCKED')
 def test_unknown_rules(self):
  self.req['conditional_rules_status']='UNKNOWN';self.assertEqual(compile_request(self.req,self.base)['status'],'BLOCKED')
 def test_stale_recipe(self):
  (self.base/'rules').write_text('changed')
  with self.assertRaises(ValueError):compile_request(self.req,self.base)
 def test_no_signoff(self):self.assertFalse(compile_request(self.req,self.base)['signoff'])
 def test_negative_spacing_rejected(self):
  self.req['recipes']['gate']['spacing_um']=-1
  with self.assertRaisesRegex(ValueError,'Invalid spacing'):compile_request(self.req,self.base)
 def test_unmapped_obstacle_rejected(self):
  self.req['obstacles']=[dict(id='foreign',net=None,layer='M1',bbox_um=[[4,0],[5,1]])]
  with self.assertRaisesRegex(ValueError,'obstacle'):compile_request(self.req,self.base)
 def test_complete_existing_access_no_duplicate_metal(self):
  plan=compile_request(self.req,self.base)
  for want,record,island in zip(self.req['requests'],plan['records'],self.req['islands']):
   want['reuse']=dict(contact_id='actual:'+island['id'],landing_id='landing:'+island['id'],lower_layer='PO',upper_layer='M1',cut_layer='CONT',cut_bbox_um=record['cut'],landing_bbox_um=record['landing'],continuity_evidence_sha256=self.req['snapshot_sha256'],existing_escape=dict(id='escape:'+island['id'],net=island['net'],layer='M1',bbox_um=record['escape']))
  result=compile_request(self.req,self.base)
  self.assertEqual(result['status'],'SELECTED_RULES_PASS');self.assertEqual(result['objects'],[])

class RunnerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
  self.state=init(dict(run_id='test',mode='execute',source=cell('source'),reference=cell('schematic'),destination=cell('final'),constraints={'axis':0},bindings={'source':'saved-A'},last_human_decision='read-only discovery'))
  write(self.base/'state.json',self.state)
  self.script=self.base/'child.py'
  self.script.write_text('''import argparse,json,hashlib\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--handoff');p.add_argument('--out');a=p.parse_args();h=json.loads(Path(a.handoff).read_text());root=Path(a.out).parent;e=root/'evidence';e.write_text('actual fixture observation');sha=lambda b:hashlib.sha256(b).hexdigest();r=dict(status='LOCALLY_VERIFIED',handoff_sha256=sha(json.dumps(h,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()),artifacts=[dict(path='evidence',sha256=sha(e.read_bytes()))],validation=dict(verdict='LOCAL_READ_ONLY'),output_revision='saved-A');Path(a.out).write_text(json.dumps(r))\n''')
  self.registry={'schema':'analog-layout-workflow.registry/v1','stages':{'discover':dict(script=str(self.script),script_sha256=filehash(self.script),python=sys.executable,mutating=False)}}
  write(self.base/'registry.json',self.registry)
 def tearDown(self):self.tmp.cleanup()
 def invoke(self,execute=False):return run_stage(self.base/'state.json',self.base/'registry.json',self.base/'runs',execute)
 def test_preview_no_outputs(self):self.assertEqual(self.invoke()['status'],'PREVIEW');self.assertFalse((self.base/'runs').exists())
 def test_executed_checkpoint(self):self.assertEqual(self.invoke(True)['status'],'CHECKPOINTED');self.assertEqual(next_action(load(self.base/'state.json'),self.base)['stage'],'place')
 def test_changed_script(self):
  self.script.write_text('changed')
  with self.assertRaises(Invalid):self.invoke(True)
 def test_missing_capability(self):
  self.registry['stages']={};write(self.base/'registry.json',self.registry);self.assertEqual(self.invoke()['status'],'BLOCKED_CAPABILITY')
 def test_unqualified_writer_refused(self):
  self.registry['stages']['discover']['mutating']=True;write(self.base/'registry.json',self.registry)
  with self.assertRaises(Invalid):self.invoke(True)
 def test_changed_import_dependency_refused(self):
  dep=self.base/'helper.py';dep.write_text('original')
  self.registry['stages']['discover']['code_dependencies']=[dict(path=str(dep),sha256=filehash(dep))]
  write(self.base/'registry.json',self.registry);dep.write_text('changed')
  with self.assertRaises(Invalid):self.invoke(True)
 def test_final_execution_log_is_bound(self):
  self.invoke(True);saved=load(self.base/'state.json')['stages']['discover']
  self.assertTrue(any(Path(a['path']).name=='console.log' for a in saved['artifacts']))
  self.assertTrue(any(Path(a['path']).name=='stage-receipt.json' for a in saved['artifacts']))
 def test_dispatcher_records_phase_time(self):
  result=self.invoke(True)
  self.assertTrue((Path(result['run'])/'performance.json').is_file())
  for key in ('dispatch_preparation','adapter_execution','receipt_validation','checkpoint','total'):
   self.assertGreaterEqual(result['timing_seconds'][key],0)
  self.assertIn('dispatcher_timing_seconds',load(self.base/'state.json')['stages']['discover'])
 def test_place_preflight_blocks_before_child_runs(self):
  self.invoke(True)
  self.registry['stages']['place']=self.registry['stages']['discover']
  write(self.base/'registry.json',self.registry)
  before=list((self.base/'runs').iterdir())
  result=self.invoke(True)
  self.assertEqual(result['status'],'BLOCKED_PREFLIGHT')
  self.assertEqual(list((self.base/'runs').iterdir()),before)

if __name__=='__main__':unittest.main()
