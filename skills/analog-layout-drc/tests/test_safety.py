import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import calibre_drc as drc
import evidence_binding as bind
import marker_geometry as geo
import symmetric_repair as repair

ZERO='Layout Primary Cell: TOP\nRULECHECK m1.s ... TOTAL Result Count = 0 (0)\n'
ONE='Layout Primary Cell: TOP\nRULECHECK m1.s ... TOTAL Result Count = 1 (1)\n'
RES='TOP 1000\nm1.s\n1 1 1\np 1 4\nCN child opaque transform\n0 0\n100 0\n100 50\n0 50\n'

class Parsing(unittest.TestCase):
 def parse(self,s=ZERO,r='TOP 1000\n',waivers=None):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'s').write_text(s);(p/'r').write_text(r)
   return drc.parse_artifacts(p/'s',p/'r',[],waivers)
 def test_unbound_zero_not_clean(self):self.assertEqual(self.parse()['status'],'UNVERIFIED')
 def test_warning_blocks(self):
  s=ZERO+'--- RUNTIME WARNINGS\nRESULT LIMIT REACHED\n'
  self.assertEqual(self.parse(s)['status'],'INCOMPLETE')
 def test_native_warning_separator(self):
  s='Layout Primary Cell: TOP\n--- RUNTIME WARNINGS\n---\nCannot open DENSITY RDB file x for output.\n-------------\n--- RULECHECK RESULTS STATISTICS\n---\nRULECHECK m1.s ... TOTAL Result Count = 0 (0)\n'
  r=self.parse(s)
  self.assertEqual(r['runtime_warnings'],['Cannot open DENSITY RDB file x for output.'])
  self.assertEqual(r['status'],'INCOMPLETE')
 def test_native_empty_warning_section(self):
  s='Layout Primary Cell: TOP\n--- RUNTIME WARNINGS\n---\n\n-------------\n--- RULECHECK RESULTS STATISTICS\n---\nRULECHECK m1.s ... TOTAL Result Count = 0 (0)\n'
  r=self.parse(s);self.assertEqual(r['runtime_warnings'],[]);self.assertEqual(r['status'],'UNVERIFIED')
 def test_truncated_polygon(self):self.assertTrue(drc.parse_results(RES.rsplit('0 50',1)[0])['parse_issues'])
 def test_edge_not_silently_lost(self):self.assertTrue(drc.parse_results('TOP 1000\nm1.s\n1 1 1\ne 1 1\n0 0 5 5')['parse_issues'])
 def test_summary_mismatch(self):self.assertEqual(self.parse(ONE)['status'],'INCOMPLETE')
 def test_primary_mismatch(self):self.assertEqual(self.parse(r='OTHER 1000\n')['status'],'INCOMPLETE')
 def test_garbage_results(self):self.assertEqual(self.parse(r='garbage')['status'],'INCOMPLETE')
 def test_waived_not_clean(self):
  w=[dict(rule_regex='^m1.s$',reason='reviewed',approval='user decision',scope='this run')]
  self.assertEqual(self.parse(ONE,RES,w)['status'],'WAIVED')
 def test_missing_result(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'s';p.write_text(ZERO)
   self.assertEqual(drc.parse_artifacts(p,p.parent/'missing',[])['status'],'INCOMPLETE')
 def test_cn_retained(self):self.assertEqual(drc.parse_results(RES)['markers'][0]['cn_raw'],'CN child opaque transform')
 def test_bad_summary(self):
  with self.assertRaises(ValueError):drc.parse_summary(ZERO+'RULECHECK bad TOTAL Result Count = ?')

class Binding(unittest.TestCase):
 def fixture(self,root):
  for name in ('oa','deck','include','map'):(root/name).write_text(name)
  config=dict(schema=drc.SCHEMA,target=dict(lib='L',cell='TOP',view='layout'),working_directory=str(root),
   inputs=dict(rule_deck='deck',layer_map='map'),artifacts=dict(stream='out.gds',summary='summary',results='results'),
   streamout=dict(argv=['export','{stream}']),drc=dict(argv=['calibre','{rule_deck}']),
   binding=dict(oa_files=['oa'],deck_dependencies=['include'],metal_option='3M-test',hierarchy_mode='hier',result_limit='ALL',adapter_id='test',export_receipt='export.json',drc_receipt='drc.json'))
  p=root/'config';p.write_text(json.dumps(config));plan=drc.prepare_run(p);return plan,bind.prepare(plan)
 def receipt(self,root,plan,b,stage):
  c=next(s for s in plan['stages'] if s['name']==stage)
  for k in ('stdout','stderr'):Path(c[k]).write_text('')
  stream=Path(plan['artifacts']['stream'])
  if not stream.exists():stream.write_text('mock-stream')
  r=dict(schema='analog-layout-drc.stage-receipt/v1',stage=stage,completed=True,target=plan['config']['target'],
   config_sha256=plan['config_sha256'],adapter_id='test',argv_sha256=bind.fingerprint(c['argv']),input_hashes=b['inputs'],oa_hashes=b['oa'],dependency_hashes=b['dependencies'],policy=b['policy'],
   tool_version='MOCK',interpreter_version=sys.version,log_hashes={k:bind.digest(c[k]) for k in ('stdout','stderr')},stream_path=str(stream.resolve()),stream_sha256=bind.digest(stream),saved_oa=True,oa_inventory_complete=True,stream_format_validated='GDSII',dependencies_complete=True,result_limit_reached=False)
  if stage=='drc':
   for k,txt in [('summary',ZERO),('results','TOP 1000\n')]:Path(plan['artifacts'][k]).write_text(txt)
   r['output_hashes']={k:bind.digest(plan['artifacts'][k]) for k in ('summary','results')}
  key='export_receipt' if stage=='streamout' else 'drc_receipt';Path(b['receipts'][key]).write_text(json.dumps(r));return r
 def test_valid_receipts(self):
  with tempfile.TemporaryDirectory() as t:
   p,b=self.fixture(Path(t));self.receipt(Path(t),p,b,'streamout');x=bind.verify_stage(p,b,'streamout');self.receipt(Path(t),p,b,'drc');bind.verify_stage(p,b,'drc',x['stream_sha256'])
 def test_oa_drift(self):
  with tempfile.TemporaryDirectory() as t:
   p,b=self.fixture(Path(t));self.receipt(Path(t),p,b,'streamout');(Path(t)/'oa').write_text('changed')
   with self.assertRaises(ValueError):bind.verify_stage(p,b,'streamout')
 def test_include_drift(self):
  with tempfile.TemporaryDirectory() as t:
   p,b=self.fixture(Path(t));(Path(t)/'include').write_text('changed')
   with self.assertRaises(ValueError):bind.verify_stage(p,b,'streamout')
 def test_wrong_consumed_stream(self):
  with tempfile.TemporaryDirectory() as t:
   p,b=self.fixture(Path(t));self.receipt(Path(t),p,b,'drc')
   with self.assertRaises(ValueError):bind.verify_stage(p,b,'drc','wrong')
 def test_collisions(self):
  with self.assertRaises(ValueError):bind.distinct_paths(['a'],['a'])
  with self.assertRaises(ValueError):bind.distinct_paths([],['a','a'])
 def test_existing_outputs(self):
  with tempfile.TemporaryDirectory() as t:
   p,b=self.fixture(Path(t));Path(p['artifacts']['stream']).touch()
   with self.assertRaises(ValueError):bind.prepare(p)
 def test_missing_binding_no_commands(self):
  with self.assertRaises(ValueError):drc.execute_plan(dict(config={},working_directory='.',stages=[]))

class Location(unittest.TestCase):
 def fixture(self):
  r=dict(drc.parse_results(RES),primary_cell='TOP');s=dict(target={'cell':'TOP'},objects=[dict(id='route1',bbox_um=[[.9,2],[1,2.1]],owner='route-owned',net='N',layer='M1')])
  p=dict(target=s['target'],report_sha256=geo.digest(r),snapshot_sha256=geo.digest(s),dbu_per_um=1000,transform_evidence='verified site mapping',placements=[dict(marker_sha256=geo.digest(r['markers'][0]),instance_path=['I0'],leaf_to_top_db_units=[[0,-1,1,0,1000,2000]])]);return r,p,s
 def test_rotated_translation(self):
  r,p,s=self.fixture();x=geo.locate(r,p,s)['occurrences'][0];self.assertEqual(x['bbox_top_um'],[[.95,2.0],[1.0,2.1]]);self.assertEqual(x['candidates'][0]['id'],'route1')
 def test_missing_path_unknown(self):
  r,p,s=self.fixture();p['placements']=[];self.assertEqual(geo.locate(r,p,s)['occurrences'][0]['status'],'UNRESOLVED')
 def test_wrong_units(self):
  r,p,s=self.fixture();p['dbu_per_um']=1
  with self.assertRaises(ValueError):geo.locate(r,p,s)
 def test_stale_snapshot(self):
  r,p,s=self.fixture();s['objects']=[]
  with self.assertRaises(ValueError):geo.locate(r,p,s)

def repair_fixture():
 def obj(ident,net,x):return dict(id=ident,owner='route-owned',net=net,kind='rect',metal=[dict(layer='M1',bbox_um=[[x,0],[x+1,2]])],cuts=[])
 s=dict(target=dict(lib='L',cell='SRC',view='layout'),objects=[obj('a','P',-3),obj('b','N',2)],symmetry_groups=[dict(id='pair',mode='pair',net_pair=['P','N'],axis_x_um=0,object_pairs=[['a','b']])],scope_by_object={'a':'pair','b':'pair'},exceptions={})
 edits=[]
 for o in s['objects']:
  new=copy.deepcopy(o);new['metal'][0]['bbox_um'][1][1]=3;edits.append(dict(id=o['id'],before_sha256=repair.digest(o),after=new))
 p=dict(snapshot_sha256=repair.digest(s),source=s['target'],target=dict(lib='L',cell='DST',view='layout'),authorization='explicit user repair request',authorized_object_ids=['a','b'],edits=edits,drc_policy_sha256='policy');return s,p

class Symmetry(unittest.TestCase):
 def test_same_net_self_pair(self):
  s,p=repair_fixture();s['objects'][1]['net']='P';s['symmetry_groups'][0]['mode']='self';p['snapshot_sha256']=repair.digest(s)
  p['edits'][1]['before_sha256']=repair.digest(s['objects'][1]);p['edits'][1]['after']['net']='P'
  repair.check(s,p)
 def test_axis_self_object(self):
  s,p=repair_fixture();s['objects']=s['objects'][:1];s['objects'][0]['metal'][0]['bbox_um']=[[-1,0],[1,2]]
  s['symmetry_groups']=[dict(id='self',mode='self',axis_x_um=0,object_pairs=[['a','a']])];s['scope_by_object']={'a':'self'}
  p['snapshot_sha256']=repair.digest(s);p['edits']=p['edits'][:1];p['edits'][0]['before_sha256']=repair.digest(s['objects'][0]);p['edits'][0]['after']=copy.deepcopy(s['objects'][0]);p['edits'][0]['after']['metal'][0]['bbox_um'][1][1]=3
  repair.check(s,p)
 def test_missing_mate(self):
  s,p=repair_fixture();s['symmetry_groups'][0]['object_pairs']=[['a','missing']];p['snapshot_sha256']=repair.digest(s)
  with self.assertRaises(ValueError):repair.check(s,p)
 def test_unapproved_exception(self):
  s,p=repair_fixture();s['symmetry_groups']=[];s['scope_by_object']={'a':'extra','b':'extra'};s['exceptions']={'extra':dict(reason='single ended',boundary='branch only')};p['snapshot_sha256']=repair.digest(s)
  with self.assertRaises(ValueError):repair.check(s,p)
 def test_paired_resize(self):
  s,p=repair_fixture();self.assertEqual(repair.check(s,p)['status'],'GEOMETRY_PLAN_PASS_NOT_DRC')
 def test_one_sided_even_only_one_marker(self):
  s,p=repair_fixture();p['edits']=p['edits'][:1]
  with self.assertRaisesRegex(ValueError,'one-sided'):repair.check(s,p)
 def test_wrong_width_or_layer(self):
  s,p=repair_fixture();p['edits'][1]['after']['metal'][0]['layer']='M2'
  with self.assertRaisesRegex(ValueError,'mirror mismatch'):repair.check(s,p)
 def test_via_cuts_participate(self):
  s,p=repair_fixture();p['edits'][0]['after']['cuts']=[dict(layer='V1',bbox_um=[[-2.9,.1],[-2.5,.5]])]
  with self.assertRaises(ValueError):repair.check(s,p)
 def test_scope_cannot_disappear(self):
  s,p=repair_fixture();s['symmetry_groups']=[];p['snapshot_sha256']=repair.digest(s)
  with self.assertRaises(ValueError):repair.check(s,p)
 def test_net_cannot_change(self):
  s,p=repair_fixture();p['edits'][0]['after']['net']='N'
  with self.assertRaises(ValueError):repair.check(s,p)
 def test_stale(self):
  s,p=repair_fixture();p['snapshot_sha256']='bad'
  with self.assertRaises(ValueError):repair.check(s,p)
 def test_protected_owner(self):
  s,p=repair_fixture();s['objects'][0]['owner']='PCell';p['snapshot_sha256']=repair.digest(s);p['edits'][0]['before_sha256']=repair.digest(s['objects'][0])
  with self.assertRaises(ValueError):repair.check(s,p)

class MockAdapter:
 def __init__(self,s):self.source=copy.deepcopy(s);self.saved=None;self.fail=False;self.rolled=False
 def snapshot(self,target):return copy.deepcopy(self.source if target==self.source['target'] else self.saved)
 def exists(self,target):return self.saved is not None
 def begin_clone(self,source,target):self.work=copy.deepcopy(self.source);self.work['target']=target;return 'transaction'
 def read(self,t):return copy.deepcopy(self.work)
 def apply(self,t,e):self.work['objects']=[copy.deepcopy(e['after']) if o['id']==e['id'] else o for o in self.work['objects']]
 def verify(self,t,b,a):return dict(before_sha256=repair.digest(b),after_sha256=repair.digest(a),**{k:('FAIL' if self.fail else 'PASS') for k in ('connectivity','pin_access','pdk_geometry','matched_metrics','environment')})
 def commit(self,t):self.saved=copy.deepcopy(self.work)
 def rollback(self,t):self.rolled=True;self.work=None
 def rerun_drc(self,target):return dict(status='CLEAN',provenance_status='BOUND_ADAPTER_ATTESTED',policy_sha256='policy',saved_snapshot_sha256=repair.digest(self.saved),integrity_issues=[])

class Transaction(unittest.TestCase):
 def test_clone_drift_rolls_back(self):
  s,p=repair_fixture();a=MockAdapter(s);original=a.begin_clone
  def bad(source,target):
   token=original(source,target);a.work['objects'][0]['net']='wrong';return token
  a.begin_clone=bad
  with self.assertRaises(ValueError):repair.execute(p,a)
  self.assertTrue(a.rolled)
 def test_policy_change_rejected(self):
  s,p=repair_fixture();a=MockAdapter(s);p['drc_policy_sha256']='changed'
  with self.assertRaises(ValueError):repair.execute(p,a)
  self.assertIsNotNone(a.saved)
 def test_saved_readback_drift(self):
  s,p=repair_fixture();a=MockAdapter(s);commit=a.commit
  def bad(t):commit(t);a.saved['objects'][0]['metal'][0]['layer']='M9'
  a.commit=bad
  with self.assertRaises(ValueError):repair.execute(p,a)
 def test_waived_cannot_close(self):
  s,p=repair_fixture();a=MockAdapter(s);a.rerun_drc=lambda t:dict(status='WAIVED',provenance_status='BOUND_ADAPTER_ATTESTED',policy_sha256='policy',saved_snapshot_sha256=repair.digest(a.saved))
  self.assertEqual(repair.execute(p,a)['status'],'SAVED_NOT_CLOSED')
 def test_commit_reread_rerun(self):
  s,p=repair_fixture();a=MockAdapter(s);self.assertEqual(repair.execute(p,a)['status'],'CLEAN');self.assertEqual(s,a.source)
 def test_failure_rolls_back_both(self):
  s,p=repair_fixture();a=MockAdapter(s);a.fail=True
  with self.assertRaises(ValueError):repair.execute(p,a)
  self.assertTrue(a.rolled);self.assertIsNone(a.saved);self.assertEqual(s,a.source)
 def test_unverified_rerun_never_closed(self):
  s,p=repair_fixture();a=MockAdapter(s);a.rerun_drc=lambda target:dict(status='CLEAN',policy_sha256='policy',saved_snapshot_sha256=repair.digest(a.saved))
  self.assertEqual(repair.execute(p,a)['status'],'SAVED_NOT_CLOSED')

if __name__=='__main__':unittest.main()
