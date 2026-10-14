import copy, sys, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from virtuoso_adapter import VirtuosoBackend
from adapter_runtime import MemoryBackend, execute, GATES
from workflow_runtime import digest, Invalid

def obj(name):
    return dict(id=name,owner='PAIR',net='N',kind='rect',lpp=['mt1','drawing'],bbox_um=[[0,0],[1,1]])

class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        self.backend=VirtuosoBackend.__new__(VirtuosoBackend)
        self.tx=dict(before=dict(objects=[],protected={'grid_um':.001}),written=set())
        self.backend.tx=self.tx
        self.commands=[]
        self.backend.ev=lambda code:self.commands.append(code) or 101
    def edits(self):
        return [dict(id=o['id'],op='create',after=o) for o in (obj('r'+str(i)) for i in range(101))]
    def test_more_than_old_chunk_limit_is_one_native_call(self):
        self.backend.apply_batch(self.tx,self.edits())
        self.assertEqual(len(self.commands),1)
        self.assertEqual(len(self.tx['written']),101)
        self.assertNotIn('dbSave',self.commands[0])
        with self.assertRaisesRegex(Invalid,'already applied'):
            self.backend.apply_batch(self.tx,[dict(id='extra',op='create',after=obj('extra'))])
    def test_invalid_last_record_prevents_entire_write(self):
        edits=self.edits();edits[-1]['after']['bbox_um']=[[1,0],[0,1]]
        with self.assertRaisesRegex(Invalid,'Invalid rectangle'):
            self.backend.apply_batch(self.tx,edits)
        self.assertEqual(self.commands,[])
        self.assertEqual(self.tx['written'],set())
    def test_stale_replacement_prevents_entire_write(self):
        old=obj('r0');self.tx['before']['objects']=[old]
        replacement=copy.deepcopy(old);replacement['bbox_um']=[[1,0],[2,1]]
        with self.assertRaisesRegex(Invalid,'Stale'):
            self.backend.apply_batch(self.tx,[dict(id='r0',op='replace',before_sha256='wrong',after=replacement)])
        self.assertEqual(self.commands,[])
    def test_protected_identity_change_prevents_write(self):
        old=obj('r0');self.tx['before']['objects']=[old]
        replacement=dict(old,net='OTHER')
        with self.assertRaisesRegex(Invalid,'protected'):
            self.backend.apply_batch(self.tx,[dict(id='r0',op='replace',before_sha256=digest(old),after=replacement)])
        self.assertEqual(self.commands,[])
    def test_off_grid_prevents_write(self):
        new=obj('off_grid');new['bbox_um'][0][0]=.0005
        with self.assertRaisesRegex(Invalid,'Off-grid'):
            self.backend.apply_batch(self.tx,[dict(id=new['id'],op='create',after=new)])
        self.assertEqual(self.commands,[])
    def test_read_never_flushes_pending_mutations(self):
        self.backend.select=lambda *args:None
        self.backend.raw=lambda *args:self.tx['before']
        self.backend.normalized=lambda value:value
        self.tx['target']=dict(lib='test',cell='target',view='layout')
        self.assertEqual(self.backend.read(self.tx),self.tx['before'])
        self.assertEqual(self.commands,[])

class StageTransactionTests(unittest.TestCase):
    def setUp(self):
        self.before=dict(objects=[],protected={'devices':'unchanged'})
        self.after=dict(self.before,objects=[obj('a'),obj('b')])
        self.backend=MemoryBackend(self.before)
        self.plan=dict(source=dict(lib='test',cell='source',view='layout'),
                       target=dict(lib='test',cell='new',view='layout'),authorization='test stage batch',
                       capability='rect-create',snapshot_sha256=digest(self.before),
                       expected_after_sha256=digest(self.after),authorized_ids=['a','b'],
                       edits=[dict(id=o['id'],op='create',after=o) for o in self.after['objects']])
    def verify(self,before,after,plan):
        return dict(before_sha256=digest(before),after_sha256=digest(after),
                    checks={key:'PASS' for key in GATES},evidence=['full fixture readback'])
    def test_one_batch_one_commit_after_verification(self):
        with patch.object(self.backend,'apply_batch',wraps=self.backend.apply_batch) as batch,patch.object(self.backend,'commit',wraps=self.backend.commit) as save:
            result=execute(self.plan,self.backend,self.verify)
            self.assertEqual(result['status'],'SAVED_LOCALLY_VERIFIED')
            self.assertEqual(batch.call_count,1)
            self.assertEqual(save.call_count,1)
            self.assertEqual(self.backend.views['source'],self.before)
    def test_batch_failure_saves_nothing(self):
        self.backend.fail_at='b'
        with patch.object(self.backend,'commit',wraps=self.backend.commit) as save:
            with self.assertRaisesRegex(Invalid,'TRANSACTION_ABORTED'):
                execute(self.plan,self.backend,self.verify)
            self.assertEqual(save.call_count,0)
        self.assertNotIn('new',self.backend.views)
        self.assertEqual(self.backend.views['source'],self.before)

if __name__=='__main__':unittest.main()
