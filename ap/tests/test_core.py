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


# ---------- condition table (facts for the 3-2.9.2.2 judgment conditions) ----------

def _axial(b, p=100.0):
    # fake intact axial: every column 100 kN except A4 in Story1 at 250 kN
    cols = {c["id"]: {"p_kn": p} for c in b["columns"]}
    cols["C_A4_S1"] = {"p_kn": 250.0}
    return {"case": "fake", "columns": cols}


def test_condition_row_tributary_neighbours_and_beams(b):
    from core.conditions import condition_table
    t = condition_table(b, _axial(b))
    r = next(r for r in t["rows"] if r["location_id"] == "A5" and r["story"] == "Story1")
    # A5 at (32, 0) touches bays 24-32 x 0-7 (56 m2) and 32-36 x 0-7 (28 m2), all
    # four corners of each have columns: 56/4 + 28/4 = 14 + 7 = 21 m2
    assert r["tributary_m2"] == pytest.approx(21.0)
    # the same at L1, L2, L3 and ROOF: 4 x 21 = 84 m2
    assert r["tributary_above_m2"] == pytest.approx(84.0)
    assert sorted((a["dx_m"], a["dy_m"]) for a in r["adjacent_bays"]) == [(4.0, 7.0), (8.0, 7.0)]
    n = {x["location_id"]: x for x in r["neighbours"]}
    # +x A6 at 36 - 32 = 4 m, -x A4 at 32 - 24 = 8 m, +y B5 at 7 m (interior)
    assert {k: v["distance_m"] for k, v in n.items()} == {"A6": 4.0, "A4": 8.0, "B5": 7.0}
    assert n["B5"]["perimeter"] is False and n["A6"]["perimeter"] is True
    # A4 carries 250 kN against A5's 100 kN: ratio 2.5
    assert n["A4"]["p_ratio_to_this"] == pytest.approx(2.5)
    # three girders frame in at the top joint, at 0, 90 and 180 degrees, no offset
    assert r["beam_count"] == 3 and r["beam_directions_deg"] == [0.0, 90.0, 180.0]
    assert r["beam_z_offsets_m"] == [0.0]
    assert r["position"] == "edge" and r["sides"] == ["south"]


def test_condition_row_splice_and_continuity(b):
    from core.conditions import condition_table
    t = condition_table(b, _axial(b))
    rows = {r["story"]: r for r in t["rows"] if r["location_id"] == "A1"}
    # W14X90 in Story1-2, W14X61 from Story3: the splice is below Story3 only
    assert [rows[s]["splice_below"] for s in ("Story1", "Story2", "Story3", "Story4")] == [False, False, True, False]
    assert all(r["continuous_to_roof"] for r in rows.values())
    # corner: 8 x 7 bay / 4 = 14 m2
    assert rows["Story1"]["tributary_m2"] == pytest.approx(14.0) and rows["Story1"]["position"] == "corner"


def test_symmetry_groups_demo(b):
    from core.conditions import condition_table
    t = condition_table(b, _axial(b))
    # x grids 0, 8, 16, 24, 32, 36 are not symmetric; y grids 0, 7, 14, 21 are:
    # only the mirror about y = 10.5 maps the framing onto itself
    assert list(t["symmetry"]["framing_ops"]) == ["mirror_y"]
    g = {r["location_id"]: r["symmetry_group"] for r in t["rows"]}
    assert g["A1"] == g["D1"] and g["A6"] == g["D6"] and g["B1"] == g["C1"]
    assert g["A1"] != g["A6"]


def test_symmetry_lists_unmatched_bay(b):
    from core.conditions import condition_table
    bb = copy.deepcopy(b)
    # a small area outside one corner breaks the mirror for the bays only
    bb["bays"].append({"id": "STRAY", "level": "L1", "z": 4.0,
                       "polygon": [[36.0, -0.15], [36.15, -0.15], [36.15, 0.0], [36.0, 0.0]],
                       "loads": bb["bays"][0]["loads"]})
    t = condition_table(bb, _axial(bb))
    assert t["symmetry"]["framing_ops"]["mirror_y"]["bays_without_image"] == ["STRAY"]


