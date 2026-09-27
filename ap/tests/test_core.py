"""Hand-checkable tests for the deterministic rules in core/.

Numbers in comments are worked by hand so a failing test points at a real
rule error, not just a changed output. Keep adding cases like these; they are
what lets Claude Code verify its own changes.
"""
import copy
from pathlib import Path

import pytest

from core.candidates import generate_candidates
from core.geometry import point_on_boundary
from core.loads import build_increment
from core.model import column, load_building, load_config, outline_from_bays
from core.regions import amplified_region, simultaneous_removals
from core.scenarios import build_scenarios
from core.stories import mid_height_index, select_stories

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return load_config(ROOT / "config" / "config.toml")


@pytest.fixture(scope="module")
def b():
    return load_building(ROOT / "fixtures" / "demo_building.json")


# ---------- story selection (3-2.9.2.2) ----------

@pytest.mark.parametrize("n,expected", [(3, 1), (4, 1), (5, 2), (10, 4)])
def test_mid_height_index(n, expected):
    # UFC example: 10-story building -> fifth story (index 4)
    assert mid_height_index(n) == expected


def test_story_selection_demo(b):
    # 4 stories, section change at Story3:
    # first=Story1, top=Story4, mid=Story2, above splice=Story3
    picks = select_stories(b, "A1")
    assert [p["story"] for p in picks] == ["Story1", "Story2", "Story3", "Story4"]
    assert "above_splice_or_size_change" in picks[2]["reasons"]


# ---------- candidates ----------

def test_candidates_demo(b, cfg):
    cands = {c["location_id"]: c for c in generate_candidates(b, cfg)}
    codes = {loc: {r["code"] for r in c["reasons"]} for loc, c in cands.items()}
    assert "corner" in codes["A1"]
    assert "mid_long_side" in codes["A3"]          # long side y=0, midpoint x=18 -> x=16
    assert "mid_short_side" in codes["B6"]         # short side x=36, midpoint y=10.5 -> y=7 (tie-break)
    assert "bay_size_change" in codes["A5"]        # spans 8 m / 4 m
    assert "bay_size_change" in codes["D5"]


# ---------- amplified region ----------

@pytest.mark.parametrize("loc,bays_per_level", [("A1", 1), ("A3", 2), ("B3", 4)])
def test_adjacent_bays(b, loc, bays_per_level):
    # corner -> 1 bay, edge -> 2, interior -> 4, on each of the 4 levels above Story1
    col = column(b, loc, "Story1")
    reg = amplified_region(b, [col])
    assert reg["levels"] == ["L1", "L2", "L3", "ROOF"]
    assert len(reg["bays"]) == 4 * bays_per_level


def test_region_only_floors_above(b):
    col = column(b, "A1", "Story3")
    reg = amplified_region(b, [col])
    assert reg["levels"] == ["L3", "ROOF"]


# ---------- simultaneous removal (30% rule) ----------

def test_no_simultaneous_on_regular_grid(b, cfg):
    col = column(b, "A3", "Story1")
    assert simultaneous_removals(b, col, cfg["removal"]["simultaneous_fraction"]) == []


def test_simultaneous_close_column(b, cfg):
    bb = copy.deepcopy(b)
    # add an extra column 1.5 m from A3 at Story1; bays touching A3 are 8 x 7 -> limit 0.3*8 = 2.4 m
    extra = dict(column(bb, "A3", "Story1"), id="C_X_S1", location_id="X", x=17.5, y=0.0)
    bb["columns"].append(extra)
    got = simultaneous_removals(bb, column(bb, "A3", "Story1"), cfg["removal"]["simultaneous_fraction"])
    assert [c["id"] for c in got] == ["C_X_S1"]


# ---------- increment loads ----------

