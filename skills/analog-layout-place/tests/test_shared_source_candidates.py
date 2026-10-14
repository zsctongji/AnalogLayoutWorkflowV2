import importlib.util
from pathlib import Path


PATH = Path(__file__).parents[1] / "scripts" / "shared_source_candidates.py"
SPEC = importlib.util.spec_from_file_location("shared_source_candidates", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)


def mos(name, source, cell="nmos", kind="nmos"):
    return {
        "name": name, "kind": kind, "logical_device": name.split("_")[0], "group": "CORE",
        "pcell_master": {"lib": "pdk", "cell": cell, "view": "layout"},
        "terminals": {"S": source},
    }


def test_finds_only_same_net_same_kind_same_master_pairs():
    intent = {
        "schema": "analog-layout-align.pcell-placement-intent/v2",
        "instances": [mos("A_0", "VSS"), mos("A_1", "VSS"), mos("B_0", "VSS", cell="lvt"), mos("P_0", "VSS", kind="pmos"), mos("C_0", "OTHER")],
    }
    result = MOD.find_candidates(intent)
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["instances"] == ["A_0", "A_1"]
    assert result["candidates"][0]["status"] == "REQUIRES_PDK_PAIR_PROBE"


def test_candidate_discovery_never_claims_shareability_without_probe():
    intent = {"schema": "analog-layout-align.pcell-placement-intent/v2", "instances": [mos("A", "VSS"), mos("B", "VSS")]}
    result = MOD.find_candidates(intent)
    assert result["decision"] == "REQUIRES_PDK_PAIR_PROBE"
    assert "no connectivity" in result["boundary"]