# ---------- similarity propagation (core/propagate.py) ----------

def _prop_inputs(b, members):
    """Fake results for the demo: members {frame: (design section, governing scenario)}.
    One scenario: A2 (8, 0) removed in Story1. Groups from the condition table (mirror y = 10.5)."""
    from core.conditions import condition_table
    axial = {"case": "fake", "columns": {c["id"]: {"p_kn": 100.0} for c in b["columns"]}}
    cond = condition_table(b, axial)
    res = {"members": {f: {"section": s, "governing_scenario": sid} for f, (s, sid) in members.items()}}
    scen = {"scenarios": [{"id": "SC01", "location_id": "A2", "story": "Story1", "removed_columns": ["C_A2_S1"]}]}
    return res, scen, cond


def test_propagate_mirrors_beam_and_column(b):
    from core.propagate import propagate
    res, scen, cond = _prop_inputs(b, {
        "B_L1_A1-A2": ("W21X62", "SC01"),   # edge girder next to the removal, W21X44 -> W21X62
        "C_A2_S2": ("W14X120", "SC01"),     # column above the removal, W14X90 -> W14X120
        "B_L1_A2-B2": ("W18X35", "SC01"),   # not heavier: not a source
    })
    out = propagate(b, res, scen, cond)
    # A2's group is {A2, D2}; the mirror about y = 10.5 maps (8, 0) to (8, 21):
    # the girder (0,0)-(8,0) at L1 -> (0,21)-(8,21) = B_L1_D1-D2, column A2 Story2 -> D2 Story2
    a = {x["frame"]: (x["from"], x["section"]) for x in out["assignments"]}
    assert a == {"B_L1_A1-A2": ("W21X44", "W21X62"), "B_L1_D1-D2": ("W21X44", "W21X62"),
                 "C_A2_S2": ("W14X90", "W14X120"), "C_D2_S2": ("W14X90", "W14X120")}
    r = next(r for r in out["rows"] if r["member"] == "B_L1_A1-A2" and r["counterpart"] == "B_L1_D1-D2")
    # girder midpoint (4, 0): x grid 0..8 -> 0.5 bay; removed column at x = 8 -> 1.0 bay: offset -0.5;
    # y: both on grid A: 0. Counterpart midpoint (4, 21) from D2 (8, 21): -0.5, 0
    assert r["offset"] == {"bays_x": -0.5, "bays_y": 0.0, "stories": 0}
    assert r["counterpart_offset"] == {"bays_x": -0.5, "bays_y": 0.0, "stories": 0}
    assert r["symmetry"] == "mirror_y" and r["flags"] == []
    # column A2 Story2 is one story above the Story1 removal
    assert next(r for r in out["rows"] if r["member"] == "C_A2_S2")["offset"]["stories"] == 1


def test_propagate_biggest_wins_and_never_lighter(b):
    from core.propagate import propagate
    res, scen, cond = _prop_inputs(b, {
        "C_A2_S2": ("W14X120", "SC01"),
        # D2 Story2 has its own heavier design (W14X145, from DStlS-type combo: no AP scenario)
        "C_D2_S2": ("W14X145", None),
    })
    out = propagate(b, res, scen, cond)
    a = {x["frame"]: x["section"] for x in out["assignments"]}
    # copy W14X120 onto D2 but its own design W14X145 is heavier: 145 > 120, keep 145
    assert a["C_D2_S2"] == "W14X145" and a["C_A2_S2"] == "W14X120"


