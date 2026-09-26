#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// results: case status, the base-reaction check per scenario, and every steel frame's design
/// ratio with its governing combination, mapped back to a scenario (ap/docs/schema/results.schema.json).
/// forces: frame forces at the last step of one case, for the staged-case validation.
///
/// Read-only on the model unless --run (runs analysis) or --design (runs steel design) is given.
/// </summary>
internal static class Results
{
    private sealed record CaseRow(string Scenario, int Status, double BaseReactionFzKn, double InitialCaseFzKn,
        double IncrementFromReactionsKn, double IncrementExpectedKn, bool ReactionCheckOk);
    private sealed record MemberRow(string Section, string Kind, double MaxRatio, string GoverningCombo,
        string? GoverningScenario, bool Passes, string Status);
    private sealed record ForceRow(double PKn, double V2Kn, double M3Knm);

    public static int Run(cSapModel sap, string scenariosPath, string templateName, string outPath, bool run, bool design)
    {
        if (run) ColumnStack.Check(sap.Analyze.RunAnalysis(), "Analyze.RunAnalysis");
        if (design) ColumnStack.Check(sap.DesignSteel.StartDesign(), "DesignSteel.StartDesign");

        var template = CaseTemplate.Read(sap, templateName);
        var scenarios = Json.ActiveScenarios(Json.Read(scenariosPath)).ToList();

        int nc = 0; string[] caseNames = Array.Empty<string>(); int[] status = Array.Empty<int>();
        sap.Analyze.GetCaseStatus(ref nc, ref caseNames, ref status);
        var statusOf = caseNames.Zip(status).ToDictionary(p => p.First, p => p.Second);

        var baseFz = Si.With(sap, () => LastFz(sap, template.InitialCase));
        var cases = new Dictionary<string, CaseRow>();
        var comboToScenario = new Dictionary<string, string>();
        foreach (var s in scenarios)
        {
            var id = (string)s["id"]!;
            var caseName = (string)s["case_name"]!;
            comboToScenario[caseName + "_CMB"] = id;
            var fz = Si.With(sap, () => LastFz(sap, caseName));
            var expected = (double?)s["increment"]?["increment_total_kn"] ?? double.NaN;
            var delta = Math.Abs(fz) - Math.Abs(baseFz);
            // status 4 = finished (VERIFY status codes for your version)
            cases[caseName] = new CaseRow(id, statusOf.GetValueOrDefault(caseName, -1), fz, baseFz, delta, expected,
                !double.IsNaN(expected) && Math.Abs(delta - expected) <= 0.01 * Math.Max(1, Math.Abs(expected)));
        }

        // Steel design summary, one row per frame: ratio and governing PMM combination (as in Probe/Governing.cs).
        int n = 0; string[] frame = Array.Empty<string>(), sect = Array.Empty<string>(), st = Array.Empty<string>(), pmm = Array.Empty<string>(),
            vmaj = Array.Empty<string>(), vmin = Array.Empty<string>();
        eFrameDesignOrientation[] type = Array.Empty<eFrameDesignOrientation>();
        double[] r = Array.Empty<double>(), p = Array.Empty<double>(), m2 = Array.Empty<double>(), m3 = Array.Empty<double>(), v2 = Array.Empty<double>(), v3 = Array.Empty<double>();
        var ret = sap.DesignSteel.GetSummaryResults_3("All", ref n, ref frame, ref type, ref sect, ref st, ref pmm, ref r, ref p, ref m2, ref m3,
            ref vmaj, ref v2, ref vmin, ref v3, eItemType.Group);
        if (ret != 0) Console.Error.WriteLine($"DesignSteel.GetSummaryResults_3 returned {ret}: run steel design first (--design)");

        var members = new Dictionary<string, MemberRow>();
        var byScenario = scenarios.ToDictionary(s => (string)s["id"]!, _ => (Max: 0.0, Failing: new List<string>()));
        for (var k = 0; k < n; k++)
        {
            comboToScenario.TryGetValue(pmm[k], out var sid);
            var passes = r[k] <= 1.0 && !st[k].Contains("fail", StringComparison.OrdinalIgnoreCase);
            members[frame[k]] = new MemberRow(sect[k], type[k].ToString(), r[k], pmm[k], sid, passes, st[k]);
            if (sid is null) continue;
            var agg = byScenario[sid];
            byScenario[sid] = (Math.Max(agg.Max, r[k]), agg.Failing);
            if (!passes) agg.Failing.Add(frame[k]);
        }

        Json.Write(outPath, new
        {
            iteration = 0,
            cases,
            members,
            by_scenario = byScenario.ToDictionary(kv => kv.Key, kv => new { max_ratio = kv.Value.Max, failing = kv.Value.Failing }),
        });
        Console.Error.WriteLine($"{cases.Count} cases, {cases.Values.Count(c => !c.ReactionCheckOk)} failing the reaction check; " +
                                $"{members.Count} designed frames, {members.Values.Count(m => !m.Passes)} over 1.0");
        return 0;
    }

