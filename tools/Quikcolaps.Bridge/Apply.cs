#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// Writes the approved scenarios into the open model, from the hand-built template case (CS1 by
/// default), the same way the Cli tool does, with two differences the UFC scope needs:
///
///  - several columns can be removed in one case (the 30% simultaneous-removal rule): the
///    template's single frame-removal operation is repeated for each removed column;
///  - the loaded group holds the region's floor areas AND its beams, so beam self-weight and
///    facade line loads in the region are amplified too (decision D13).
///
/// The template must: start from an initial case carrying 1.2D + (0.5L or 0.2S) on the whole
/// building, remove exactly one frame, and load exactly one group with the same patterns at
/// (amplification − 1) = 1.0. `results` checks the base reactions against that.
///
/// Without --commit nothing is written. Every write is read back; differences are reported.
/// </summary>
internal static class Apply
{
    private const int RemoveStructure = CaseTemplate.RemoveStructure, LoadObjects = CaseTemplate.LoadObjects;

    public static int Run(cSapModel sap, string scenariosPath, string templateName, bool commit)
    {
        var template = CaseTemplate.Read(sap, templateName);
        Console.WriteLine($"template  {template.Name}: initial '{template.InitialCase}', removes {template.RemovedFrame}, loads group '{template.LoadedGroup}'");
        foreach (var o in template.Stages.SelectMany(s => s.Operations).Where(o => o.Operation == LoadObjects))
            Console.WriteLine($"          + {o.Scale} × {o.LoadName}");

        var doc = Json.Read(scenariosPath);
        var scenarios = Json.ActiveScenarios(doc).ToList();
        var failed = 0;
        foreach (var s in scenarios)
        {
            var caseName = (string)s["case_name"]!;
            var group = (string)s["group_name"]!;
            var removed = Json.Strings(s["removed_columns"]);
            var areas = Json.Strings(s["region"]?["bays"]);
            var beams = Json.Strings(s["region"]?["beams"]);
            Console.WriteLine($"{caseName,-12} remove {string.Join(", ", removed)}  → {group}: {areas.Count} areas, {beams.Count} beams");
            if (!commit) continue;

            var faults = new List<string>();
            faults.AddRange(WriteGroup(sap, template.LoadedGroup, group, areas, beams));
            faults.AddRange(WriteCase(sap, template, caseName, removed, group));
            var combo = new CollapseCase(caseName, group, new ColumnStack(Array.Empty<StackLevel>(), ""));
            faults.AddRange(combo.WriteCombo(sap));
            Console.WriteLine($"    {(faults.Count == 0 ? "written, read back ok" : "READ BACK DIFFERS")}  combo {combo.ComboName}");
            foreach (var f in faults) Console.WriteLine($"      {f}");
            if (faults.Count > 0) failed++;
        }

        if (!commit) { Console.WriteLine($"\n{scenarios.Count} scenario(s). Dry run — add --commit to write."); return 0; }
        sap.View.RefreshView(0, false);
        Console.WriteLine($"\n{scenarios.Count - failed} of {scenarios.Count} written and verified. The model is not saved.");
        return failed == 0 ? 0 : 1;
    }

    /// <summary>The template's stages with its removal repeated for each removed frame and its group swapped.</summary>
    private static List<Stage> StagesFor(CaseTemplate t, IReadOnlyList<string> removed, string group)
    {
        var templateFrame = t.RemovedFrame;
        var templateGroup = t.LoadedGroup;
        return t.Stages.Select(stage => stage with
        {
            Operations = stage.Operations.SelectMany(o =>
                o.Operation == RemoveStructure && Is(o.ObjectType, "Frame") && o.ObjectName == templateFrame
                    ? removed.Select(f => o with { ObjectName = f })
                    : Is(o.ObjectType, "Group") && o.ObjectName == templateGroup
                        ? new[] { o with { ObjectName = group } }
                        : new[] { o }).ToList()
        }).ToList();
    }

