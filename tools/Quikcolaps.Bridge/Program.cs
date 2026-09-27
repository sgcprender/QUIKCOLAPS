#if CSI
using Quikcolaps.Etabs;

namespace Quikcolaps.Bridge;

/// <summary>
/// JSON bridge between ETABS and the Python side (ap/). Reuses Quikcolaps.Etabs for attaching,
/// column stacks and combinations; adds export, stacks, apply and results.
///
/// Read-only unless a command is given --commit. The model is never saved.
///
///   export   --out building.json                     geometry, stories, floor areas, loads (kN, m)
///   stacks   --scenarios scenarios.json --out stacks.json   influence area per removed column
///   apply    --scenarios scenarios.json [--template CS1] [--commit]   cases, load groups, combos
///   results  --scenarios scenarios.json --out results.json [--run] [--design]
///   forces   --case NAME --frames F1,F2 --out forces.json            for the staged-case validation
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
                    args.Contains("--run"), args.Contains("--design")),
                "forces" => Results.Forces(sap, Arg("--case", ""), Arg("--frames", ""), Arg("--out", "forces.json")),
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
        Console.Error.WriteLine("quikcolaps-bridge export|stacks|apply|results|forces [--model NAME] ... (see Program.cs)");
        return 2;
    }
}
#endif
