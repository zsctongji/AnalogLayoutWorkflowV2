import copy
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "refine_placement_intent.py"
SPEC = importlib.util.spec_from_file_location("refine_placement_intent", SCRIPT)
REFINE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(REFINE)


def instance(name, logical, x):
    return {
        "name": name,
        "kind": "nmos",
        "logical_device": logical,
        "group": "MATCH",
        "placement_role": "active",
        "origin": [x, 0.0],
        "orientation": "R0",
        "bbox": [[x, 0.0], [x + 1.0, 1.0]],
        "pcell_master": {"lib": "pdk", "cell": "nmos", "view": "layout"},
        "pcell_parameters": {"m": "1", "w": "1u"},
        "terminals": {"D": name + "_D", "G": name + "_G", "S": "VSS", "B": "VSS"},
    }


def parent_intent():
    return {
        "schema": "analog-layout-align.pcell-placement-intent/v2",
        "coordinate_contract": {"manufacturing_grid": 0.1},
        "instances": [instance("LEFT", "A", 0.0), instance("RIGHT", "B", 2.0)],
        "groups": [{"name": "MATCH", "role": "differential_pair", "logical_devices": ["A", "B"], "instances": ["LEFT", "RIGHT"]}],
        "macro_instances": [{"name": "CORE", "rows": [["LEFT", "RIGHT"]]}],
        "floorplan": {"bbox": [[0.0, 0.0], [3.0, 1.0]], "core_macros": ["CORE"]},
        "validation": {},
    }


