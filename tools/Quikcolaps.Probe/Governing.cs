#if CSI
using CSiAPIv1;

namespace Quikcolaps.Probe;

/// <summary>Read-only: which combination governs each steel-designed frame, and the load cases' run status.</summary>
internal static class Governing
{
    public static void Dump(cSapModel sap)
    {
        int n = 0; string[] frame = Array.Empty<string>(), sect = Array.Empty<string>(), status = Array.Empty<string>(), pmm = Array.Empty<string>(),
            vmaj = Array.Empty<string>(), vmin = Array.Empty<string>();
        eFrameDesignOrientation[] type = Array.Empty<eFrameDesignOrientation>();
        double[] r = Array.Empty<double>(), p = Array.Empty<double>(), m2 = Array.Empty<double>(), m3 = Array.Empty<double>(), v2 = Array.Empty<double>(), v3 = Array.Empty<double>();
        var ret = sap.DesignSteel.GetSummaryResults_3("All", ref n, ref frame, ref type, ref sect, ref status, ref pmm, ref r, ref p, ref m2, ref m3,
            ref vmaj, ref v2, ref vmin, ref v3, eItemType.Group);
        Console.WriteLine($"\nsteel summary ret {ret}, {n} frames");
        foreach (var g in pmm.GroupBy(c => c).OrderByDescending(g => g.Count()).Take(15))
            Console.WriteLine($"  PMM governed by {g.Key,-22} {g.Count(),5}");
        Console.WriteLine($"  max PMM ratio {(n > 0 ? r.Max() : 0):0.###}");

        int nc = 0; string[] cases = Array.Empty<string>(); int[] st = Array.Empty<int>();
        sap.Analyze.GetCaseStatus(ref nc, ref cases, ref st);
        Console.WriteLine("case run status: " + string.Join(", ", cases.Zip(st).GroupBy(c => c.Second).Select(g => $"{g.Key}×{g.Count()}")));
        Console.WriteLine("  collapse cases: " + string.Join(", ", cases.Zip(st).Where(c => c.First.StartsWith("CS")).GroupBy(c => c.Second).Select(g => $"status {g.Key}×{g.Count()}")));
    }
}
#endif
