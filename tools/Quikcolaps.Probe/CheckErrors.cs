#if CSI
using CSiAPIv1;

namespace Quikcolaps.Probe;

/// <summary>Read-only: the steel designer's error and warning text per frame, grouped.</summary>
internal static class CheckErrors
{
    public static void Dump(cSapModel sap)
    {
        Console.WriteLine($"\nsteel results available {sap.DesignSteel.GetResultsAvailable()}");
        int n = 0; string[] frame = Array.Empty<string>(), combo = Array.Empty<string>(), err = Array.Empty<string>(), warn = Array.Empty<string>();
        double[] ratio = Array.Empty<double>(), loc = Array.Empty<double>(); int[] rtype = Array.Empty<int>();
        var ret = sap.DesignSteel.GetSummaryResults("All", ref n, ref frame, ref ratio, ref rtype, ref loc, ref combo, ref err, ref warn, eItemType.Group);
        Console.WriteLine($"summary ret {ret}, {n} frames");
        foreach (var g in frame.Select((f, k) => (f, k)).GroupBy(x => (Err: err[x.k], Warn: warn[x.k])).OrderByDescending(g => g.Count()).Take(12))
        {
            var labels = g.Take(4).Select(x => { string l = "", s = ""; sap.FrameObj.GetLabelFromName(x.f, ref l, ref s); return $"{l}@{s}"; });
            Console.WriteLine($"  {g.Count(),5}  error '{g.Key.Err}'  warning '{g.Key.Warn}'   e.g. {string.Join(", ", labels)}");
        }
        foreach (var g in combo.GroupBy(c => c).OrderByDescending(g => g.Count()).Take(8))
            Console.WriteLine($"  governed by {g.Key,-20} {g.Count(),5}");
        Console.WriteLine("strength selection: " + string.Join(", ", Selected(sap)));
    }

    private static string[] Selected(cSapModel sap) { int n = 0; string[] s = Array.Empty<string>(); sap.DesignSteel.GetComboStrength(ref n, ref s); return s; }
}
#endif
