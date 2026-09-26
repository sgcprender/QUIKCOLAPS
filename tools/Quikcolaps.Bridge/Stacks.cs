#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// For every column in scenarios.json (removed_columns, including simultaneous removals), the
/// ColumnStack trace: the stack of columns standing on it and the floor areas on each top joint.
/// This is ETABS's own answer to "which bays are adjacent, at all floors above", and core/ uses it
/// as the amplified region when it is available (ap/docs/decisions.md, D12).
/// </summary>
internal static class Stacks
{
    private sealed record LevelRow(string Frame, string Label, string Story, string TopJoint, IReadOnlyList<string> Floors);
    private sealed record StackRow(IReadOnlyList<LevelRow> Levels, IReadOnlyList<string> InfluenceAreas, string Stop);

    public static int Run(cSapModel sap, string scenariosPath, string outPath)
    {
        var doc = Json.Read(scenariosPath);
        var frames = Json.ActiveScenarios(doc).SelectMany(s => Json.Strings(s["removed_columns"])).Distinct().ToList();
        var stacks = new Dictionary<string, StackRow>();
        foreach (var f in frames)
        {
            var st = ColumnStack.Trace(sap, f);
            stacks[f] = new StackRow(
                st.Levels.Select(l => new LevelRow(l.Frame, l.Label, l.Story, l.TopJoint, l.Floors)).ToList(),
                st.InfluenceArea, st.Stop);
            Console.Error.WriteLine($"  {f,-8} {st.Removed.Label}@{st.Removed.Story}: {st.Levels.Count} levels, {st.InfluenceArea.Count} floor areas; stops: {st.Stop}");
        }
        Json.Write(outPath, new { plan_tolerance = ColumnStack.PlanTolerance, stacks });
        return 0;
    }
}
#endif
