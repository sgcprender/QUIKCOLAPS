#if CSI
using CSiAPIv1;

namespace Quikcolaps.Etabs;

/// <summary>
/// One column-removal case: the staged case that removes the column and loads the floors it and
/// the columns above it carry, through a group holding those floors.
/// </summary>
public sealed record CollapseCase(string CaseName, string GroupName, ColumnStack Stack)
{
    /// <summary>
    /// A case per column in the removal group, named from the column's label and story. The group
    /// name follows the template's: its group name with the template case name replaced, or the
    /// case name appended when the template's group does not end in its case name.
    /// </summary>
    public static IReadOnlyList<CollapseCase> Plan(cSapModel sap, string removalGroup, CaseTemplate template)
    {
        int n = 0; int[] types = Array.Empty<int>(); string[] names = Array.Empty<string>();
        ColumnStack.Check(sap.GroupDef.GetAssignments(removalGroup, ref n, ref types, ref names), $"GroupDef.GetAssignments {removalGroup}");

        var prefix = template.LoadedGroup.EndsWith(template.Name, StringComparison.OrdinalIgnoreCase)
            ? template.LoadedGroup[..^template.Name.Length]
            : template.LoadedGroup + "_";

        var plans = new List<CollapseCase>();
        for (var k = 0; k < n; k++)
        {
            if (types[k] != ObjectType.Frame || !ColumnStack.IsColumn(sap, names[k])) continue;
            var stack = ColumnStack.Trace(sap, names[k]);
            var caseName = $"CS_{stack.Removed.Label}_{stack.Removed.Story}";
            plans.Add(new CollapseCase(caseName, prefix + caseName, stack));
        }
        var clash = plans.GroupBy(p => p.CaseName).FirstOrDefault(g => g.Count() > 1);
        if (clash is not null) throw new InvalidOperationException($"two removal columns would both be named {clash.Key}");
        return plans;
    }

    /// <summary>
    /// Writes the group and the case, then reads both back. A zero return code does not mean the
    /// program kept what was sent, so the membership and every stage operation are compared, and
    /// what differs is returned. Rewriting an existing case or group replaces it.
    /// </summary>
    public IReadOnlyList<string> Write(cSapModel sap, CaseTemplate template)
    {
        WriteGroup(sap, template.LoadedGroup);

        var st = sap.LoadCases.StaticNonlinearStaged;
        ColumnStack.Check(st.SetCase(CaseName), $"SetCase {CaseName}");
        ColumnStack.Check(st.SetInitialCase(CaseName, template.InitialCase), $"SetInitialCase {CaseName}");
        st.SetGeometricNonlinearity(CaseName, template.GeometricNonlinearity);
        st.SetMaterialNonlinearity(CaseName, template.TimeDependentMaterial);
        st.SetHingeUnloading(CaseName, template.HingeUnloading);
        if (template.MassSource.Length > 0) st.SetMassSource(CaseName, template.MassSource);
        st.SetResultsSaved(CaseName, template.ResultsSaved.Option, template.ResultsSaved.MinSteps, template.ResultsSaved.MinStepsTD);

        var stages = template.For(Stack.Removed.Frame, GroupName);
        var dur = stages.Select(s => s.Duration).ToArray();
        var output = stages.Select(s => s.Output).ToArray();
        var oname = stages.Select(s => s.OutputName).ToArray();
        var comment = stages.Select(s => s.Comment).ToArray();
        ColumnStack.Check(st.SetStageDefinitions_2(CaseName, stages.Count, ref dur, ref output, ref oname, ref comment), $"SetStageDefinitions_2 {CaseName}");

        for (var s = 0; s < stages.Count; s++)
        {
            var ops = stages[s].Operations;
            var op = ops.Select(o => o.Operation).ToArray();
            var ot = ops.Select(o => o.ObjectType).ToArray();
            var on = ops.Select(o => o.ObjectName).ToArray();
            var age = ops.Select(o => o.Age).ToArray();
            var mt = ops.Select(o => o.LoadType).ToArray();
            var mn = ops.Select(o => o.LoadName).ToArray();
            var sf = ops.Select(o => o.Scale).ToArray();
            ColumnStack.Check(st.SetStageData_2(CaseName, s + 1, ops.Count, ref op, ref ot, ref on, ref age, ref mt, ref mn, ref sf), $"SetStageData_2 {CaseName} stage {s + 1}");
        }

        return Verify(sap, template, stages);
    }

    /// <summary>The combination wrapping this case, so steel design can select it.</summary>
    public string ComboName => CaseName + "_CMB";