class RefinementTests(unittest.TestCase):
    def test_generic_macro_translation_rebuilds_geometry_and_delta(self):
        spec = {
            "schema": "analog-layout-align.refinement-spec/v1",
            "metadata": {"reason": "synthetic regression"},
            "operations": [{"op": "translate", "selector": {"macro": "CORE"}, "dx": 1.0, "dy": 2.0}],
        }
        child, delta = REFINE.refine(parent_intent(), spec)
        self.assertEqual([item["origin"] for item in child["instances"]], [[1.0, 2.0], [3.0, 2.0]])
        self.assertEqual(child["floorplan"]["bbox"], [[1.0, 2.0], [4.0, 3.0]])
        self.assertTrue(child["validation"]["bbox_overlap_free"])
        self.assertEqual(delta["changed_instance_count"], 2)

    def test_parameter_change_requires_geometry_evidence(self):
        spec = {
            "schema": "analog-layout-align.refinement-spec/v1",
            "operations": [{"op": "set_parameters", "selector": {"names": ["LEFT"]}, "parameters": {"w": "2u"}}],
        }
        with self.assertRaisesRegex(ValueError, "evaluated bboxes"):
            REFINE.refine(parent_intent(), spec)

    def test_explicit_place_allows_parameter_change_and_snaps_to_grid(self):
        spec = {
            "schema": "analog-layout-align.refinement-spec/v1",
            "operations": [
                {"op": "set_parameters", "selector": {"names": ["LEFT"]}, "parameters": {"w": "2u"}},
                {"op": "place", "placements": [{"name": "LEFT", "origin": [0.04, 0.04], "orientation": "MY", "bbox": [[-1.04, 0.04], [0.04, 1.04]]}]},
            ],
        }
        child, _ = REFINE.refine(parent_intent(), spec)
        left = next(item for item in child["instances"] if item["name"] == "LEFT")
        self.assertEqual(left["origin"], [0.0, 0.0])
        self.assertEqual(left["bbox"], [[-1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(left["orientation"], "MY")
        self.assertEqual(left["pcell_parameters"]["w"], "2u")

    def test_parent_is_not_mutated(self):
        parent = parent_intent()
        original = copy.deepcopy(parent)
        spec = {"schema": "analog-layout-align.refinement-spec/v1", "operations": [{"op": "translate", "selector": {"kind": "nmos"}, "dx": 1, "dy": 0}]}
        REFINE.refine(parent, spec)
        self.assertEqual(parent, original)

    def shared_diffusion_operation(self):
        return {
            "op": "share_source_diffusion",
            "id": "VSS_SOURCE_PAIR",
            "instances": ["LEFT", "RIGHT"],
            "net": "VSS",
            "axis": "x",
            "placements": [
                {"name": "LEFT", "origin": [0, 0], "orientation": "R0", "bbox": [[0, 0], [1, 1]], "pcell_parameters": {"rightAbut": "source"}, "pcell_parameter_types": {"rightAbut": "string"}},
                {"name": "RIGHT", "origin": [0.5, 0], "orientation": "MY", "bbox": [[0.5, 0], [1.5, 1]], "pcell_parameters": {"leftAbut": "source"}, "pcell_parameter_types": {"leftAbut": "string"}},
            ],
            "evidence": {
                "source": "live PDK pair probe",
                "pdk_fingerprint": "sha256:test",
                "pair_probe_sha256": "sha256:pair",
                "abutment_geometry_verified": True,
                "terminal_continuity_verified": True,
                "no_ds_short_verified": True,
                "source_contact_overlap_verified": True,
                "contact_layer": "cont/drawing",
                "source_contacts_um": {"LEFT": [[[0.6, 0.4], [0.7, 0.5]]],
                                       "RIGHT": [[[0.6, 0.4], [0.7, 0.5]]]},
                "expected_bbox_overlap_um": 0.5,
                "overlap_isolation_verified": True,
            },
        }

    def test_shared_source_diffusion_requires_same_net_and_measured_abutment(self):
        spec = {"schema": "analog-layout-place.refinement-spec/v1", "operations": [self.shared_diffusion_operation()]}
        child, delta = REFINE.refine(parent_intent(), spec)
        self.assertTrue(child["validation"]["shared_diffusion_complete"])
        self.assertEqual(child["validation"]["shared_diffusion_checks"][0]["coordinate_um"], 0.75)
        self.assertEqual(child["validation"]["shared_diffusion_checks"][0]["coincident_source_contact_count"], 1)
        self.assertEqual(child["shared_diffusion_groups"][0]["net"], "VSS")
        self.assertEqual(child["instances"][0]["pcell_parameter_types"]["rightAbut"], "string")
        self.assertEqual(delta["shared_diffusion_groups"][0]["id"], "VSS_SOURCE_PAIR")

    def test_shared_source_diffusion_rejects_different_source_nets(self):
        parent = parent_intent()
        parent["instances"][1]["terminals"]["S"] = "OTHER"
        spec = {"schema": "analog-layout-place.refinement-spec/v1", "operations": [self.shared_diffusion_operation()]}
        with self.assertRaisesRegex(ValueError, "both S terminals"):
            REFINE.refine(parent, spec)

    def test_shared_source_diffusion_rejects_unsourced_claim(self):
        operation = self.shared_diffusion_operation()
        operation["evidence"].pop("no_ds_short_verified")
        spec = {"schema": "analog-layout-place.refinement-spec/v1", "operations": [operation]}
        with self.assertRaisesRegex(ValueError, "no-short evidence"):
            REFINE.refine(parent_intent(), spec)

    def test_shared_source_diffusion_rejects_non_touching_boxes(self):
        operation = self.shared_diffusion_operation()
        operation["placements"][1]["origin"] = [1.1, 0]
        operation["placements"][1]["bbox"] = [[1.1, 0], [2.1, 1]]
        spec = {"schema": "analog-layout-place.refinement-spec/v1", "operations": [operation]}
        with self.assertRaisesRegex(ValueError, "do not touch"):
            REFINE.refine(parent_intent(), spec)

    def test_probed_margin_overlap_is_scoped_to_one_shared_source_pair(self):
        operation = self.shared_diffusion_operation()
        child, _ = REFINE.refine(parent_intent(), {
            'schema': 'analog-layout-place.refinement-spec/v1', 'operations': [operation]})
        self.assertFalse(child['validation']['bbox_overlap_free'])
        self.assertTrue(child['validation']['shared_diffusion_only_bbox_overlaps'])
        self.assertEqual(child['validation']['bbox_overlaps'], [['LEFT', 'RIGHT']])
        operation['evidence'].pop('overlap_isolation_verified')
        with self.assertRaisesRegex(ValueError, 'overlap isolation verification'):
            REFINE.refine(parent_intent(), {
                'schema': 'analog-layout-place.refinement-spec/v1', 'operations': [operation]})

    def test_rejects_split_contact_columns(self):
        operation = self.shared_diffusion_operation()
        operation['evidence']['source_contacts_um']['RIGHT'] = [[[0.8, 0.4], [0.9, 0.5]]]
        with self.assertRaisesRegex(ValueError, 'cont arrays do not coincide'):
            REFINE.refine(parent_intent(), {
                'schema': 'analog-layout-place.refinement-spec/v1', 'operations': [operation]})

    def test_middle_device_can_share_both_source_sides(self):
        parent = parent_intent()
        parent['instances'].append(instance('THIRD', 'C', 4.0))
        parent['groups'][0]['instances'].append('THIRD')
        parent['macro_instances'][0]['rows'][0].append('THIRD')
        first = self.shared_diffusion_operation()
        second = copy.deepcopy(first)
        second['id'] = 'VSS_SOURCE_PAIR_2'
        second['instances'] = ['RIGHT', 'THIRD']
        second['placements'] = [copy.deepcopy(first['placements'][1]),
                                {'name': 'THIRD', 'origin': [1, 0], 'orientation': 'R0',
                                 'bbox': [[1, 0], [2, 1]]}]
        second['evidence']['source_contacts_um'] = {
            'RIGHT': [[[1.1, 0.4], [1.2, 0.5]]],
            'THIRD': [[[1.1, 0.4], [1.2, 0.5]]]}
        child, _ = REFINE.refine(parent, {
            'schema': 'analog-layout-place.refinement-spec/v1', 'operations': [first, second]})
        self.assertEqual(len(child['validation']['shared_diffusion_checks']), 2)
        self.assertEqual(len(child['instances'][1]['shared_diffusion_ids']), 2)

    def test_rejects_two_neighbors_on_same_source_side(self):
        parent = parent_intent()
        parent['instances'].append(instance('THIRD', 'C', 4.0))
        parent['groups'][0]['instances'].append('THIRD')
        parent['macro_instances'][0]['rows'][0].append('THIRD')
        first = self.shared_diffusion_operation()
        second = copy.deepcopy(first)
        second['id'] = 'BAD_BRANCH'
        second['instances'] = ['LEFT', 'THIRD']
        second['placements'][1] = {'name': 'THIRD', 'origin': [0.5, 0],
                                   'orientation': 'MY', 'bbox': [[0.5, 0], [1.5, 1]]}
        second['evidence']['source_contacts_um'] = {
            'LEFT': [[[0.6, 0.4], [0.7, 0.5]]],
            'THIRD': [[[0.6, 0.4], [0.7, 0.5]]]}
        with self.assertRaisesRegex(ValueError, 'already shared'):
            REFINE.refine(parent, {
                'schema': 'analog-layout-place.refinement-spec/v1', 'operations': [first, second]})


if __name__ == "__main__":
    unittest.main()
