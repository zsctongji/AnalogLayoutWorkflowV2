import copy
import itertools
import unittest

from test_route_planner import PLANNER as P, fixtures, refresh


def fixture_points(points):
    profile, access, obstacles, request = fixtures()
    access["instances"] = []
    request["nets"][0]["terminals"] = []
    for index, point in enumerate(points):
        name = f"T{index}"
        island = name + ":G:p0"
        access["instances"].append({"name":name,"terminals":{"G":{"net":"N","pin_islands":[{
            "id":island,"candidate_centers":[list(point)],"selected_center":list(point),"access_layers":["m1"]}]}}})
        request["nets"][0]["terminals"].append({"instance":name,"terminal":"G","pin_island_id":island})
    obstacles["obstacles"] = []
    obstacles["bounds_um"] = [[-3,-3],[23,13]]
    refresh(profile,access,obstacles,request)
    return profile,access,obstacles,request


def geometric_cost(path):
    return P.SEARCH.evaluate_path(path, {}, 2, 0.1, 0)


class SharedTreeTests(unittest.TestCase):
    def test_comb_shares_trunk_with_less_wire_and_fewer_bends(self):
        args = fixture_points([(0,0),(4,4),(8,0),(12,4),(16,0),(20,4)])
        args[3].update(shared_tree=False,topology_frontier_limit=1)
        old = P.plan(*args)["candidates"][0]["metrics"]["N"]
        args[3].update(shared_tree=True,topology_frontier_limit=4)
        result = P.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        new = result["candidates"][0]["metrics"]["N"]
        self.assertLess(new["length_um"],old["length_um"])
        self.assertLess(new["bends"],old["bends"])
        intent = P.ROUTE.build(args[0],args[1],result["candidates"][0]["route_spec"])
        self.assertTrue(intent["physical_connectivity"]["complete"])
        self.assertTrue(intent["physical_access_coverage"]["complete"])

    def test_area_cost_can_avoid_wide_layer_without_forbidding_it(self):
        args = (P._module_api(),(0,0,"m1"),{(10,0,"m1")},
                {"m1":[(4,-1,6,1)],"m2":[]},[[-1,-2],[11,2]],
                {"m1":[("m2","V")],"m2":[("m1","V")]},set(),0.1,0.01)
        low = P.SEARCH.directional_astar(*args,layer_costs={"m1":0,"m2":0})
        high = P.SEARCH.directional_astar(*args,layer_costs={"m1":0,"m2":20})
        self.assertIn("m2",{n[2] for n in low})
        self.assertEqual({n[2] for n in high},{"m1"})
        self.assertGreater(geometric_cost(high)["wire_length_um"],geometric_cost(low)["wire_length_um"])
        full_wall_args = list(args)
        full_wall_args[3] = {"m1":[(4,-20,6,20)],"m2":[]}
        necessary = P.SEARCH.directional_astar(*full_wall_args,layer_costs={"m1":0,"m2":20})
        self.assertIn("m2",{n[2] for n in necessary})

    def test_single_layer_width_is_preserved_and_area_reported(self):
        args = fixture_points([(0,0),(10,0),(5,4)])
        args[3]["nets"][0]["width_um"] = 0.8
        result = P.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        candidate = result["candidates"][0]
        self.assertEqual({r["width_um"] for r in candidate["route_spec"]["routes"]},{0.8})
        metric = candidate["metrics"]["N"]
        self.assertAlmostEqual(metric["drawn_wire_area_um2"],0.8*metric["length_um"])
        self.assertAlmostEqual(metric["cost_breakdown"]["metal_area_penalty"],0)

    def test_frontier_compares_actual_detour_cost(self):
        nodes = [(0,0,"m1"),(1,0,"m1"),(0,3,"m1")]
        def search(start, goals):
            return P.astar_layered(start,goals,{"m1":[(0.4,-2,0.6,2)]},
                [[-1,-3],[2,4]],{"m1":[]},set(),0.1,2,{},0)
        fast = P.SEARCH.synthesize_topology(nodes,search,geometric_cost,frontier_limit=1)
        ranked = P.SEARCH.synthesize_topology(nodes,search,geometric_cost,frontier_limit=4)
        self.assertEqual(fast[0][1],1)
        self.assertEqual(ranked[0][1],2)
        self.assertLess(sum(geometric_cost(ranked[0][2]).values()),sum(geometric_cost(fast[0][2]).values()))

    def test_tree_projection_is_layer_specific(self):
        goals = P.SEARCH.tree_attachment_points((5,4,"m2"),
            [[(0,0,"m1"),(10,0,"m1")]],[(0,0,"m1")])
        self.assertIn((5,0,"m1"),goals)
        self.assertNotIn((5,0,"m2"),goals)

    def test_normalization_removes_overlap_cycles_and_dead_stubs(self):
        paths = [
            [(0,0,"m1"),(10,0,"m1")],
            [(3,0,"m1"),(7,0,"m1")],
            [(0,0,"m1"),(0,4,"m1"),(10,4,"m1"),(10,0,"m1")],
            [(5,0,"m1"),(5,-2,"m1")],
        ]
        terminals = {(0,0,"m1"),(10,0,"m1"),(5,0,"m1")}
        result, evidence = P.TREE.normalize_tree(paths,terminals,geometric_cost)
        self.assertTrue(evidence["applied"])
        self.assertEqual(evidence["duplicate_length_removed_um"],4)
        self.assertEqual(evidence["output_unique_length_um"],10)
        self.assertEqual(evidence["cycle_or_stub_length_removed_um"],20)
        vertices = set(n for path in result for n in path)
        self.assertTrue(terminals <= vertices)

    def test_crossing_layers_are_not_electrically_joined(self):
        paths = [[(0,0,"m1"),(10,0,"m1")],[(5,-2,"m2"),(5,2,"m2")]]
        result,evidence = P.TREE.normalize_tree(paths,{(0,0,"m1"),(5,2,"m2")},geometric_cost)
        self.assertFalse(evidence["applied"])
        self.assertEqual(result,paths)

    def test_vias_are_preserved_when_needed(self):
        paths = [[(0,0,"m1"),(5,0,"m1"),(5,0,"m2"),(5,5,"m2")]]
        result,evidence = P.TREE.normalize_tree(paths,{(0,0,"m1"),(5,5,"m2")},geometric_cost)
        self.assertTrue(evidence["applied"])
        self.assertTrue(any(a[2] != b[2] for path in result for a,b in zip(path,path[1:])))

    def test_normalized_geometry_stays_on_input_segments(self):
        paths = [[(0,0,"m1"),(2,0,"m1"),(2,4,"m1"),(10,4,"m1"),(10,0,"m1")],
                 [(2,4,"m1"),(2,6,"m1")]]
        result,_ = P.TREE.normalize_tree(paths,{(0,0,"m1"),(10,0,"m1")},geometric_cost)
        self.assertTrue(all(any(P.TREE.on_edge(a,x,y) and P.TREE.on_edge(b,x,y)
                               for path in paths for x,y in zip(path,path[1:]))
                            for path in result for a,b in zip(path,path[1:])))

    def test_emitted_shared_tree_is_connected_and_nonduplicated(self):
        args = fixture_points([(0,0),(10,0),(5,4),(5,0),(20,0)])
        result = P.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        candidate = result["candidates"][0]
        metric = candidate["metrics"]["N"]
        self.assertTrue(metric["tree_refinement"]["applied"])
        self.assertAlmostEqual(metric["directness"]["duplicate_centerline_length_um"],0)
        self.assertEqual(metric["directness"]["terminal_span_um"],[20,4])
        intent = P.ROUTE.build(args[0],args[1],candidate["route_spec"])
        self.assertTrue(intent["physical_connectivity"]["complete"])
        self.assertTrue(intent["physical_access_coverage"]["complete"])

    def test_terminal_order_does_not_change_shared_geometry(self):
        args = fixture_points([(0,0),(10,0),(5,4)])
        baseline = P.plan(*args)["candidates"][0]["route_spec"]
        for order in itertools.permutations(args[3]["nets"][0]["terminals"]):
            args[3]["nets"][0]["terminals"] = list(order)
            self.assertEqual(P.plan(*args)["candidates"][0]["route_spec"],baseline)

    def test_excursion_limit_is_used_during_search(self):
        args = fixtures()
        args[3]["nets"][0]["max_bbox_excursion_um"] = 0.5
        result = P.plan(*args)
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["failures"][0]["code"],"TOPOLOGY_EDGE_BLOCKED")
        args[3]["nets"][0]["max_bbox_excursion_um"] = 2
        result = P.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        self.assertEqual(result["candidates"][0]["metrics"]["N"]["directness"]["search_bounds_um"],[[-1,-2],[11,2]])

    def test_bend_default_scales_with_width_and_spacing(self):
        args = fixtures()
        args[0]["manufacturing_grid_um"] = 0.001
        refresh(*args)
        result = P.plan(*args)
        self.assertEqual(result["candidates"][0]["metrics"]["N"]["effective_bend_cost_um"],0.4)
        args[3]["nets"][0]["bend_cost_um"] = 0
        result = P.plan(*args)
        self.assertEqual(result["candidates"][0]["metrics"]["N"]["effective_bend_cost_um"],0)

    def test_electrical_topology_is_not_pruned_without_recomputing_currents(self):
        args = fixture_points([(0,0),(10,0),(5,4)])
        args[3]["nets"][0]["electrical"] = {"source":"fixture DC", "root_pin_island_id":"T0:G:p0",
            "sink_currents_a":{"T1:G:p0":0.002,"T2:G:p0":0.001}}
        result = P.plan(*args)
        self.assertEqual(result["status"],"PLANNED",result["failures"])
        self.assertFalse(result["candidates"][0]["metrics"]["N"]["tree_refinement"]["applied"])
        self.assertTrue(all("current_a" in e for e in result["candidates"][0]["metrics"]["N"]["topology_edges"]))

    def test_invalid_frontier_limit_is_structured_failure(self):
        args = fixtures()
        args[3]["topology_frontier_limit"] = 0
        result = P.plan(*args)
        self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["failures"][0]["code"],"INVALID_SEARCH_BUDGET")


if __name__ == "__main__":
    unittest.main()