def test_propagate_flags_mismatched_counterpart(b):
    import copy
    from core.propagate import propagate
    bb = copy.deepcopy(b)
    next(bm for bm in bb["beams"] if bm["id"] == "B_L1_D1-D2")["section"] = "W18X35"
    res, scen, cond = _prop_inputs(bb, {"B_L1_A1-A2": ("W21X62", "SC01")})
    out = propagate(bb, res, scen, cond)
    # the mirror image was W18X35, not W21X44: flagged, not copied
    assert {x["frame"] for x in out["assignments"]} == {"B_L1_A1-A2"}
    r = next(r for r in out["rows"] if r["counterpart"] == "B_L1_D1-D2")
    assert r["to"] is None and any("original section differs" in f for f in r["flags"])
    assert out["summary"]["flagged_rows"] == 1


def test_propagate_after_redesign_rounds(b):
    from core.propagate import propagate
    res, scen, cond = _prop_inputs(b, {"B_L1_A1-A2": ("W21X62", "SC01")})
    # after a redesign round the model already carries W21X62 on the source (current = design):
    # it is still collapse-driven (original W21X44), and it is assigned (fixed) at W21X62 from W21X62
    current = {"B_L1_A1-A2": "W21X62"}
    cur = {c["id"]: c["section"] for c in b["columns"]} | {m["id"]: m["section"] for m in b["beams"]} | current
    out = propagate(b, res, scen, cond, cur)
    a = {x["frame"]: (x["from"], x["section"]) for x in out["assignments"]}
    assert a == {"B_L1_A1-A2": ("W21X62", "W21X62"), "B_L1_D1-D2": ("W21X44", "W21X62")}
    assert out["summary"]["frames_changing_now"] == 1
    # added over the original: (62 - 44) x 2 frames = 36 lb/ft
    assert out["summary"]["added_lb_per_ft_over_original"] == pytest.approx(36.0)


def test_stepup_member_and_mirror(b):
    from core.stepup import next_heavier, step_up
    # W14 ladder: 90 -> 99, 61 -> 68; nothing after 730
    assert next_heavier("W14X90") == "W14X99" and next_heavier("W14X61") == "W14X68"
    assert next_heavier("W14X730") is None and next_heavier("W21X44") is None
    current = {c["id"]: c["section"] for c in b["columns"]} | {m["id"]: m["section"] for m in b["beams"]}
    prop = {"assignments": [{"frame": "C_D2_S2", "section": "W14X120", "from": "W14X90"}], "summary": {}}
    # C_A2_S2 is W14X90 -> W14X99; its mirror about y = 10.5 is C_D2_S2, already assigned W14X120:
    # heavier, so it keeps W14X120
    out, msgs = step_up(b, prop, ["C_A2_S2"], current)
    a = {x["frame"]: (x["from"], x["section"]) for x in out["assignments"]}
    assert a == {"C_A2_S2": ("W14X90", "W14X99"), "C_D2_S2": ("W14X90", "W14X120")}
    assert msgs == []


# ---------- finalize loop (core/finalize.py) with a fake ETABS ----------

class _FakeEtabs:
    """ratio = demand / (lb/ft of the section); auto-select picks the lightest passing W14,
    or the heaviest if none passes. pick_override forces what auto-select answers."""

    def __init__(self, b, sections, demand, auto_limit=None, pick_override=None, composite=None):
        self.b, self.sec, self.demand = b, dict(sections), demand
        self.auto, self.auto_limit, self.pick_override = set(), auto_limit, pick_override or {}
        self.composite = composite or {}
        self.calls = []

    def _pick(self, f):
        from core.stepup import W14
        if f in self.pick_override:
            return self.pick_override[f]
        ok = [w for w in W14 if (self.auto_limit is None or w <= self.auto_limit) and self.demand[f] / w <= 1.0]
        return f"W14X{ok[0] if ok else min(W14[-1], self.auto_limit or W14[-1])}"

    def check(self):
        from core.propagate import weight
        self.calls.append("check")
        out = {}
        for f, d in self.demand.items():
            s = self._pick(f) if f in self.auto else self.sec[f]
            out[f] = {"section": s, "max_ratio": d / weight(s), "kind": "Column", "governing_combo": "AP_SC01_CMB"}
        for f, r in self.composite.items():
            out[f] = {"section": "W24X55", "max_ratio": r, "kind": "CompositeBeam", "governing_combo": ""}
        return {"members": out}

    def autoselect(self, frames):
        self.calls.append(("autoselect", tuple(frames)))
        self.auto = set(frames)

    def current_sections(self):
        return dict(self.sec)

    def assign(self, prop):
        self.calls.append("assign")
        for a in prop["assignments"]:
            assert a["from"] == self.sec[a["frame"]], "from must be the model's section"
            self.sec[a["frame"]] = a["section"]
        self.auto = set()

    def building(self):
        return self.b


