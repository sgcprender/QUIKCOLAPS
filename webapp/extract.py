"""Pull progressive-collapse results out of ETABS into data.json for the web viewer.

Collapse model (QUIKCOLAPS2) must be open in ETABS with analysis + steel design run.
Baseline model (QUIKCOLAPS) is opened in a hidden second ETABS instance, only to read its design sections.
"""
import json, re, sys
from collections import defaultdict
import comtypes.client

helper = comtypes.client.CreateObject('ETABSv1.Helper')
import comtypes.gen.ETABSv1 as E
helper = helper.QueryInterface(E.cHelper)

BASELINE = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\sxmoore\Downloads\QUIKCOLAPS.EDB'
LB_IN = 1


def plf(section):
    """Nominal weight (lb/ft) from a W-shape name like W14X211."""
    m = re.match(r'W\d+X([\d.]+)$', section)
    return float(m.group(1)) if m else 0.0


def summary(m):
    """{frame: (design section, ratio, governing combo)} for all steel frames."""
    out = {}
    for nm in m.FrameObj.GetNameList()[1]:  # group 'All' returns nothing in v23, so go per frame
        r = m.DesignSteel.GetSummaryResults(nm, 0)
        if r[0]:
            out[nm] = (m.DesignSteel.GetDesignSection(nm)[0], round(r[2][0], 3), r[5][0])
    return out


INTACT = '1.2D+0.5L'  # same gravity combo on the undamaged structure


def station_forces(m, case):
    """{(frame, station): (P kip, M3 kip-ft)} for every frame, last step of the case."""
    m.Results.Setup.DeselectAllCasesAndCombosForOutput()
    m.Results.Setup.SetCaseSelectedForOutput(case)
    fr = m.Results.FrameForce('All', 2)  # 2 = group
    return {(fr[1][i], round(fr[2][i], 1)): (fr[8][i] / 1000, fr[13][i] / 12000) for i in range(fr[0])}


def grid_lines(m):
    """[{axis: 'X'|'Y', id, at (ft)}] from the Cartesian grid table."""
    r = m.DatabaseTables.GetTableForDisplayArray('Grid Definitions - Grid Lines', [], '')
    cols, n, rows = r[2], r[3], r[4]
    w = len(cols)
    out = []
    for i in range(n):
        row = dict(zip(cols, rows[i * w:(i + 1) * w]))
        if 'Cartesian' in row['LineType']:
            out.append(dict(axis=row['LineType'][0], id=row['ID'], at=float(row['Ordinate']) / 12))
    return out


def grid_of(grids, p, tol=0.5):
    """'B-3' style grid intersection for a plan point (ft); '' if off-grid."""
    x = next((g['id'] for g in grids if g['axis'] == 'X' and abs(g['at'] - p[0]) < tol), '')
    y = next((g['id'] for g in grids if g['axis'] == 'Y' and abs(g['at'] - p[1]) < tol), '')
    return f'{x}-{y}' if x and y else x or y


def attach():
    return helper.GetObject('CSI.ETABS.API.ETABSObject').SapModel


def baseline_sections(path):
    app = helper.CreateObjectProgID('CSI.ETABS.API.ETABSObject')
    app.ApplicationStart()
    try:
        app.Hide()
        m = app.SapModel
        assert m.File.OpenFile(path) == 0, f'could not open {path}'
        m.SetPresentUnits(LB_IN)
        if not m.DesignSteel.GetResultsAvailable():
            print('baseline has no design results; falling back to analysis sections')
            names = m.FrameObj.GetNameList()[1]
            return {n: m.FrameObj.GetSection(n)[0] for n in names}
        return {k: v[0] for k, v in summary(m).items()}
    finally:
        app.ApplicationExit(False)  # never save the baseline


