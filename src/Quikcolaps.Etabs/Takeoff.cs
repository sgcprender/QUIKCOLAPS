#if CSI
using System.Globalization;
using System.Text.RegularExpressions;
using CSiAPIv1;

namespace Quikcolaps.Etabs;

/// <summary>One frame's weight: its length times the weight per foot of the section it is sized to.</summary>
public sealed record FrameWeight(
    string Frame, string Label, string Story, string Kind, string Section, string SectionSource,
    double LengthFt, double LbPerFt, string WeightSource, double Lb);

/// <summary>
/// Steel takeoff from the sections the designers chose.
///
/// A frame's section is the steel designer's, else the composite beam designer's, else the analysis
/// section — whichever answers first — and the source is kept on the row, because a frame the
/// designers did not size is weighed at what was drawn. Weight per foot is the nominal value in an
/// AISC shape name (W14X90 is 90 lb/ft); a section without one is weighed as area × material unit
/// weight.
/// </summary>
public static class Takeoff
{
    public const double LbPerShortTon = 2000;

    private static readonly Regex Nominal = new(@"^(W|M|S|HP|C|MC)\d+(\.\d+)?X(?<w>\d+(\.\d+)?)$", RegexOptions.IgnoreCase);

    public static IReadOnlyList<FrameWeight> Read(cSapModel sap)
    {
        var (toFt, toLb) = Scale(sap.GetPresentUnits());
        var steel = sap.DesignSteel.GetResultsAvailable();
        var composite = sap.DesignCompositeBeam.GetResultsAvailable();
        var perFt = new Dictionary<string, (double LbPerFt, string Source)>();

        int n = 0; string[] frames = Array.Empty<string>();
        ColumnStack.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");

        var rows = new List<FrameWeight>(n);
        foreach (var f in frames)
        {
            string label = "", story = "", i = "", j = "", analysis = "", auto = "", design = "";
            sap.FrameObj.GetLabelFromName(f, ref label, ref story);
            eFrameDesignOrientation o = default; sap.FrameObj.GetDesignOrientation(f, ref o);
            sap.FrameObj.GetSection(f, ref analysis, ref auto);

            string section, source;
            if (steel && sap.DesignSteel.GetDesignSection(f, ref design) == 0 && design.Length > 0) (section, source) = (design, "steel design");
            else if (composite && sap.DesignCompositeBeam.GetDesignSection(f, ref design) == 0 && design.Length > 0) (section, source) = (design, "composite design");
            else (section, source) = (analysis, "analysis");

            ColumnStack.Check(sap.FrameObj.GetPoints(f, ref i, ref j), $"FrameObj.GetPoints {f}");
            var lengthFt = Distance(sap, i, j) * toFt;

            if (!perFt.TryGetValue(section, out var w)) perFt[section] = w = WeightPerFoot(sap, section, toFt, toLb);
            rows.Add(new FrameWeight(f, label, story, o.ToString(), section, source, lengthFt, w.LbPerFt, w.Source, lengthFt * w.LbPerFt));
        }
        return rows;
    }

    private static (double LbPerFt, string Source) WeightPerFoot(cSapModel sap, string section, double toFt, double toLb)
    {
        string nameInFile = "", file = "", mat = ""; eFramePropType type = default;
        sap.PropFrame.GetNameInPropFile(section, ref nameInFile, ref file, ref mat, ref type);
        foreach (var name in new[] { nameInFile, section })
        {
            var m = Nominal.Match(name ?? "");
            if (m.Success) return (double.Parse(m.Groups["w"].Value, CultureInfo.InvariantCulture), "nominal");
        }

        double area = 0, x = 0, unitW = 0, mass = 0;
        ColumnStack.Check(sap.PropFrame.GetSectProps(section, ref area, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x, ref x), $"PropFrame.GetSectProps {section}");
        if (string.IsNullOrEmpty(mat)) sap.PropFrame.GetMaterial(section, ref mat);
        ColumnStack.Check(sap.PropMaterial.GetWeightAndMass(mat, ref unitW, ref mass, 0), $"PropMaterial.GetWeightAndMass {mat}");
        // area × unit weight is force per model length; per foot, in pounds.
        return (area * unitW * toLb / toFt, "area × unit weight");
    }

    private static double Distance(cSapModel sap, string a, string b)
    {
        double x1 = 0, y1 = 0, z1 = 0, x2 = 0, y2 = 0, z2 = 0;
        sap.PointObj.GetCoordCartesian(a, ref x1, ref y1, ref z1, "Global");
        sap.PointObj.GetCoordCartesian(b, ref x2, ref y2, ref z2, "Global");
        return Math.Sqrt((x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1) + (z2 - z1) * (z2 - z1));
    }

    /// <summary>Feet per model length unit and pounds per model force unit, from the present units.</summary>
    private static (double ToFt, double ToLb) Scale(eUnits units)
    {
        var parts = units.ToString().Split('_');
        double lb = parts[0].ToLowerInvariant() switch
        {
            "lb" => 1, "kip" => 1000, "n" => 0.224808943, "kn" => 224.808943, "kgf" => 2.20462262, "ton" => 2204.62262,
            _ => throw new NotSupportedException($"force unit in {units}")
        };
        double ft = parts[1].ToLowerInvariant() switch
        {
            "in" => 1 / 12.0, "ft" => 1, "mm" => 1 / 304.8, "cm" => 1 / 30.48, "m" => 1 / 0.3048,
            _ => throw new NotSupportedException($"length unit in {units}")
        };
        return (ft, lb);
    }

    public static void WriteCsv(string path, IReadOnlyList<FrameWeight> rows)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        using var w = new StreamWriter(path);
        w.WriteLine("Frame,Label,Story,Kind,Section,SectionSource,LengthFt,LbPerFt,WeightSource,Lb");
        foreach (var r in rows)
            w.WriteLine(string.Join(",", r.Frame, r.Label, r.Story, r.Kind, r.Section, r.SectionSource,
                r.LengthFt.ToString("0.###", CultureInfo.InvariantCulture), r.LbPerFt.ToString("0.###", CultureInfo.InvariantCulture),
                r.WeightSource, r.Lb.ToString("0.#", CultureInfo.InvariantCulture)));
    }

    public static IReadOnlyList<FrameWeight> ReadCsv(string path) => File.ReadLines(path).Skip(1).Select(l => l.Split(',')).Select(c =>
        new FrameWeight(c[0], c[1], c[2], c[3], c[4], c[5], D(c[6]), D(c[7]), c[8], D(c[9]))).ToList();

    private static double D(string s) => double.Parse(s, CultureInfo.InvariantCulture);
}
#endif
