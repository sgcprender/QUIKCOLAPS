#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// axial: every column's axial force at the last step of one case (the intact gravity case,
/// 1.2D+0.5L, for the condition table), keyed by frame with its label (location_id) and story as
/// `export` writes them. Read-only: the case must already have been run.
///
/// p_kn is max |P| along the member (compression for gravity, at the bottom end, with the
/// column's self-weight). Check: the columns starting at the lowest level against the case's
/// base reaction FZ (they match when every support is a column base; measured on AP2:
/// 141,439.9 against 141,440.4 kN).
/// </summary>
internal static class Axial
{
    private sealed record Row(string LocationId, string Story, double PKn);

    public static int Run(cSapModel sap, string modelPath, string caseName, string outPath)
    {
        if (caseName.Length == 0) { Console.Error.WriteLine("axial --case NAME --out FILE"); return 2; }

        int n = 0; string[] frames = Array.Empty<string>();
        Api.Check(sap.FrameObj.GetNameList(ref n, ref frames), "FrameObj.GetNameList");
        var columns = frames.Take(n).Where(f => ColumnStack.IsColumn(sap, f)).ToList();
        if (columns.Count == 0) throw new InvalidOperationException("no columns in the model");

        var (rows, bottom, fz) = Si.With(sap, () =>
        {
            var setup = sap.Results.Setup;
            setup.DeselectAllCasesAndCombosForOutput();
            Api.Check(setup.SetCaseSelectedForOutput(caseName, true), $"SetCaseSelectedForOutput '{caseName}' (is it a load case in this model?)");
            setup.SetOptionMultiStepStatic(3);   // last step (measured, CLAUDE.md)
            setup.SetOptionNLStatic(3);
            var rows = new Dictionary<string, Row>();
            var bottomZ = new Dictionary<string, double>();
            foreach (var f in columns)
            {
                int k = 0; string[] obj = Array.Empty<string>(), elm = Array.Empty<string>(), lc = Array.Empty<string>(), stepType = Array.Empty<string>();
                double[] objSta = Array.Empty<double>(), elmSta = Array.Empty<double>(), step = Array.Empty<double>(),
                    P = Array.Empty<double>(), V2 = Array.Empty<double>(), V3 = Array.Empty<double>(), T = Array.Empty<double>(),
                    M2 = Array.Empty<double>(), M3 = Array.Empty<double>();
                Api.Check(sap.Results.FrameForce(f, eItemTypeElm.ObjectElm, ref k, ref obj, ref objSta, ref elm, ref elmSta, ref lc,
                    ref stepType, ref step, ref P, ref V2, ref V3, ref T, ref M2, ref M3), $"Results.FrameForce {f}");
                if (k == 0) throw new InvalidOperationException($"no results for column {f} in '{caseName}': has the case been run?");
                var last = step.Take(k).Max();
                var p = Enumerable.Range(0, k).Where(x => step[x] == last).Max(x => Math.Abs(P[x]));
                string label = "", story = "", i = "", j = "";
                sap.FrameObj.GetLabelFromName(f, ref label, ref story);
                Api.Check(sap.FrameObj.GetPoints(f, ref i, ref j), $"FrameObj.GetPoints {f}");
                bottomZ[f] = Math.Min(Export.Coord(sap, i).Z, Export.Coord(sap, j).Z);
                rows[f] = new Row(label, story, Math.Round(p, 1));
            }
            return (rows, bottomZ, Results.LastFz(sap, caseName));
        });

        var lowest = bottom.Values.Min();
        var baseSum = rows.Where(r => bottom[r.Key] <= lowest + 1e-3).Sum(r => r.Value.PKn);
        var diff = Math.Abs(fz) > 0 ? (baseSum - Math.Abs(fz)) / Math.Abs(fz) : double.NaN;
        Json.Write(outPath, new
        {
            model = Path.GetFileNameWithoutExtension(modelPath),
            @case = caseName,
            source = $"bridge axial (read-only, no analysis run), {DateTime.Now:yyyy-MM-dd}",
            units = "kN",
            p_kn_note = "max |P| along the member (compression for gravity; at the bottom end, includes the column's self-weight)",
            check = new
            {
                lowest_columns_sum_kn = Math.Round(baseSum, 1),
                base_reaction_fz_kn = Math.Round(Math.Abs(fz), 1),
                difference_percent = Math.Round(100 * diff, 4),
                note = "equal when every support is a column base",
            },
            columns = rows.OrderBy(r => r.Value.LocationId, StringComparer.Ordinal).ThenBy(r => bottom[r.Key])
                .ToDictionary(r => r.Key, r => r.Value),
        });
        Console.Error.WriteLine($"axial     {rows.Count} columns in '{caseName}'; lowest columns {baseSum:0.0} kN, base reaction {Math.Abs(fz):0.0} kN ({100 * diff:0.000}%)");
        return 0;
    }
}
#endif
