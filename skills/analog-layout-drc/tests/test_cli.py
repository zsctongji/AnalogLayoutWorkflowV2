"""Actual CLI/subprocess tests using a clearly synthetic CAD adapter, not EDA."""
import json,sys,tempfile,subprocess,unittest
from pathlib import Path
SCRIPTS=Path(__file__).parents[1]/'scripts'
MOCK='''
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import calibre_drc as d
import evidence_binding as b
stage=sys.argv[2];p=d.prepare_run(Path(sys.argv[3]));root=Path(p['working_directory']);c=p['config'];cfg=c['binding']
cmd=next(s for s in p['stages'] if s['name']==stage)
inp={v['path']:b.digest(v['path']) for v in p['inputs'].values()}
oa=b.snapshot_files([root/x for x in cfg['oa_files']]);deps=b.snapshot_files([root/x for x in cfg['deck_dependencies']])
stream=Path(p['artifacts']['stream'])
if stage=='streamout':stream.write_text('SYNTHETIC_NOT_GDS')
else:
 Path(p['artifacts']['summary']).write_text('Layout Primary Cell: TOP\\nRULECHECK m1.s ... TOTAL Result Count = 0 (0)\\n')
 Path(p['artifacts']['results']).write_text('TOP 1000\\n')
policy={k:cfg[k] for k in ('metal_option','hierarchy_mode','result_limit','adapter_id')}
r=dict(schema='analog-layout-drc.stage-receipt/v1',stage=stage,completed=True,target=c['target'],config_sha256=p['config_sha256'],adapter_id=cfg['adapter_id'],argv_sha256=b.fingerprint(cmd['argv']),input_hashes=inp,oa_hashes=oa,dependency_hashes=deps,policy=policy,tool_version='MOCK_TEST_ONLY',interpreter_version=sys.version,log_hashes={k:b.digest(cmd[k]) for k in ('stdout','stderr')},stream_path=str(stream.resolve()),stream_sha256=b.digest(stream),saved_oa=True,oa_inventory_complete=True,stream_format_validated='GDSII',dependencies_complete=True,result_limit_reached=False)
if stage=='drc':r['output_hashes']={k:b.digest(p['artifacts'][k]) for k in ('summary','results')}
(root/cfg['export_receipt' if stage=='streamout' else 'drc_receipt']).write_text(json.dumps(r))
'''

class CLI(unittest.TestCase):
 def fixture(self,root):
  for f in ('oa','deck','map'):(root/f).write_text(f)
  (root/'mock.py').write_text(MOCK)
  cfg=root/'config.json'
  c=dict(schema='analog-layout-drc.calibre-run/v1',target=dict(lib='L',cell='TOP',view='layout'),working_directory=str(root),inputs=dict(rule_deck='deck',layer_map='map',adapter_source='mock.py'),artifacts=dict(stream='stream.gds',summary='summary.txt',results='results.txt'),binding=dict(oa_files=['oa'],deck_dependencies=['deck'],metal_option='MOCK',hierarchy_mode='hier',result_limit='ALL',adapter_id='MOCK',export_receipt='export.json',drc_receipt='drc.json'))
  for stage in ('streamout','drc'):c[stage]=dict(argv=[sys.executable,str(root/'mock.py'),str(SCRIPTS),stage,str(cfg)])
  cfg.write_text(json.dumps(c));return cfg
 def test_mock_full_bound_run(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);cfg=self.fixture(r)
   result=subprocess.run([sys.executable,str(SCRIPTS/'calibre_drc.py'),'run','--execute','--config',str(cfg),'--out',str(r/'report.json'),'--report',str(r/'report.md')],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   report=json.loads((r/'report.json').read_text());self.assertEqual(report['status'],'CLEAN');self.assertEqual(report['provenance_status'],'BOUND_ADAPTER_ATTESTED');self.assertEqual(len(report['stage_results']),2)
 def test_report_cannot_overwrite_deck(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);cfg=self.fixture(r)
   result=subprocess.run([sys.executable,str(SCRIPTS/'calibre_drc.py'),'run','--execute','--config',str(cfg),'--out',str(r/'deck'),'--report',str(r/'report.md')],capture_output=True,text=True)
   self.assertEqual(result.returncode,3);self.assertEqual((r/'deck').read_text(),'deck');self.assertFalse((r/'stream.gds').exists())
 def test_unbound_parse_exit3(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);(r/'s').write_text('Layout Primary Cell: TOP\nRULECHECK m1.s ... TOTAL Result Count = 0 (0)\n');(r/'r').write_text('TOP 1000\n')
   result=subprocess.run([sys.executable,str(SCRIPTS/'calibre_drc.py'),'parse','--summary',str(r/'s'),'--results',str(r/'r'),'--out',str(r/'o'),'--report',str(r/'m')],capture_output=True,text=True)
   self.assertEqual(result.returncode,3);self.assertEqual(json.loads((r/'o').read_text())['status'],'UNVERIFIED')
if __name__=='__main__':unittest.main()
