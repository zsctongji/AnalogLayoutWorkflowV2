import importlib.util
import unittest
import copy
import itertools
import random
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("route_planner", HERE / "scripts" / "route_planner.py")
PLANNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PLANNER)


def fixtures():
    profile = {
        "schema": PLANNER.ROUTE.PROFILE_SCHEMA,
        "technology": {"library": "pdk"},
        "manufacturing_grid_um": 0.1,
        "layers": [{"name": "m1"}],
        "layer_purposes": [{"layer": "m1", "purpose": "drawing"}],
        "layer_functions": [],
        "constraints": {"rules": []},
        "routing_layers": [{
            "layer": "m1",
            "minimum_width_rules": [{"value": 0.2, "parameters": None}],
            "minimum_spacing_rules": [{"value": 0.2, "parameters": None}],
        }],
        "vias": [],
        "coverage": {"basic_routing_ready": True, "unknown_signoff_categories": []},
        "boundaries": {"may_drive_automatic_routing": True},
        "validation": {"structurally_valid": True},
    }
    profile["fingerprint"] = {"value": PLANNER.ROUTE.fingerprint(profile)}
    access = {
        "schema": PLANNER.ROUTE.ACCESS_SCHEMA,
        "target": {"lib": "l", "cell": "c", "view": "layout"},
        "instances": [
            {"name": "A", "terminals": {"G": {"net": "N", "pin_islands": [{"id": "A:G:p0", "candidate_centers": [[0, 0]], "selected_center": [0, 0], "access_layers": ["m1"]}]}}},
            {"name": "B", "terminals": {"G": {"net": "N", "pin_islands": [{"id": "B:G:p0", "candidate_centers": [[10, 0]], "selected_center": [10, 0], "access_layers": ["m1"]}]}}},
        ],
    }
    obstacles = {
        "schema": PLANNER.OBSTACLE_SCHEMA,
        "target": access["target"],
        "sources": {"profile_fingerprint": profile["fingerprint"]["value"], "terminal_access_sha256": PLANNER.ROUTE.digest(access)},
        "bounds_um": [[-1, -3], [11, 3]],
        "obstacles": [{"id": "block", "layer": "m1", "bbox_um": [[4, -1], [6, 1]], "hard": True, "net": None}],
    }
    request = {
        "schema": PLANNER.REQUEST_SCHEMA,
        "target": access["target"],
        "sources": {
            "profile_fingerprint": profile["fingerprint"]["value"],
            "terminal_access_sha256": PLANNER.ROUTE.digest(access),
            "obstacles_sha256": PLANNER.ROUTE.digest(obstacles),
        },
        "nets": [{
            "net": "N", "net_class": "ordinary", "layer": "m1", "width_um": 0.2,
            "terminals": [
                {"instance": "A", "terminal": "G", "pin_island_id": "A:G:p0"},
                {"instance": "B", "terminal": "G", "pin_island_id": "B:G:p0"},
            ],
        }],
    }
    return profile, access, obstacles, request


def refresh(profile, access, obstacles, request):
    profile["fingerprint"] = {"value": PLANNER.ROUTE.fingerprint(profile)}
    obstacles["sources"] = {"profile_fingerprint": profile["fingerprint"]["value"],
                            "terminal_access_sha256": PLANNER.ROUTE.digest(access)}
    request["sources"] = {**obstacles["sources"], "obstacles_sha256": PLANNER.ROUTE.digest(obstacles)}


