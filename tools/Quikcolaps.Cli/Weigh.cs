#if CSI
using Quikcolaps.Etabs;

namespace Quikcolaps.Cli;

/// <summary>
/// <c>weigh</c> takes off the designed steel and saves it under a label; <c>compare</c> sets two
/// saved takeoffs side by side. Both are read-only on the model.
/// </summary>
internal static class Weigh
{
    public static int Run(Instance inst, string label)
    {
        var sap = inst.Api.SapModel;
        Console.WriteLine($"model     {inst.ModelPath}");
        Console.WriteLine($"results   steel {sap.DesignSteel.GetResultsAvailable()}   composite beam {sap.DesignCompositeBeam.GetResultsAvailable()}");

        var rows = Takeoff.Read(sap);
        var path = Path.Combine(Root(), "takeoffs", $"{label}.csv");
        Takeoff.WriteCsv(path, rows);

        Console.WriteLine("\nsection sources");
        foreach (var g in rows.GroupBy(r => (r.Kind, r.SectionSource, r.WeightSource)).OrderBy(g => g.Key.ToString()))
            Console.WriteLine($"  {g.Key.Kind,-8} {g.Key.SectionSource,-17} {g.Key.WeightSource,-20} {g.Count(),5} frames");

        Console.WriteLine();
        Print(label, rows);
        Console.WriteLine($"\nsaved     {path}");
        return 0;
    }

    public static int Compare(string a, string b)
    {
        var ra = Takeoff.ReadCsv(Find(a));
        var rb = Takeoff.ReadCsv(Find(b));
        a = Path.GetFileNameWithoutExtension(a);
        b = Path.GetFileNameWithoutExtension(b);
        Console.WriteLine($"{"",-26}{a,16}{b,16}{"difference",16}");
        foreach (var (name, pick) in Groups)
        {
            double wa = ra.Where(pick).Sum(r => r.Lb), wb = rb.Where(pick).Sum(r => r.Lb);
            Console.WriteLine($"{name + " (tons)",-26}{wa / Takeoff.LbPerShortTon,16:N2}{wb / Takeoff.LbPerShortTon,16:N2}{(wb - wa) / Takeoff.LbPerShortTon,16:+0.00;-0.00;0.00}" +
                              (wa > 0 ? $"  {(wb - wa) / wa,8:+0.0%;-0.0%;0.0%}" : ""));
        }

        // The weight the second design adds to the first is taken frame by frame: a frame the second
        // design sizes lighter is still built at the first's section, so it adds nothing rather than
        // offsetting a frame that does get heavier. This is the envelope of both less the first.
        var first = ra.ToDictionary(r => r.Frame);
        var paired = rb.Where(r => first.ContainsKey(r.Frame)).Select(r => (A: first[r.Frame], B: r)).ToList();
        Console.WriteLine($"\nweight {b} adds to {a}, frame by frame (envelope of both − {a})");
        Console.WriteLine($"{"",-26}{"frames heavier",16}{"added tons",16}{"envelope tons",16}{"added",9}");
        foreach (var (name, pick) in Groups)
        {
            var g = paired.Where(p => pick(p.A)).ToList();
            if (g.Count == 0 && name.StartsWith("  ")) continue;
            var added = g.Sum(p => Math.Max(0, p.B.Lb - p.A.Lb));
            var baseLb = g.Sum(p => p.A.Lb);
            Console.WriteLine($"{name,-26}{g.Count(p => p.B.Lb > p.A.Lb),16}{added / Takeoff.LbPerShortTon,16:N2}{(baseLb + added) / Takeoff.LbPerShortTon,16:N2}" +
                              (baseLb > 0 ? $"{added / baseLb,9:+0.0%;-0.0%;0.0%}" : ""));
        }

        var byFrame = rb.ToDictionary(r => r.Frame);
        var changed = ra.Where(r => byFrame.TryGetValue(r.Frame, out var o) && o.Section != r.Section)
            .GroupBy(r => (r.Kind, From: r.Section, To: byFrame[r.Frame].Section))
            .OrderByDescending(g => g.Count()).ToList();
        Console.WriteLine($"\n{changed.Sum(g => g.Count())} frames sized differently");
        foreach (var g in changed.Take(40))
            Console.WriteLine($"  {g.Count(),4}  {g.Key.Kind,-8} {g.Key.From,-10} → {g.Key.To}");
        return 0;
    }

    private static readonly (string Name, Func<FrameWeight, bool> Pick)[] Groups =
    {
        ("columns", r => r.Kind == "Column"),
        ("beams", r => r.Kind == "Beam"),
        ("  steel designed", r => r.Kind == "Beam" && r.SectionSource == "steel design"),
        ("  composite designed", r => r.Kind == "Beam" && r.SectionSource == "composite design"),
        ("  not designed", r => r.Kind == "Beam" && r.SectionSource == "analysis"),
        ("other", r => r.Kind != "Column" && r.Kind != "Beam"),
        ("total", r => true),
    };

    private static void Print(string label, IReadOnlyList<FrameWeight> rows)
    {
        Console.WriteLine($"{label,-26}{"frames",8}{"length ft",14}{"lb",16}{"tons",12}");
        foreach (var (name, pick) in Groups)
        {
            var g = rows.Where(pick).ToList();
            if (g.Count == 0 && name.StartsWith("  ")) continue;
            Console.WriteLine($"{name,-26}{g.Count,8}{g.Sum(r => r.LengthFt),14:N1}{g.Sum(r => r.Lb),16:N0}{g.Sum(r => r.Lb) / Takeoff.LbPerShortTon,12:N2}");
        }
        Console.WriteLine("tons are short tons, 2000 lb");
    }

    private static string Find(string labelOrPath) => File.Exists(labelOrPath) ? labelOrPath : Path.Combine(Root(), "takeoffs", $"{labelOrPath}.csv");

    /// <summary>The repository root, so takeoffs land in one place whatever directory this runs from.</summary>
    private static string Root()
    {
        for (var d = new DirectoryInfo(AppContext.BaseDirectory); d is not null; d = d.Parent)
            if (File.Exists(Path.Combine(d.FullName, "QUIKCOLAPS.sln"))) return d.FullName;
        return Directory.GetCurrentDirectory();
    }
}
#endif