def _cols(b):
    return {c["id"]: c["section"] for c in b["columns"]} | {m["id"]: m["section"] for m in b["beams"]}


def test_finalize_takes_etabs_pick_and_mirrors(b):
    from core.finalize import finalize
    # C_A2_S2 is W14X90 with demand 100: ratio 100/90 = 1.111; lightest passing W14 is X109 (0.917)
    ets = _FakeEtabs(b, _cols(b), {"C_A2_S2": 100.0, "C_D2_S2": 50.0}, composite={"CB1": 1.02})
    log, prop = finalize(ets, {"assignments": []}, max_rounds=5)
    assert log["status"] == "passed" and len(log["rounds"]) == 1
    mv = log["rounds"][0]["moves"][0]
    assert (mv["frame"], mv["from"], mv["to"], mv["reason"], mv["ratio_before"]) == \
        ("C_A2_S2", "W14X90", "W14X109", "auto-select", 1.111)
    # the mirror about y = 10.5 gets the same section (W14X90 -> W14X109)
    assert ets.sec["C_A2_S2"] == ets.sec["C_D2_S2"] == "W14X109"
    # check, autoselect, check (pick), assign, check
    assert ets.calls == ["check", ("autoselect", ("C_A2_S2",)), "check", "assign", "check"]
    assert log["composite_over_reported"] == {"CB1": 1.02}


def test_finalize_falls_back_to_step_up(b):
    from core.finalize import finalize, pick
    # auto-select answers a section that is not heavier: one size up (W14X90 -> W14X99)
    assert pick("W14X90", "W14X82", 0.98) == ("W14X99", "step-up (auto-select picked W14X82, not heavier than W14X90)")
    # the list tops out below the demand: 120 / 109 = 1.10 still fails -> one size up from the pick
    assert pick("W14X90", "W14X109", 1.10)[0] == "W14X120"
    # loop: the list only reaches W14X99, demand 110 needs W14X120: two fallback rounds
    ets = _FakeEtabs(b, _cols(b), {"C_A2_S2": 110.0}, auto_limit=99)
    log, _ = finalize(ets, {"assignments": []}, max_rounds=5)
    # round 1: pick W14X99 fails (110/99 = 1.11) -> W14X109 (1.009, still over); round 2 -> W14X120 (0.917)
    assert [m["to"] for r in log["rounds"] for m in r["moves"]] == ["W14X109", "W14X120"]
    assert log["status"] == "passed"


def test_finalize_stops_after_max_rounds(b):
    from core.finalize import finalize
    # auto-select always answers the current section: every round steps one size, demand 200 needs X211
    ets = _FakeEtabs(b, _cols(b), {"C_A2_S2": 200.0}, pick_override={})
    ets.pick_override = type("Current", (dict,), {"__contains__": lambda s, k: True,
                                                   "__getitem__": lambda s, k: ets.sec[k]})()
    log, _ = finalize(ets, {"assignments": []}, max_rounds=2)
    # W14X90 -> 99 -> 109: 200/109 = 1.83 still over after 2 rounds
    assert log["status"] == "not converged" and len(log["rounds"]) == 2
    assert ets.sec["C_A2_S2"] == "W14X109" and log["steel_over"] == {"C_A2_S2": round(200 / 109, 3)}
