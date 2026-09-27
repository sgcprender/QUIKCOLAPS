#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// iterate --cases SW,SDL,LL [--max-rounds 3] [--weight-tol 0.005] --out rounds.json [--commit --accept-design-sections]:
/// design iteration.
/// One round = run the given cases (lean flags, restored afterwards) → composite beam design →
/// steel design → compare each auto-select frame's design section with its analysis section.
/// The next run adopts the design sections (measured, CLAUDE.md), so the loop is: design →
/// accept → run → design, until a design proposes no change (converged) or max-rounds runs.
/// With --weight-tol, converged instead means: from round 2, the steel weight (Takeoff: design
/// sections × length, as `quikcolaps weigh`) changed by less than that fraction since the last
/// round and no steel or composite member is over 1.0. Every round is weighed.
/// --commit needs --accept-design-sections (every run after the first adopts the design
/// sections), and unlocks a locked model first (ModelLock, read back).
///
/// Used for the strength-only baseline (plan item C) and the collapse redesign (item D). This
/// is a redesign on purpose, so SectionGuard does not stop it. Dry run by default: lists the
/// cases, the design selections and any combination case that would not be run.
/// Exit 0 converged, 5 not converged within max-rounds, 1 error, 3 unknown message box.
/// </summary>
internal static class Iterate
{
    public const int ExitNotConverged = 5;

    private sealed record Round(int Number, int FramesDiffering, List<string> Examples, double SteelMaxRatio, int SteelOverOne,
        double CompositeMaxRatio, int CompositeOverOne, double Tons, double ColumnTons, double BeamTons, double? ChangePercent);

    public static int Run(cSapModel sap, int pid, string modelPath, string casesCsv, int maxRounds, double? weightTol, string outPath,
        bool commit, bool accept)
    {
        var cases = casesCsv.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        if (cases.Count == 0 || maxRounds < 1) { Console.Error.WriteLine("iterate --cases SW,SDL,LL [--max-rounds 3] --out rounds.json [--commit]"); return 2; }

        var steel = Selection(sap, composite: false);
        var comp = Selection(sap, composite: true);
        Console.WriteLine($"cases     {string.Join(", ", cases)}");
        Console.WriteLine($"steel     {string.Join(", ", steel)}");
        Console.WriteLine($"composite {string.Join(", ", comp)}");
        var notRun = steel.Concat(comp).Distinct().SelectMany(c => LoadCasesOf(sap, c, 0)).Distinct().Where(c => !cases.Contains(c)).ToList();
        if (notRun.Count > 0) throw new InvalidOperationException($"the design combinations use case(s) that would not be run: {string.Join(", ", notRun)}");
        if (steel.Count == 0) throw new InvalidOperationException("no steel strength combinations selected (design-select first)");
        var differNow = SectionGuard.Differences(SectionGuard.Read(sap));
        Console.WriteLine($"sections  {differNow.Count} auto-select frame(s) with a design section different from the analysis section now; the first run adopts them");
        Console.WriteLine($"converged {(weightTol is double t ? $"weight change < {t:P2} between rounds and nothing over 1.0" : "no auto-select frame would change")}, max {maxRounds} round(s)");
        if (!commit) { Console.WriteLine($"Dry run — add --commit {SectionGuard.AcceptFlag} to run up to {maxRounds} round(s)."); return 0; }
        if (!accept) throw new InvalidOperationException($"iterate adopts the design sections on every run after the first: pass {SectionGuard.AcceptFlag} with --commit");
        ModelLock.EnsureUnlocked(sap, true, "iterate");

        var original = AnalysisSections(sap);
        var compositeFrames = Results.FramesWithProcedure(sap, 3);
        var composite = compositeFrames.Count > 0;
        var rounds = new List<Round>();
        var converged = false;
        var saved = RunFlags.Only(sap, cases);
        try
        {
            for (var r = 1; r <= maxRounds && !converged; r++)
            {
                Api.Check(Watch.During(pid, "Analyze.RunAnalysis", () => sap.Analyze.RunAnalysis()), "Analyze.RunAnalysis");
                CheckFinished(sap, cases);
                if (composite) Api.Check(Watch.During(pid, "DesignCompositeBeam.StartDesign", () => sap.DesignCompositeBeam.StartDesign()), "DesignCompositeBeam.StartDesign");
                Api.Check(Watch.During(pid, "DesignSteel.StartDesign", () => sap.DesignSteel.StartDesign()), "DesignSteel.StartDesign");
                var differ = SectionGuard.Differences(SectionGuard.Read(sap));
                var (maxRatio, over) = SteelRatios(sap);
                var compRows = compositeFrames.Select(f => Results.CompositeResult(sap, f)).Where(x => x is not null).ToList();
                var compMax = compRows.Count > 0 ? compRows.Max(x => x!.MaxRatio) : 0.0;
                var compOver = compRows.Count(x => x!.MaxRatio > 1.0);
                var weights = Takeoff.Read(sap);
                double tons = weights.Sum(w => w.Lb) / Takeoff.LbPerShortTon;
                double colTons = weights.Where(w => w.Kind == "Column").Sum(w => w.Lb) / Takeoff.LbPerShortTon;
                double? change = rounds.Count > 0 ? (tons - rounds[^1].Tons) / rounds[^1].Tons : null;
                Takeoff.WriteCsv(Path.ChangeExtension(outPath, null) + $"_round{r}.csv", weights);
                rounds.Add(new Round(r, differ.Count, differ.Take(10).Select(d => $"{d.Frame} {d.Analysis}->{d.Design}").ToList(), Math.Round(maxRatio, 3), over,
                    Math.Round(compMax, 3), compOver, Math.Round(tons, 2), Math.Round(colTons, 2), Math.Round(tons - colTons, 2),
                    change is double c ? Math.Round(100 * c, 3) : null));
                Console.Error.WriteLine($"round {r}   run + design: {differ.Count} frame(s) would change; {tons:0.00} short tons" +
                    (change is double c2 ? $" ({c2:+0.00%;-0.00%})" : "") +
                    $"; steel max {maxRatio:0.000} ({over} over 1.0), composite max {compMax:0.000} ({compOver} over 1.0)");
                var clean = over == 0 && compOver == 0;
                converged = weightTol is double tol ? change is double c3 && Math.Abs(c3) < tol && clean : differ.Count == 0;
            }
        }
        finally { RunFlags.Restore(sap, saved); }

        var final = AnalysisSections(sap);
        var changed = final.Where(f => original.TryGetValue(f.Key, out var o) && o != f.Value)
            .OrderBy(f => f.Key.Length).ThenBy(f => f.Key)
            .Select(f => new { frame = f.Key, from = original[f.Key], to = f.Value }).ToList();
        Json.Write(outPath, new
        {
            model = Path.GetFileNameWithoutExtension(modelPath),
            cases,
            steel_combos = steel,
            composite_combos = comp,
            max_rounds = maxRounds,
            weight_tolerance = weightTol,
            converged,
            rounds,
            changed_from_start = changed,
        });
        Console.Error.WriteLine($"iterate   {(converged ? "converged" : "NOT converged")} after {rounds.Count} round(s); {changed.Count} frame(s) changed from the start");
        return converged ? 0 : ExitNotConverged;
    }

