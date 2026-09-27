#if CSI
using System.Runtime.InteropServices;
using System.Text;

namespace Quikcolaps.Bridge;

/// <summary>
/// Watches the ETABS process for message boxes while a long API call runs. A call made while a
/// modal box is up waits behind it, so without this a stray box looks like a hang.
///
/// A box whose text starts with "Error initializing shader" (a display error ETABS raises when it
/// redraws; see CLAUDE.md) is answered with its default button and logged. Any other box is logged
/// and the bridge exits with code 3, leaving the box up for the user: the call behind it cannot be
/// cancelled, and pressing a button on a box nobody has read answers a question nobody asked.
///
/// Window handles, not the API, as in tools/Quikcolaps.Cli/Dialogs.cs (copied, not referenced:
/// that project is not modified on this branch, D14).
/// </summary>
internal static class Watch
{
    public const int ExitOtherBox = 3;
    private const string Dismissable = "Error initializing shader";

    public static T During<T>(int pid, string what, Func<T> call)
    {
        using var stop = new CancellationTokenSource();
        var watcher = Task.Run(() => Loop(pid, what, stop.Token));
        try { return call(); }
        finally { stop.Cancel(); watcher.Wait(); }
    }

    private static void Loop(int pid, string what, CancellationToken stop)
    {
        var handled = new HashSet<IntPtr>();
        while (!stop.IsCancellationRequested)
        {
            foreach (var h in Boxes(pid).Where(h => !handled.Contains(h)))
            {
                var title = TextOf(h);
                var body = string.Join(" | ", Children(h).Where(c => ClassOf(c) == "Static").Select(TextOf).Where(t => t.Length > 0));
                var buttons = Children(h).Where(c => ClassOf(c) == "Button" && IsWindowVisible(c)).Select(c => TextOf(c).Replace("&", "")).Where(t => t.Length > 0);
                if (body.TrimStart().StartsWith(Dismissable, StringComparison.OrdinalIgnoreCase))
                {
                    var target = DefaultButton(h);
                    if (target == IntPtr.Zero) continue;
                    PostMessage(target, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
                    handled.Add(h);
                    Console.Error.WriteLine($"dismissed ETABS box during {what}: {body} → {TextOf(target).Replace("&", "")}");
                    continue;
                }
                Console.Error.WriteLine($"error: ETABS is showing a message box during {what}, left up for you to answer:");
                Console.Error.WriteLine($"  [{title}] {body}   buttons: {string.Join(", ", buttons)}");
                Console.Error.WriteLine("  stopping; the call behind the box cannot be cancelled. Answer it in ETABS and check the model before running again.");
                Environment.Exit(ExitOtherBox);
            }
            stop.WaitHandle.WaitOne(500);
        }
    }

    /// <summary>Visible standard dialogs owned by the process.</summary>
    private static List<IntPtr> Boxes(int pid)
    {
        var found = new List<IntPtr>();
        EnumWindows((h, _) =>
        {
            GetWindowThreadProcessId(h, out var p);
            if (p == pid && IsWindowVisible(h) && ClassOf(h) == "#32770") found.Add(h);
            return true;
        }, IntPtr.Zero);
        return found;
    }

    private static IntPtr DefaultButton(IntPtr dlg)
    {
        if (SendMessageTimeout(dlg, DM_GETDEFID, IntPtr.Zero, IntPtr.Zero, SMTO_ABORTIFHUNG, 500, out var r) != IntPtr.Zero
            && (r.ToInt64() >> 16) == DC_HASDEFID)
        {
            var byId = GetDlgItem(dlg, (int)(r.ToInt64() & 0xFFFF));
            if (byId != IntPtr.Zero) return byId;
        }
        return Children(dlg).FirstOrDefault(c => ClassOf(c) == "Button" && IsWindowVisible(c) && TextOf(c).Replace("&", "").Length > 0);
    }

    private static List<IntPtr> Children(IntPtr parent)
    {
        var list = new List<IntPtr>();
        EnumChildWindows(parent, (h, _) => { list.Add(h); return true; }, IntPtr.Zero);
        return list;
    }

    private static string ClassOf(IntPtr h) { var sb = new StringBuilder(256); return GetClassName(h, sb, sb.Capacity) > 0 ? sb.ToString() : ""; }

    private static string TextOf(IntPtr h)
    {
        var len = GetWindowTextLength(h);
        if (len <= 0) return "";
        var sb = new StringBuilder(len + 1);
        GetWindowText(h, sb, sb.Capacity);
        return sb.ToString();
    }

    private const int BM_CLICK = 0x00F5, DM_GETDEFID = 0x0400, DC_HASDEFID = 0x534B, SMTO_ABORTIFHUNG = 0x0002;
    private delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] private static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr h, out int pid);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern int GetWindowText(IntPtr h, StringBuilder sb, int n);
    [DllImport("user32.dll")] private static extern int GetWindowTextLength(IntPtr h);
    [DllImport("user32.dll")] private static extern IntPtr GetDlgItem(IntPtr dlg, int id);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] private static extern IntPtr SendMessageTimeout(IntPtr h, int msg, IntPtr w, IntPtr l, int flags, int timeout, out IntPtr result);
}
#endif