def pair_fixture(strategy="mirror_guided"):
    profile, access, obstacles, request = fixtures()
    access["instances"] = []
    requests = []
    for net, xs in (("N", (-5, -2)), ("P", (5, 2))):
        terminals = []
        for i, x in enumerate(xs):
            name = net + str(i)
            island = name + ":G:p0"
            access["instances"].append({"name": name, "terminals": {"G": {"net": net, "pin_islands": [{
                "id": island, "candidate_centers": [[x, 0]], "selected_center": [x, 0], "access_layers": ["m1"]}]}}})
            terminals.append({"instance": name, "terminal": "G", "pin_island_id": island})
        requests.append({"net":net, "net_class":"differential", "layer":"m1",
                         "max_bbox_excursion_um":5, "terminals":terminals})
    obstacles["bounds_um"] = [[-7,-4],[7,4]]
    obstacles["obstacles"] = [{"id":"asymmetric", "layer":"m1", "hard":True,
                              "bbox_um":[[3,-0.5],[4,0.5]]}]
    request["nets"] = requests
    request["reserve_matched_pairs_first"] = True
    request["matching"] = [{"first_net":"N","second_net":"P","strategy":strategy,"axis_um":0,
        "pin_pairs":[["N0:G:p0","P0:G:p0"],["N1:G:p0","P1:G:p0"]],
        "guide_weight":2, "max_length_delta_um":2, "max_via_delta":0,
        "max_per_layer_length_delta_um":2, "max_bend_delta":4}]
    refresh(profile, access, obstacles, request)
    return profile, access, obstacles, request


