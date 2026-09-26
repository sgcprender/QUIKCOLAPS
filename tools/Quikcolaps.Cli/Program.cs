#if CSI
using Quikcolaps.Etabs;

namespace Quikcolaps.Cli;

/// <summary>
/// Plans a column-removal case for every column in the removal group, and writes them with
/// <c>--commit</c>. Without it nothing in the model changes.
/// </summary>
internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string Arg(string flag, string fallback) => args.SkipWhile(a => a != flag).Skip(1).FirstOrDefault() ?? fallback;
        var commit = args.Contains("--commit");
        var combosOnly = args.Contains("--combos-only");
        var only = Arg("--only", "");
        if (double.TryParse(Arg("--plan-tolerance", ""), out var tol)) ColumnStack.PlanTolerance = tol;

        if (args.FirstOrDefault() == "compare" && args.Length >= 3) return Weigh.Compare(args[1], args[2]);
        if (args.FirstOrDefault() == "dialogs") return Dialogs.Run(Arg("--model", "progressive collapse"), args.Contains("--close"), int.TryParse(Arg("--pid", ""), out var pid) ? pid : null);

        var inst = Select.Instance(Arg("--model", "progressive collapse"));
        if (args.FirstOrDefault() == "weigh") return Weigh.Run(inst, Arg("--label", "takeoff"));
        if (args.FirstOrDefault() == "design-combos") return SteelCombos(inst.Api.SapModel, args.ElementAtOrDefault(1) ?? "", Arg("--strength-prefix", "DStlS"), commit);

        var sap = inst.Api.SapModel;
        Console.WriteLine($"model     {inst.ModelPath}");

        var template = CaseTemplate.Read(sap, Arg("--template", "CS1"));

        // add-load: put a pattern into the initial case and the template, then rebuild every case from
        // the template below, so the whole set carries it.
        if (args.FirstOrDefault() == "add-load")
        {
            var pattern = Arg("--pattern", "");
            if (pattern.Length == 0 || !double.TryParse(Arg("--scale", ""), out var scale))
            {
                Console.Error.WriteLine("add-load --pattern SDL --scale 1.2 [--commit]");
                return 2;
            }
            Console.WriteLine($"\n{template.InitialCase} now: {string.Join(" + ", CaseLoads.Initial(sap, template.InitialCase).Select(l => $"{l.Scale}×{l.Name}"))}");
            Console.WriteLine($"adding {scale}×{pattern} to {template.InitialCase}, and to {template.Name} on group '{template.LoadedGroup}'");
            if (!commit) { Console.WriteLine("dry run — add --commit"); return 0; }

            var faults = CaseLoads.SetInInitial(sap, template.InitialCase, pattern, scale).Concat(CaseLoads.SetInTemplate(sap, template, pattern, scale)).ToList();
            foreach (var f in faults) Console.WriteLine($"  READ BACK DIFFERS: {f}");
            if (faults.Count > 0) return 1;
            Console.WriteLine($"{template.InitialCase} now: {string.Join(" + ", CaseLoads.Initial(sap, template.InitialCase).Select(l => $"{l.Scale}×{l.Name}"))}");
            template = CaseTemplate.Read(sap, template.Name);
            Console.WriteLine("rebuilding every collapse case from the template");
        }
        Console.WriteLine($"template  {template.Name}: initial '{template.InitialCase}', removes frame {template.RemovedFrame}, loads group '{template.LoadedGroup}'");
        foreach (var o in template.Stages.SelectMany(s => s.Operations).Where(o => o.Operation == CaseTemplate.LoadObjects))
            Console.WriteLine($"          + {o.Scale} × {o.LoadName}");

        var plans = CollapseCase.Plan(sap, Arg("--group", "COLS_REMOVED"), template)
            .Where(p => only.Length == 0 || p.CaseName.Equals(only, StringComparison.OrdinalIgnoreCase) || p.Stack.Removed.Frame == only)
            .ToList();
        Console.WriteLine($"\n{plans.Count} case(s)\n");

        foreach (var p in plans)
        {
            Console.WriteLine($"{p.CaseName} (combo {p.ComboName})  remove {p.Stack.Removed.Frame} ({p.Stack.Removed.Label}@{p.Stack.Removed.Story})  → {p.GroupName}: {p.Stack.InfluenceArea.Count} floor areas");
            foreach (var l in p.Stack.Levels)
                Console.WriteLine($"    {l.Story,-10} {l.Label,-6} top joint {l.TopJoint,-6} floors {string.Join(" ", l.Floors)}");
            Console.WriteLine($"    stops: {p.Stack.Stop}");
        }

        if (!commit) { Console.WriteLine("\ndry run — add --commit to write these cases"); return 0; }

        var failed = 0;
        foreach (var p in plans)
        {
            // add-load leaves the combinations and the steel design selection as they are.
            var withCombos = args.FirstOrDefault() != "add-load";
            var faults = (combosOnly ? Array.Empty<string>() : p.Write(sap, template)).Concat(withCombos ? p.WriteCombo(sap) : Array.Empty<string>()).ToList();
            Console.WriteLine($"wrote {(combosOnly ? "" : p.CaseName + (withCombos ? " + " : "")),-23}{(withCombos ? p.ComboName : ""),-24} {(faults.Count == 0 ? "read back ok" : "READ BACK DIFFERS")}");
            foreach (var f in faults) Console.WriteLine($"    {f}");
            if (faults.Count > 0) failed++;
        }
        sap.View.RefreshView(0, false);
        Console.WriteLine($"\n{plans.Count - failed} of {plans.Count} written and verified. The model is not saved.");
        return failed == 0 ? 0 : 1;
    }

    /// <summary>
    /// <c>design-combos strength</c> selects the strength combinations for steel design and removes the
    /// collapse ones; <c>design-combos collapse</c> selects both; <c>design-combos collapseonly</c>
    /// selects the collapse combinations and removes the strength ones.
    /// </summary>
    private static int SteelCombos(CSiAPIv1.cSapModel sap, string which, string strengthPrefix, bool commit)
    {
        if (!Enum.TryParse<DesignCombos.Set>(which, true, out var set))
        {
            Console.Error.WriteLine("design-combos strength | collapse | collapseonly   [--strength-prefix DStlS] [--commit]");
            return 2;
        }
        var changes = DesignCombos.Plan(sap, set, strengthPrefix);
        foreach (var c in changes) Console.WriteLine($"  {(c.Selected ? "add   " : "remove")} {c.Combo}");
        if (changes.Count == 0) Console.WriteLine("  nothing to change");

        if (commit && changes.Count > 0)
        {
            var faults = DesignCombos.Apply(sap, changes);
            foreach (var f in faults) Console.WriteLine($"  READ BACK DIFFERS: {f}");
            if (faults.Count > 0) return 1;
        }
        else if (changes.Count > 0) Console.WriteLine("\ndry run — add --commit to change the selection");

        var now = DesignCombos.Selected(sap);
        var collapse = now.Count(c => DesignCombos.IsCollapse(sap, c));
        Console.WriteLine($"\nsteel strength combos now: {now.Count} — {now.Count - collapse} strength, {collapse} collapse. Re-run steel design before weighing.");
        return 0;
    }
}
#endif
