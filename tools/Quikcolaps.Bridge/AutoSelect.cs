#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// autoselect --frames 9,422 [--commit]: gives fixed frames back an auto-select list, so the next
/// design picks their section (the finalize loop).
///
/// The list is a copy of the frame's original steel auto-select list (the one that contains its
/// current section; lists named FIN_* are skipped) that starts at the frame's current section:
/// FIN_&lt;list&gt;_&lt;section&gt;. Starting there keeps the analysis section, so the next run gives the
/// same forces as the last one and ETABS's pick answers "what does this member need".
///
/// Measured on locked AP2 (2026-09-26): PropFrame.SetAutoSelectSteel and FrameObj.SetSection both
/// answer 1 and change nothing while the model is locked, so --commit unlocks first (ModelLock;
/// deletes the results) and a run is needed before the design. Read-back: the frame's auto list
/// is the new one and its analysis section is unchanged. Dry run by default.
/// </summary>
internal static class AutoSelect
{
    public static int Run(cSapModel sap, string framesCsv, bool commit)
    {
        var frames = framesCsv.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        if (frames.Count == 0) { Console.Error.WriteLine("autoselect --frames F1,F2 [--commit]"); return 2; }
        var lists = SteelLists(sap);
        var plan = new List<(string Frame, string Section, string List, string Temp)>();
        var problems = new List<string>();
        foreach (var f in frames)
        {
            string s = "", auto = "";
            if (sap.FrameObj.GetSection(f, ref s, ref auto) != 0) { problems.Add($"frame {f} does not exist"); continue; }
            var list = lists.FirstOrDefault(l => l.Value.Contains(s)).Key;
            if (list is null) { problems.Add($"frame {f}: no steel auto-select list contains its section {s}"); continue; }
            plan.Add((f, s, list, $"FIN_{list}_{s}"));
            Console.WriteLine($"{f,-7} {s,-10} now auto '{auto}'  → {list} starting at {s} as FIN_{list}_{s}");
        }
        foreach (var p in problems) Console.Error.WriteLine($"problem   {p}");
        if (problems.Count > 0) { Console.Error.WriteLine("error: nothing written."); return 1; }
        if (!commit) { ModelLock.EnsureUnlocked(sap, false, "autoselect"); Console.WriteLine("Dry run — add --commit to write."); return 0; }

        ModelLock.EnsureUnlocked(sap, true, "autoselect");
        foreach (var g in plan.GroupBy(p => p.Temp))
        {
            var first = g.First();
            var names = lists[first.List].ToArray();
            Api.Check(sap.PropFrame.SetAutoSelectSteel(first.Temp, names.Length, ref names, first.Section,
                $"finalize: {first.List} starting at {first.Section}"), $"PropFrame.SetAutoSelectSteel {first.Temp}");
        }
        var failed = new List<string>();
        foreach (var p in plan)
        {
            var ret = sap.FrameObj.SetSection(p.Frame, p.Temp, eItemType.Objects);
            string s = "", auto = "";
            sap.FrameObj.GetSection(p.Frame, ref s, ref auto);
            if (ret != 0 || auto != p.Temp || s != p.Section)
                failed.Add($"frame {p.Frame}: SetSection returned {ret}; reads back {s} auto '{auto}', wanted {p.Section} in {p.Temp}");
        }
        foreach (var f in failed) Console.Error.WriteLine($"READ BACK {f}");
        Console.WriteLine($"{plan.Count - failed.Count} of {plan.Count} frame(s) on an auto-select list, read back. The model is not saved.");
        return failed.Count == 0 ? 0 : 1;
    }

    /// <summary>Every steel auto-select list (GetAutoSelectSteel answers 0) except the FIN_* copies: name → its sections.</summary>
    private static Dictionary<string, List<string>> SteelLists(cSapModel sap)
    {
        int n = 0; string[] props = Array.Empty<string>();
        Api.Check(sap.PropFrame.GetNameList(ref n, ref props), "PropFrame.GetNameList");
        var lists = new Dictionary<string, List<string>>();
        foreach (var p in props.Take(n).Where(p => !p.StartsWith("FIN_", StringComparison.Ordinal)))
        {
            int m = 0; string[] secs = Array.Empty<string>(); string start = "", notes = "", guid = "";
            if (sap.PropFrame.GetAutoSelectSteel(p, ref m, ref secs, ref start, ref notes, ref guid) == 0 && m > 0)
                lists[p] = secs.Take(m).ToList();
        }
        return lists;
    }
}
#endif
