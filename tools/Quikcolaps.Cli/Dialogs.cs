using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

namespace Quikcolaps.Cli;

/// <summary>
/// Lists, and with <c>--close</c> answers, the message boxes an ETABS instance has up.
///
/// Works from window handles, not the API: a call made while a modal box is up waits behind it.
/// Each box is answered with the button it nominates as its default — what Enter would press — and
/// the sweep repeats, because answering one box can raise the next. File choosers are left alone:
/// answering one picks a path nobody chose.
/// </summary>
internal static class Dialogs
{
    public static int Run(string modelName, bool close, int? pidGiven = null)
    {
        // The main window's title drops the model name while the program is busy, so a process id
        // can be given instead.
        var procs = pidGiven is int given ? new List<Process> { Process.GetProcessById(given) }
            : Process.GetProcessesByName("ETABS").Where(p => p.MainWindowTitle.Contains(modelName, StringComparison.OrdinalIgnoreCase)).ToList();
        if (procs.Count != 1)
        {
            Console.Error.WriteLine($"{procs.Count} ETABS windows have '{modelName}' in their title:");
            foreach (var p in Process.GetProcessesByName("ETABS")) Console.Error.WriteLine($"  pid {p.Id}  {p.MainWindowTitle}");
            return 1;
        }
        var pid = procs[0].Id;
        Console.WriteLine($"pid {pid}  {procs[0].MainWindowTitle}");

        var answered = 0;
        var quiet = 0;
        for (var sweep = 0; sweep < 500 && quiet < 6; sweep++)
        {
            var boxes = Boxes(pid).ToList();
            if (boxes.Count == 0) { quiet++; Thread.Sleep(250); continue; }
            quiet = 0;

            foreach (var h in boxes)
            {
                var title = TextOf(h);
                var body = string.Join(" | ", Children(h).Where(c => ClassOf(c) == "Static").Select(TextOf).Where(t => t.Length > 0));
                var buttons = Children(h).Where(c => ClassOf(c) == "Button" && IsWindowVisible(c)).Select(c => TextOf(c).Replace("&", "")).Where(t => t.Length > 0).ToList();
                var chooser = new[] { "SHELLDLL_DefView", "DirectUIHWND" }.Any(cls => Children(h).Any(c => ClassOf(c) == cls));

                if (!close || chooser)
                {
                    Console.WriteLine($"  [{title}] {body}   buttons: {string.Join(", ", buttons)}{(chooser ? "   (file chooser — left alone)" : "")}");
                    continue;
                }
                var target = DefaultButton(h);
                if (target == IntPtr.Zero) { Console.WriteLine($"  [{title}] {body}   — no button to press"); continue; }
                Console.WriteLine($"  [{title}] {body}   → {TextOf(target).Replace("&", "")}");
                PostMessage(target, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
                answered++;
            }
            if (!close) return 0;
            Thread.Sleep(300);
        }
        Console.WriteLine(close ? $"\n{answered} answered; none left up." : "\nno message boxes up.");
        return 0;
    }

    /// <summary>Visible standard dialogs owned by the process.</summary>
    private static IEnumerable<IntPtr> Boxes(int pid)
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
