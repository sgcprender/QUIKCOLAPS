#if CSI
using CSiAPIv1;

namespace Quikcolaps.Etabs;

/// <summary>One story of the stack standing on a removed column: the column and the floors at its top joint.</summary>
public sealed record StackLevel(string Frame, string Label, string Story, string TopJoint, IReadOnlyList<string> Floors);

/// <summary>
/// The removed column and every column carried on it, story by story, with the floor areas each
/// top joint holds.
///
/// A column above shares its bottom joint with the top joint of the column below, so the stack is
/// walked joint to joint through <c>PointObj.GetConnectivity</c>. <c>GetCommonTo</c> only counts the
/// objects on a joint and does not name them. The walk stops where no column stands on the joint,
/// or where the one that does is not directly above — its far end is off plan by more than
/// <see cref="PlanTolerance"/>.
/// </summary>
public sealed record ColumnStack(IReadOnlyList<StackLevel> Levels, string Stop)
{
    /// <summary>Plan offset, in the model's present length unit, that still counts as directly above.</summary>
    public static double PlanTolerance { get; set; } = 1.0;

    public StackLevel Removed => Levels[0];

    /// <summary>Every floor area on any top joint in the stack, each once, bottom first.</summary>
    public IReadOnlyList<string> InfluenceArea => Levels.SelectMany(l => l.Floors).Distinct().ToList();

    public static ColumnStack Trace(cSapModel sap, string column)
    {
        var levels = new List<StackLevel>();
        var seen = new HashSet<string>();
        var frame = column;
        string stop;

        while (true)
        {
            if (!seen.Add(frame)) { stop = $"frame {frame} reached twice"; break; }
            var (_, top) = Ends(sap, frame);
            var (x, y, z) = Coord(sap, top);

            string label = "", story = "";
            sap.FrameObj.GetLabelFromName(frame, ref label, ref story);

            var floors = new List<string>();
            var above = new List<(string Name, double Off)>();
            var skew = new List<string>();
            foreach (var (type, name) in Connected(sap, top))
            {
                if (type == ObjectType.Area && IsFloor(sap, name)) floors.Add(name);
                else if (type == ObjectType.Frame && name != frame && IsColumn(sap, name))
                {
                    var (lower, upper) = Ends(sap, name);
                    if (lower != top) continue;
                    var (fx, fy, _) = Coord(sap, upper);
                    var off = Math.Sqrt((fx - x) * (fx - x) + (fy - y) * (fy - y));
                    if (off <= PlanTolerance) above.Add((name, off)); else skew.Add(name);
                }
            }
            levels.Add(new StackLevel(frame, label, story, top, floors));

            if (above.Count > 0) { frame = above.OrderBy(a => a.Off).First().Name; continue; }
            stop = skew.Count > 0
                ? $"column {string.Join(", ", skew)} on joint {top} is not directly above"
                : $"no column above joint {top}";
            break;
        }
        return new ColumnStack(levels, stop);
    }

    /// <summary>A column's lower and upper joints, whichever way round it was drawn.</summary>
    private static (string Lower, string Upper) Ends(cSapModel sap, string frame)
    {
        string i = "", j = "";
        Check(sap.FrameObj.GetPoints(frame, ref i, ref j), $"FrameObj.GetPoints {frame}");
        return Coord(sap, i).Z <= Coord(sap, j).Z ? (i, j) : (j, i);
    }

    private static (double X, double Y, double Z) Coord(cSapModel sap, string point)
    {
        double x = 0, y = 0, z = 0;
        Check(sap.PointObj.GetCoordCartesian(point, ref x, ref y, ref z, "Global"), $"PointObj.GetCoordCartesian {point}");
        return (x, y, z);
    }

    private static IEnumerable<(int Type, string Name)> Connected(cSapModel sap, string point)
    {
        int n = 0; int[] types = Array.Empty<int>(); string[] names = Array.Empty<string>(); int[] at = Array.Empty<int>();
        Check(sap.PointObj.GetConnectivity(point, ref n, ref types, ref names, ref at), $"PointObj.GetConnectivity {point}");
        for (var k = 0; k < n; k++) yield return (types[k], names[k]);
    }

    public static bool IsColumn(cSapModel sap, string frame)
    {
        eFrameDesignOrientation o = default;
        return sap.FrameObj.GetDesignOrientation(frame, ref o) == 0 && o == eFrameDesignOrientation.Column;
    }

    private static bool IsFloor(cSapModel sap, string area)
    {
        eAreaDesignOrientation o = default;
        return sap.AreaObj.GetDesignOrientation(area, ref o) == 0 && o == eAreaDesignOrientation.Floor;
    }

    internal static void Check(int ret, string call)
    {
        if (ret != 0) throw new InvalidOperationException($"{call} returned {ret}");
    }
}

/// <summary>Object type codes as <c>PointObj.GetConnectivity</c> and <c>GroupDef.GetAssignments</c> report them.</summary>
public static class ObjectType
{
    public const int Point = 1, Frame = 2, Area = 5;
}
#endif
