import importlib.util
from pathlib import Path


PATH = Path(__file__).parents[1] / "scripts" / "compare_reference_layout.py"
SPEC = importlib.util.spec_from_file_location("compare_reference_layout", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def fixtures():
    intent = {
        "target": {"lib": "L", "cell": "AUTO", "view": "layout"},
        "required_nets": ["VDD", "INP", "INN"],
        "routes": [
            {"net": "VDD", "layer": "m1", "width_um": 0.5},
            {"net": "INP", "layer": "m2", "width_um": 0.5},
            {"net": "INN", "layer": "m2", "width_um": 0.5},
        ],
        "net_metrics": {
            "VDD": {"path_length_um": 20, "route_count": 4, "via_count": 2, "layer_lengths_um": {"m1": 20}, "detour_ratio": 1.2, "off_preference_ratio": 0.1},
            "INP": {"path_length_um": 10, "route_count": 2, "via_count": 1, "layer_lengths_um": {"m2": 10}},
            "INN": {"path_length_um": 10, "route_count": 2, "via_count": 1, "layer_lengths_um": {"m2": 10}},
        },
        "matching": {"first_net": "INP", "second_net": "INN", "max_length_delta_um": 0.1, "max_via_delta": 0, "max_route_count_delta": 0, "max_per_layer_length_delta_um": 0.1},
    }
    reference = {
        "target": {"lib": "L", "cell": "MANUAL", "view": "layout"},
        "bbox_um": [[0, 0], [20, 20]],
        "database_counts": {"instances": 3},
        "route_object_counts": {"paths": 5, "polygons": 0, "vias": 4},
        "unassigned": {"paths": 1, "polygons": 0, "vias": 0},
        "boundary": "Read-only evidence; no DRC/LVS/PEX or schematic-equivalence claim.",
        "net_metrics": {
            "VDD": {"path_length_um": 30, "path_count": 2, "via_count": 2, "closed_path_count": 1, "layer_lengths_um": {"m1": 30}, "widths_um": {"m1": [2.0]}},
            "INP": {"path_length_um": 8, "path_count": 1, "via_count": 1, "layer_lengths_um": {"m2": 8}},
            "INN": {"path_length_um": 5, "path_count": 1, "via_count": 1, "layer_lengths_um": {"m2": 5}},
        },
    }
    access = {"intent_instance_count": 4, "nets": [
        {"name": "VDD", "terminal_count": 4, "terminals": [{"selected_center": [0, 0]}, {"selected_center": [10, 0]}]},
        {"name": "INP", "terminal_count": 2, "terminals": [{"selected_center": [0, 1]}]},
        {"name": "INN", "terminal_count": 2, "terminals": [{"selected_center": [0, 2]}]},
    ]}
    spec = {"net_constraints": [{"net": "VDD", "net_class": "power"}], "matching": intent["matching"]}
    return intent, reference, access, spec


def test_blocks_raw_geometry_and_bad_reference_pair():
    report = MOD.compare(*fixtures())
    assert not report["placement_comparison"]["raw_geometry_comparison_allowed"]
    vdd = next(item for item in report["per_net"] if item["net"] == "VDD")
    assert vdd["policy_comparison"]["raw_length_delta_um"] is None
    assert vdd["target"]["vias_per_terminal"] == 0.5
    assert not report["matching"][0]["reference_self_consistent"]
    assert {finding["code"] for finding in report["findings"]} >= {"REFERENCE_POWER_LOOP", "POWER_WIDTH_BASIS", "REFERENCE_PAIR_NOT_MATCHED"}


def test_raw_deltas_require_explicit_equivalence():
    report = MOD.compare(*fixtures(), placement_equivalent=True)
    vdd = next(item for item in report["per_net"] if item["net"] == "VDD")
    assert report["placement_comparison"]["raw_geometry_comparison_allowed"]
    assert vdd["policy_comparison"]["raw_length_delta_um"] == -10
    assert vdd["policy_comparison"]["raw_via_delta"] == 0


def test_reference_assignment_is_reported_not_hidden():
    report = MOD.compare(*fixtures())
    assignment = report["reference_quality_gate"]["assignment"]
    assert assignment["unassigned_route_objects"] == 1
    assert assignment["assigned_fraction"] == 0.888889
