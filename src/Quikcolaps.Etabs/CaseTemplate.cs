#if CSI
using CSiAPIv1;

namespace Quikcolaps.Etabs;

public sealed record StageOperation(int Operation, string ObjectType, string ObjectName, double Age, string LoadType, string LoadName, double Scale);

public sealed record Stage(double Duration, bool Output, string OutputName, string Comment, IReadOnlyList<StageOperation> Operations);

/// <summary>
/// A staged-construction case as the API reports it. Read from the example collapse case so that
/// everything set there — the initial case, the load operations and their factors, the nonlinear
/// settings — carries into every generated case, and only the removed column and the
/// influence-area group change.
/// </summary>
public sealed record CaseTemplate(
    string Name,
    string InitialCase,
    IReadOnlyList<Stage> Stages,
    int GeometricNonlinearity,
    bool TimeDependentMaterial,
    int HingeUnloading,
    string MassSource,
    (int Option, int MinSteps, int MinStepsTD) ResultsSaved)
{
    /// <summary>Stage operation codes for <c>SetStageData_2</c>.</summary>
    public const int RemoveStructure = 2, LoadObjects = 4;

    public static CaseTemplate Read(cSapModel sap, string name)
    {
        var st = sap.LoadCases.StaticNonlinearStaged;
        string init = "";
        ColumnStack.Check(st.GetInitialCase(name, ref init), $"GetInitialCase {name} (is it a staged construction case?)");

        int ns = 0; double[] dur = Array.Empty<double>(); bool[] output = Array.Empty<bool>();
        string[] oname = Array.Empty<string>(), comment = Array.Empty<string>();
        ColumnStack.Check(st.GetStageDefinitions_2(name, ref ns, ref dur, ref output, ref oname, ref comment), $"GetStageDefinitions_2 {name}");

        var stages = new List<Stage>();
        for (var s = 1; s <= ns; s++)
        {
            var stage = s;
            int no = 0; int[] op = Array.Empty<int>(); string[] ot = Array.Empty<string>(), on = Array.Empty<string>();
            double[] age = Array.Empty<double>(); string[] mt = Array.Empty<string>(), mn = Array.Empty<string>(); double[] sf = Array.Empty<double>();
            ColumnStack.Check(st.GetStageData_2(name, ref stage, ref no, ref op, ref ot, ref on, ref age, ref mt, ref mn, ref sf), $"GetStageData_2 {name} stage {s}");
            var ops = Enumerable.Range(0, no).Select(k => new StageOperation(op[k], ot[k], on[k], age[k], mt[k], mn[k], sf[k])).ToList();
            stages.Add(new Stage(dur[s - 1], output[s - 1], oname[s - 1], comment[s - 1], ops));
        }

        int nl = 0, unload = 0, opt = 0, min = 0, minTd = 0; bool td = false; string mass = "";
        st.GetGeometricNonlinearity(name, ref nl);
        st.GetMaterialNonlinearity(name, ref td);
        st.GetHingeUnloading(name, ref unload);
        st.GetMassSource(name, ref mass);
        st.GetResultsSaved(name, ref opt, ref min, ref minTd);
        return new CaseTemplate(name, init, stages, nl, td, unload, mass, (opt, min, minTd));
    }

    private IEnumerable<StageOperation> All => Stages.SelectMany(s => s.Operations);

    /// <summary>The frame the template removes. There must be exactly one.</summary>
    public string RemovedFrame => All.Where(IsFrameRemoval).Select(o => o.ObjectName).Distinct()
        .SingleOr(() => new InvalidOperationException($"template {Name} must remove exactly one frame"));

    /// <summary>The group the template loads. There must be exactly one.</summary>
    public string LoadedGroup => All.Where(o => o.Operation == LoadObjects && Is(o.ObjectType, "Group")).Select(o => o.ObjectName).Distinct()
        .SingleOr(() => new InvalidOperationException($"template {Name} must load exactly one group"));

    /// <summary>The template's stages with its removed frame and loaded group replaced.</summary>
    public IReadOnlyList<Stage> For(string frame, string group)
    {
        var removed = RemovedFrame;
        var loaded = LoadedGroup;
        return Stages.Select(s => s with
        {
            Operations = s.Operations.Select(o =>
                IsFrameRemoval(o) && o.ObjectName == removed ? o with { ObjectName = frame } :
                Is(o.ObjectType, "Group") && o.ObjectName == loaded ? o with { ObjectName = group } : o).ToList()
        }).ToList();
    }

    private static bool IsFrameRemoval(StageOperation o) => o.Operation == RemoveStructure && Is(o.ObjectType, "Frame");

    private static bool Is(string a, string b) => string.Equals(a, b, StringComparison.OrdinalIgnoreCase);
}

internal static class Seq
{
    public static T SingleOr<T>(this IEnumerable<T> xs, Func<Exception> fail)
    {
        var list = xs.Take(2).ToList();
        return list.Count == 1 ? list[0] : throw fail();
    }
}
#endif
