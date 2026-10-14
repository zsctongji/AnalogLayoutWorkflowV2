import importlib.util
import unittest
import copy
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "placement_flow.py"
SPEC = importlib.util.spec_from_file_location("placement_flow", SCRIPT)
FLOW = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(FLOW)


def mos(name, mult=2, fingers=4):
    return {
        "name": name,
        "lib": "test_pdk",
        "cell": "nmos",
        "params": {"w": "20u", "fw": "5u", "l": "1.5u", "fingers": str(fingers), "m": str(mult)},
        "terms": {"D": f"d_{name}", "G": f"g_{name}", "S": "tail", "B": "vss"},
    }


class ExplicitMultiplierTests(unittest.TestCase):
    def test_expansion_preserves_fingers_and_sets_each_copy_m_to_one(self):
        copies, by_logical = FLOW.expand_mos_copies({"instances": [mos("NM3")]})
        self.assertEqual(len(copies), 2)
        self.assertEqual([copy["name"] for copy in copies], ["NM3__M0", "NM3__M1"])
        self.assertTrue(all(copy["pcell_parameters"]["fingers"] == "4" for copy in copies))
        self.assertTrue(all(copy["pcell_parameters"]["m"] == "1" for copy in copies))
        self.assertEqual(len(by_logical["NM3"]), 2)

    def test_two_by_two_copies_form_abba(self):
        _, by_logical = FLOW.expand_mos_copies({"instances": [mos("NM4"), mos("NM3")]})
        rows = FLOW.abba_rows(by_logical["NM4"], by_logical["NM3"])
        self.assertEqual([[copy["logical_device"] for copy in row] for row in rows], [["NM4", "NM3", "NM3", "NM4"]])

    def test_pm3_four_copies_form_two_by_two_array(self):
        copies, _ = FLOW.expand_mos_copies({"instances": [mos("PM3", mult=4, fingers=8)]})
        rows = FLOW.rectangular_rows(copies)
        self.assertEqual([len(row) for row in rows], [2, 2])

    def test_copy_group_records_explicit_abba_positions(self):
        _, by_logical = FLOW.expand_mos_copies({"instances": [mos("NM4"), mos("NM3")]})
        intent = {"differential_pairs": [["NM4", "NM3"]], "mirror_pairs": [], "roles": {}}
        groups = FLOW.build_copy_groups(intent, by_logical)
        self.assertEqual(groups[0]["pattern_mode"], "explicit_m_copy_abba_common_axis")
        self.assertEqual(groups[0]["rows"], [["NM4__M0", "NM3__M0", "NM3__M1", "NM4__M1"]])

    def test_two_lateral_dummies_preserve_diagonal_spans(self):
        devices = [mos('A'), mos('B'), mos('D')]
        copies, by_logical = FLOW.expand_mos_copies({'instances':devices})
        group = FLOW.build_copy_groups({'differential_pairs':[['A','B']], 'mirror_pairs':[], 'dummies':['D'], 'roles':{}},by_logical,matching_mode='common_centroid')[0]
        group.update(dummy_copies=[c['name'] for c in by_logical['D']],dummy_logical_devices=['D'])
        geometry = {'devices':{n:{'bbox_at_r0_origin':[[0,0],[5,7]]} for n in ('A','B','D')}}
        macro = FLOW.build_local_macro(group,{c['name']:c for c in copies},geometry,2,.001)
        self.assertEqual(len(macro['instances']),6)
        families = [[i['bbox_center'] for i in macro['instances'] if i['logical_device']==n] for n in ('A','B')]
        self.assertEqual([sum(p[a] for p in families[0])/2 for a in (0,1)], [sum(p[a] for p in families[1])/2 for a in (0,1)])
        self.assertEqual([abs(f[0][0]-f[1][0])+abs(f[0][1]-f[1][1]) for f in families],[16,16])
        for idx,a in enumerate(macro['instances']):
            for b in macro['instances'][idx+1:]: self.assertFalse(FLOW.bbox_overlap(a['bbox'],b['bbox']))

    def test_standalone_packing_uses_empty_space(self):
        boxes = [[[0,0],[50,50]],[[55,30],[100,50]]]
        ll = FLOW.compact_standalone_anchor(40,15,boxes,[105,35],5,.001)
        self.assertEqual(ll,[55,10])

    def test_equal_ratio_mirror_still_uses_abba(self):
        _, families = FLOW.expand_mos_copies({'instances':[mos('A'),mos('B')]})
        group = FLOW.build_copy_groups({'differential_pairs':[], 'mirror_pairs':[['A','B']], 'roles':{}},families)[0]
        self.assertEqual(group['pattern_mode'],'explicit_m_copy_abba_common_axis')

    def test_ratio_1_2_6_forms_three_by_three_common_centroid(self):
        devices = [mos("NM0", mult=1, fingers=1), mos("NM1", mult=2, fingers=1), mos("NM2", mult=6, fingers=1)]
        _, by_logical = FLOW.expand_mos_copies({"instances": devices})
        rows = FLOW.ratioed_common_centroid_rows(["NM0", "NM1", "NM2"], by_logical)
        labels = [[copy["logical_device"] for copy in row] for row in rows]
        self.assertEqual(labels, [["NM2", "NM2", "NM2"], ["NM1", "NM0", "NM1"], ["NM2", "NM2", "NM2"]])
        centroids = {}
        for logical in ("NM0", "NM1", "NM2"):
            positions = [(r, c) for r, row in enumerate(labels) for c, value in enumerate(row) if value == logical]
            centroids[logical] = tuple(sum(p[axis] for p in positions) / len(positions) for axis in (0, 1))
        self.assertEqual(set(centroids.values()), {(1.0, 1.0)})

    def test_dummy_family_associates_by_master_length_and_finger_width(self):
        active = [mos("NM0", mult=1, fingers=1), mos("NM1", mult=2, fingers=1), mos("NM2", mult=6, fingers=1)]
        dummy = mos("NM6", mult=6, fingers=1)
        for item in active + [dummy]:
            item["params"].update({"w": "5u", "fw": "5u", "l": "1u"})
        _, by_logical = FLOW.expand_mos_copies({"instances": active + [dummy]})
        group = {"name": "XCC_RATIO", "logical_devices": ["NM0", "NM1", "NM2"]}
        associations = FLOW.associate_dummies([group], {"dummies": ["NM6"]}, by_logical)
        self.assertEqual(associations[0]["target_group"], "XCC_RATIO")
        self.assertEqual(len(group["dummy_copies"]), 6)

    def test_six_dummies_wrap_three_rows_symmetrically(self):
        group = {
            "rows": [["C0", "C1", "C2"], ["B0", "A0", "B1"], ["C3", "C4", "C5"]],
            "dummy_copies": [f"D{i}" for i in range(6)],
        }
        rows, strategy = FLOW.dummy_augmented_rows(group)
        self.assertEqual(strategy, "symmetric_left_right_per_row")
        self.assertEqual([len(row) for row in rows], [5, 5, 5])
        self.assertTrue(all(row[0].startswith("D") and row[-1].startswith("D") for row in rows))


    def test_topology_discovery_ignores_names_and_normalizes_units(self):
        a,b=mos('renamed_left'),mos('renamed_right')
        b['params']={'w':'0.000020','fw':'5000n','l':'1.5um','nf':'4','m':'2'}
        intent=FLOW.infer_intent({'instances':[b,a]})
        self.assertEqual(intent['differential_pairs'],[['renamed_left','renamed_right']])
        _,families=FLOW.expand_mos_copies({'instances':[a,b]})
        rows=FLOW.build_copy_groups(intent,families)[0]['rows']
        self.assertEqual(rows,[['renamed_left__M0','renamed_right__M0','renamed_right__M1','renamed_left__M1']])

    def test_same_dimensions_different_master_do_not_match(self):
        a,b=mos('A'),mos('B');b['cell']='nmos_other'
        self.assertFalse(FLOW.infer_intent({'instances':[a,b]})['differential_pairs'])

    def test_mirror_requires_same_source_and_body(self):
        a,b=mos('A'),mos('B')
        a['terms']['G']=b['terms']['G']='bias';a['terms']['D']='bias'
        self.assertEqual(len(FLOW.infer_intent({'instances':[a,b]})['mirror_pairs']),1)
        b['terms']['S']='other_source'
        self.assertFalse(FLOW.infer_intent({'instances':[a,b]})['mirror_pairs'])

    def test_unknown_dimension_does_not_match(self):
        a,b=mos('A'),mos('B')
        a['params']['l']=b['params']['l']='length_var'
        self.assertFalse(FLOW.infer_intent({'instances':[a,b]})['differential_pairs'])

    def test_ambiguous_partner_blocks_before_placement(self):
        schematic={'instances':[mos('A'),mos('B'),mos('C')]}
        intent=FLOW.infer_intent(schematic);_,families=FLOW.expand_mos_copies(schematic)
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            FLOW.build_copy_groups(intent,families)

    def test_unequal_copy_counts_never_drop_copies(self):
        _,families=FLOW.expand_mos_copies({'instances':[mos('A',mult=2),mos('B',mult=3)]})
        with self.assertRaisesRegex(ValueError,'equal even'):
            FLOW.build_copy_groups({'differential_pairs':[['A','B']],'mirror_pairs':[],'roles':{}},families)

    def test_four_copy_rows_all_use_axis_abba(self):
        schematic={'instances':[mos('A',mult=4),mos('B',mult=4)]}
        intent=FLOW.infer_intent(schematic);_,families=FLOW.expand_mos_copies(schematic)
        rows=FLOW.build_copy_groups(intent,families)[0]['rows']
        self.assertEqual([[n.split('__')[0] for n in row] for row in rows],[['A','B','B','A']]*2)

    def test_capacitor_multiplier_is_preserved(self):
        cap={'name':'CAP','lib':'pdk','cell':'capacitor','params':{'m':'2','w':'35u','l':'35u'},'terms':{}}
        copies,_=FLOW.expand_mos_copies({'instances':[cap]})
        self.assertEqual([c['name'] for c in copies],['CAP__M0','CAP__M1'])
        self.assertTrue(all(c['pcell_parameters']['m']=='1' for c in copies))

    def test_unresolved_or_fractional_m_never_becomes_a_guessed_copy_count(self):
        for mult in ('2*ratio','unknown','0','-1','1.5'):
            item=mos('A');item['params']['m']=mult
            with self.subTest(mult=mult),self.assertRaisesRegex(ValueError,'multiplicity'):
                FLOW.expand_mos_copies({'instances':[item]})


if __name__ == "__main__":
    unittest.main()