def main():
    m = attach()
    print('collapse model:', m.GetModelFilename())
    units0 = m.GetPresentUnits()
    step0 = m.Results.Setup.GetOptionMultiStepStatic()[0]
    m.SetPresentUnits(LB_IN)
    try:
        data = extract(m)
    finally:
        m.SetPresentUnits(units0)
        m.Results.Setup.SetOptionMultiStepStatic(step0)

    print('opening baseline:', BASELINE)
    base = baseline_sections(BASELINE)
    add_steel(data, base)
    with open('data.json', 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    print(f"wrote data.json: {len(data['frames'])} frames, {len(data['cases'])} cases, "
          f"+{data['totalExtraLb']:,.0f} lb steel")


def extract(m):
    # geometry (ft)
    r = m.FrameObj.GetAllFrames()
    n, names, props, stories = r[0], r[1], r[2], r[3]
    x1, y1, z1, x2, y2, z2 = (r[i] for i in (6, 7, 8, 9, 10, 11))
    des = summary(m)
    grids = grid_lines(m)
    frames = {}
    for i in range(n):
        nm = names[i]
        label = m.FrameObj.GetLabelFromName(nm)[0]
        sec, ratio, combo = des.get(nm, (props[i], None, ''))
        a = [x1[i] / 12, y1[i] / 12, z1[i] / 12]
        b = [x2[i] / 12, y2[i] / 12, z2[i] / 12]
        frames[nm] = dict(label=label, story=stories[i], a=a, b=b, sec=sec, ratio=ratio, combo=combo,
                          col=abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6)
        if frames[nm]['col']:
            frames[nm]['grid'] = grid_of(grids, a)

    # deck areas (ft)
    px = {}
    pr = m.PointObj.GetAllPoints()
    for i in range(pr[0]):
        px[pr[1][i]] = [pr[2][i] / 12, pr[3][i] / 12, pr[4][i] / 12]
    areas = {}
    for a in m.AreaObj.GetNameList()[1]:
        pts = m.AreaObj.GetPoints(a)[1]
        areas[a] = [px[p] for p in pts]

    # collapse cases: removed column + loaded influence area from staged-construction stage 1
    m.Results.Setup.SetOptionMultiStepStatic(3)  # last step
    intact = station_forces(m, INTACT)
    cases = []
    for c in m.LoadCases.GetNameList()[1]:
        if not c.startswith('CS_C'):
            continue
        sd = m.LoadCases.StaticNonlinearStaged.GetStageData_2(c, 1)
        ops, objtypes, objs = sd[2], sd[3], sd[4]
        removed = [objs[i] for i in range(sd[1]) if ops[i] == 2 and objtypes[i] == 'Frame']
        group = next((objs[i] for i in range(sd[1]) if ops[i] == 4), '')
        g = m.GroupDef.GetAssignments(group) if group else (0, (), ())
        infl = [g[2][i] for i in range(g[0]) if g[1][i] == 5]  # 5 = area

        # per frame: peak |P| (kip) / |M3| (kip-ft) in the collapse case, and peak change vs the intact structure
        P, M, dP, dM = (defaultdict(float) for _ in range(4))
        for (o, sta), (p, m3) in station_forces(m, c).items():
            p0, m0 = intact.get((o, sta), (0, 0))
            P[o], M[o] = max(P[o], abs(p)), max(M[o], abs(m3))
            dP[o], dM[o] = max(dP[o], abs(p - p0)), max(dM[o], abs(m3 - m0))
        r2 = lambda d: {k: round(v, 1) for k, v in d.items() if v >= 0.05}
        cases.append(dict(name=c, combo=c + '_CMB', removed=removed,
                          removedLabel=[frames[r]['label'] + ' @ ' + frames[r]['story'] for r in removed],
                          influence=infl, P=r2(P), M=r2(M), dP=r2(dP), dM=r2(dM)))
        print('  ', c, 'removed', removed, 'infl areas', len(infl))
    cases.sort(key=lambda c: int(re.search(r'CS_C(\d+)', c['name']).group(1)))
    return dict(model=m.GetModelFilename(), frames=frames, areas=areas, cases=cases, grids=grids)


def add_steel(data, base):
    """Upsized member weight delta, attributed to the collapse case whose combo governs it."""
    by_combo = defaultdict(list)
    total = base_total = 0.0
    for nm, f in data['frames'].items():
        b = base.get(nm, f['sec'])
        f['baseSec'] = b
        L = sum((p - q) ** 2 for p, q in zip(f['a'], f['b'])) ** 0.5
        d = (plf(f['sec']) - plf(b)) * L
        f['extraLb'] = round(d, 1)
        base_total += plf(b) * L
        if d > 0:
            total += d
            by_combo[f['combo']].append(nm)
    for c in data['cases']:
        up = by_combo.get(c['combo'], [])
        c['upsized'] = up
        c['extraLb'] = round(sum(data['frames'][n]['extraLb'] for n in up), 1)
    data['totalExtraLb'] = round(total, 1)
    data['baseTotalLb'] = round(base_total, 1)
    data['unattributedLb'] = round(total - sum(c['extraLb'] for c in data['cases']), 1)


if __name__ == '__main__':
    # self-check for the weight math
    assert plf('W14X211') == 211 and plf('AS-W14') == 0
    G = [dict(axis='X', id='B', at=24.0), dict(axis='Y', id='3', at=48.0)]
    assert grid_of(G, [24.1, 48, 0]) == 'B-3' and grid_of(G, [10, 10, 0]) == ""
    main()
