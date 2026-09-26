#if CSI
using CSiAPIv1;

namespace Quikcolaps.Probe;

/// <summary>Read-only: the model's combinations and what the steel designer is set to use.</summary>
internal static class Combos
{
    public static void Dump(cSapModel sap)
    {
        int n = 0; string[] names = Array.Empty<string>();
        sap.RespCombo.GetNameList(ref n, ref names);
        Console.WriteLine($"\ncombinations ({n})");
        foreach (var c in names.Take(40))
        {
            int type = 0; sap.RespCombo.GetTypeOAPI(c, ref type);
            int k = 0; eCNameType[] ct = Array.Empty<eCNameType>(); string[] cn = Array.Empty<string>(); double[] sf = Array.Empty<double>();
            sap.RespCombo.GetCaseList(c, ref k, ref ct, ref cn, ref sf);
            Console.WriteLine($"  {c,-24} type {type}  " + string.Join(" + ", Enumerable.Range(0, k).Select(i => $"{sf[i]}×{cn[i]}({ct[i]})")));
        }
        bool auto = false;
        Console.WriteLine($"\nsteel design code '{Code(sap)}'  auto-generate ret {sap.DesignSteel.GetComboAutoGenerate(ref auto)} value {auto}");
        n = 0; names = Array.Empty<string>();
        var ret = sap.DesignSteel.GetComboStrength(ref n, ref names);
        Console.WriteLine($"steel strength combos ret {ret} ({n}): {string.Join(", ", names.Take(40))}");
    }

    private static string Code(cSapModel sap) { string c = ""; sap.DesignSteel.GetCode(ref c); return c; }
}
#endif