def test_increment_corner_hand_calc(b, cfg):
    # Corner A1, Story1 removal, amp = 2.0 -> increment = 1.0 x base combination on region.
    # Floor bay 8x7=56 m2: 1.2*(1.5+2.6) + 0.5*2.4 = 6.12 kPa -> 342.72 kN, x3 floors = 1028.16
    # Roof bay: 1.2*(1.0+2.6) + max(0.5*1.0, 0.2*1.2) = 4.82 kPa -> 269.92 kN
    # Beams per level (D13: every beam touching the region bay): 2x8 m W21X44 (65.5 kg/m) +
    #   2x7 m W18X35 (52.1 kg/m) self-weight, facade on the 8 m + 7 m perimeter beams:
    #   3.5 kN/m floors, 1.5 kN/m roof. The demo has no deck span, so bays load by area.
    sw = 2 * 8 * 65.5 * 9.81e-3 + 2 * 7 * 52.1 * 9.81e-3
    beams = 3 * 1.2 * (sw + 15 * 3.5) + 1.2 * (sw + 15 * 1.5)
    expected = 1028.16 + 269.92 + beams
    reg = amplified_region(b, [column(b, "A1", "Story1")])
    inc = build_increment(b, reg, cfg)
    assert inc["increment_total_kn"] == pytest.approx(expected, rel=1e-4)
    assert inc["region_amplified_total_kn"] == pytest.approx(2 * inc["region_base_total_kn"], rel=1e-6)


def test_increment_combination_factors_roof_hand_calc(b, cfg):
    # D17: factors exported from the ETABS initial case (1.2 SW + 1.2 SDL + 0.5 LL) apply to
    # every bay, roof included. The roof bay here carries LL 2.4 kPa as in the ETABS model.
    # Floor bay 56 m2: 1.2*2.6 + 1.2*1.5 + 0.5*2.4 = 3.12 + 1.8 + 1.2 = 6.12 kPa -> 342.72 kN, x3 = 1028.16
    # Roof bay 56 m2: 1.2*2.6 + 1.2*1.0 + 0.5*2.4 + 0*1.0 (Lr) + 0*1.2 (S) = 5.52 kPa -> 309.12 kN
    #   (config path would give 4.82 kPa: 0.5 Lr / 0.2 S instead of 0.5 L)
    # Beams: all four per level, self-weight x 1.2 and facade x 1.2, as in the config path.
    bb = copy.deepcopy(b)
    bb["combination"] = {"initial_case": "1.2D+0.5L", "patterns": {"SW": 1.2, "SDL": 1.2, "LL": 0.5},
                         "factors": {"self_weight": 1.2, "sdl": 1.2, "live": 0.5, "roof_live": 0.0, "snow": 0.0}}
    for a in bb["bays"]:
        if a["level"] == "ROOF":
            a["loads"]["live_kpa"] = 2.4
    sw = 2 * 8 * 65.5 * 9.81e-3 + 2 * 7 * 52.1 * 9.81e-3
    beams = 3 * 1.2 * (sw + 15 * 3.5) + 1.2 * (sw + 15 * 1.5)
    expected = 1028.16 + 309.12 + beams
    inc = build_increment(bb, amplified_region(bb, [column(bb, "A1", "Story1")]), cfg)
    assert inc["increment_total_kn"] == pytest.approx(expected, rel=1e-4)
    roof = [x for x in inc["area_loads"] if x["bay_id"] == "A_ROOF_A1"][0]
    assert roof["q_kpa"] == pytest.approx(5.52, abs=1e-4)


def test_region_beams_label_shared_edges(b):
    # D13: corner A1, Story1 -> one 8 x 7 m corner bay per level (L1, L2, L3, ROOF).
    # All four edge beams go in the group; B1-B2 (y = 7) and A2-B2 (x = 8) are also on a
    # neighbouring bay's edge, so they are labelled shared; A1-A2 and A1-B1 are on the building edge.
    reg = amplified_region(b, [column(b, "A1", "Story1")])
    levels = ["L1", "L2", "L3", "ROOF"]
    assert sorted(reg["beams"]) == sorted(f"B_{lv}_{n}" for lv in levels for n in ("A1-A2", "B1-B2", "A1-B1", "A2-B2"))
    assert sorted(reg["shared_edge_beams"]) == sorted(f"B_{lv}_{n}" for lv in levels for n in ("B1-B2", "A2-B2"))


