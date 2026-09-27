#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// check-model [--template CS1] [--out check.json]: read-only readiness check before a project
/// starts (app step 0). Each item is pass / warning / fail with one line:
///   ETABS version        SapModel.GetVersion
///   deck floors          floor areas are decks, and each is one bay: every corner on a column
///   template case        CS1 is staged, starts from 1.2D+0.5L (dead ×1.2, live ×0.5, nothing else),
///                        removes exactly one frame, loads exactly one group
///   load patterns        dead and live present; others (wind, quake …) listed, not used
///   auto-select lists    columns and steel girders on an auto-select list
/// Exit 0 when nothing fails, 6 when an item fails.
/// </summary>
internal static class CheckModel
{
    public const int ExitFailed = 6;
    private sealed record Item(string Name, string Status, string Message);

    public static int Run(cSapModel sap, string modelPath, string templateName, string outPath)
    {
        var items = new List<Item>
        {
            Guard("ETABS version", () => Version(sap)),
            Guard("Deck floors", () => Decks(sap)),
            Guard("Template case", () => Template(sap, templateName)),
            Guard("Load patterns", () => Patterns(sap)),
            Guard("Auto-select lists", () => AutoLists(sap)),
        };
        foreach (var i in items) Console.WriteLine($"{i.Status,-8} {i.Name,-18} {i.Message}");
        Json.Write(outPath, new { model = Path.GetFileNameWithoutExtension(modelPath), model_path = modelPath, locked = sap.GetModelIsLocked(), items });
        return items.Any(i => i.Status == "fail") ? ExitFailed : 0;
    }

    private static Item Guard(string name, Func<(string, string)> f)
    {
        try { var (s, m) = f(); return new Item(name, s, m); }
        catch (Exception e) { return new Item(name, "fail", e.Message); }
    }

    private static (string, string) Version(cSapModel sap)
    {
        string v = ""; double n = 0;
        Api.Check(sap.GetVersion(ref v, ref n), "SapModel.GetVersion");
        // MyVersionNumber is not the major version (measured: 23.3.0 does not answer >= 23); use the string
        return v.StartsWith("23.") ? ("pass", $"ETABS {v} (the bridge was checked against ETABS 23, API 2.16)")
            : ("warning", $"ETABS {v}: the bridge was checked against ETABS 23 (API 2.16); signatures may differ");
    }

    private static (string, string) Decks(cSapModel sap)
    {
        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        var colPts = new List<(double X, double Y)>();
        foreach (var f in frames.Take(n).Where(f => ColumnStack.IsColumn(sap, f)))
        {
            string i = "", j = "";
            sap.FrameObj.GetPoints(f, ref i, ref j);
            var p = Export.Coord(sap, i);
            colPts.Add((p.X, p.Y));
        }
        n = 0; string[] areas = Array.Empty<string>();
        Api.Check(sap.AreaObj.GetNameList(ref n, ref areas), "AreaObj.GetNameList");
        int floors = 0, decks = 0; var offGrid = new List<string>();
        var deckOf = new Dictionary<string, bool>();
        foreach (var a in areas.Take(n))
        {
            eAreaDesignOrientation o = default;
            if (sap.AreaObj.GetDesignOrientation(a, ref o) != 0 || o != eAreaDesignOrientation.Floor) continue;
            floors++;
            string prop = ""; sap.AreaObj.GetProperty(a, ref prop);
            if (!deckOf.TryGetValue(prop, out var d)) deckOf[prop] = d = Export.IsDeck(sap, prop);
            if (d) decks++;
            int np = 0; string[] pts = Array.Empty<string>();
            sap.AreaObj.GetPoints(a, ref np, ref pts);
            if (pts.Take(np).Any(p => { var c = Export.Coord(sap, p); return !colPts.Any(q => Math.Abs(q.X - c.X) < 0.05 && Math.Abs(q.Y - c.Y) < 0.05); }))
                offGrid.Add(a);
        }
        if (floors == 0) return ("fail", "no floor areas");
        if (decks < floors) return ("warning", $"{floors} floor areas, {floors - decks} not decks (loads to beams are measured for decks only)");
        return offGrid.Count == 0
            ? ("pass", $"{floors} deck floor areas, each one bay (every corner on a column)")
            : ("warning", $"{floors} deck floor areas; {offGrid.Count} have a corner off the column grid (e.g. {string.Join(", ", offGrid.Take(5))}): not one area per bay");
    }

    private static (string, string) Template(cSapModel sap, string name)
    {
        var t = CaseTemplate.Read(sap, name);
        _ = t.RemovedFrame; _ = t.LoadedGroup;   // throw unless exactly one each
        var loads = CaseLoads.Initial(sap, t.InitialCase);
        var wrong = new List<string>();
        foreach (var l in loads)
        {
            eLoadPatternType pt = default;
            sap.LoadPatterns.GetLoadType(l.Name, ref pt);
            var want = pt.ToString() switch { "Dead" or "SuperDead" => 1.2, "Live" or "ReduceLive" => 0.5, _ => double.NaN };
            if (double.IsNaN(want) || Math.Abs(l.Scale - want) > 1e-6) wrong.Add($"{l.Scale}×{l.Name} ({pt})");
        }
        var desc = string.Join(" + ", loads.Select(l => $"{l.Scale}×{l.Name}"));
        return wrong.Count == 0
            ? ("pass", $"{name}: initial '{t.InitialCase}' = {desc}; removes frame {t.RemovedFrame}; loads group '{t.LoadedGroup}'")
            : ("warning", $"{name}: initial '{t.InitialCase}' = {desc}; not 1.2D + 0.5L: {string.Join(", ", wrong)}");
    }

    private static (string, string) Patterns(cSapModel sap)
    {
        var flags = new List<string>();
        var kinds = Export.PatternKinds(sap, flags);
        var dead = kinds.Where(k => k.Value == "sdl").Select(k => k.Key).ToList();
        var live = kinds.Where(k => k.Value == "live").Select(k => k.Key).ToList();
        var ignored = flags.Select(f => f.Split(' ')[2]).ToList();
        if (dead.Count == 0 || live.Count == 0) return ("fail", $"dead: {string.Join(", ", dead)}; live: {string.Join(", ", live)}; both are needed");
        return ("pass", $"dead {string.Join(", ", dead)}; live {string.Join(", ", live)}" +
                        (ignored.Count > 0 ? $"; not used (no wind or quake in AP): {string.Join(", ", ignored)}" : ""));
    }

    private static (string, string) AutoLists(cSapModel sap)
    {
        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        int cols = 0, colsAuto = 0, girders = 0, girdersAuto = 0;
        foreach (var f in frames.Take(n))
        {
            string s = "", auto = "";
            sap.FrameObj.GetSection(f, ref s, ref auto);
            if (ColumnStack.IsColumn(sap, f)) { cols++; if (auto.Length > 0) colsAuto++; continue; }
            int proc = -1;
            if (sap.FrameObj.GetDesignProcedure(f, ref proc) == 0 && proc == 1) { girders++; if (auto.Length > 0) girdersAuto++; }
        }
        var msg = $"columns {colsAuto}/{cols}, steel girders {girdersAuto}/{girders} on an auto-select list";
        if (colsAuto == 0 && girdersAuto == 0) return ("fail", msg + ": the redesign steps need them");
        return colsAuto == cols && girdersAuto == girders ? ("pass", msg)
            : ("warning", msg + " (fixed sections are kept as they are, e.g. after assign-sections)");
    }
}
#endif
