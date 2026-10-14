import copy
import unittest
from lvs_repair import check, execute, digest, FINGERPRINTS


def obj(ident, x):
    return dict(id=ident, owner='route-owned', kind='metal', net='VSS',
                metal=[dict(layer='M2', bbox_um=[[x,0],[x+1,1]])], cuts=[])


def case():
    left, right = obj('left', -2), obj('right', 1)
    s = dict(target=dict(lib='test',cell='old',view='layout'), objects=[left,right], slots={},
             protected={'devices':'frozen'}, groups=[dict(id='core',axis_x_um=0,net_pair=['VSS','VSS'],pairs=[['left','right']])],
             scope={'left':'core','right':'core'}, exceptions={})
    p = dict(source=s['target'],target=dict(lib='test',cell='new',view='layout'),snapshot_sha256=digest(s),
             authorization='synthetic repair authorization',authorized_ids=['left','right'],findings=[dict(id='open1',category='open',evidence={'islands':['a','b']},expected_delta={'join':['a','b']})],edits=[])
    for k in FINGERPRINTS:p[k]=digest(k)
    for o in s['objects']:
        n=copy.deepcopy(o);n['metal'][0]['bbox_um'][1][1]=2
        p['edits'].append(dict(id=o['id'],op='replace',before_sha256=digest(o),after=n,finding_ids=['open1']))
    return s,p


def ev():return [dict(path='synthetic-only',sha256='a'*64)]


class Fake:
    def __init__(self,s,p):
        self.s=copy.deepcopy(s);self.p=p;self.current=None;self.saved=None;self.rolled=False;self.saved_flag=False
        self.fail_apply=False;self.bad_verify=False;self.bad_read=False;self.bad_commit=False
        self.drc_status='CLEAN';self.lvs_status='VERIFIED_MATCH';self.policy_drift=False;self.source_drift=False
    def snapshot(self,t):return copy.deepcopy(self.s if t==self.p['source'] else self.saved)
    def exists(self,t):return False
    def validate_baseline(self,p,s):return dict(status='BOUND_MISMATCH',snapshot_sha256=digest(s),evidence=ev(),**{k:p[k] for k in FINGERPRINTS})
    def begin_clone(self,s,t):
        self.current=copy.deepcopy(self.s);self.current['target']=t;return 'tx'
    def read(self,t):return copy.deepcopy(self.current)
    def apply(self,t,e):
        if self.fail_apply:raise RuntimeError('simulated write failure')
        objects={o['id']:o for o in self.current['objects']}
        if e['op']=='delete':
            old=objects.pop(e['id']);self.current['slots'][e['id']]={k:old[k] for k in ('id','owner','kind','net')}
        else:
            objects[e['id']]=copy.deepcopy(e['after']);self.current['slots'].pop(e['id'],None)
        self.current['objects']=[objects[k] for k in sorted(objects)]
        if self.bad_read:self.current['protected']={'devices':'changed'}
    def verify(self,t,b,a,p):
        checks={k:'PASS' for k in ('expected_delta','no_unintended_connectivity','pdk_geometry','pin_access','matched_metrics','environment')}
        if self.bad_verify:checks['expected_delta']='UNKNOWN'
        return dict(checks=checks,before_sha256=digest(b),after_sha256=digest(a),evidence=ev())
    def commit(self,t):
        self.saved=copy.deepcopy(self.current);self.saved_flag=True
        if self.bad_commit:raise RuntimeError('partial save')
    def rollback(self,t):self.rolled=True;self.saved=None;self.current=None
    def rerun_lvs(self,t):
        return dict(status=self.lvs_status,bound=True,evidence=ev(),integrity_issues=[],saved_snapshot_sha256=digest(self.saved),policy_sha256=self.p['lvs_policy_sha256'],reference_sha256=self.p['reference_sha256'])
    def rerun_drc(self,t):
        r=dict(status=self.drc_status,bound=True,evidence=ev(),integrity_issues=[],saved_snapshot_sha256=digest(self.saved),policy_sha256=('b'*64 if self.policy_drift else self.p['drc_policy_sha256']))
        if self.source_drift:self.s['protected']['devices']='changed'
        return r


