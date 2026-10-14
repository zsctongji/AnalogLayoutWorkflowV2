import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from macro_opt import digest,optimize,verify_translation,shifted


def fixture():
    s={'schema':'analog-layout-macro-opt.snapshot/v1','source':{'lib':'test','cell':'example','view':'layout'},
       'grid_um':1,'evidence':{'basis':'synthetic test, not PDK'},'cross_macro_connections':[],
       'macros':[{'id':'PAIR'},{'id':'MIRROR'},{'id':'CAP'}],
       'objects':[{'id':n,'macro':n,'bbox_um':[[x,0],[x+4,4]],'payload_sha256':'payload-'+n}
                  for n,x in [('PAIR',0),('MIRROR',12),('CAP',24)]],
       'source_object_ids':['PAIR','MIRROR','CAP'],'protected_sets':[]}
    r={'schema':'analog-layout-macro-opt.request/v1','snapshot_sha256':digest(s),'bounds_um':[[0,0],[40,20]],
       'pair_gaps':[{'macros':[a,b],'x_um':1,'y_um':1,'basis':'synthetic planning gap'}
                    for a,b in [('PAIR','MIRROR'),('PAIR','CAP'),('MIRROR','CAP')]],
       'search':{'max_evaluations':500,'max_iterations':12,'beam_width':8,'top_k':3,'step_um':1}}
    return s,r


