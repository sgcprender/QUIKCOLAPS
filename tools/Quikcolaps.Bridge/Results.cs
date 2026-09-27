#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// results: case status, the base-reaction check per scenario, and every steel frame's design
/// ratio with its governing combination, mapped back to a scenario (ap/docs/schema/results.schema.json).
/// Composite beams (design procedure 3) are designed and read separately: their results name
/// neither the frame nor the governing combination, so each beam is read on its own and counts
/// toward every scenario whose region holds it.
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

    public static int Run(cSapModel sap, int pid, string scenariosPath, string templateName, string outPath, bool run, bool design,
        bool acceptDesignSections)
    {
        if (run && !SectionGuard.Allows(sap, acceptDesignSections)) return SectionGuard.ExitSectionsDiffer;
        if (run) Api.Check(Watch.During(pid, "Analyze.RunAnalysis", () => sap.Analyze.RunAnalysis()), "Analyze.RunAnalysis");
        // Composite first: composite beam design resets every steel frame's design section to its
        // analysis section and leaves the steel ratios (measured, CLAUDE.md), so steel runs last.
        var composite = FramesWithProcedure(sap, CompositeBeamDesign);
        if (design && composite.Count > 0)
            Api.Check(Watch.During(pid, "DesignCompositeBeam.StartDesign", () => sap.DesignCompositeBeam.StartDesign()), "DesignCompositeBeam.StartDesign");
        if (design) Api.Check(Watch.During(pid, "DesignSteel.StartDesign", () => sap.DesignSteel.StartDesign()), "DesignSteel.StartDesign");

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
            comboToScenario.TryGetValue(ComboName(pmm[k]), out var sid);
            var passes = r[k] <= 1.0 && !st[k].Contains("fail", StringComparison.OrdinalIgnoreCase);
            members[frame[k]] = new MemberRow(sect[k], type[k].ToString(), r[k], pmm[k], sid, passes, st[k]);
            if (sid is null) continue;
            var agg = byScenario[sid];
            byScenario[sid] = (Math.Max(agg.Max, r[k]), agg.Failing);
            if (!passes) agg.Failing.Add(frame[k]);
        }

        // Composite beams: read one at a time (VERIFY GetSummaryResults: no frame names in its output).
        var regionOf = scenarios.SelectMany(s => Json.Strings(s["region"]?["beams"]).Select(b => (Beam: b, Id: (string)s["id"]!)))
            .ToLookup(x => x.Beam, x => x.Id);
        var compositeMissing = new List<string>();
        foreach (var f in composite)
        {
            var row = CompositeResult(sap, f);
            if (row is null) { compositeMissing.Add(f); continue; }
            members[f] = row;
            foreach (var sid in regionOf[f].Where(byScenario.ContainsKey))
            {
                var agg = byScenario[sid];
                byScenario[sid] = (Math.Max(agg.Max, row.MaxRatio), agg.Failing);
                if (!row.Passes) agg.Failing.Add(f);
            }
        }
        if (compositeMissing.Count > 0)
            Console.Error.WriteLine($"{compositeMissing.Count} of {composite.Count} composite beams have no composite design result (run composite design: --design), e.g. {string.Join(", ", compositeMissing.Take(5))}");

        Json.Write(outPath, new
        {
            iteration = 0,
            cases,
            members,
            by_scenario = byScenario.ToDictionary(kv => kv.Key, kv => new { max_ratio = kv.Value.Max, failing = kv.Value.Failing }),
        });
        Console.Error.WriteLine($"{cases.Count} cases, {cases.Values.Count(c => !c.ReactionCheckOk)} failing the reaction check; " +
                                $"{members.Count} designed frames ({composite.Count - compositeMissing.Count} composite), {members.Values.Count(m => !m.Passes)} failing");
        return 0;
    }

    /// <summary>FrameObj.GetDesignProcedure codes (documented): 1 steel frame, 3 composite beam.</summary>
    private const int CompositeBeamDesign = 3;

    private static List<string> FramesWithProcedure(cSapModel sap, int procedure)
    {
        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        return frames.Take(n).Where(f => { int t = -1; return sap.FrameObj.GetDesignProcedure(f, ref t) == 0 && t == procedure; }).ToList();
    }

    /// <summary>
    /// One composite beam's design, or null without a result. The ratio is strength only, the larger
    /// of the strength bending (StrPMRat) and strength shear (StrShrRat) ratios: deflection and
    /// construction-stage checks are not collapse checks. The stud ratio and ETABS's overall
    /// ratio and pass/fail (which include them) are kept in the status text.
    /// </summary>
    private static MemberRow? CompositeResult(cSapModel sap, string frame)
    {
        int n = 0;
        string[] sect = Array.Empty<string>(), layout = Array.Empty<string>(), passFail = Array.Empty<string>();
        bool[] shored = Array.Empty<bool>();
        double[] fy = Array.Empty<double>(), dia = Array.Empty<double>(), camber = Array.Empty<double>(), reacL = Array.Empty<double>(), reacR = Array.Empty<double>(),
            mNeg = Array.Empty<double>(), mPos = Array.Empty<double>(), pcc = Array.Empty<double>(), overall = Array.Empty<double>(), stud = Array.Empty<double>(),
            strPM = Array.Empty<double>(), conPM = Array.Empty<double>(), strShr = Array.Empty<double>(), conShr = Array.Empty<double>(),
            pcdl = Array.Empty<double>(), sdl = Array.Empty<double>(), ll = Array.Empty<double>(), totCam = Array.Empty<double>(), freq = Array.Empty<double>(), damp = Array.Empty<double>();
        var ret = sap.DesignCompositeBeam.GetSummaryResults(frame, ref n, ref sect, ref fy, ref dia, ref layout, ref shored, ref camber, ref passFail,
            ref reacL, ref reacR, ref mNeg, ref mPos, ref pcc, ref overall, ref stud, ref strPM, ref conPM, ref strShr, ref conShr,
            ref pcdl, ref sdl, ref ll, ref totCam, ref freq, ref damp, eItemType.Objects);
        if (ret != 0 || n == 0) return null;
        var strength = Math.Max(strPM[0], strShr[0]);
        return new MemberRow(sect[0], "CompositeBeam", strength, "", null, strength <= 1.0,
            $"strength PM {strPM[0]:0.###} shear {strShr[0]:0.###}; studs {stud[0]:0.###}; overall {overall[0]:0.###} {passFail[0]}");
    }

    /// <summary>
    /// The combination's own name from a governing-combo string: design results report it with a
    /// suffix, e.g. <c>AP_SC03_CMB(C)</c> (measured), so a trailing parenthesised tag is removed.
    /// </summary>
    internal static string ComboName(string reported)
    {
        var s = reported.TrimEnd();
        if (!s.EndsWith(')')) return s;
        var open = s.LastIndexOf('(');
        return open > 0 ? s[..open].TrimEnd() : s;
    }

    /// <summary>Total vertical base reaction at the last step of a case, kN (call inside Si.With).</summary>
    private static double LastFz(cSapModel sap, string caseName)
    {
        var setup = sap.Results.Setup;
        setup.DeselectAllCasesAndCombosForOutput();
        Api.Check(setup.SetCaseSelectedForOutput(caseName, true), $"SetCaseSelectedForOutput {caseName}");
        setup.SetOptionMultiStepStatic(3);   // last step (VERIFY for staged construction)
        setup.SetOptionNLStatic(3);          // last step (VERIFY)

        int n = 0; string[] lc = Array.Empty<string>(), stepType = Array.Empty<string>(); double[] step = Array.Empty<double>();
        double[] fx = Array.Empty<double>(), fy = Array.Empty<double>(), fz = Array.Empty<double>(),
            mx = Array.Empty<double>(), my = Array.Empty<double>(), mz = Array.Empty<double>();
        double gx = 0, gy = 0, gz = 0;
        Api.Check(sap.Results.BaseReact(ref n, ref lc, ref stepType, ref step, ref fx, ref fy, ref fz, ref mx, ref my, ref mz,
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
            Api.Check(setup.SetCaseSelectedForOutput(caseName, true), $"SetCaseSelectedForOutput {caseName}");
            setup.SetOptionMultiStepStatic(3);
            setup.SetOptionNLStatic(3);
            var outRows = new Dictionary<string, ForceRow>();
            foreach (var f in frames)
            {
                int n = 0; string[] obj = Array.Empty<string>(), elm = Array.Empty<string>(), lc = Array.Empty<string>(), stepType = Array.Empty<string>();
                double[] objSta = Array.Empty<double>(), elmSta = Array.Empty<double>(), step = Array.Empty<double>(),
                    P = Array.Empty<double>(), V2 = Array.Empty<double>(), V3 = Array.Empty<double>(), T = Array.Empty<double>(),
                    M2 = Array.Empty<double>(), M3 = Array.Empty<double>();
                Api.Check(sap.Results.FrameForce(f, eItemTypeElm.ObjectElm, ref n, ref obj, ref objSta, ref elm, ref elmSta, ref lc,
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
