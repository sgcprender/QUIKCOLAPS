#if CSI
using CSiAPIv1;

namespace Quikcolaps.Etabs;

/// <summary>
/// Adding a load pattern to the cases the collapse set is built from: the initial case, whose loads
/// are a plain list, and the template staged case, whose loads are operations on its influence-area
/// group. Each is idempotent — a pattern already present has its factor set rather than being
/// added twice.
/// </summary>
public static class CaseLoads
{
    public sealed record Load(string Type, string Name, double Scale);

    public static IReadOnlyList<Load> Initial(cSapModel sap, string caseName)
    {
        int n = 0; string[] t = Array.Empty<string>(), name = Array.Empty<string>(); double[] sf = Array.Empty<double>();
        ColumnStack.Check(sap.LoadCases.StaticNonlinear.GetLoads(caseName, ref n, ref t, ref name, ref sf), $"StaticNonlinear.GetLoads {caseName}");
        return Enumerable.Range(0, n).Select(k => new Load(t[k], name[k], sf[k])).ToList();
    }

    /// <summary>The initial case's loads with the pattern at the given factor; written and read back.</summary>
    public static IReadOnlyList<string> SetInInitial(cSapModel sap, string caseName, string pattern, double scale)
    {
        var loads = Initial(sap, caseName).ToList();
        var at = loads.FindIndex(l => l.Type == "Load" && l.Name == pattern);
        if (at >= 0) loads[at] = loads[at] with { Scale = scale }; else loads.Add(new Load("Load", pattern, scale));

        var t = loads.Select(l => l.Type).ToArray();
        var name = loads.Select(l => l.Name).ToArray();
        var sf = loads.Select(l => l.Scale).ToArray();
        ColumnStack.Check(sap.LoadCases.StaticNonlinear.SetLoads(caseName, loads.Count, ref t, ref name, ref sf), $"StaticNonlinear.SetLoads {caseName}");

        var back = Initial(sap, caseName);
        return back.SequenceEqual(loads) ? Array.Empty<string>()
            : new[] { $"{caseName} reads back as {string.Join(" + ", back.Select(l => $"{l.Scale}×{l.Name}"))}" };
    }

    /// <summary>
    /// The template with the pattern loaded on its influence-area group at the given factor, in every
    /// stage that loads that group; written and read back. Stage definitions and settings are left.
    /// </summary>
    public static IReadOnlyList<string> SetInTemplate(cSapModel sap, CaseTemplate template, string pattern, double scale)
    {
        var group = template.LoadedGroup;
        var st = sap.LoadCases.StaticNonlinearStaged;
        var sent = new List<Stage>();
        for (var s = 0; s < template.Stages.Count; s++)
        {
            var ops = template.Stages[s].Operations.ToList();
            var loadsGroup = ops.Where(o => o.Operation == CaseTemplate.LoadObjects && o.ObjectName == group).ToList();
            if (loadsGroup.Count > 0)
            {
                var at = ops.FindIndex(o => o.Operation == CaseTemplate.LoadObjects && o.ObjectName == group && o.LoadType == "Load" && o.LoadName == pattern);
                if (at >= 0) ops[at] = ops[at] with { Scale = scale };
                else ops.Insert(ops.IndexOf(loadsGroup[^1]) + 1, loadsGroup[0] with { LoadType = "Load", LoadName = pattern, Scale = scale });
            }
            sent.Add(template.Stages[s] with { Operations = ops });

            var op = ops.Select(o => o.Operation).ToArray();
            var ot = ops.Select(o => o.ObjectType).ToArray();
            var on = ops.Select(o => o.ObjectName).ToArray();
            var age = ops.Select(o => o.Age).ToArray();
            var mt = ops.Select(o => o.LoadType).ToArray();
            var mn = ops.Select(o => o.LoadName).ToArray();
            var sf = ops.Select(o => o.Scale).ToArray();
            ColumnStack.Check(st.SetStageData_2(template.Name, s + 1, ops.Count, ref op, ref ot, ref on, ref age, ref mt, ref mn, ref sf), $"SetStageData_2 {template.Name} stage {s + 1}");
        }

        var back = CaseTemplate.Read(sap, template.Name);
        return sent.Zip(back.Stages).All(p => p.First.Operations.SequenceEqual(p.Second.Operations)) && back.Stages.Count == sent.Count
            ? Array.Empty<string>()
            : new[] { $"{template.Name} stage operations read back differently" };
    }
}
#endif