class PlannerTests(unittest.TestCase):
    def test_rotation_and_partial_guidance(self):
        for strategy in ("rotate180_guided", "partial_mirror_guided"):
            args = pair_fixture(strategy)
            pair = args[3]["matching"][0]
            if strategy == "rotate180_guided":
                pair.update(axis_x_um=0,axis_y_um=0)
                pair.pop("axis_um")
            else:
                pair["pin_pairs"] = pair["pin_pairs"][:1]
            result = PLANNER.plan(*args)
            self.assertEqual(result["status"],"PLANNED",result["failures"])
            self.assertEqual(result["candidates"][0]["metrics"]["P"]["coupled_strategy"],strategy)

    def test_zero_weight_cannot_disable_pair_guidance(self):
        args = pair_fixture()
        args[3]["matching"][0]["guide_weight"] = 0
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["failures"][0]["code"],"INVALID_GUIDANCE")

    def test_dynamic_protection_changes_later_net_route(self):
        args = pair_fixture()
        profile,access,obstacles,request = args
        request.pop("matching"); request.pop("reserve_matched_pairs_first")
        obstacles["obstacles"] = []
        for net in request["nets"]: net["net_class"] = "ordinary"
        coords = {"N0":[-5,0],"N1":[5,0],"P0":[-5,1],"P1":[5,1]}
        for instance in access["instances"]:
            island = instance["terminals"]["G"]["pin_islands"][0]
            island["candidate_centers"] = [coords[instance["name"]]]
            island["selected_center"] = coords[instance["name"]]
        refresh(*args)
        plain = PLANNER.plan(*args)
        request["nets"][0]["protection"] = {"margin_um":2,"cost_per_um":100}
        protected = PLANNER.plan(*args)
        self.assertEqual(plain["status"],"PLANNED",plain["failures"])
        self.assertEqual(protected["status"],"PLANNED",protected["failures"])
        self.assertGreater(protected["candidates"][0]["metrics"]["P"]["length_um"],
                           plain["candidates"][0]["metrics"]["P"]["length_um"])

    def test_current_evidence_is_propagated_with_branch_currents(self):
        args = fixtures()
        args[3]["nets"][0]["electrical"] = {"source":"fixture schematic DC operating point",
            "root_pin_island_id":"A:G:p0","sink_currents_a":{"B:G:p0":0.002},"epsilon_a":1e-8}
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        metric = result["candidates"][0]["metrics"]["N"]
        self.assertEqual(metric["electrical_data_status"],"provided")
        self.assertEqual(metric["topology_edges"][0]["current_a"],0.002)

    def test_normalized_width_spacing_is_enforced_and_conditional_rules_unknown(self):
        args = fixtures()
        args[0]["routing_layers"][0]["width_spacing_rules"] = [
            {"min_width_um":0.2,"spacing_um":0.7,"source":"test-deck spacing table"}]
        refresh(*args)
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        points = result["candidates"][0]["route_spec"]["routes"][0]["points_um"]
        self.assertTrue(any(abs(p[1]) >= 1.8 for p in points))
        self.assertEqual(result["candidates"][0]["rule_coverage"]["end_of_line"],"unknown")

    def test_guidance_integral_does_not_change_after_compaction(self):
        guides = [{"layer":"m1","points_um":[[0,0],[0,2]]},
                  {"layer":"m1","points_um":[[10,0],[10,2]]}]
        direct = PLANNER.SEARCH.guide_integral((0,1,"m1"),(10,1,"m1"),guides)
        split = sum(PLANNER.SEARCH.guide_integral((x,1,"m1"),(x+1,1,"m1"),guides) for x in range(10))
        self.assertAlmostEqual(direct,25)
        self.assertAlmostEqual(direct,split)

    def test_invalid_via_and_nonfinite_cost_return_structured_failure(self):
        args = fixtures()
        args[0]["vias"] = [{"name":"bad","layer1":"m1","layer2":"m2","standard_geometry":{"cut_size_um":[1,1]}}]
        refresh(*args)
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["failures"][0]["code"],"INVALID_VIA")
        args = fixtures()
        args[3]["nets"][0]["bend_cost_um"] = float("nan")
        result = PLANNER.plan(*args)
        self.assertEqual(result["failures"][0]["code"],"INVALID_COST")

    def test_bend_cost_selects_fewer_turns(self):
        # Two equal-length corridors, one crossing multiple narrow teeth.
        rng = random.Random(8)
        found = False
        for _ in range(80):
            rects = [(x-0.4,y-0.4,x+0.4,y+0.4)
                     for x,y in rng.sample(list(itertools.product(range(1,6),range(1,6))),8)]
            args = ((0,0,"m1"),{(6,6,"m1")},{"m1":rects},[[0,0],[6,6]],{"m1":[]},set(),0.1,2,{},0)
            a = PLANNER.astar_layered(*args,bend_cost_um=0)
            b = PLANNER.astar_layered(*args,bend_cost_um=10)
            def bends(path):
                return sum(max(0,len(points)-2) for _,points in PLANNER.split_layered_path(path)[0])
            if a and b and bends(b) < bends(a):
                found = True
                self.assertLessEqual(bends(b), bends(a))
                break
        self.assertTrue(found, "fixture must demonstrate an observable bend-cost tradeoff")

    def test_via_cost_changes_layer_selection(self):
        args = ((0,0,"m1"), {(2,2,"m1")}, {"m1":[],"m2":[]}, [[0,0],[2,2]],
                {"m1":[("m2","V")],"m2":[("m1","V")]},set(),1)
        low = PLANNER.astar_layered(*args,0.1,{"m1":"vertical","m2":"horizontal"},1)
        high = PLANNER.astar_layered(*args,20,{"m1":"vertical","m2":"horizontal"},1)
        self.assertIn("m2",{n[2] for n in low})
        self.assertEqual({n[2] for n in high},{"m1"})

    def test_terminal_permutations_preserve_topology_and_connectivity(self):
        profile, access, obstacles, request = fixtures()
        access["instances"].append({"name":"C","terminals":{"G":{"net":"N","pin_islands":[{
            "id":"C:G:p0","candidate_centers":[[5,2]],"access_layers":["m1"]}]}}})
        request["nets"][0]["terminals"].append({"instance":"C","terminal":"G","pin_island_id":"C:G:p0"})
        refresh(profile,access,obstacles,request)
        baseline = None
        for order in itertools.permutations(request["nets"][0]["terminals"]):
            request["nets"][0]["terminals"] = list(order)
            result = PLANNER.plan(profile,access,obstacles,request)
            self.assertEqual(result["status"],"PLANNED",result["failures"])
            spec = result["candidates"][0]["route_spec"]
            if baseline is None: baseline = spec
            self.assertEqual(spec,baseline)
            self.assertTrue(PLANNER.ROUTE.build(profile,access,spec)["physical_connectivity"]["complete"])

    def test_blocked_first_access_uses_alternative(self):
        args = list(fixtures())
        profile,access,obstacles,request = args
        island = access["instances"][0]["terminals"]["G"]["pin_islands"][0]
        island["candidate_centers"] = [[0,0],[0,2]]
        obstacles["obstacles"].append({"id":"pinblock","layer":"m1","hard":True,"bbox_um":[[-0.2,-0.2],[0.2,0.2]]})
        refresh(*args)
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        self.assertEqual(result["candidates"][0]["metrics"]["N"]["selected_access"][0]["pin_xy_um"],[0,2])

    def test_nonfirst_access_has_better_total_path(self):
        args = fixtures()
        profile,access,obstacles,request = args
        obstacles["obstacles"] = []
        island = access["instances"][0]["terminals"]["G"]["pin_islands"][0]
        island["candidate_centers"] = [[0,0],[3,0]]
        refresh(*args)
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        self.assertEqual(result["candidates"][0]["metrics"]["N"]["selected_access"][0]["pin_xy_um"],[3,0])
        self.assertAlmostEqual(result["candidates"][0]["metrics"]["N"]["length_um"],7)

    def test_soft_region_is_avoided_but_remains_crossable(self):
        args = ((0,0,"m1"),{(10,0,"m1")},{"m1":[]},[[0,-2],[10,2]],{"m1":[]},set(),0.1,2,{},0)
        region = {"layer":"m1","bbox_um":[[4,-1],[6,1]],"cost_per_um":100}
        avoided = PLANNER.astar_layered(*args,cost_regions=[region])
        self.assertTrue(any(abs(n[1]) >= 1 for n in avoided))
        region["bbox_um"] = [[4,-10],[6,10]]
        crossed = PLANNER.astar_layered(*args,cost_regions=[region])
        self.assertIsNotNone(crossed)
        self.assertTrue(any(PLANNER.SEARCH.overlap_length(a,b,region["bbox_um"]) > 0 for a,b in zip(crossed,crossed[1:])))

    def test_current_weighted_tree_shortens_high_current_root_path(self):
        nodes = [(0,0,"m1"),(1,5,"m1"),(2,5,"m1")]
        def search(a, goals):
            b = min(goals, key=lambda node: (abs(a[0]-node[0])+abs(a[1]-node[1]),node))
            return [a,(b[0],a[1],a[2]),b]
        def cost(path):
            return {"wire_length_um":sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(path,path[1:]))}
        ordinary = PLANNER.SEARCH.synthesize_topology(nodes,search,cost,share_tree=False,frontier_limit=1)
        weighted = PLANNER.SEARCH.synthesize_topology(nodes,search,cost,(0,[0,0.001,1],1e-6))
        def root_length(tree, node):
            links = {}
            for a,b,path in tree:
                links.setdefault(a,[]).append((b,sum(cost(path).values())))
                links.setdefault(b,[]).append((a,sum(cost(path).values())))
            pending = [(0,None,0)]
            for n,prev,d in pending:
                if n == node: return d
                pending.extend((j,n,d+w) for j,w in links[n] if j != prev)
        # Select a geometry where the MST detours from root for the high-current sink.
        nodes[1] = (2,5,"m1")
        nodes[2] = (0,6,"m1")
        ordinary = PLANNER.SEARCH.synthesize_topology(nodes,search,cost,share_tree=False,frontier_limit=1)
        weighted = PLANNER.SEARCH.synthesize_topology(nodes,search,cost,(0,[0,1,0.001],1e-6))
        self.assertLess(root_length(weighted,1),root_length(ordinary,1))

    def test_missing_currents_report_unavailable_and_cost_sums(self):
        result = PLANNER.plan(*fixtures())
        candidate = result["candidates"][0]
        metric = candidate["metrics"]["N"]
        self.assertEqual(metric["electrical_data_status"],"unavailable")
        self.assertTrue(all("current_a" not in edge for edge in metric["topology_edges"]))
        self.assertAlmostEqual(candidate["cost"],sum(candidate["cost_breakdown"].values()))

    def test_mirror_guidance_routes_asymmetric_obstacle_as_checked_pair(self):
        args = pair_fixture()
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        candidate = result["candidates"][0]
        intent = PLANNER.ROUTE.build(args[0],args[1],candidate["route_spec"])
        self.assertTrue(intent["matching"][0]["pass"])
        self.assertTrue(intent["physical_connectivity"]["complete"])
        self.assertTrue(candidate["metrics"]["P"]["guidance"])
        self.assertGreater(candidate["metrics"]["P"]["length_um"],candidate["metrics"]["N"]["length_um"])

    def test_pair_failure_never_publishes_single_branch(self):
        args = pair_fixture()
        args[3]["matching"][0]["max_length_delta_um"] = 0
        result = PLANNER.plan(*args)
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["candidates"],[])
        self.assertEqual(result["diagnostic_route_spec"]["routes"],[])
        self.assertEqual(result["failures"][0]["code"],"SYMMETRY_UNSATISFIABLE")

    def test_invalid_access_unknown_layer_and_missing_current_evidence(self):
        for change in ("access","layer","current"):
            args = fixtures()
            net = args[3]["nets"][0]
            if change == "access": net["terminals"][0]["xy_um"] = [99,99]
            if change == "layer": net["layer"] = "invalid"
            if change == "current": net["electrical"] = {"sink_currents_a":{"B:G:p0":1}}
            result = PLANNER.plan(*args)
            self.assertEqual(result["status"],"BLOCKED")
            self.assertTrue(result["failures"][0]["code"])

    def test_via_enclosure_collision_even_when_origin_is_clear(self):
        via = {"name":"V","lower":"m1","upper":"m2","geometry":{
            "cut_layer":"v","cut_size_um":[0.2,0.2],"rows":1,"columns":1,
            "layer1_enclosure_um":[0.5,0.5],"layer2_enclosure_um":[0.5,0.5]}}
        obstacle = {"layer":"m2","bbox_um":[[0.4,-0.1],[0.8,0.1]],"hard":True}
        self.assertFalse(PLANNER.BACKEND_IMPL.via_clear(via,0,0,[obstacle],"N",{"m1":0.1,"m2":0.1},[[-2,-2],[2,2]]))
        self.assertTrue(PLANNER.BACKEND_IMPL.via_clear(via,-1,0,[obstacle],"N",{"m1":0.1,"m2":0.1},[[-2,-2],[2,2]]))

    def test_layer_direction_is_a_soft_cost_not_a_hard_rule(self):
        path = PLANNER.astar_layered(
            (0, 0, "m1"), {(2, 2, "m1")}, {"m1": [], "m2": []},
            [[0, 0], [2, 2]], {"m1": [("m2", "V")], "m2": [("m1", "V")]},
            set(), 1.0, 0.1, {"m1": "vertical", "m2": "horizontal"}, 1.0,
        )
        self.assertIsNotNone(path)
        self.assertIn("m2", {node[2] for node in path})
    def test_routes_around_expanded_obstacle_and_builds_existing_contract(self):
        profile, access, obstacles, request = fixtures()
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "PLANNED")
        spec = result["candidates"][0]["route_spec"]
        points = spec["routes"][0]["points_um"]
        self.assertGreater(len(points), 2)
        intent = PLANNER.ROUTE.build(profile, access, spec)
        self.assertEqual(intent["decision"]["status"], "READY_FOR_REVIEW")

    def test_is_deterministic(self):
        args = fixtures()
        first = PLANNER.plan(*args)
        second = PLANNER.plan(*args)
        self.assertEqual(first["candidates"], second["candidates"])

    def test_explicit_target_length_adds_obstacle_aware_trombone(self):
        profile, access, obstacles, request = fixtures()
        baseline = PLANNER.plan(profile, access, obstacles, request)
        base_length = baseline["candidates"][0]["metrics"]["N"]["length_um"]
        request["nets"][0]["target_length_um"] = base_length + 2.0
        tuned = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(tuned["status"], "PLANNED", tuned["failures"])
        self.assertAlmostEqual(tuned["candidates"][0]["metrics"]["N"]["length_um"], base_length + 2.0)

    def test_rejects_stale_obstacle_hash(self):
        profile, access, obstacles, request = fixtures()
        request["sources"]["obstacles_sha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "obstacle hash drift"):
            PLANNER.plan(profile, access, obstacles, request)

    def test_authoritative_builder_blocks_wrong_net_mapping(self):
        profile, access, obstacles, request = fixtures()
        request["nets"][0]["net"] = "WRONG"
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("authoritative route-intent preflight", result["failures"][-1]["reason"])

    def test_reports_no_route(self):
        profile, access, obstacles, request = fixtures()
        obstacles["obstacles"][0]["bbox_um"] = [[4, -10], [6, 10]]
        request["sources"]["obstacles_sha256"] = PLANNER.ROUTE.digest(obstacles)
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["failures"][0]["reason"], "no legal layered rectilinear path")

    def test_power_requires_explicit_width_basis(self):
        profile, access, obstacles, request = fixtures()
        request["nets"][0]["net_class"] = "power"
        request["nets"][0].pop("width_um")
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("explicit width", result["failures"][0]["reason"])

    def test_candidate_declares_every_requested_net_required(self):
        profile, access, obstacles, request = fixtures()
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["candidates"][0]["route_spec"]["required_nets"], ["N"])

    def test_candidate_preserves_svg_symmetry_groups(self):
        profile, access, obstacles, request = fixtures()
        request["symmetry_groups"] = [{"id": "n_self", "mode": "self", "net": "N",
            "transform": "mirror_x", "axis_um": 5.0, "tolerance_um": 0.01}]
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["candidates"][0]["route_spec"]["symmetry_groups"], request["symmetry_groups"])

    def test_unclassified_net_is_blocked(self):
        profile, access, obstacles, request = fixtures()
        request["nets"][0].pop("net_class")
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("net_class is required", result["failures"][0]["reason"])

    def test_matching_without_coupled_strategy_is_blocked(self):
        profile, access, obstacles, request = fixtures()
        request["nets"][0]["net_class"] = "differential"
        request["nets"].append({**request["nets"][0], "net": "P"})
        request["matching"] = [{"first_net":"N","second_net":"P","max_length_delta_um":0.1,"max_via_delta":0}]
        request["reserve_matched_pairs_first"] = True
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("supported coupled strategy", result["failures"][0]["reason"])

    def test_single_sided_length_tuning_on_matched_net_is_blocked(self):
        profile, access, obstacles, request = fixtures()
        request["nets"][0]["net_class"] = "differential"
        request["nets"][0]["target_length_um"] = 20.0
        request["nets"].append({**request["nets"][0], "net": "P", "target_length_um": None})
        request["matching"] = [{
            "first_net":"N","second_net":"P","max_length_delta_um":0.1,"max_via_delta":0,
            "strategy":"common_centroid_columns","contact_layer":"m1","bus_layer":"m1",
            "contact_escape_um":0.2,"landing_stub_um":0.2,"bus_clearance_um":0.4,
        }]
        request["reserve_matched_pairs_first"] = True
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("target_length_um is forbidden" in item["reason"] for item in result["failures"]))

    def test_multilayer_via_and_poly_contact(self):
        profile, access, obstacles, request = fixtures()
        profile["layers"].extend([{"name": "m2"}, {"name": "poly1"}])
        profile["layer_purposes"].extend([
            {"layer": "m2", "purpose": "drawing"},
            {"layer": "poly1", "purpose": "drawing"},
        ])
        profile["constraints"]["rules"].append({
            "definition": "minWidth", "layers": ["poly1"], "parameters": None, "value": 0.2,
        })
        profile["routing_layers"].append({
            "layer": "m2",
            "minimum_width_rules": [{"value": 0.2, "parameters": None}],
            "minimum_spacing_rules": [{"value": 0.2, "parameters": None}],
        })
        geometry = {
            "cut_layer": "v", "cut_size_um": [0.2, 0.2], "rows": 1, "columns": 1,
            "cut_spacing_um": [0.2, 0.2], "layer1_enclosure_um": [0.1, 0.1],
            "layer2_enclosure_um": [0.1, 0.1],
        }
        profile["vias"] = [
            {"name": "PO_M1", "layer1": "poly1", "layer2": "m1", "standard_geometry": geometry},
            {"name": "M1_M2", "layer1": "m1", "layer2": "m2", "standard_geometry": geometry},
        ]
        access["instances"][0]["terminals"]["G"]["pin_islands"][0]["access_layers"] = ["poly1"]
        access["instances"][1]["terminals"]["G"]["pin_islands"][0]["access_layers"] = ["m2"]
        obstacles["obstacles"][0]["bbox_um"] = [[4, -3], [6, 3]]
        request["nets"][0].pop("layer")
        request["nets"][0].pop("width_um")
        request["nets"][0]["layers"] = ["m1", "m2"]
        profile["fingerprint"] = {"value": PLANNER.ROUTE.fingerprint(profile)}
        obstacles["sources"] = {
            "profile_fingerprint": profile["fingerprint"]["value"],
            "terminal_access_sha256": PLANNER.ROUTE.digest(access),
        }
        request["sources"] = {
            "profile_fingerprint": profile["fingerprint"]["value"],
            "terminal_access_sha256": PLANNER.ROUTE.digest(access),
            "obstacles_sha256": PLANNER.ROUTE.digest(obstacles),
        }
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "PLANNED", result["failures"])
        spec = result["candidates"][0]["route_spec"]
        self.assertEqual(len(spec["contact_landings"]), 1)
        self.assertGreaterEqual(len(spec["vias"]), 1)
        self.assertEqual(PLANNER.ROUTE.build(profile, access, spec)["decision"]["status"], "READY_FOR_REVIEW")

    def test_contact_escape_reserves_full_via_landing_envelope(self):
        terminal = {
            "pin_island_id": "A:G:p0", "pin_xy_um": [0.0, 0.0], "xy_um": [0.0, 0.0],
            "route_layer": "m1", "contact": {"source_layer": "poly1", "via": "PO_M1"},
        }
        obstacles = [{"layer": "m1", "bbox_um": [[-0.1, -0.1], [0.1, 0.1]], "net": "OTHER", "hard": True}]
        PLANNER.legalize_contact_escape(
            terminal, obstacles, "N", width=0.2, spacing=0.2,
            bounds=[[-2.0, -2.0], [2.0, 2.0]], grid=0.1, landing_half_um=(0.5, 0.5),
        )
        self.assertEqual(terminal["xy_um"], [-0.8, 0.0])

    def test_contact_escape_clears_overlapping_obstacle_union(self):
        terminal = {
            "pin_island_id": "A:G:p0", "pin_xy_um": [0.0, 0.0], "xy_um": [0.0, 0.0],
            "route_layer": "m1", "contact": {"source_layer": "poly1", "via": "PO_M1"},
        }
        obstacles = [
            {"layer": "m1", "bbox_um": [[-1.0, -0.1], [0.2, 0.1]], "net": "X", "hard": True},
            {"layer": "m1", "bbox_um": [[-0.2, -0.1], [1.0, 0.1]], "net": "Y", "hard": True},
        ]
        PLANNER.legalize_contact_escape(
            terminal, obstacles, "N", width=0.2, spacing=0.2,
            bounds=[[-3.0, -3.0], [3.0, 3.0]], grid=0.1, landing_half_um=(0.1, 0.1),
        )
        self.assertEqual(terminal["xy_um"], [0.0, -0.4])

    def test_single_access_groups_synthesize_topology_once(self):
        groups = [[{"xy_um": [float(x), 0.0], "route_layer": "m1", "pin_island_id": f"p{x}",
                    "escape_clearance_um": 1.0}]
                  for x in (0, 2, 4, 6)]
        calls = {"search": 0}
        def search(start, goals):
            calls["search"] += 1
            goal = min(goals, key=lambda g: (abs(start[0]-g[0])+abs(start[1]-g[1]), g))
            return [start, goal]
        def evaluate(path):
            return {"wire_length_um": sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a, b in zip(path, path[1:]))}
        selected, topology, electrical = PLANNER.BACKEND_IMPL.choose_access_topology(
            PLANNER, groups, {"net_class": "ordinary", "access_candidate_limit": 4,
                              "access_beam_width": 16, "topology_frontier_limit": 1}, search, evaluate,
        )
        self.assertEqual(len(selected), 4)
        self.assertEqual(len(topology), 3)
        self.assertIsNone(electrical)
        self.assertLessEqual(calls["search"], 6)

    def test_common_centroid_pair_supports_four_by_two_grids_and_matches_geometry(self):
        profile, _, _, _ = fixtures()
        profile["layers"].extend([{"name": "m2"}, {"name": "poly1"}])
        profile["layer_purposes"].extend([
            {"layer": "m2", "purpose": "drawing"}, {"layer": "poly1", "purpose": "drawing"},
        ])
        profile["constraints"]["rules"].append({
            "definition": "minWidth", "layers": ["poly1"], "parameters": None, "value": 0.2,
        })
        profile["routing_layers"].append({
            "layer": "m2", "minimum_width_rules": [{"value": 0.2, "parameters": None}],
            "minimum_spacing_rules": [{"value": 0.2, "parameters": None}],
        })
        geometry = {
            "cut_layer": "v", "cut_size_um": [0.2, 0.2], "rows": 1, "columns": 1,
            "cut_spacing_um": [0.2, 0.2], "layer1_enclosure_um": [0.1, 0.1], "layer2_enclosure_um": [0.1, 0.1],
        }
        profile["vias"] = [
            {"name": "PO_M1", "layer1": "poly1", "layer2": "m1", "standard_geometry": geometry},
            {"name": "M1_M2", "layer1": "m1", "layer2": "m2", "standard_geometry": geometry},
        ]
        profile["fingerprint"] = {"value": PLANNER.ROUTE.fingerprint(profile)}
        positions = {
            "P": [(x, y) for x in (4, 5, 7, 8) for y in (0, 4)],
            "N": [(x, y) for x in (1, 2, 10, 11) for y in (0, 4)],
        }
        instances, requests = [], []
        for net, points in positions.items():
            terminals = []
            for index, point in enumerate(points):
                name, island = f"{net}{index}", f"{net}{index}:G:p0"
                instances.append({"name": name, "terminals": {"G": {"net": net, "pin_islands": [{
                    "id": island, "candidate_centers": [list(point)], "selected_center": list(point), "access_layers": ["poly1"],
                }]}}})
                terminals.append({"instance": name, "terminal": "G", "pin_island_id": island})
            requests.append({"net": net, "net_class": "differential", "max_bbox_excursion_um": 20.0, "layers": ["m1", "m2"], "terminals": terminals})
        access = {"schema": PLANNER.ROUTE.ACCESS_SCHEMA, "target": {"lib": "l", "cell": "pair", "view": "layout"}, "instances": instances}
        obstacles = {
            "schema": PLANNER.OBSTACLE_SCHEMA, "target": access["target"],
            "sources": {"profile_fingerprint": profile["fingerprint"]["value"], "terminal_access_sha256": PLANNER.ROUTE.digest(access)},
            "bounds_um": [[-2, -2], [14, 6]], "obstacles": [],
        }
        matching = {
            "first_net": "N", "second_net": "P", "max_length_delta_um": 0.1, "max_via_delta": 0,
            "strategy": "common_centroid_columns", "contact_layer": "m1", "bus_layer": "m2",
            "contact_escape_um": 0.5, "landing_stub_um": 0.2, "bus_clearance_um": 1.0,
        }
        request = {
            "schema": PLANNER.REQUEST_SCHEMA, "target": access["target"], "reserve_matched_pairs_first": True,
            "sources": {"profile_fingerprint": profile["fingerprint"]["value"], "terminal_access_sha256": PLANNER.ROUTE.digest(access), "obstacles_sha256": PLANNER.ROUTE.digest(obstacles)},
            "nets": requests, "matching": [matching],
        }
        result = PLANNER.plan(profile, access, obstacles, request)
        self.assertEqual(result["status"], "PLANNED", result["failures"])
        spec = result["candidates"][0]["route_spec"]
        intent = PLANNER.ROUTE.build(profile, access, spec)
        self.assertTrue(intent["matching"][0]["pass"])
        self.assertEqual(len(spec["contact_landings"]), 16)
        for layer in ("m1", "m2"):
            lengths = [sum(route["length_um"] for route in intent["routes"] if route["net"] == net and route["layer"] == layer) for net in ("N", "P")]
            self.assertAlmostEqual(lengths[0], lengths[1])
        buses = [route for route in spec["routes"] if route["id"].endswith("_pair_bus")]
        columns = [route for route in spec["routes"] if "_pair_column_" in route["id"]]
        self.assertTrue(buses)
        for bus in buses:
            bx0, bx1 = sorted((bus["points_um"][0][0], bus["points_um"][1][0]))
            own_columns = [route for route in columns if route["net"] == bus["net"]]
            self.assertTrue(all(bx0 <= route["points_um"][0][0] <= bx1 for route in own_columns))
        self.assertTrue(intent["physical_connectivity"]["complete"])
        self.assertTrue(all(len(route["points_um"]) == 2 for route in intent["routes"]))


if __name__ == "__main__":
    unittest.main()
