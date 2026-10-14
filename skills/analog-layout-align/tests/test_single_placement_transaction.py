import importlib.util, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import patch

script=Path(__file__).resolve().parents[1]/'scripts/apply_placement_intent.py'
spec=importlib.util.spec_from_file_location('placement_transaction_fixture',script)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class SinglePlacementTransactionTests(unittest.TestCase):
    def test_initial_devices_and_labels_use_one_mutation_call_and_one_save(self):
        item=dict(name='MOS',kind='nmos',origin=[0,0],orientation='R0',bbox=[[0,0],[1,1]],
                  terminals=dict(D='OUT',G='IN',S='VSS',B='VSS'),
                  pcell_master=dict(lib='test_pdk',cell='nmos',view='layout'),
                  pcell_parameters=dict(w='20u',fw='5u',l='1u',fingers='4',m='1'))
        intent=dict(schema='analog-layout-align.pcell-placement-intent/v2',instances=[item],
                    coordinate_contract={'manufacturing_grid':.001},
                    validation=dict(expected_instances=1,placed_instances=1,all_mos_copies_have_m_1=True,
                                    all_origins_on_manufacturing_grid=True,bbox_overlap_free=True,dummy_families_associated=True))
        calls=[]
        client=SimpleNamespace(execute_skill=lambda code:calls.append(code) or SimpleNamespace(ok=True,output='OK|created=1',errors=[]))
        bridge=ModuleType('virtuoso_bridge');bridge.VirtuosoClient=SimpleNamespace(from_env=lambda:client)
        env=ModuleType('virtuoso_bridge.env');env.set_runtime_env_file=lambda path:None
        report=dict(readback_match=True,bbox_overlap_free=True,placement_only=True,
                    drain_annotations={'mismatches':[]},readback_instances=1)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'intent.json';source.write_text(json.dumps(intent))
            args=module.parser().parse_args([str(source),'--env','fixture.env','--lib','test','--cell','new','--report',str(root/'report.json')])
            with patch.object(module,'parser',return_value=SimpleNamespace(parse_args=lambda:args)),patch.object(module,'verify',return_value=report),patch.dict(sys.modules,{'virtuoso_bridge':bridge,'virtuoso_bridge.env':env}),patch('builtins.print'):
                module.main()
        self.assertEqual(len(calls),1)
        self.assertIn('dbCreateParamInstByMasterName',calls[0])
        self.assertIn('dbCreateLabel',calls[0])
        self.assertEqual(calls[0].count('dbSave(cv)'),1)
        self.assertIn('length(labels)!=1',calls[0])
        self.assertIn('dbPurge(cv)',calls[0])
        self.assertLess(calls[0].index('dbCreateLabel'),calls[0].index('dbSave(cv)'))

if __name__=='__main__':unittest.main()
