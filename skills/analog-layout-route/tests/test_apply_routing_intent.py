import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
route_spec = importlib.util.spec_from_file_location("route_for_apply_test", ROOT / "scripts" / "route_intent.py")
route = importlib.util.module_from_spec(route_spec); route_spec.loader.exec_module(route)
apply_spec = importlib.util.spec_from_file_location("apply_routing_intent", ROOT / "scripts" / "apply_routing_intent.py")
apply = importlib.util.module_from_spec(apply_spec); apply_spec.loader.exec_module(apply)


def fixture():
    profile={"schema":route.PROFILE_SCHEMA,"technology":{"library":"pdk"},"manufacturing_grid_um":.01,
        "layers":[{"name":"m1"},{"name":"poly"},{"name":"cut"}],"layer_purposes":[],"layer_functions":[],
        "constraints":{"rules":[{"definition":"minWidth","layers":["poly"],"value":.2,"parameters":None}]},
        "routing_layers":[{"layer":"m1","minimum_width_rules":[{"value":.2,"parameters":None}],"minimum_spacing_rules":[{"value":.2,"parameters":None}]}],
        "vias":[{"name":"P_M1","layer1":"poly","layer2":"m1","standard_geometry":{"cut_layer":"cut","cut_size_um":[.1,.1],"layer1_enclosure_um":[.1,.1],"layer2_enclosure_um":[.1,.1]}}],
        "coverage":{"basic_routing_ready":True,"unknown_signoff_categories":[]},"boundaries":{"may_drive_automatic_routing":True},"validation":{"structurally_valid":True}}
    profile["fingerprint"]={"value":route.fingerprint(profile)}
    access={"schema":route.ACCESS_SCHEMA,"target":{"lib":"l","cell":"c","view":"layout"},
        "instances":[{"name":"M0","master":{"lib":"pdk","cell":"nmos","view":"layout"},"origin":[0,0],"orientation":"R0","bbox":[[-1,-1],[1,1]],
            "terminals":{"G":{"net":"IN","candidate_centers":[[0,0]],"selected_center":[0,0],"access_layers":["poly"]}}}]}
    spec={"schema":route.SPEC_SCHEMA,"target":access["target"],"routes":[{"id":"r","net":"IN","layer":"m1","points_um":[[0,0],[1,0]],"access":[]}],
        "contact_landings":[{"id":"g","net":"IN","instance":"M0","terminal":"G","via":"P_M1","xy_um":[0,0]}]}
    intent=route.build(profile,access,spec)
    return profile,access,intent


class ApplyTests(unittest.TestCase):
    def test_input_hash_and_coverage_are_required(self):
        profile,access,intent=fixture(); apply.validate_inputs(profile,access,intent)
        access["target"]["cell"]="drift"
        with self.assertRaisesRegex(ValueError,"target|hash"):
            apply.validate_inputs(profile,access,intent)

    def test_apply_is_transactional_and_materializes_contact_landing(self):
        _,access,intent=fixture(); skill=apply.build_apply_skill(intent,access)
        self.assertIn("target-open-in-window",skill)
        self.assertIn("live-placement-drift",skill)
        self.assertIn("dbCreatePath",skill)
        self.assertIn("dbCreateRect",skill)
        self.assertIn("techFindViaDefByName",skill)
        self.assertIn("dbPurge",skill)
        self.assertIn("dbSave",skill)

    def test_readback_checks_routes_vias_landings_and_hashes(self):
        _,_,intent=fixture(); skill=apply.build_verify_skill(intent)
        self.assertIn("g:extension",skill)
        self.assertIn("g:via",skill)
        self.assertIn(intent["sources"]["profile_fingerprint"],skill)
        self.assertIn(route.digest(intent),skill)


if __name__ == "__main__": unittest.main()