    private static List<string> Selection(cSapModel sap, bool composite)
    {
        int n = 0; string[] c = Array.Empty<string>();
        Api.Check(composite ? sap.DesignCompositeBeam.GetComboStrength(ref n, ref c) : sap.DesignSteel.GetComboStrength(ref n, ref c),
            composite ? "DesignCompositeBeam.GetComboStrength" : "DesignSteel.GetComboStrength");
        return c.Take(n).ToList();
    }

    /// <summary>Load cases a combination uses, through nested combinations.</summary>
    private static IEnumerable<string> LoadCasesOf(cSapModel sap, string combo, int depth)
    {
        int n = 0; eCNameType[] types = Array.Empty<eCNameType>(); string[] names = Array.Empty<string>(); double[] sf = Array.Empty<double>();
        Api.Check(sap.RespCombo.GetCaseList(combo, ref n, ref types, ref names, ref sf), $"RespCombo.GetCaseList {combo}");
        for (var k = 0; k < n; k++)
        {
            if (types[k] == eCNameType.LoadCase) yield return names[k];
            else if (depth < 5) foreach (var c in LoadCasesOf(sap, names[k], depth + 1)) yield return c;
        }
    }

    private static Dictionary<string, string> AnalysisSections(cSapModel sap)
    {
        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        return frames.Take(n).ToDictionary(f => f, f =>
        {
            string s = "", auto = "";
            Api.Check(sap.FrameObj.GetSection(f, ref s, ref auto), $"FrameObj.GetSection {f}");
            return s;
        });
    }

    /// <summary>Analyze.GetCaseStatus: 4 = finished (documented).</summary>
    private static void CheckFinished(cSapModel sap, List<string> cases)
    {
        int n = 0; string[] names = Array.Empty<string>(); int[] status = Array.Empty<int>();
        Api.Check(sap.Analyze.GetCaseStatus(ref n, ref names, ref status), "Analyze.GetCaseStatus");
        var of = names.Take(n).Zip(status).ToDictionary(p => p.First, p => p.Second);
        var bad = cases.Where(c => of.GetValueOrDefault(c, -1) != 4).Select(c => $"{c} status {of.GetValueOrDefault(c, -1)}").ToList();
        if (bad.Count > 0) throw new InvalidOperationException($"case(s) did not finish: {string.Join(", ", bad)}");
    }

    private static (double Max, int Over) SteelRatios(cSapModel sap)
    {
        int n = 0; string[] frame = Array.Empty<string>(), sect = Array.Empty<string>(), st = Array.Empty<string>(), pmm = Array.Empty<string>(),
            vmaj = Array.Empty<string>(), vmin = Array.Empty<string>();
        eFrameDesignOrientation[] type = Array.Empty<eFrameDesignOrientation>();
        double[] r = Array.Empty<double>(), p = Array.Empty<double>(), m2 = Array.Empty<double>(), m3 = Array.Empty<double>(), v2 = Array.Empty<double>(), v3 = Array.Empty<double>();
        Api.Check(sap.DesignSteel.GetSummaryResults_3("All", ref n, ref frame, ref type, ref sect, ref st, ref pmm, ref r, ref p, ref m2, ref m3,
            ref vmaj, ref v2, ref vmin, ref v3, eItemType.Group), "DesignSteel.GetSummaryResults_3");
        return n == 0 ? (0, 0) : (r.Take(n).Max(), r.Take(n).Count(x => x > 1.0));
    }
}
#endif