    /// <summary>
    /// Writes a linear additive combination of 1.0 × this case and selects it for steel strength
    /// design, then reads both back. An existing combination of the same name is emptied and refilled.
    /// </summary>
    public IReadOnlyList<string> WriteCombo(cSapModel sap)
    {
        const int linearAdditive = 0;
        if (!Exists(sap, ComboName))
            ColumnStack.Check(sap.RespCombo.Add(ComboName, linearAdditive), $"RespCombo.Add {ComboName}");

        int n = 0; eCNameType[] ct = Array.Empty<eCNameType>(); string[] cn = Array.Empty<string>(); double[] sf = Array.Empty<double>();
        sap.RespCombo.GetCaseList(ComboName, ref n, ref ct, ref cn, ref sf);
        for (var k = 0; k < n; k++)
            ColumnStack.Check(sap.RespCombo.DeleteCase(ComboName, ct[k], cn[k]), $"RespCombo.DeleteCase {ComboName} {cn[k]}");

        var type = eCNameType.LoadCase;
        ColumnStack.Check(sap.RespCombo.SetCaseList(ComboName, ref type, CaseName, 1.0), $"RespCombo.SetCaseList {ComboName}");
        ColumnStack.Check(sap.DesignSteel.SetComboStrength(ComboName, true), $"DesignSteel.SetComboStrength {ComboName}");

        var faults = new List<string>();
        int ctype = -1; sap.RespCombo.GetTypeOAPI(ComboName, ref ctype);
        n = 0; ct = Array.Empty<eCNameType>(); cn = Array.Empty<string>(); sf = Array.Empty<double>();
        sap.RespCombo.GetCaseList(ComboName, ref n, ref ct, ref cn, ref sf);
        if (ctype != linearAdditive || n != 1 || ct[0] != eCNameType.LoadCase || cn[0] != CaseName || sf[0] != 1.0)
            faults.Add($"combo {ComboName} reads back as type {ctype}: " + string.Join(" + ", Enumerable.Range(0, n).Select(k => $"{sf[k]}×{cn[k]}")));

        int ns = 0; string[] strength = Array.Empty<string>();
        sap.DesignSteel.GetComboStrength(ref ns, ref strength);
        if (!strength.Contains(ComboName)) faults.Add($"combo {ComboName} is not in the steel strength selection");
        return faults;
    }

    private static bool Exists(cSapModel sap, string combo)
    {
        int n = 0; string[] names = Array.Empty<string>();
        sap.RespCombo.GetNameList(ref n, ref names);
        return names.Contains(combo);
    }

    private void WriteGroup(cSapModel sap, string templateGroup)
    {
        int color = 0; bool sel = false, cut = false, steel = false, conc = false, alum = false, stage = false,
            seis = false, wind = false, mass = false, joist = false, wall = false, plate = false, conn = false;
        ColumnStack.Check(sap.GroupDef.GetGroup_1(templateGroup, ref color, ref sel, ref cut, ref steel, ref conc, ref alum, ref stage,
            ref seis, ref wind, ref mass, ref joist, ref wall, ref plate, ref conn), $"GetGroup_1 {templateGroup}");
        ColumnStack.Check(sap.GroupDef.SetGroup_1(GroupName, color, sel, cut, steel, conc, alum, stage,
            seis, wind, mass, joist, wall, plate, conn), $"SetGroup_1 {GroupName}");
        // GroupDef.Clear answers -99 in ETABS, so an existing group is emptied member by member.
        int n = 0; int[] types = Array.Empty<int>(); string[] names = Array.Empty<string>();
        sap.GroupDef.GetAssignments(GroupName, ref n, ref types, ref names);
        for (var k = 0; k < n; k++)
        {
            var ret = types[k] switch
            {
                ObjectType.Point => sap.PointObj.SetGroupAssign(names[k], GroupName, true, eItemType.Objects),
                ObjectType.Frame => sap.FrameObj.SetGroupAssign(names[k], GroupName, true, eItemType.Objects),
                ObjectType.Area => sap.AreaObj.SetGroupAssign(names[k], GroupName, true, eItemType.Objects),
                _ => throw new InvalidOperationException($"group {GroupName} holds object type {types[k]} ({names[k]}), which this does not remove")
            };
            ColumnStack.Check(ret, $"remove {names[k]} from {GroupName}");
        }
        foreach (var area in Stack.InfluenceArea)
            ColumnStack.Check(sap.AreaObj.SetGroupAssign(area, GroupName, false, eItemType.Objects), $"AreaObj.SetGroupAssign {area} -> {GroupName}");
    }

    private IReadOnlyList<string> Verify(cSapModel sap, CaseTemplate template, IReadOnlyList<Stage> sent)
    {
        var faults = new List<string>();

        int n = 0; int[] types = Array.Empty<int>(); string[] names = Array.Empty<string>();
        sap.GroupDef.GetAssignments(GroupName, ref n, ref types, ref names);
        var held = names.Where((_, k) => types[k] == ObjectType.Area).ToHashSet();
        if (!held.SetEquals(Stack.InfluenceArea) || n != held.Count)
            faults.Add($"group {GroupName} holds {n} objects, {held.Count} areas; expected {Stack.InfluenceArea.Count} areas");

        var back = CaseTemplate.Read(sap, CaseName);
        if (back.InitialCase != template.InitialCase) faults.Add($"initial case reads back as '{back.InitialCase}'");
        if (back.Stages.Count != sent.Count) faults.Add($"{sent.Count} stages sent, {back.Stages.Count} read back");
        foreach (var (a, b) in sent.Zip(back.Stages))
            if (!a.Operations.SequenceEqual(b.Operations))
                faults.Add("stage operations read back differently:\n    sent " + string.Join("; ", a.Operations) + "\n    read " + string.Join("; ", b.Operations));
        return faults;
    }
}
#endif
