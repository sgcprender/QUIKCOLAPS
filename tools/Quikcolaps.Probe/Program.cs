#if CSI
using CSiAPIv1;
using Quikcolaps.Etabs;

namespace Quikcolaps.Probe;

/// <summary>
/// Read-only survey of the model the collapse cases are built in: groups, the staged cases and
/// what their stages hold, and what the API reports as standing on each removal column's joints.
/// </summary>
internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        var model = args.SkipWhile(a => a != "--model").Skip(1).FirstOrDefault() ?? "progressive collapse";
        var inst = Select.Instance(model, Console.WriteLine);
        var sap = inst.Api.SapModel;
        Console.WriteLine($"model  {inst.ModelPath}  (pid {inst.ProcessId})");
        Console.WriteLine($"units  {sap.GetPresentUnits()}   locked {sap.GetModelIsLocked()}");

        int n = 0; string[] names = Array.Empty<string>();
        sap.GroupDef.GetNameList(ref n, ref names);
        Console.WriteLine($"\ngroups ({n})");
        foreach (var g in names)
        {
            int k = 0; int[] types = Array.Empty<int>(); string[] objs = Array.Empty<string>();
            sap.GroupDef.GetAssignments(g, ref k, ref types, ref objs);
            var byType = string.Join(" ", types.GroupBy(t => t).Select(t => $"type{t.Key}×{t.Count()}"));
            Console.WriteLine($"  {g,-30} {k,5}  {byType}");
        }

        n = 0; names = Array.Empty<string>();
        sap.LoadPatterns.GetNameList(ref n, ref names);
        Console.WriteLine($"\nload patterns ({n})");
        foreach (var p in names)
        {
            eLoadPatternType t = default; double sw = 0;
            sap.LoadPatterns.GetLoadType(p, ref t); sap.LoadPatterns.GetSelfWTMultiplier(p, ref sw);
            Console.WriteLine($"  {p,-20} {t,-12} selfwt×{sw}");
        }

        n = 0; names = Array.Empty<string>();
        sap.LoadCases.GetNameList(ref n, ref names, eLoadCaseType.NonlinearStatic);
        Console.WriteLine($"\nnonlinear static cases ({n})");
        foreach (var c in names) DumpCase(sap, c);

        if (args.Contains("--combos")) { Combos.Dump(sap); return 0; }
        if (args.Contains("--sections")) { Sections.Dump(sap); return 0; }
        if (args.Contains("--governing")) { Governing.Dump(sap); return 0; }
        if (args.Contains("--check-errors")) { CheckErrors.Dump(sap); return 0; }

        var removeGroup = args.SkipWhile(a => a != "--group").Skip(1).FirstOrDefault() ?? "column remove";
        var group = FindGroup(sap, removeGroup);
        if (group is null) { Console.WriteLine($"\nno group named like '{removeGroup}'"); return 1; }
        int m = 0; int[] ot = Array.Empty<int>(); string[] on = Array.Empty<string>();
        sap.GroupDef.GetAssignments(group, ref m, ref ot, ref on);
        Console.WriteLine($"\n'{group}' — {m} objects");
        var limit = int.TryParse(args.SkipWhile(a => a != "--columns").Skip(1).FirstOrDefault(), out var l) ? l : 3;
        foreach (var (type, name) in ot.Zip(on).Take(limit))
        {
            Console.WriteLine($"\n  object type {type}  {name}");
            if (type != 2) continue;
            var col = name;
            for (var level = 0; col is not null && level < 200; level++)
            {
                string label = "", story = "", i = "", j = "";
                sap.FrameObj.GetLabelFromName(col, ref label, ref story);
                sap.FrameObj.GetPoints(col, ref i, ref j);
                eFrameDesignOrientation o = default; sap.FrameObj.GetDesignOrientation(col, ref o);
                double xi = 0, yi = 0, zi = 0, xj = 0, yj = 0, zj = 0;
                sap.PointObj.GetCoordCartesian(i, ref xi, ref yi, ref zi, "Global");
                sap.PointObj.GetCoordCartesian(j, ref xj, ref yj, ref zj, "Global");
                Console.WriteLine($"    frame {col} {label}@{story} {o}  I {i} ({xi:0.###},{yi:0.###},{zi:0.###})  J {j} ({xj:0.###},{yj:0.###},{zj:0.###})");

                int common = 0; sap.PointObj.GetCommonTo(j, ref common);
                int c = 0; int[] ct = Array.Empty<int>(); string[] cn = Array.Empty<string>(); int[] cp = Array.Empty<int>();
                sap.PointObj.GetConnectivity(j, ref c, ref ct, ref cn, ref cp);
                Console.WriteLine($"      J commonTo {common}  connectivity {c}");
                string? next = null;
                for (var q = 0; q < c; q++)
                {
                    var extra = "";
                    if (ct[q] == 2)
                    {
                        string a = "", b = ""; sap.FrameObj.GetPoints(cn[q], ref a, ref b);
                        eFrameDesignOrientation fo = default; sap.FrameObj.GetDesignOrientation(cn[q], ref fo);
                        extra = $"{fo} I {a} J {b}";
                        if (fo == eFrameDesignOrientation.Column && a == j) next = cn[q];
                    }
                    else if (ct[q] == 5)
                    {
                        eAreaDesignOrientation ao = default; sap.AreaObj.GetDesignOrientation(cn[q], ref ao);
                        string al = "", ast = ""; sap.AreaObj.GetLabelFromName(cn[q], ref al, ref ast);
                        extra = $"{ao} {al}@{ast}";
                    }
                    Console.WriteLine($"        type {ct[q]}  {cn[q],-8} pt#{cp[q]}  {extra}");
                }
                col = next;
            }
        }
        return 0;
    }

    private static string? FindGroup(cSapModel sap, string like)
    {
        int n = 0; string[] names = Array.Empty<string>();
        sap.GroupDef.GetNameList(ref n, ref names);
        return names.FirstOrDefault(g => g.Equals(like, StringComparison.OrdinalIgnoreCase))
               ?? names.FirstOrDefault(g => g.Contains(like, StringComparison.OrdinalIgnoreCase));
    }

    private static void DumpCase(cSapModel sap, string name)
    {
        eLoadCaseType type = default; int sub = 0; eLoadPatternType design = default; int opt = 0, auto = 0;
        sap.LoadCases.GetTypeOAPI_1(name, ref type, ref sub, ref design, ref opt, ref auto);
        Console.WriteLine($"  {name}  subtype {sub}");
        var st = sap.LoadCases.StaticNonlinearStaged;
        string init = "";
        if (st.GetInitialCase(name, ref init) != 0) return;
        Console.WriteLine($"    initial '{init}'");
        int ns = 0; double[] dur = Array.Empty<double>(); bool[] output = Array.Empty<bool>();
        string[] oname = Array.Empty<string>(), comment = Array.Empty<string>();
        if (st.GetStageDefinitions_2(name, ref ns, ref dur, ref output, ref oname, ref comment) != 0) return;
        int nl = 0; st.GetGeometricNonlinearity(name, ref nl);
        for (var s = 1; s <= ns; s++)
        {
            Console.WriteLine($"    stage {s}  duration {dur[s - 1]}  output {output[s - 1]} '{oname[s - 1]}'  '{comment[s - 1]}'");
            int no = 0; int[] op = Array.Empty<int>(); string[] objType = Array.Empty<string>(), objName = Array.Empty<string>();
            double[] age = Array.Empty<double>(); string[] myType = Array.Empty<string>(), myName = Array.Empty<string>();
            double[] sf = Array.Empty<double>();
            var stage = s; st.GetStageData_2(name, ref stage, ref no, ref op, ref objType, ref objName, ref age, ref myType, ref myName, ref sf);
            for (var k = 0; k < no; k++)
                Console.WriteLine($"      op {op[k]}  {objType[k]} '{objName[k]}'  age {age[k]}  {myType[k]} '{myName[k]}'  sf {sf[k]}");
        }
        Console.WriteLine($"    geometric nonlinearity {nl}");
    }
}
#endif
