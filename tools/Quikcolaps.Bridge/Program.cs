#if CSI
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// JSON bridge between ETABS and the Python side (ap/). Reuses Quikcolaps.Etabs for attaching,
/// column stacks and combinations; adds export, stacks, apply and results.
///
/// Read-only unless a command is given --commit (apply and assign-sections unlock a locked model
/// first, with read-back) or results --run/--design. The bridge never saves the model itself.
///
///   export   --out building.json                     geometry, stories, floor areas, loads (kN, m)
///   stacks   --scenarios scenarios.json --out stacks.json   influence area per removed column
///   apply    --scenarios scenarios.json [--template CS1] [--commit]   cases, load groups, combos
///   results  --scenarios scenarios.json --out results.json [--run] [--design]
///   forces   --case NAME --frames F1,F2 --out forces.json            for the staged-case validation
///   axial    --case "1.2D+0.5L" --out intact_axial.json               every column's axial force (read-only)
///   assign-sections --file propagation.json [--commit]                fixed analysis sections from a file
///   open     --file PATH                                               open another model file (never saves)
///   design-select --combos DStlS1,DStlS2 [--commit]                   steel + composite strength selection
///   iterate  --cases SW,SDL,LL [--max-rounds 3] --out rounds.json [--commit]   run → design until no section changes
///   sections                                                          auto-select frames: analysis vs design section
///
/// results --run stops (exit 4) when an auto-select frame's design section differs from its analysis
/// section, since the run would adopt the design sections; --accept-design-sections runs anyway.
/// </summary>
internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string Arg(string flag, string fallback) => args.SkipWhile(a => a != flag).Skip(1).FirstOrDefault() ?? fallback;
        var cmd = args.FirstOrDefault() ?? "";
        if (double.TryParse(Arg("--plan-tolerance", ""), out var tol)) ColumnStack.PlanTolerance = tol;

        try
        {
            var inst = Select.Instance(Arg("--model", "progressive collapse"));
            var sap = inst.Api.SapModel;
            Console.Error.WriteLine($"model     {inst.ModelPath}");
            return cmd switch
            {
                "export" => Export.Run(sap, inst.ModelPath, Arg("--out", "building.json"), Arg("--template", "CS1")),
                "stacks" => Stacks.Run(sap, Arg("--scenarios", "scenarios.json"), Arg("--out", "stacks.json")),
                "apply" => Apply.Run(sap, Arg("--scenarios", "scenarios.json"), Arg("--template", "CS1"), args.Contains("--commit")),
                "results" => Results.Run(sap, inst.ProcessId, Arg("--scenarios", "scenarios.json"), Arg("--template", "CS1"), Arg("--out", "results.json"),
                    args.Contains("--run"), args.Contains("--design"), args.Contains(SectionGuard.AcceptFlag)),
                "sections" => SectionGuard.Allows(sap, false) ? 0 : SectionGuard.ExitSectionsDiffer,
                "forces" => Results.Forces(sap, Arg("--case", ""), Arg("--frames", ""), Arg("--out", "forces.json")),
                "axial" => Axial.Run(sap, inst.ModelPath, Arg("--case", ""), Arg("--out", "intact_axial.json")),
                "open" => OpenModel.Run(sap, inst.ProcessId, Arg("--file", "")),
                "design-select" => DesignSelect.Run(sap, Arg("--combos", ""), args.Contains("--commit")),
                "iterate" => Iterate.Run(sap, inst.ProcessId, inst.ModelPath, Arg("--cases", ""), int.TryParse(Arg("--max-rounds", "3"), out var mr) ? mr : 3,
                    Arg("--out", "rounds.json"), args.Contains("--commit")),
                "assign-sections" => AssignSections.Run(sap, Arg("--file", "ap/web/data/propagation.json"), args.Contains("--commit")),
                _ => Usage()
            };
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"error: {e.Message}");
            return 1;
        }
    }

    private static int Usage()
    {
        Console.Error.WriteLine("quikcolaps-bridge export|stacks|apply|results|forces|axial|assign-sections|open|design-select|iterate|sections [--model NAME] ... (see Program.cs)");
        return 2;
    }
}
#endif
