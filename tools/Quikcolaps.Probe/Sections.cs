#if CSI
using CSiAPIv1;

namespace Quikcolaps.Probe;

/// <summary>Read-only: what the steel designer and the section definitions report for a sample of frames.</summary>
internal static class Sections
{
    public static void Dump(cSapModel sap)
    {
        Console.WriteLine($"\nsteel results available {sap.DesignSteel.GetResultsAvailable()}");
        int n = 0; string[] frames = Array.Empty<string>();
        sap.FrameObj.GetNameList(ref n, ref frames);
        Console.WriteLine($"frames {n}");
        var procs = new Dictionary<int, int>();
        var pairs = new Dictionary<string, int>();
        foreach (var f in frames)
        {
            int proc = -1; sap.FrameObj.GetDesignProcedure(f, ref proc);
            procs[proc] = procs.GetValueOrDefault(proc) + 1;
            string analysis = "", auto = "", design = "";
            sap.FrameObj.GetSection(f, ref analysis, ref auto);
            var ret = sap.DesignSteel.GetDesignSection(f, ref design);
            var key = $"analysis {analysis} auto '{auto}' -> design ret {ret} '{design}'";
            pairs[key] = pairs.GetValueOrDefault(key) + 1;
        }
        Console.WriteLine("design procedures: " + string.Join(", ", procs.Select(p => $"{p.Key}×{p.Value}")));
        foreach (var p in pairs.OrderByDescending(p => p.Value).Take(25)) Console.WriteLine($"  {p.Value,4}  {p.Key}");

        foreach (var s in pairs.Keys.Select(k => k.Split('\'')[3]).Where(s => s.Length > 0).Distinct().Take(8))
        {
            string file = "", nameIn = "", mat = ""; eFramePropType t = default;
            sap.PropFrame.GetNameInPropFile(s, ref nameIn, ref file, ref mat, ref t);
            double a = 0, x = 0; sap.PropFrame.GetSectProps(s, ref a, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x);
            string m2 = ""; sap.PropFrame.GetMaterial(s, ref m2);
            double w = 0, mass = 0; sap.PropMaterial.GetWeightAndMass(m2, ref w, ref mass, 0);
            Console.WriteLine($"  {s,-12} type {t} inFile '{nameIn}' file '{file}' mat {m2} area {a} unitW {w} -> {a * w * 12} lb/ft");
        }
    }
}
#endif