    /// <summary>Total vertical base reaction at the last step of a case, kN (call inside Si.With).</summary>
    private static double LastFz(cSapModel sap, string caseName)
    {
        var setup = sap.Results.Setup;
        setup.DeselectAllCasesAndCombosForOutput();
        ColumnStack.Check(setup.SetCaseSelectedForOutput(caseName, true), $"SetCaseSelectedForOutput {caseName}");
        setup.SetOptionMultiStepStatic(3);   // last step (VERIFY for staged construction)
        setup.SetOptionNLStatic(3);          // last step (VERIFY)

        int n = 0; string[] lc = Array.Empty<string>(), stepType = Array.Empty<string>(); double[] step = Array.Empty<double>();
        double[] fx = Array.Empty<double>(), fy = Array.Empty<double>(), fz = Array.Empty<double>(),
            mx = Array.Empty<double>(), my = Array.Empty<double>(), mz = Array.Empty<double>();
        double gx = 0, gy = 0, gz = 0;
        ColumnStack.Check(sap.Results.BaseReact(ref n, ref lc, ref stepType, ref step, ref fx, ref fy, ref fz, ref mx, ref my, ref mz,
            ref gx, ref gy, ref gz), $"Results.BaseReact {caseName}");
        if (n == 0) throw new InvalidOperationException($"no base reaction for {caseName}: has it been run?");
        var last = Enumerable.Range(0, n).OrderBy(k => step[k]).Last();
        return fz[last];
    }

    /// <summary>Max |P|, |V2|, |M3| per frame at the last step of one case, kN and kN·m.</summary>
    public static int Forces(cSapModel sap, string caseName, string framesCsv, string outPath)
    {
        var frames = framesCsv.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (caseName.Length == 0 || frames.Length == 0) { Console.Error.WriteLine("forces --case NAME --frames F1,F2 --out forces.json"); return 2; }

        var rows = Si.With(sap, () =>
        {
            var setup = sap.Results.Setup;
            setup.DeselectAllCasesAndCombosForOutput();
            ColumnStack.Check(setup.SetCaseSelectedForOutput(caseName, true), $"SetCaseSelectedForOutput {caseName}");
            setup.SetOptionMultiStepStatic(3);
            setup.SetOptionNLStatic(3);
            var outRows = new Dictionary<string, ForceRow>();
            foreach (var f in frames)
            {
                int n = 0; string[] obj = Array.Empty<string>(), elm = Array.Empty<string>(), lc = Array.Empty<string>(), stepType = Array.Empty<string>();
                double[] objSta = Array.Empty<double>(), elmSta = Array.Empty<double>(), step = Array.Empty<double>(),
                    P = Array.Empty<double>(), V2 = Array.Empty<double>(), V3 = Array.Empty<double>(), T = Array.Empty<double>(),
                    M2 = Array.Empty<double>(), M3 = Array.Empty<double>();
                ColumnStack.Check(sap.Results.FrameForce(f, eItemTypeElm.ObjectElm, ref n, ref obj, ref objSta, ref elm, ref elmSta, ref lc,
                    ref stepType, ref step, ref P, ref V2, ref V3, ref T, ref M2, ref M3), $"Results.FrameForce {f}");
                if (n == 0) continue;
                var lastStep = step.Take(n).Max();
                var at = Enumerable.Range(0, n).Where(k => step[k] == lastStep).ToList();
                outRows[f] = new ForceRow(at.Max(k => Math.Abs(P[k])), at.Max(k => Math.Abs(V2[k])), at.Max(k => Math.Abs(M3[k])));
            }
            return outRows;
        });
        Json.Write(outPath, new { @case = caseName, frames = rows });
        return 0;
    }
}
#endif
