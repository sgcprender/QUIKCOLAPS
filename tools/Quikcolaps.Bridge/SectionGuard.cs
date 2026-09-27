#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// Stops an analysis run from quietly becoming a redesign iteration. The next RunAnalysis after a
/// design replaces the analysis section of every auto-select frame whose design section differs
/// (measured, CLAUDE.md), so before running, the two are compared and any difference stops the
/// run unless --accept-design-sections is given.
///
/// Design section: DesignSteel.GetDesignSection, else DesignCompositeBeam.GetDesignSection. With
/// no design results the steel call answers the analysis section and the composite call answers 1
/// (measured), so a model that has never been designed shows no differences.
/// </summary>
internal static class SectionGuard
{
    public const int ExitSectionsDiffer = 4;
    public const string AcceptFlag = "--accept-design-sections";

    public sealed record Row(string Frame, string AutoList, string Analysis, string Design);

    /// <summary>Auto-select frames whose design section is reported and differs from the analysis section.</summary>
    public static List<Row> Differences(IEnumerable<Row> rows) =>
        rows.Where(r => r.AutoList.Length > 0 && r.Design.Length > 0 && r.Design != r.Analysis).ToList();

    public static List<Row> Read(cSapModel sap)
    {
        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        var rows = new List<Row>();
        foreach (var f in frames.Take(n))
        {
            string analysis = "", auto = "";
            Api.Check(sap.FrameObj.GetSection(f, ref analysis, ref auto), $"FrameObj.GetSection {f}");
            if (auto.Length == 0) continue;
            string design = "";
            if (sap.DesignSteel.GetDesignSection(f, ref design) != 0)
            {
                design = "";
                if (sap.DesignCompositeBeam.GetDesignSection(f, ref design) != 0) design = "";
            }
            rows.Add(new Row(f, auto, analysis, design));
        }
        return rows;
    }

    /// <summary>True when the run may go ahead; otherwise the differing frames are printed.</summary>
    public static bool Allows(cSapModel sap, bool accept)
    {
        var rows = Read(sap);
        var differ = Differences(rows);
        Console.Error.WriteLine($"sections  {rows.Count} auto-select frames, {differ.Count} with a design section different from the analysis section");
        if (differ.Count == 0) return true;
        foreach (var r in differ.Take(60)) Console.Error.WriteLine($"          {r.Frame,-6} {r.AutoList,-8} analysis {r.Analysis,-9} design {r.Design}");
        if (differ.Count > 60) Console.Error.WriteLine($"          ... and {differ.Count - 60} more");
        if (accept)
        {
            Console.Error.WriteLine($"          {AcceptFlag}: running anyway; these frames will be analysed with their design sections");
            return true;
        }
        Console.Error.WriteLine($"error: running the analysis now would replace these analysis sections with the design sections. " +
                                $"Not run. Pass {AcceptFlag} to run a redesign iteration on purpose.");
        return false;
    }
}
#endif
