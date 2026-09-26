"""Generate fixtures/demo_building.json: a synthetic 4-story steel frame.

This is NOT an ETABS export. It mimics the shape of what `quikcolaps-bridge export`
produces (see docs/schema/building.schema.json) so the rest of the team can
work without ETABS. Replace it with a real export once the bridge works.

Layout (plan, metres):  x grids 1..6 at 0, 8, 16, 24, 32, 36  (last bay short: 4 m)
                        y grids A..D at 0, 7, 14, 21
The short last bay is deliberate: it triggers the bay-size-change candidate rule.
Column size changes at Story3 -> triggers the "story above splice" rule.
"""
import json
from pathlib import Path

X = [0.0, 8.0, 16.0, 24.0, 32.0, 36.0]
Y = [0.0, 7.0, 14.0, 21.0]
XN = ["1", "2", "3", "4", "5", "6"]
YN = ["A", "B", "C", "D"]

LEVELS = [("Base", 0.0), ("L1", 4.0), ("L2", 7.6), ("L3", 11.2), ("ROOF", 14.8)]

SECTIONS = {
    "W14X90": {"shape": "W", "d_m": 0.356, "mass_kg_per_m": 134.0},
    "W14X61": {"shape": "W", "d_m": 0.353, "mass_kg_per_m": 90.8},
    "W21X44": {"shape": "W", "d_m": 0.525, "mass_kg_per_m": 65.5},
    "W18X35": {"shape": "W", "d_m": 0.450, "mass_kg_per_m": 52.1},
}

FLOOR_LOADS = {"sdl_kpa": 1.5, "slab_sw_kpa": 2.6, "live_kpa": 2.4, "roof_live_kpa": 0.0, "snow_kpa": 0.0}
ROOF_LOADS = {"sdl_kpa": 1.0, "slab_sw_kpa": 2.6, "live_kpa": 0.0, "roof_live_kpa": 1.0, "snow_kpa": 1.2}
FACADE_KN_PER_M = 3.5
PARAPET_KN_PER_M = 1.5


def main() -> None:
    levels = [{"name": n, "z": z} for n, z in LEVELS]
    stories = []
    for i in range(1, len(LEVELS)):
        stories.append({
            "name": f"Story{i}",
            "bottom_level": LEVELS[i - 1][0],
            "top_level": LEVELS[i][0],
            "bottom_z": LEVELS[i - 1][1],
            "top_z": LEVELS[i][1],
            "below_grade": False,
            "occupied": True,
        })

    columns = []
    for s_idx, st in enumerate(stories, start=1):
        section = "W14X90" if s_idx <= 2 else "W14X61"
        for xi, x in enumerate(X):
            for yi, y in enumerate(Y):
                loc = f"{YN[yi]}{XN[xi]}"
                columns.append({
                    "id": f"C_{loc}_S{s_idx}",
                    "location_id": loc,
                    "x": x, "y": y,
                    "story": st["name"],
                    "bottom_z": st["bottom_z"], "top_z": st["top_z"],
                    "section": section,
                    "splice_at_bottom": s_idx == 3,
                })

    beams, bays, line_loads = [], [], []
    outline = [[X[0], Y[0]], [X[-1], Y[0]], [X[-1], Y[-1]], [X[0], Y[-1]]]
    for lvl_name, z in LEVELS[1:]:
        roof = lvl_name == "ROOF"
        # beams along x (girders W21X44) and along y (W18X35)
        for yi, y in enumerate(Y):
            for xi in range(len(X) - 1):
                bid = f"B_{lvl_name}_{YN[yi]}{XN[xi]}-{YN[yi]}{XN[xi+1]}"
                perim = yi in (0, len(Y) - 1)
                beams.append({"id": bid, "level": lvl_name, "z": z,
                              "i": [X[xi], y], "j": [X[xi + 1], y],
                              "section": "W21X44", "perimeter": perim})
                if perim:
                    line_loads.append({"beam_id": bid, "pattern": "FACADE",
                                       "w_kn_per_m": PARAPET_KN_PER_M if roof else FACADE_KN_PER_M})
        for xi, x in enumerate(X):
            for yi in range(len(Y) - 1):
                bid = f"B_{lvl_name}_{YN[yi]}{XN[xi]}-{YN[yi+1]}{XN[xi]}"
                perim = xi in (0, len(X) - 1)
                beams.append({"id": bid, "level": lvl_name, "z": z,
                              "i": [x, Y[yi]], "j": [x, Y[yi + 1]],
                              "section": "W18X35", "perimeter": perim})
                if perim:
                    line_loads.append({"beam_id": bid, "pattern": "FACADE",
                                       "w_kn_per_m": PARAPET_KN_PER_M if roof else FACADE_KN_PER_M})
        for xi in range(len(X) - 1):
            for yi in range(len(Y) - 1):
                x0, x1, y0, y1 = X[xi], X[xi + 1], Y[yi], Y[yi + 1]
                bays.append({
                    "id": f"A_{lvl_name}_{YN[yi]}{XN[xi]}",
                    "level": lvl_name, "z": z,
                    "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                    "loads": dict(ROOF_LOADS if roof else FLOOR_LOADS),
                })

    building = {
        "meta": {
            "name": "Demo 4-story steel frame (synthetic)",
            "source": "synthetic",
            "units": {"length": "m", "force": "kN", "pressure": "kPa"},
            "material": "steel",
        },
        "grids": {"x": [{"name": n, "coord": c} for n, c in zip(XN, X)],
                  "y": [{"name": n, "coord": c} for n, c in zip(YN, Y)]},
        "levels": levels,
        "stories": stories,
        "outlines": {lvl: outline for lvl, _ in LEVELS[1:]},
        "sections": SECTIONS,
        "columns": columns,
        "beams": beams,
        "bays": bays,
        "line_loads": line_loads,
        "point_loads": [],
        "zones": [],
        "flags": [],
    }
    out = Path(__file__).resolve().parents[1] / "fixtures" / "demo_building.json"
    out.write_text(json.dumps(building, indent=2))
    print(f"wrote {out} ({len(columns)} columns, {len(beams)} beams, {len(bays)} bays)")


if __name__ == "__main__":
    main()
