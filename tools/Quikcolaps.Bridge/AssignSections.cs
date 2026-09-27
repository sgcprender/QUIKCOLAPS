#if CSI
using System.Text.Json.Nodes;
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// assign-sections: sets analysis sections from a file as fixed sections (no auto-select list),
/// for the propagated redesign (ap/web/data/propagation.json, written by `python -m core.propagate`).
///
/// File: { "assignments": [ { "frame": "165", "section": "W14X145", "from": "W14X61" }, ... ] }.
/// "from" is optional: when given, the frame's current analysis section must equal it, so a file
/// made from an older state of the model is refused rather than applied.
///
/// Dry run by default: checks every frame and section exists and prints what would change.
/// --commit: stops without writing if the dry-run checks find a problem; otherwise unlocks the
/// model (deletes the analysis results), calls FrameObj.SetSection (documented: assigns a frame
/// section property) and reads each frame back with FrameObj.GetSection: the analysis section
/// must be the new one and the auto-select list must be blank. The help does not say whether
/// SetSection clears an auto-select list; the read-back decides (VERIFY on the first commit).
/// </summary>
internal static class AssignSections
{
    private sealed record Item(string Frame, string Section, string? From);

    public static int Run(cSapModel sap, string path, bool commit)
    {
        var items = Read(path);
        int n = 0; string[] props = Array.Empty<string>();
        Api.Check(sap.PropFrame.GetNameList(ref n, ref props), "PropFrame.GetNameList");
        var defined = props.Take(n).ToHashSet(StringComparer.Ordinal);
        n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        var exists = frames.Take(n).ToHashSet(StringComparer.Ordinal);

        var problems = new List<string>();
        var change = new List<Item>();
        Console.WriteLine($"{"frame",-7} {"now",-10} {"auto",-8} {"to",-10} note");
        foreach (var it in items)
        {
            if (!exists.Contains(it.Frame)) { problems.Add($"frame {it.Frame} does not exist"); continue; }
            if (!defined.Contains(it.Section)) { problems.Add($"frame {it.Frame}: section {it.Section} is not defined"); continue; }
            string now = "", auto = "";
            Api.Check(sap.FrameObj.GetSection(it.Frame, ref now, ref auto), $"FrameObj.GetSection {it.Frame}");
            var note = "";
            if (it.From is not null && it.From != now) { problems.Add($"frame {it.Frame}: file says from {it.From}, model has {now}"); note = "FROM DIFFERS"; }
            else if (now == it.Section && auto.Length == 0) note = "already fixed at this section";
            else change.Add(it);
            Console.WriteLine($"{it.Frame,-7} {now,-10} {auto,-8} {it.Section,-10} {note}");
        }
        foreach (var p in problems) Console.Error.WriteLine($"problem   {p}");
        Console.WriteLine($"\n{items.Count} assignment(s): {change.Count} to write, {items.Count - change.Count - problems.Count} already in place, {problems.Count} problem(s).");

        ModelLock.EnsureUnlocked(sap, commit && problems.Count == 0 && change.Count > 0, "assign-sections");
        if (problems.Count > 0)
        {
            Console.Error.WriteLine("error: the file does not match the model; nothing written.");
            return 1;
        }
        if (!commit) { Console.WriteLine("Dry run — add --commit to write."); return 0; }
        if (change.Count == 0) { Console.WriteLine("Nothing to write."); return 0; }

        var failed = new List<string>();
        foreach (var it in change)
        {
            var ret = sap.FrameObj.SetSection(it.Frame, it.Section, eItemType.Objects);
            string now = "", auto = "";
            sap.FrameObj.GetSection(it.Frame, ref now, ref auto);
            if (ret != 0 || now != it.Section || auto.Length != 0)
                failed.Add($"frame {it.Frame}: SetSection returned {ret}; reads back {now} auto '{auto}', wanted {it.Section} with no auto list");
        }
        foreach (var f in failed) Console.Error.WriteLine($"READ BACK {f}");
        Console.WriteLine($"{change.Count - failed.Count} of {change.Count} written and read back. The model is not saved.");
        return failed.Count == 0 ? 0 : 1;
    }

    private static List<Item> Read(string path)
    {
        if (!File.Exists(path)) throw new InvalidOperationException($"{path} not found (write it with python -m core.propagate)");
        var arr = Json.Read(path)["assignments"]?.AsArray()
                  ?? throw new InvalidOperationException($"{path} has no \"assignments\" list");
        var items = new List<Item>();
        foreach (var a in arr)
        {
            var frame = (string?)a?["frame"];
            var section = (string?)a?["section"];
            if (string.IsNullOrEmpty(frame) || string.IsNullOrEmpty(section))
                throw new InvalidOperationException($"{path}: every assignment needs \"frame\" and \"section\" ({a?.ToJsonString()})");
            items.Add(new Item(frame, section, (string?)a?["from"]));
        }
        var dup = items.GroupBy(i => i.Frame).Where(g => g.Select(i => i.Section).Distinct().Count() > 1).Select(g => g.Key).ToList();
        if (dup.Count > 0) throw new InvalidOperationException($"{path}: frames with more than one section: {string.Join(", ", dup)}");
        return items.DistinctBy(i => i.Frame).ToList();
    }
}
#endif
