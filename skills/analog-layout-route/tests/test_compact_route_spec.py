import importlib.util
from pathlib import Path


PATH = Path(__file__).parents[1] / "scripts" / "compact_route_spec.py"
SPEC = importlib.util.spec_from_file_location("compact_route_spec", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def test_merges_collinear_overlap_and_preserves_access():
    spec = {
        "routes": [
            {"id": "a", "net": "N", "layer": "m1", "purpose": "drawing", "width_um": 0.5,
             "points_um": [[0, 0], [5, 0]], "access": [{"instance": "A", "terminal": "G", "pin_island_id": "A:G:p0", "xy_um": [0, 0]}]},
            {"id": "b", "net": "N", "layer": "m1", "purpose": "drawing", "width_um": 0.5,
             "points_um": [[3, 0], [8, 0]], "access": [{"instance": "B", "terminal": "G", "pin_island_id": "B:G:p0", "xy_um": [8, 0]}]},
        ],
        "vias": [
            {"id": "v0", "net": "N", "via": "V1", "xy_um": [4, 0]},
            {"id": "v1", "net": "N", "via": "V1", "xy_um": [4, 0]},
        ],
    }
    result, evidence = MOD.compact(spec)
    assert result["routes"][0]["points_um"] == [[0.0, 0.0], [8.0, 0.0]]
    assert len(result["routes"][0]["access"]) == 2
    assert len(result["vias"]) == 1
    assert evidence["input_routes"] == 2
    assert evidence["output_routes"] == 1


def test_keeps_widths_and_nets_separate():
    spec = {"routes": [], "vias": []}
    for index, (net, width) in enumerate((("A", 0.5), ("A", 1.0), ("B", 0.5))):
        spec["routes"].append({"id": str(index), "net": net, "layer": "m1", "purpose": "drawing", "width_um": width, "points_um": [[0, 0], [5, 0]], "access": []})
    result, _ = MOD.compact(spec)
    assert len(result["routes"]) == 3


def test_assigns_junction_access_once():
    access = {"instance": "A", "terminal": "G", "pin_island_id": "A:G:p0", "xy_um": [2, 0]}
    spec = {"routes": [
        {"id": "h", "net": "N", "layer": "m1", "purpose": "drawing", "width_um": 0.5, "points_um": [[0, 0], [4, 0]], "access": [access]},
        {"id": "v", "net": "N", "layer": "m1", "purpose": "drawing", "width_um": 0.5, "points_um": [[2, -2], [2, 2]], "access": [access]},
    ], "vias": []}
    result, _ = MOD.compact(spec)
    assert sum(len(route["access"]) for route in result["routes"]) == 1
