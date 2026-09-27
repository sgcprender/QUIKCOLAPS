#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// open --file PATH: opens a model file in the running ETABS (the one --model attached to), for
/// switching between the working copy and the strength baseline. File.OpenFile(FileName) is
/// documented ("Returns zero if the file is successfully opened"); the help does not say what
/// happens to unsaved changes in the model that was open. The call runs under Watch, so a
/// question box (e.g. save changes?) stops the bridge with exit 3 and is left for the user
/// rather than answered. The bridge never saves: RunAnalysis is the only thing that does.
/// Read-back: SapModel.GetModelFilename must be the file asked for.
/// </summary>
internal static class OpenModel
{
    public static int Run(cSapModel sap, int pid, string file)
    {
        if (file.Length == 0) { Console.Error.WriteLine("open --file PATH"); return 2; }
        var path = Path.GetFullPath(file);
        if (!File.Exists(path)) throw new InvalidOperationException($"{path} not found");
        Console.Error.WriteLine($"open      closing {sap.GetModelFilename()} (locked {sap.GetModelIsLocked()}; not saved by the bridge)");
        var ret = Watch.During(pid, "File.OpenFile", () => sap.File.OpenFile(path));
        var now = sap.GetModelFilename() ?? "";
        if (ret != 0 || !string.Equals(Path.GetFullPath(now), path, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException($"File.OpenFile returned {ret}; the open model is '{now}', not '{path}'");
        Console.Error.WriteLine($"open      {now} (locked {sap.GetModelIsLocked()})");
        return 0;
    }
}
#endif
