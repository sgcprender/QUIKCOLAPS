"""Python side of the C# bridge contract: derived outlines/grids for ETABS exports,
ETABS stacks as the amplified region, naming, and the force comparison script."""
import copy
from pathlib import Path

from core.candidates import generate_candidates
from core.geometry import area
from core.model import column, ensure_derived, load_building, load_config, outline_from_bays
from core.regions import amplified_region
from core.scenarios import build_scenarios
from scripts.compare_forces import compare

ROOT = Path(__file__).resolve().parents[1]
cfg = load_config(ROOT / "config" / "config.toml")
b = load_building(ROOT / "fixtures" / "demo_building.json")


def fake_stacks(bld, frames, extra_area=None):
    """What `quikcolaps-bridge stacks` would return on the demo building: floors on the
    top joint of the removed column and of every column above it."""
    out = {}
    for f in frames:
        col = next(c for c in bld["columns"] if c["id"] == f)
        reg = amplified_region(bld, [col])
        areas = list(reg["bays"]) + ([extra_area] if extra_area else [])
        out[f] = {"levels": [], "influence_areas": areas, "stop": "no column above joint X"}
    return out


def test_outline_from_bays_matches_fixture():
    bays = [a for a in b["bays"] if a["level"] == "L1"]
    derived = outline_from_bays(bays)
    assert area(derived) == area(b["outlines"]["L1"]) == 36 * 21
    assert len(derived) == 4          # collinear grid points removed


def test_export_without_outlines_or_grids_still_generates_candidates():
    raw = copy.deepcopy(b)
    raw.pop("outlines")
    raw.pop("grids")
    bb = ensure_derived(raw)
    assert bb["grids"]["derived"] is True
    locs = {c["location_id"] for c in generate_candidates(bb, cfg)}
    assert {"A1", "A3", "B6"} <= locs


def test_etabs_stacks_define_region_and_match_rule():
    cands = [c for c in generate_candidates(b, cfg) if c["location_id"] == "A3"]
    frames = [column(b, "A3", s["story"])["id"] for s in cands[0]["stories"]]
    scen = build_scenarios(b, cands, cfg, fake_stacks(b, frames))
    assert all(s["region"]["source"] == "etabs" for s in scen)
    assert all("etabs_region_differs_from_rule" not in s["flags"] for s in scen)


def test_etabs_region_difference_is_flagged():
    cands = [c for c in generate_candidates(b, cfg) if c["location_id"] == "A3"]
    frames = [column(b, "A3", "Story1")["id"]]
    cands[0] = dict(cands[0], stories=[{"story": "Story1", "reasons": []}])
    scen = build_scenarios(b, cands, cfg, fake_stacks(b, frames, extra_area="A_L1_B3"))
    s = scen[0]
    assert "etabs_region_differs_from_rule" in s["flags"]
    assert "A_L1_B3" in s["region"]["bays"]            # ETABS wins; the rule region is kept for review
    assert "A_L1_B3" not in s["region"]["rule_bays"]


def test_names_follow_quikcolaps_convention():
    s = build_scenarios(b, generate_candidates(b, cfg), cfg)[0]
    assert s["combo_name"] == s["case_name"] + "_CMB"
    assert s["group_name"] == s["case_name"] + "_LOAD"


def test_compare_forces():
    a = {"101": {"p_kn": 100.0, "v2_kn": 50.0, "m3_knm": 200.0}}
    same = {"101": {"p_kn": 100.5, "v2_kn": 50.0, "m3_knm": 200.0}}
    off = {"101": {"p_kn": 100.0, "v2_kn": 50.0, "m3_knm": 230.0}}
    assert compare(a, same, 0.01) == []
    assert len(compare(a, off, 0.01)) == 1