    private static IReadOnlyList<string> WriteCase(cSapModel sap, CaseTemplate t, string caseName, IReadOnlyList<string> removed, string group)
    {
        var st = sap.LoadCases.StaticNonlinearStaged;
        ColumnStack.Check(st.SetCase(caseName), $"SetCase {caseName}");
        ColumnStack.Check(st.SetInitialCase(caseName, t.InitialCase), $"SetInitialCase {caseName}");
        st.SetGeometricNonlinearity(caseName, t.GeometricNonlinearity);
        st.SetMaterialNonlinearity(caseName, t.TimeDependentMaterial);
        st.SetHingeUnloading(caseName, t.HingeUnloading);
        if (t.MassSource.Length > 0) st.SetMassSource(caseName, t.MassSource);
        st.SetResultsSaved(caseName, t.ResultsSaved.Option, t.ResultsSaved.MinSteps, t.ResultsSaved.MinStepsTD);

        var stages = StagesFor(t, removed, group);
        var dur = stages.Select(s => s.Duration).ToArray();
        var output = stages.Select(s => s.Output).ToArray();
        var oname = stages.Select(s => s.OutputName).ToArray();
        var comment = stages.Select(s => s.Comment).ToArray();
        ColumnStack.Check(st.SetStageDefinitions_2(caseName, stages.Count, ref dur, ref output, ref oname, ref comment), $"SetStageDefinitions_2 {caseName}");
        for (var k = 0; k < stages.Count; k++)
        {
            var ops = stages[k].Operations;
            var op = ops.Select(o => o.Operation).ToArray();
            var ot = ops.Select(o => o.ObjectType).ToArray();
            var on = ops.Select(o => o.ObjectName).ToArray();
            var age = ops.Select(o => o.Age).ToArray();
            var mt = ops.Select(o => o.LoadType).ToArray();
            var mn = ops.Select(o => o.LoadName).ToArray();
            var sf = ops.Select(o => o.Scale).ToArray();
            ColumnStack.Check(st.SetStageData_2(caseName, k + 1, ops.Count, ref op, ref ot, ref on, ref age, ref mt, ref mn, ref sf), $"SetStageData_2 {caseName} stage {k + 1}");
        }

        var faults = new List<string>();
        var back = CaseTemplate.Read(sap, caseName);
        if (back.InitialCase != t.InitialCase) faults.Add($"initial case reads back as '{back.InitialCase}'");
        if (back.Stages.Count != stages.Count) faults.Add($"{stages.Count} stages sent, {back.Stages.Count} read back");
        foreach (var (a, b) in stages.Zip(back.Stages))
            if (!a.Operations.SequenceEqual(b.Operations))
                faults.Add("stage operations read back differently:\n        sent " + string.Join("; ", a.Operations) + "\n        read " + string.Join("; ", b.Operations));
        return faults;
    }

    /// <summary>
    /// The load group: template group's flags, emptied member by member (GroupDef.Clear answers −99),
    /// then the region's areas and beams. Read back and compared.
    /// </summary>
    private static IReadOnlyList<string> WriteGroup(cSapModel sap, string templateGroup, string group, IReadOnlyList<string> areas, IReadOnlyList<string> beams)
    {
        int color = 0; bool sel = false, cut = false, steel = false, conc = false, alum = false, stage = false,
            seis = false, wind = false, mass = false, joist = false, wall = false, plate = false, conn = false;
        ColumnStack.Check(sap.GroupDef.GetGroup_1(templateGroup, ref color, ref sel, ref cut, ref steel, ref conc, ref alum, ref stage,
            ref seis, ref wind, ref mass, ref joist, ref wall, ref plate, ref conn), $"GetGroup_1 {templateGroup}");
        ColumnStack.Check(sap.GroupDef.SetGroup_1(group, color, sel, cut, steel, conc, alum, stage,
            seis, wind, mass, joist, wall, plate, conn), $"SetGroup_1 {group}");

        int n = 0; int[] types = Array.Empty<int>(); string[] names = Array.Empty<string>();
        sap.GroupDef.GetAssignments(group, ref n, ref types, ref names);
        for (var k = 0; k < n; k++)
        {
            var ret = types[k] switch
            {
                ObjectType.Point => sap.PointObj.SetGroupAssign(names[k], group, true, eItemType.Objects),
                ObjectType.Frame => sap.FrameObj.SetGroupAssign(names[k], group, true, eItemType.Objects),
                ObjectType.Area => sap.AreaObj.SetGroupAssign(names[k], group, true, eItemType.Objects),
                _ => throw new InvalidOperationException($"group {group} holds object type {types[k]} ({names[k]})")
            };
            ColumnStack.Check(ret, $"remove {names[k]} from {group}");
        }
        foreach (var a in areas) ColumnStack.Check(sap.AreaObj.SetGroupAssign(a, group, false, eItemType.Objects), $"AreaObj.SetGroupAssign {a}");
        foreach (var b in beams) ColumnStack.Check(sap.FrameObj.SetGroupAssign(b, group, false, eItemType.Objects), $"FrameObj.SetGroupAssign {b}");

        n = 0; types = Array.Empty<int>(); names = Array.Empty<string>();
        sap.GroupDef.GetAssignments(group, ref n, ref types, ref names);
        var heldAreas = names.Where((_, k) => types[k] == ObjectType.Area).ToHashSet();
        var heldBeams = names.Where((_, k) => types[k] == ObjectType.Frame).ToHashSet();
        var faults = new List<string>();
        if (!heldAreas.SetEquals(areas)) faults.Add($"group {group} holds {heldAreas.Count} areas; expected {areas.Count}");
        if (!heldBeams.SetEquals(beams)) faults.Add($"group {group} holds {heldBeams.Count} frames; expected {beams.Count}");
        return faults;
    }

    private static bool Is(string a, string b) => string.Equals(a, b, StringComparison.OrdinalIgnoreCase);
}
#endif
