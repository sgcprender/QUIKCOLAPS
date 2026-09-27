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