class RepairTests(unittest.TestCase):
    def test_paired_replace(self):
        s,p=case();a=Fake(s,p)
        self.assertEqual(execute(p,a)['status'],'REPAIR_CLOSED')
        self.assertEqual(a.s,s)
    def test_one_side(self):
        s,p=case();p['edits'].pop()
        with self.assertRaisesRegex(ValueError,'one-sided'):check(s,p)
    def test_stale(self):
        s,p=case();s['protected']['devices']='new'
        with self.assertRaisesRegex(ValueError,'stale'):check(s,p)
    def test_net_change(self):
        s,p=case();p['edits'][0]['after']['net']='OTHER'
        with self.assertRaisesRegex(ValueError,'net change'):check(s,p)
    def test_unequal_cut(self):
        s,p=case();p['edits'][0]['after']['cuts']=[dict(layer='V1',bbox_um=[[-1.9,.1],[-1.8,.2]])]
        with self.assertRaisesRegex(ValueError,'mirror'):check(s,p)
    def test_missing_via_mate_create_verify(self):
        s,p=case()
        for o in s['objects']:
            o['kind']='via';o['cuts']=copy.deepcopy(o['metal']);o['cuts'][0]['layer']='V1'
        left=s['objects'].pop(0);s['slots']['left']={k:left[k] for k in ('id','owner','kind','net')}
        p['snapshot_sha256']=digest(s)
        p['edits'][0].update(op='create',before_sha256=None,after=left)
        right=s['objects'][0];p['edits'][1].update(op='verify',before_sha256=digest(right),after=copy.deepcopy(right))
        a=Fake(s,p);self.assertEqual(execute(p,a)['status'],'REPAIR_CLOSED')
        self.assertEqual(a.saved['slots'],{})
    def test_paired_delete(self):
        s,p=case()
        for e in p['edits']:e.update(op='delete',after=None)
        result=check(s,p);self.assertEqual(result['objects'],[]);self.assertEqual(len(result['slots']),2)
    def test_unknown_gate_rolls_back(self):
        s,p=case();a=Fake(s,p);a.bad_verify=True
        with self.assertRaisesRegex(ValueError,'expected_delta'):execute(p,a)
        self.assertTrue(a.rolled);self.assertFalse(a.saved_flag)
    def test_apply_failure(self):
        s,p=case();a=Fake(s,p);a.fail_apply=True
        with self.assertRaises(RuntimeError):execute(p,a)
        self.assertTrue(a.rolled)
    def test_partial_commit_failure(self):
        s,p=case();a=Fake(s,p);a.bad_commit=True
        with self.assertRaises(RuntimeError):execute(p,a)
        self.assertTrue(a.rolled);self.assertIsNone(a.saved)
    def test_unexpected_change(self):
        s,p=case();a=Fake(s,p);a.bad_read=True
        with self.assertRaisesRegex(ValueError,'readback'):execute(p,a)
        self.assertTrue(a.rolled)
    def test_drc_not_closed(self):
        s,p=case();a=Fake(s,p);a.drc_status='WAIVED'
        self.assertEqual(execute(p,a)['status'],'SAVED_NOT_CLOSED');self.assertFalse(a.rolled)
    def test_lvs_report_only(self):
        s,p=case();a=Fake(s,p);a.lvs_status='REPORT_MATCH_UNVERIFIED'
        self.assertEqual(execute(p,a)['status'],'SAVED_NOT_CLOSED')
    def test_policy_drift(self):
        s,p=case();a=Fake(s,p);a.policy_drift=True
        self.assertEqual(execute(p,a)['status'],'SAVED_NOT_CLOSED')
    def test_postrun_source_drift(self):
        s,p=case();a=Fake(s,p);a.source_drift=True
        self.assertEqual(execute(p,a)['status'],'SAVED_NOT_CLOSED')
    def test_protected_owner(self):
        s,p=case();s['objects'][0]['owner']='pcell';p['snapshot_sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'protected'):check(s,p)
    def test_noop_not_repair(self):
        s,p=case()
        for e,o in zip(p['edits'],s['objects']):e.update(op='verify',after=copy.deepcopy(o))
        with self.assertRaisesRegex(ValueError,'effective'):check(s,p)
    def test_no_baseline_digest(self):
        s,p=case();p.pop('baseline_sha256')
        with self.assertRaisesRegex(ValueError,'baseline'):check(s,p)
    def test_existing_destination(self):
        s,p=case();a=Fake(s,p);a.exists=lambda t:True
        with self.assertRaisesRegex(ValueError,'destination'):execute(p,a)
        self.assertIsNone(a.current)
    def test_baseline_self_compare(self):
        s,p=case();a=Fake(s,p);a.validate_baseline=lambda p,s:dict(status='INVALID_COMPARISON')
        with self.assertRaisesRegex(ValueError,'baseline'):execute(p,a)

    def test_pin_requires_authorization(self):
        s,p=case()
        for o,e in zip(s['objects'],p['edits']):
            o.update(owner='pin-owned',kind='pin');e['after'].update(owner='pin-owned',kind='pin');e['before_sha256']=digest(o)
        p['snapshot_sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'pin edit'):check(s,p)
        p['authorize_pin_edits']=True
        self.assertEqual(len(check(s,p)['objects']),2)

    def test_missing_geometry_mate(self):
        s,p=case();p['edits'][0].update(op='delete',after=None)
        with self.assertRaisesRegex(ValueError,'final mate'):check(s,p)

    def test_axis_object(self):
        s,p=case();o=obj('axis',-.5);s['objects']=[o];s['groups'][0]['pairs']=[['axis','axis']];s['scope']={'axis':'core'}
        p['snapshot_sha256']=digest(s);p['authorized_ids']=['axis'];n=copy.deepcopy(o);n['metal'][0]['bbox_um'][1][1]=2
        p['edits']=[dict(id='axis',op='replace',before_sha256=digest(o),after=n,finding_ids=['open1'])]
        self.assertEqual(len(check(s,p)['objects']),1)

    def test_pair_net_identity(self):
        s,p=case();s['objects'][0]['net']='INP';s['objects'][1]['net']='INN';s['groups'][0]['net_pair']=['INP','INN']
        for o,e in zip(s['objects'],p['edits']):e['before_sha256']=digest(o);e['after']['net']=o['net']
        p['snapshot_sha256']=digest(s)
        self.assertEqual(len(check(s,p)['objects']),2)

    def test_unapproved_exception(self):
        s,p=case();s['groups']=[];s['scope']={'left':'extra','right':'extra'};s['exceptions']={'extra':dict(reason='single ended',approval='user',boundary='branch')};p['snapshot_sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'exception edit'):check(s,p)

    def test_unbound_rerun(self):
        s,p=case();a=Fake(s,p);a.rerun_lvs=lambda t:dict(status='VERIFIED_MATCH',bound=False)
        self.assertEqual(execute(p,a)['status'],'SAVED_NOT_CLOSED')


if __name__=='__main__':unittest.main()
