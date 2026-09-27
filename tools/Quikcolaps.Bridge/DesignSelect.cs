#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// design-select --combos A,B [--commit]: makes the steel frame and the composite beam strength
/// design selections exactly these combinations (DesignSteel / DesignCompositeBeam
/// Get/SetComboStrength, documented and used by apply). Dry run by default; every change is read
/// back. Changing the selection does not need an unlocked model.
/// </summary>
internal static class DesignSelect
{
    public static int Run(cSapModel sap, string combosCsv, bool commit)
    {
        var want = combosCsv.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
        if (want.Count == 0) { Console.Error.WriteLine("design-select --combos DStlS1,DStlS2 [--commit]"); return 2; }
        int n = 0; string[] all = Array.Empty<string>();
        Api.Check(sap.RespCombo.GetNameList(ref n, ref all), "RespCombo.GetNameList");
        var missing = want.Except(all.Take(n)).ToList();
        if (missing.Count > 0) throw new InvalidOperationException($"combination(s) not in the model: {string.Join(", ", missing)}");

        var faults = new List<string>();
        foreach (var (name, get, set) in Designers(sap))
        {
            var now = get();
            var add = want.Except(now).ToList();
            var remove = now.Except(want).ToList();
            Console.WriteLine($"{name,-14} now {string.Join(", ", now)}");
            Console.WriteLine($"{"",-14} add {(add.Count > 0 ? string.Join(", ", add) : "-")}; remove {(remove.Count > 0 ? string.Join(", ", remove) : "-")}");
            if (!commit) continue;
            foreach (var c in add) Api.Check(set(c, true), $"{name}.SetComboStrength {c} true");
            foreach (var c in remove) Api.Check(set(c, false), $"{name}.SetComboStrength {c} false");
            var back = get();
            if (!back.ToHashSet().SetEquals(want)) faults.Add($"{name} reads back {string.Join(", ", back)}");
        }
        foreach (var f in faults) Console.Error.WriteLine($"READ BACK {f}");
        if (!commit) { Console.WriteLine("Dry run — add --commit to change the selection."); return 0; }
        Console.WriteLine(faults.Count == 0 ? $"selection is {string.Join(", ", want)} for steel and composite, read back ok" : "READ BACK DIFFERS");
        return faults.Count == 0 ? 0 : 1;
    }

    private static IEnumerable<(string Name, Func<List<string>> Get, Func<string, bool, int> Set)> Designers(cSapModel sap)
    {
        yield return ("DesignSteel", () =>
        {
            int n = 0; string[] c = Array.Empty<string>();
            Api.Check(sap.DesignSteel.GetComboStrength(ref n, ref c), "DesignSteel.GetComboStrength");
            return c.Take(n).ToList();
        }, (c, on) => sap.DesignSteel.SetComboStrength(c, on));
        yield return ("DesignComposite", () =>
        {
            int n = 0; string[] c = Array.Empty<string>();
            Api.Check(sap.DesignCompositeBeam.GetComboStrength(ref n, ref c), "DesignCompositeBeam.GetComboStrength");
            return c.Take(n).ToList();
        }, (c, on) => sap.DesignCompositeBeam.SetComboStrength(c, on));
    }
}
#endif
