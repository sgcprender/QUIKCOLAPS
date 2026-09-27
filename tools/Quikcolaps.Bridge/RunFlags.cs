#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// Lean runs: flag only the cases a step needs, then put every flag back.
/// Analyze.GetRunCaseFlag (ref NumberItems, ref CaseName, ref Run) and SetRunCaseFlag(Name, Run,
/// All = false) are documented; measured on AP2: set and restore read back exactly. Setting the
/// flags does not unlock the model.
/// </summary>
internal static class RunFlags
{
    public static Dictionary<string, bool> Read(cSapModel sap)
    {
        int n = 0; string[] c = Array.Empty<string>(); bool[] r = Array.Empty<bool>();
        Api.Check(sap.Analyze.GetRunCaseFlag(ref n, ref c, ref r), "Analyze.GetRunCaseFlag");
        return c.Take(n).Zip(r).ToDictionary(p => p.First, p => p.Second);
    }

    /// <summary>Flags exactly <paramref name="cases"/> to run; returns the flags as they were. Throws on a missing case or a wrong read-back.</summary>
    public static Dictionary<string, bool> Only(cSapModel sap, IReadOnlyCollection<string> cases)
    {
        var original = Read(sap);
        var missing = cases.Where(c => !original.ContainsKey(c)).ToList();
        if (missing.Count > 0) throw new InvalidOperationException($"load case(s) not in the model: {string.Join(", ", missing)}");
        var want = cases.ToHashSet();
        foreach (var c in original.Keys) Api.Check(sap.Analyze.SetRunCaseFlag(c, want.Contains(c)), $"Analyze.SetRunCaseFlag {c}");
        var wrong = Read(sap).Where(f => f.Value != want.Contains(f.Key)).Select(f => f.Key).ToList();
        if (wrong.Count > 0) { Restore(sap, original); throw new InvalidOperationException($"run flags read back wrong for {string.Join(", ", wrong)}; restored"); }
        Console.Error.WriteLine($"flags     run only {string.Join(", ", cases)} ({original.Count} flags saved, {original.Count(f => f.Value)} were on)");
        return original;
    }

    /// <summary>
    /// run --cases A,B [--commit]: analysis of only these cases (lean flags, restored afterwards),
    /// no design, so no section changes. For the intact gravity run before `axial` (app step 1).
    /// RunAnalysis runs under Watch; every case must finish (GetCaseStatus 4). The section guard
    /// applies as for `results --run`: a pending design section would be adopted, so that stops it.
    /// </summary>
    public static int RunCases(cSapModel sap, int pid, string casesCsv, bool commit)
    {
        var cases = casesCsv.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        if (cases.Count == 0) { Console.Error.WriteLine("run --cases A,B [--commit]"); return 2; }
        Console.WriteLine($"cases     {string.Join(", ", cases)}");
        if (!commit) { Console.WriteLine("Dry run — add --commit to run the analysis."); return 0; }
        if (!SectionGuard.Allows(sap, false)) return SectionGuard.ExitSectionsDiffer;
        var saved = Only(sap, cases);
        try { Api.Check(Watch.During(pid, "Analyze.RunAnalysis", () => sap.Analyze.RunAnalysis()), "Analyze.RunAnalysis"); }
        finally { Restore(sap, saved); }
        int n = 0; string[] names = Array.Empty<string>(); int[] status = Array.Empty<int>();
        Api.Check(sap.Analyze.GetCaseStatus(ref n, ref names, ref status), "Analyze.GetCaseStatus");
        var of = names.Take(n).Zip(status).ToDictionary(p => p.First, p => p.Second);
        var bad = cases.Where(c => of.GetValueOrDefault(c, -1) != 4).ToList();
        if (bad.Count > 0) throw new InvalidOperationException($"case(s) did not finish: {string.Join(", ", bad)}");
        Console.WriteLine($"{cases.Count} of {cases.Count} case(s) finished.");
        return 0;
    }

    public static void Restore(cSapModel sap, Dictionary<string, bool> saved)
    {
        foreach (var (c, v) in saved) Api.Check(sap.Analyze.SetRunCaseFlag(c, v), $"Analyze.SetRunCaseFlag {c}");
        var back = Read(sap);
        var wrong = saved.Where(s => back.GetValueOrDefault(s.Key) != s.Value).Select(s => s.Key).ToList();
        if (wrong.Count > 0) throw new InvalidOperationException($"run flags not restored for {string.Join(", ", wrong)}");
        Console.Error.WriteLine($"flags     restored ({saved.Count(f => f.Value)} of {saved.Count} on), read back ok");
    }
}
#endif
