#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// scenario-ratios --scenarios scenarios.json --out scenario_ratios.json [--commit]: each steel
/// member's ratio under each scenario's combination, for the app's scenario heat map.
///
/// ETABS reports only the governing ratio per member, and the design database tables
/// ("Steel Frame Design Summary - AISC 360-16") carry the same governing row (measured
/// 2026-09-27: no per-combination table). So this is a cached batch: for each scenario, the steel
/// strength selection is set to that one combination, steel design runs (no analysis), and
/// DesignSteel.GetSummaryResults_3 is read. Composite beams are not included.
///
/// A design with one combination would re-pick the auto-select frames, so before the batch every
/// auto-select frame's design section is pinned to its analysis section
/// (DesignSteel.SetDesignSection(frame, section, LastAnalysis: false), documented) and each pass
/// reports how many still moved. Afterwards the full selection is restored (read back), the design
/// sections are reset to the analysis sections (SetDesignSection(frame, "", true), measured) and
/// the full steel design runs once, so the model ends as it started. Needs analysis results.
/// Dry run by default.
/// </summary>
internal static class ScenarioRatios
{
    public static int Run(cSapModel sap, int pid, string scenariosPath, string outPath, bool commit)
    {
        var scenarios = Json.ActiveScenarios(Json.Read(scenariosPath)).Select(s => ((string)s["id"]!, (string)s["combo_name"]!)).ToList();
        int n = 0; string[] saved = Array.Empty<string>();
        Api.Check(sap.DesignSteel.GetComboStrength(ref n, ref saved), "DesignSteel.GetComboStrength");
        var selection = saved.Take(n).ToList();
        var missing = scenarios.Where(s => !selection.Contains(s.Item2)).Select(s => s.Item2).ToList();
        Console.WriteLine($"scenarios {scenarios.Count}; steel selection {selection.Count} combos" + (missing.Count > 0 ? $"; not selected now: {string.Join(", ", missing)}" : ""));
        if (!sap.GetModelIsLocked()) throw new InvalidOperationException("no analysis results (the model is unlocked): run the AP cases first");
        if (!commit) { Console.WriteLine($"Dry run — add --commit to run {scenarios.Count} steel design(s) and restore."); return 0; }

        var auto = AutoFrames(sap);
        foreach (var (f, s) in auto) Api.Check(sap.DesignSteel.SetDesignSection(f, s, false, eItemType.Objects), $"DesignSteel.SetDesignSection {f}");
        var ratios = new Dictionary<string, Dictionary<string, double>>();
        var moved = new Dictionary<string, int>();
        try
        {
            foreach (var (id, combo) in scenarios)
            {
                foreach (var c in selection) Api.Check(sap.DesignSteel.SetComboStrength(c, c == combo), $"DesignSteel.SetComboStrength {c}");
                if (!selection.Contains(combo)) Api.Check(sap.DesignSteel.SetComboStrength(combo, true), $"DesignSteel.SetComboStrength {combo}");
                Api.Check(Watch.During(pid, "DesignSteel.StartDesign", () => sap.DesignSteel.StartDesign()), "DesignSteel.StartDesign");
                var rows = Summary(sap);
                ratios[id] = rows.Values.ToDictionary(r => r.Frame, r => Math.Round(r.Ratio, 4));
                moved[id] = auto.Count(a => rows.TryGetValue(a.Frame, out var r) && r.Section != a.Section);
                Console.Error.WriteLine($"{id,-6} {combo,-14} max {rows.Values.Max(r => r.Ratio):0.000}; auto-select frames moved {moved[id]}");
                if (!selection.Contains(combo)) Api.Check(sap.DesignSteel.SetComboStrength(combo, false), $"DesignSteel.SetComboStrength {combo}");
            }
        }
        finally
        {
            foreach (var c in selection) sap.DesignSteel.SetComboStrength(c, true);
            foreach (var (f, _) in auto) sap.DesignSteel.SetDesignSection(f, "", true, eItemType.Objects);
        }
        int m = 0; string[] back = Array.Empty<string>();
        Api.Check(sap.DesignSteel.GetComboStrength(ref m, ref back), "DesignSteel.GetComboStrength");
        if (!back.Take(m).ToHashSet().SetEquals(selection)) throw new InvalidOperationException("steel selection not restored");
        Api.Check(Watch.During(pid, "DesignSteel.StartDesign", () => sap.DesignSteel.StartDesign()), "DesignSteel.StartDesign");
        Console.Error.WriteLine($"restored  steel selection ({selection.Count} combos, read back) and design sections; full steel design run");
        Json.Write(outPath, new
        {
            source = "one steel design per scenario combination (bridge scenario-ratios); composite beams not included",
            auto_select_frames = auto.Count,
            auto_select_moved = moved,
            ratios,
        });
        return 0;
    }

    private static List<(string Frame, string Section)> AutoFrames(cSapModel sap)
    {
        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        var list = new List<(string, string)>();
        foreach (var f in frames.Take(n))
        {
            string s = "", auto = "";
            sap.FrameObj.GetSection(f, ref s, ref auto);
            int proc = -1;
            if (auto.Length > 0 && sap.FrameObj.GetDesignProcedure(f, ref proc) == 0 && proc == 1) list.Add((f, s));
        }
        return list;
    }

    private sealed record Row(string Frame, string Section, double Ratio);

    private static Dictionary<string, Row> Summary(cSapModel sap)
    {
        int n = 0; string[] frame = Array.Empty<string>(), sect = Array.Empty<string>(), st = Array.Empty<string>(), pmm = Array.Empty<string>(),
            vmaj = Array.Empty<string>(), vmin = Array.Empty<string>();
        eFrameDesignOrientation[] type = Array.Empty<eFrameDesignOrientation>();
        double[] r = Array.Empty<double>(), p = Array.Empty<double>(), m2 = Array.Empty<double>(), m3 = Array.Empty<double>(), v2 = Array.Empty<double>(), v3 = Array.Empty<double>();
        Api.Check(sap.DesignSteel.GetSummaryResults_3("All", ref n, ref frame, ref type, ref sect, ref st, ref pmm, ref r, ref p, ref m2, ref m3,
            ref vmaj, ref v2, ref vmin, ref v3, eItemType.Group), "DesignSteel.GetSummaryResults_3");
        var rows = new Dictionary<string, Row>();
        for (var k = 0; k < n; k++) rows[frame[k]] = new Row(frame[k], sect[k], r[k]);
        return rows;
    }
}
#endif
