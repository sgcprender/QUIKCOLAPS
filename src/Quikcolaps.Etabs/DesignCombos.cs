#if CSI
using CSiAPIv1;

namespace Quikcolaps.Etabs;

/// <summary>
/// Which combinations the steel designer uses for strength.
///
/// A collapse combination is one whose every case is a staged-construction case. A strength
/// combination is one whose name starts with the strength prefix — the program's own generated set
/// is named <c>DStlS1</c>, <c>DStlS2</c>, …
/// </summary>
public static class DesignCombos
{
    public enum Set { Strength, Collapse, CollapseOnly }

    public sealed record Change(string Combo, bool Selected);

    /// <summary>
    /// The selections that make the steel strength list the given set. <see cref="Set.Strength"/>
    /// selects the strength combinations and removes the collapse ones; <see cref="Set.Collapse"/>
    /// selects both; <see cref="Set.CollapseOnly"/> selects the collapse combinations and removes the
    /// strength ones.
    /// </summary>
    public static IReadOnlyList<Change> Plan(cSapModel sap, Set set, string strengthPrefix = "DStlS")
    {
        int n = 0; string[] combos = Array.Empty<string>();
        ColumnStack.Check(sap.RespCombo.GetNameList(ref n, ref combos), "RespCombo.GetNameList");
        var selected = Selected(sap);

        var changes = new List<Change>();
        foreach (var c in combos)
        {
            bool? want = IsCollapse(sap, c) ? set != Set.Strength
                : c.StartsWith(strengthPrefix, StringComparison.OrdinalIgnoreCase) ? set != Set.CollapseOnly
                : null;
            if (want is bool w && w != selected.Contains(c)) changes.Add(new Change(c, w));
        }
        return changes;
    }

    /// <summary>Applies the selections and returns any combination whose selection did not read back as sent.</summary>
    public static IReadOnlyList<string> Apply(cSapModel sap, IReadOnlyList<Change> changes)
    {
        foreach (var c in changes)
            ColumnStack.Check(sap.DesignSteel.SetComboStrength(c.Combo, c.Selected), $"DesignSteel.SetComboStrength {c.Combo} {c.Selected}");
        var now = Selected(sap);
        return changes.Where(c => now.Contains(c.Combo) != c.Selected)
            .Select(c => $"{c.Combo} reads back as {(now.Contains(c.Combo) ? "selected" : "not selected")}").ToList();
    }

    public static HashSet<string> Selected(cSapModel sap)
    {
        int n = 0; string[] names = Array.Empty<string>();
        ColumnStack.Check(sap.DesignSteel.GetComboStrength(ref n, ref names), "DesignSteel.GetComboStrength");
        return names.ToHashSet();
    }

    public static bool IsCollapse(cSapModel sap, string combo)
    {
        int n = 0; eCNameType[] types = Array.Empty<eCNameType>(); string[] names = Array.Empty<string>(); double[] sf = Array.Empty<double>();
        sap.RespCombo.GetCaseList(combo, ref n, ref types, ref names, ref sf);
        return n > 0 && Enumerable.Range(0, n).All(k => types[k] == eCNameType.LoadCase && IsStaged(sap, names[k]));
    }

    /// <summary>Staged construction reports as a nonlinear static case of subtype 2.</summary>
    private static bool IsStaged(cSapModel sap, string loadCase)
    {
        eLoadCaseType type = default; int sub = 0; eLoadPatternType design = default; int opt = 0, auto = 0;
        return sap.LoadCases.GetTypeOAPI_1(loadCase, ref type, ref sub, ref design, ref opt, ref auto) == 0
               && type == eLoadCaseType.NonlinearStatic && sub == 2;
    }
}
#endif
