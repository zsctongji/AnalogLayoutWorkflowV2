import importlib.util, unittest
from pathlib import Path
path=Path(__file__).parents[1]/"scripts"/"route_intent.py"; s=importlib.util.spec_from_file_location("route_intent",path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def fx():
    p={"schema":m.PROFILE_SCHEMA,"technology":{"library":"pdk"},"manufacturing_grid_um":.01,"layers":[{"name":"m1"},{"name":"poly"},{"name":"cut"}],"layer_purposes":[],"layer_functions":[],"constraints":{"rules":[{"definition":"minWidth","layers":["poly"],"value":.2,"parameters":None}]},"routing_layers":[{"layer":"m1","minimum_width_rules":[{"value":.2,"parameters":None}],"minimum_spacing_rules":[{"value":.2,"parameters":None}]}],"vias":[{"name":"P_M1","layer1":"poly","layer2":"m1","standard_geometry":{"cut_layer":"cut","cut_size_um":[.1,.1],"layer1_enclosure_um":[.1,.1],"layer2_enclosure_um":[.1,.1]}}],"coverage":{"basic_routing_ready":True,"unknown_signoff_categories":[]},"boundaries":{"may_drive_automatic_routing":True},"validation":{"structurally_valid":True}}; p["fingerprint"]={"value":m.fingerprint(p)}
    a={"schema":m.ACCESS_SCHEMA,"target":{"lib":"l","cell":"c","view":"layout"},"instances":[{"name":"M0","terminals":{"G":{"net":"IN","candidate_centers":[[0,0]],"selected_center":[0,0],"access_layers":["poly"]}}}]}
    r={"schema":m.SPEC_SCHEMA,"target":a["target"],"routes":[{"id":"r","net":"IN","layer":"m1","width_um":None,"points_um":[[0,0],[1,0]],"access":[{"instance":"M0","terminal":"G"}]}],"vias":[{"id":"v","net":"IN","via":"P_M1","xy_um":[0,0]}]}; return p,a,r
class Test(unittest.TestCase):
    def test_valid(self): p,a,s=fx(); o=m.build(p,a,s); self.assertTrue(o["validation"]["valid"],o["validation"]["errors"]); self.assertEqual(o["routes"][0]["width_um"],.2)
    def test_net(self): p,a,s=fx(); s["routes"][0]["net"]="BAD"; self.assertFalse(m.build(p,a,s)["validation"]["valid"])
    def test_spacing(self): p,a,s=fx(); s["routes"].append({"id":"x","net":"X","layer":"m1","width_um":.2,"points_um":[[0,.3],[1,.3]],"access":[]}); self.assertTrue(any("cross-net" in x for x in m.build(p,a,s)["validation"]["errors"]))
    def test_drift(self): p,a,s=fx(); o=m.build(p,a,s); p["manufacturing_grid_um"]=.02; self.assertTrue(m.validate(p,o))
    def test_multi_island_terminal_must_be_fully_covered(self):
        p,a,s=fx(); term=a["instances"][0]["terminals"]["G"]
        term["pin_islands"]=[
            {"id":"M0:G:p0","candidate_centers":[[0,0]],"selected_center":[0,0],"access_layers":["poly"]},
            {"id":"M0:G:p1","candidate_centers":[[2,0]],"selected_center":[2,0],"access_layers":["poly"]},
        ]
        s["routes"][0]["access"][0]["pin_island_id"]="M0:G:p0"
        out=m.build(p,a,s)
        self.assertTrue(any("uncovered physical pin island" in item for item in out["validation"]["errors"]))
    def test_contact_landing_covers_poly_island_and_enclosure(self):
        p,a,s=fx(); s["routes"][0]["access"]=[]; s["vias"]=[]
        s["contact_landings"]=[{"id":"g0","net":"IN","instance":"M0","terminal":"G","via":"P_M1","xy_um":[0,0]}]
        out=m.build(p,a,s)
        self.assertTrue(out["validation"]["valid"],out["validation"]["errors"])
        self.assertEqual(out["physical_access_coverage"]["covered_count"],1)
        self.assertEqual(out["contact_landings"][0]["extension_bbox_um"],[[-.15,-.15],[.15,.15]])
    def test_required_net_cannot_be_silently_omitted(self):
        p,a,s=fx(); s["required_nets"]=["IN","MISSING"]
        out=m.build(p,a,s)
        self.assertIn("required net MISSING has no route",out["validation"]["errors"])
    def test_required_net_must_be_one_physical_component(self):
        p,a,s=fx(); s["required_nets"]=["IN"]
        s["routes"].append({"id":"island","net":"IN","layer":"m1","width_um":.2,"points_um":[[3,0],[4,0]],"access":[]})
        out=m.build(p,a,s)
        self.assertTrue(any("disconnected physical routing" in item for item in out["validation"]["errors"]))
        self.assertEqual(out["net_metrics"]["IN"]["connected_component_count"],2)
    def test_offline_obstacles_require_live_reconciliation_before_handoff(self):
        p,a,s=fx(); s["planning_evidence"]={"obstacle_coverage":{"live_snapshot":False},"offline_obstacle_review":None}
        out=m.build(p,a,s)
        self.assertTrue(any("offline obstacle snapshot" in item for item in out["validation"]["warnings"]))
        self.assertTrue(any("live-target reconciliation" in item for item in m.validate(p,out)))
        s["planning_evidence"]["offline_obstacle_review"]={"reviewed_live_target":True,"basis":"live polygon review"}
        out=m.build(p,a,s)
        self.assertFalse(any("live-target reconciliation" in item for item in m.validate(p,out)))
    def test_missing_body_terminal_requires_verified_waiver(self):
        p,a,s=fx(); a["instances"][0].update({"intent_terminals":{"B":"IN"},"missing_master_terminals":["B"]}); s["required_nets"]=["IN"]
        out=m.build(p,a,s)
        self.assertTrue(any("unresolved physical terminal M0/B" in item for item in out["validation"]["errors"]))
        s["terminal_waivers"]=[{"instance":"M0","terminal":"B","reason":"PCell internal tie","evidence":"verified master connectivity"}]
        out=m.build(p,a,s)
        self.assertTrue(out["terminal_obligations"]["complete"],out["validation"]["errors"])
    def test_directness_limit_blocks_large_excursion(self):
        p,a,s=fx(); s["routes"][0]["points_um"]=[[0,0],[0,5],[1,5],[1,0]]
        s["net_constraints"]=[{"net":"IN","max_detour_ratio":2.0,"max_bbox_excursion_um":1.0}]
        out=m.build(p,a,s)
        self.assertTrue(any("detour ratio" in x for x in out["validation"]["errors"]))
        self.assertTrue(any("bbox excursion" in x for x in out["validation"]["errors"]))
    def test_matching_checks_per_layer_and_bends_not_only_total_length(self):
        p,a,s=fx(); p["layers"].append({"name":"m2"}); p["routing_layers"].append({"layer":"m2","minimum_width_rules":[{"value":.2,"parameters":None}],"minimum_spacing_rules":[{"value":.2,"parameters":None}]}); p["fingerprint"]={"value":m.fingerprint(p)}
        a["instances"].append({"name":"M1","terminals":{"G":{"net":"REF","candidate_centers":[[0,2]],"selected_center":[0,2],"access_layers":["m2"]}}})
        s["routes"][0]["points_um"]=[[0,0],[0,1],[1,1]]; s["routes"][0]["access"]=[]; s["vias"]=[]
        s["routes"].append({"id":"r2","net":"REF","layer":"m2","width_um":.2,"points_um":[[0,2],[2,2]],"access":[{"instance":"M1","terminal":"G"}]})
        s["matching"]=[{"first_net":"IN","second_net":"REF","max_length_delta_um":0,"max_via_delta":0}]
        out=m.build(p,a,s)
        self.assertFalse(out["matching"][0]["pass"])
        self.assertGreater(out["matching"][0]["max_per_layer_length_delta_um_observed"],0)
    def test_matching_cannot_reference_two_absent_nets(self):
        p,a,s=fx(); s["matching"]=[{"first_net":"P","second_net":"N","max_length_delta_um":0,"max_via_delta":0}]
        out=m.build(p,a,s)
        self.assertIn("matching P/N: both nets must have route geometry",out["validation"]["errors"])
if __name__=="__main__": unittest.main()
