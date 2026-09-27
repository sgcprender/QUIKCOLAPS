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
///   autoselect --frames F1,F2 [--commit]                              fixed frames back on (a copy of) their auto-select list
///   autoselect --cleanup [--commit]                                   delete FIN_* lists no frame uses
///   run      --cases SW,SDL,LL,1.2D+0.5L [--commit]                  analysis of these cases only (lean flags), no design
///   check-model [--template CS1] --out check_model.json               read-only readiness check (app step 0)
///   scenario-ratios --scenarios scenarios.json --out ratios.json [--commit]   each member's ratio per scenario combo
///   open     --file PATH                                               open another model file (never saves)
///   design-select --combos DStlS1,DStlS2 [--commit]                   steel + composite strength selection
///   iterate  --cases SW,SDL,LL [--max-rounds 3] [--weight-tol 0.005] --out rounds.json [--commit --accept-design-sections]
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
                    double.TryParse(Arg("--weight-tol", ""), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var wt) ? wt : null,
                    Arg("--out", "rounds.json"), args.Contains("--commit"), args.Contains(SectionGuard.AcceptFlag)),
                "run" => RunFlags.RunCases(sap, inst.ProcessId, Arg("--cases", ""), args.Contains("--commit")),
                "check-model" => CheckModel.Run(sap, inst.ModelPath, Arg("--template", "CS1"), Arg("--out", "check_model.json")),
                "scenario-ratios" => ScenarioRatios.Run(sap, inst.ProcessId, Arg("--scenarios", "scenarios.json"), Arg("--out", "scenario_ratios.json"), args.Contains("--commit")),
                "autoselect" => args.Contains("--cleanup") ? AutoSelect.Cleanup(sap, args.Contains("--commit"))
                    : AutoSelect.Run(sap, Arg("--frames", ""), args.Contains("--commit")),
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
        Console.Error.WriteLine("quikcolaps-bridge export|stacks|apply|results|forces|axial|assign-sections|autoselect|run|check-model|scenario-ratios|open|design-select|iterate|sections [--model NAME] ... (see Program.cs)");
        return 2;
    }
}
#endif