class MacroTests(unittest.TestCase):
    def test_objective_priority_changes_area_wirelength_tradeoff(self):
        s,r=fixture();r['locked']=['PAIR']
        r['nets']=[{'id':'sensitive','weight':5,'pins':[
            {'island_id':'a','macro':'PAIR','xy_um':[4,4]},
            {'island_id':'c','macro':'CAP','xy_um':[24,0]}]}]
        area=optimize(s,r)['candidates'][0]['metrics']
        r['objective_priority']=['weighted_hpwl_um','area_um2']
        wire=optimize(s,r)['candidates'][0]['metrics']
        self.assertLess(area['area_um2'],wire['area_um2'])
        self.assertLess(wire['weighted_hpwl_um'],area['weighted_hpwl_um'])
        self.assertTrue(area['valid'] and wire['valid'])

    def test_invalid_objective_priority_rejected(self):
        s,r=fixture()
        for priority in ([],['area_um2','area_um2'],['unknown_metric']):
            r['objective_priority']=priority
            with self.assertRaisesRegex(ValueError,'objective priority'):optimize(s,r)

    def stack(self):
        s,r=fixture()
        for j,o in enumerate(s['objects']):o['bbox_um']=[[0,j*12],[4,j*12+4]]
        r['snapshot_sha256']=digest(s);r['bounds_um']=[[0,0],[10,40]]
        r['align']=[{'axis':'x','macros':['PAIR','MIRROR','CAP']}];r['locked']=['PAIR']
        r['order']=[{'axis':'y','before':a,'after':b,'gap_um':1} for a,b in [('PAIR','MIRROR'),('MIRROR','CAP')]]
        r['search'].update(max_evaluations=3,max_iterations=1,beam_width=1)
        return s,r

    def test_full_stack_under_tight_budget(self):
        s,r=self.stack();out=optimize(s,r);best=out['candidates'][0]
        self.assertEqual(best['metrics']['height_um'],14)
        self.assertEqual(best['metrics']['deltas_um']['PAIR'],[0,0])
        self.assertEqual(out['ordered_compaction_seeds_evaluated'],1)
        self.assertTrue(all(x['axis_slack_um']==0 for x in best['ordered_gap_audit']))
        self.assertLessEqual(out['evaluations'],3)

    def test_stack_respects_nonadjacent_gap(self):
        s,r=self.stack();r['pair_gaps'][1]['y_um']=20
        out=optimize(s,r)
        for candidate in out['candidates']:
            self.assertGreaterEqual(candidate['positions_um']['CAP'][1],24)

    def test_stack_order_gap_is_not_silently_relaxed(self):
        s,r=self.stack();r['order'][0]['gap_um']=7
        best=optimize(s,r)['candidates'][0]
        self.assertEqual(best['positions_um']['MIRROR'][1],11)

    def test_stack_coupled_axis_falls_back(self):
        s,r=self.stack();r['align'].append({'axis':'y','macros':['MIRROR','CAP']})
        out=optimize(s,r)
        self.assertEqual(out['ordered_compaction_seeds_evaluated'],0)

    def test_stack_rounds_clearance_outward(self):
        s,r=self.stack()
        for p in r['pair_gaps']:p['y_um']=1.2
        best=optimize(s,r)['candidates'][0]
        self.assertEqual(best['positions_um']['MIRROR'][1],6)
        self.assertEqual(best['positions_um']['CAP'][1],12)

    def test_stack_seed_cannot_bypass_pin_span(self):
        s,r=self.stack()
        r['nets']=[{'id':'limited','pins':[{'island_id':'a','macro':'PAIR','xy_um':[0,0]},
            {'island_id':'c','macro':'CAP','xy_um':[0,24]}],'max_hpwl_um':9}]
        self.assertFalse(optimize(s,r)['candidates'])

    def test_cyclic_stack_not_compacted(self):
        s,r=self.stack();r['order'].append({'axis':'y','before':'CAP','after':'PAIR','gap_um':1})
        result=optimize(s,r)
        self.assertEqual(result['ordered_compaction_seeds_evaluated'],0)
        self.assertFalse(result['candidates'])

    def test_compaction_includes_cap_and_all_objects(self):
        s,r=fixture(); result=optimize(s,r)
        best=result['candidates'][0]
        self.assertLess(best['metrics']['area_um2'],result['baseline']['area_um2'])
        self.assertEqual(len(best['object_moves']),3)
        self.assertTrue(best['metrics']['valid'])
        self.assertLessEqual(result['evaluations'],r['search']['max_evaluations'])

    def test_alignment_and_order(self):
        s,r=fixture(); r['align']=[{'axis':'x','macros':['PAIR','MIRROR']}]
        r['order']=[{'axis':'y','before':'PAIR','after':'MIRROR','gap_um':1}]
        result=optimize(s,r)
        self.assertTrue(result['candidates'])
        for c in result['candidates']:
            p=c['positions_um']; self.assertEqual(p['PAIR'][0],p['MIRROR'][0])
            self.assertGreaterEqual(p['MIRROR'][1],p['PAIR'][1]+5)

    def test_mirror_components(self):
        s,r=fixture(); r['mirror']=[{'axis':'x','coordinate_um':15,'pairs':[['PAIR','MIRROR']]}]
        result=optimize(s,r); self.assertTrue(result['candidates'])
        for c in result['candidates']:
            p=c['positions_um']; self.assertEqual(p['PAIR'][0]+p['MIRROR'][0]+4,30)
            self.assertEqual(p['PAIR'][1],p['MIRROR'][1])

    def test_fixed_capacitor(self):
        s,r=fixture(); r['locked']=['CAP']
        for c in optimize(s,r)['candidates']: self.assertEqual(c['metrics']['deltas_um']['CAP'],[0,0])

    def test_stale_hash(self):
        s,r=fixture(); s['objects'][0]['payload_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'Stale'): optimize(s,r)

    def test_missing_ring_object(self):
        s,r=fixture(); s['source_object_ids'].append('ring-cut'); r['snapshot_sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'coverage'): optimize(s,r)

    def test_split_shared_edge(self):
        s,r=fixture(); s['protected_sets']=[{'kind':'shared_source','object_ids':['PAIR','MIRROR']}];r['snapshot_sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'split'): optimize(s,r)

    def test_cross_macro_wire(self):
        s,r=fixture(); s['cross_macro_connections']=['wire1'];r['snapshot_sha256']=digest(s)
        with self.assertRaisesRegex(ValueError,'Cross-macro'): optimize(s,r)

    def test_missing_clearance(self):
        s,r=fixture(); r['pair_gaps'].pop()
        with self.assertRaisesRegex(ValueError,'Missing pair'): optimize(s,r)

    def test_unknown_constraint(self):
        s,r=fixture();r['relax_symmetry']=True
        with self.assertRaisesRegex(ValueError,'Unsupported'): optimize(s,r)

    def test_lock_conflict(self):
        s,r=fixture();r['align']=[{'axis':'x','macros':['PAIR','MIRROR']}];r['locked']=['PAIR','MIRROR']
        with self.assertRaisesRegex(ValueError,'Conflicting'): optimize(s,r)

    def test_impossible_bounds_not_claimed_infeasible(self):
        s,r=fixture();r['bounds_um']=[[0,0],[4,4]]
        self.assertEqual(optimize(s,r)['status'],'NO_FEASIBLE_CANDIDATE_IN_BUDGET')

    def test_readback_and_left_behind_ring(self):
        s,r=fixture();c=optimize(s,r)['candidates'][0];t=copy.deepcopy(s)
        for o in t['objects']: o['bbox_um']=shifted(o['bbox_um'],c['metrics']['deltas_um'][o['macro']])
        self.assertTrue(verify_translation(s,t,c)['valid'])
        t['objects'][0]['bbox_um'][0][0]+=.1
        self.assertFalse(verify_translation(s,t,c)['valid'])

    def test_changed_payload(self):
        s,r=fixture();c=optimize(s,r)['candidates'][0];t=copy.deepcopy(s)
        t['objects'][0]['payload_sha256']='different'
        self.assertFalse(verify_translation(s,t,c)['valid'])

    def test_hpwl_limit(self):
        s,r=fixture();r['nets']=[{'id':'critical','pins':[{'island_id':n,'macro':n,'xy_um':xy}
            for n,xy in [('PAIR',[2,2]),('CAP',[26,2])]],'max_hpwl_um':8}]
        result=optimize(s,r);self.assertTrue(result['candidates'])
        for c in result['candidates']: self.assertLessEqual(c['metrics']['net_hpwl_um']['critical'],8)

    def test_source_not_mutated_and_deterministic(self):
        s,r=fixture();before=copy.deepcopy(s)
        self.assertEqual(optimize(s,r),optimize(s,r));self.assertEqual(s,before)

    def test_ring_cut_and_pin_move_with_devices(self):
        s,r=fixture()
        for name,box in [('RING',[[-1,-1],[5,5]]),('CUT',[[-1,0],[-.5,.5]]),('PIN',[[0,-1],[1,-.5]])]:
            s['objects'].append({'id':name,'macro':'PAIR','bbox_um':box,'payload_sha256':name})
            s['source_object_ids'].append(name)
        s['protected_sets']=[{'kind':'guard_ring','object_ids':['PAIR','RING','CUT','PIN']}]
        r['snapshot_sha256']=digest(s)
        result=optimize(s,r); self.assertTrue(result['candidates'])
        for c in result['candidates']:
            moves=[tuple(m['delta_um']) for m in c['object_moves'] if m['macro']=='PAIR']
            self.assertEqual(len(moves),4);self.assertEqual(len(set(moves)),1)

    def test_physical_anchor_not_ring_center(self):
        s,r=fixture();s['macros'][0]['anchor_um']=[1,2];s['macros'][1]['anchor_um']=[15,2]
        r['snapshot_sha256']=digest(s);r['align']=[{'axis':'x','macros':['PAIR','MIRROR']}]
        result=optimize(s,r);self.assertTrue(result['candidates'])
        for c in result['candidates']:
            p=c['positions_um'];self.assertEqual(p['PAIR'][0]+1,p['MIRROR'][0]+3)

    def test_offgrid_symmetry_not_relaxed(self):
        s,r=fixture();r['mirror']=[{'axis':'x','coordinate_um':15.25,'pairs':[['PAIR','MIRROR']]}]
        self.assertEqual(optimize(s,r)['candidates'],[])

    def test_nonrigid_move_manifest_rejected(self):
        s,r=fixture();s['objects'].append({'id':'cut','macro':'PAIR','bbox_um':[[0,0],[1,1]],'payload_sha256':'cut'})
        s['source_object_ids'].append('cut');r['snapshot_sha256']=digest(s)
        c=optimize(s,r)['candidates'][0];c['object_moves'][-1]['delta_um']=[99,99]
        self.assertFalse(verify_translation(s,s,c)['valid'])

if __name__=='__main__': unittest.main()