def test_deck_to_beams_two_bays_hand_calc(cfg):
    # D13: deck spans along Y (90 deg). Region bay A [0,6]x[0,4], neighbour bay B [0,6]x[4,8].
    # X-direction beams (6 m) at y = 0, 2, 4 (A) and 6, 8 (B); Y-direction edge beams (4 m) at x = 0, 6.
    # Factors 1.2 SW, 1.2 SDL, 0.5 LL; amplification 2.0 -> increment = 1.0 x base.
    # q_A = 1.2*2 (deck) + 1.2*1 (SDL) + 0.5*3 (LL) = 5.1 kPa; q_B = 1.2*2 + 1.2*2 + 0.5*3 = 6.3 kPa.
    # Strips in A: y=0 1 m, y=2 2 m, y=4 1 m; in B: y=4 1 m, y=6 2 m, y=8 1 m. Y beams take none.
    # Group (beams touching A): y=0: 5.1*1*6 = 30.6; y=2: 5.1*2*6 = 61.2; y=4: 5.1*1*6 + 6.3*1*6 = 68.4;
    #   x=0 and x=6 (A's edges): 0. Beams weightless. Increment 160.2 kN (A by area: 5.1*24 = 122.4;
    #   the difference 37.8 is B's strip on the shared beam y=4).
    def beam(i, a, c):
        return {"id": i, "level": "L1", "z": 3.0, "i": a, "j": c, "section": "S"}
    loads = lambda sdl: {"sdl_kpa": sdl, "live_kpa": 3.0, "roof_live_kpa": 0.0, "snow_kpa": 0.0, "slab_sw_kpa": 2.0}
    bb = {
        "levels": [{"name": "Base", "z": 0.0}, {"name": "L1", "z": 3.0}, {"name": "L2", "z": 6.0}],
        "sections": {"S": {"mass_kg_per_m": 0.0}},
        "bays": [{"id": "A", "level": "L1", "z": 3.0, "polygon": [[0, 0], [6, 0], [6, 4], [0, 4]], "loads": loads(1.0), "deck_span_deg": 90},
                 {"id": "B", "level": "L1", "z": 3.0, "polygon": [[0, 4], [6, 4], [6, 8], [0, 8]], "loads": loads(2.0), "deck_span_deg": 90}],
        "beams": [beam("y0", [0, 0], [6, 0]), beam("y2", [0, 2], [6, 2]), beam("y4", [0, 4], [6, 4]),
                  beam("y6", [0, 6], [6, 6]), beam("y8", [0, 8], [6, 8]),
                  beam("xa0", [0, 0], [0, 4]), beam("xa6", [6, 0], [6, 4])],
        "line_loads": [], "point_loads": [],
        "combination": {"initial_case": "1.2D+0.5L",
                        "factors": {"self_weight": 1.2, "sdl": 1.2, "live": 0.5, "roof_live": 0.0, "snow": 0.0}},
    }
    region = {"bays": ["A"], "beams": ["y0", "y2", "y4", "xa0", "xa6"]}
    inc = build_increment(bb, region, cfg)
    assert inc["method"] == "deck_to_beams" and inc["flags"] == []
    deck = {f["beam_id"]: f["components"]["deck"] * f["length_m"] for f in inc["frame_loads"]}
    assert deck == pytest.approx({"y0": 30.6, "y2": 61.2, "y4": 68.4, "xa0": 0.0, "xa6": 0.0})
    assert inc["increment_total_kn"] == pytest.approx(160.2)


