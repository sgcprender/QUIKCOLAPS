#if CSI
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using CSiAPIv1;

namespace Quikcolaps.Etabs;

public sealed record Instance(string Moniker, int ProcessId, cOAPI Api, string ModelPath);

/// <summary>
/// Finding a running program and getting a handle that works.
///
/// The vendor helper cannot be used: it calls Marshal.GetActiveObject, which .NET Framework has
/// and .NET removed, so it throws "Method not found" for every ProgID. The two OLE calls it used
/// to make are made directly here instead.
/// </summary>
public static class Attach
{
    private static readonly string[] ProgIds =
    {
        "CSI.ETABS.API.ETABSObject",
        "CSI.SAFE.API.ETABSObject",
        "CSI.SAP2000.API.SapObject"
    };

    /// <summary>The instance the user nominated for the API, if any.</summary>
    public static cOAPI? Nominated(Action<string>? log = null)
    {
        foreach (var id in ProgIds)
        {
            try
            {
                CLSIDFromProgID(id, out var clsid);
                GetActiveObject(ref clsid, IntPtr.Zero, out var obj);
                if (obj is cOAPI api) { log?.Invoke($"  nominated via {id}"); return api; }
            }
            catch (Exception e) { log?.Invoke($"  {id}: {e.GetType().Name}"); }
        }
        return null;
    }

    /// <summary>
    /// Everything registered and answering. A stale registration hands back an object that looks
    /// fine and fails on the first real call, so each candidate is probed by calling something
    /// rather than merely by being reached.
    /// </summary>
    public static List<Instance> Running(Action<string>? log = null)
    {
        var found = new List<Instance>();
        IRunningObjectTable rot;
        IBindCtx ctx;
        try { GetRunningObjectTable(0, out rot); CreateBindCtx(0, out ctx); }
        catch (Exception e) { log?.Invoke($"  ROT unavailable: {e.Message}"); return found; }

        rot.EnumRunning(out var monikers);
        var one = new IMoniker[1];

        while (monikers.Next(1, one, IntPtr.Zero) == 0)
        {
            string name;
            try { one[0].GetDisplayName(ctx, null, out name); } catch { continue; }
            if (name.IndexOf("etabs", StringComparison.OrdinalIgnoreCase) < 0 &&
                name.IndexOf("sap", StringComparison.OrdinalIgnoreCase) < 0 &&
                name.IndexOf("safe", StringComparison.OrdinalIgnoreCase) < 0) continue;

            try
            {
                rot.GetObject(one[0], out var obj);
                if (obj is not cOAPI api) continue;
                if (!Answers(api, out var path, log)) { log?.Invoke($"  {name}: registered but not answering"); continue; }
                found.Add(new Instance(name, PidFrom(name), api, path));
            }
            catch (Exception e) { log?.Invoke($"  {name}: {e.GetType().Name} {e.Message}"); }
        }
        return found;
    }

    /// <summary>
    /// Whether a handle is usable. Reaching an object proves nothing — it has to be called, and
    /// called on the part that fails: results setup is where pulls die. The call chosen is a getter
    /// so probing changes nothing.
    /// </summary>
    public static bool Answers(cOAPI api, out string modelPath, Action<string>? log = null)
    {
        modelPath = "";
        try
        {
            var sap = api.SapModel;
            modelPath = sap.GetModelFilename() ?? "";
            var onlyStatic = 0;
            sap.Results.Setup.GetOptionMultiStepStatic(ref onlyStatic);
            return true;
        }
        catch (Exception e) { log?.Invoke($"    unusable: {e.GetType().Name}"); return false; }
    }

    private static int PidFrom(string moniker)
    {
        var colon = moniker.LastIndexOf(':');
        return colon >= 0 && int.TryParse(moniker.Substring(colon + 1), out var pid) ? pid : 0;
    }

    [DllImport("ole32.dll", PreserveSig = false)]
    private static extern void CLSIDFromProgID([MarshalAs(UnmanagedType.LPWStr)] string progId, out Guid clsid);

    [DllImport("oleaut32.dll", PreserveSig = false)]
    private static extern void GetActiveObject(ref Guid rclsid, IntPtr reserved,
        [MarshalAs(UnmanagedType.IUnknown)] out object ppunk);

    [DllImport("ole32.dll")]
    private static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable prot);

    [DllImport("ole32.dll")]
    private static extern int CreateBindCtx(int reserved, out IBindCtx ppbc);
}
#endif