def test_increment_etabs_sc03_hand_calc(cfg):
    # ETABS model (deck spans Y, 90 deg), C1 @ Story5: one 24 x 24 ft (7.3152 m) corner bay per
    # level, Story5..Story10 (6 levels). All 6 beams per bay are in the group (36); the 2 on edges
    # shared with neighbours (y = 7.3152: 588.., x = 7.3152: 612..) are labelled (12).
    # q (every bay) = 1.2*3.10264 (deck) + 1.2*4.78803 (SDL) + 0.5*4.78803 (LL) = 11.86281 kPa
    # Deck strips per level on the X-direction beams: y=0 1.2192, y=2.4384 2.4384, y=4.8768 2.4384,
    #   y=7.3152 1.2192 + 1.2192 from the neighbour = 8.5344 m x 7.3152 m = 62.4308 m2
    #   -> 740.604 kN per level, x 6 = 4443.62 kN. Y-direction beams take none.
    # Beams: 12 W24X62 (92.1314 kg/m) + 23 W24X55 (82.0070) + 1 W24X68 (101.7495), 7.3152 m each:
    #   1.2 * 9.81e-3 * 7.3152 * 3093.487 = 266.40 kN.  Total 4710.02 kN (ETABS, measured: 4699.6).
    eb = load_building(ROOT / "fixtures" / "etabs_building.json")
    reg = amplified_region(eb, [column(eb, "C1", "Story5")])
    assert len(reg["bays"]) == 6 and len(reg["beams"]) == 36 and len(reg["shared_edge_beams"]) == 12
    assert {"588", "612", "328", "352"} <= set(reg["shared_edge_beams"])
    inc = build_increment(eb, reg, cfg)
    assert inc["method"] == "deck_to_beams" and inc["flags"] == []
    q = 1.2 * 3.102641 + 1.2 * 4.788026 + 0.5 * 4.788026
    beams = 1.2 * 9.81e-3 * 7.3152 * (12 * 92.131355 + 23 * 82.007030 + 101.749464)
    expected = 6 * 7.3152 * 8.5344 * q + beams
    assert expected == pytest.approx(4710.02, abs=0.05)
    assert inc["increment_total_kn"] == pytest.approx(expected, rel=1e-5)


def test_combination_missing_factor_raises(b, cfg):
    bb = copy.deepcopy(b)
    bb["combination"] = {"initial_case": "1.2D+0.5L", "factors": {"self_weight": 1.2, "sdl": 1.2}}
    with pytest.raises(ValueError, match="live"):
        build_increment(bb, amplified_region(bb, [column(bb, "A1", "Story1")]), cfg)


def test_no_wind_in_config(cfg):
    assert cfg["loads"]["include_wind"] is False


# ---------- scenarios ----------

def test_scenarios_demo(b, cfg):
    scen = build_scenarios(b, generate_candidates(b, cfg), cfg)
    assert len(scen) == 5 * 4                       # 5 locations x 4 stories
    assert len({s["id"] for s in scen}) == len(scen)
    for s in scen:
        assert s["increment"]["increment_total_kn"] > 0
        assert s["case_name"].startswith("AP_")


# ---------- outlines from an ETABS export ----------

def test_outline_keeps_bay_coordinates():
    # Two 24 ft bays side by side: 2 x 7.3152 = 14.6304 m by 7.3152 m. Rounding the far corner to
    # 1 mm (14.630) put the columns at x = 14.6304 0.4 mm off the outline, beyond the 1e-6 tolerance.
    ft24 = 7.3152
    bays = [{"polygon": [[0, 0], [ft24, 0], [ft24, ft24], [0, ft24]]},
            {"polygon": [[ft24, 0], [2 * ft24, 0], [2 * ft24, ft24], [ft24, ft24]]}]
    outline = outline_from_bays(bays)
    assert sorted(map(tuple, outline)) == [(0, 0), (0, ft24), (2 * ft24, 0), (2 * ft24, ft24)]
    grid = [(x, y) for x in (0, ft24, 2 * ft24) for y in (0, ft24)]
    assert all(point_on_boundary(p, outline) for p in grid)


def test_candidates_etabs_fixture(cfg):
    # ETABS model: 7 x 3 bays of 24 ft (7.3152 m) -> 51.2064 m x 21.9456 m, 20 perimeter columns.
    # Corner: C1 at (0, 0). Long side y = 0, mid x = 25.6032: C13 (21.9456) and C17 (29.2608) are
    # both 3.6576 away; tie-break closer to the edge start -> C13.
    # Short side x = 51.2064, mid y = 10.9728: C30 (7.3152) and the column at 14.6304 tie at
    # 3.6576; closer to the edge start (51.2064, 0) -> C30.
    eb = load_building(ROOT / "fixtures" / "etabs_building.json")
    got = {c["location_id"]: [r["code"] for r in c["reasons"]] for c in generate_candidates(eb, cfg)}
    assert got == {"C1": ["corner"], "C13": ["mid_long_side"], "C30": ["mid_short_side"]}
