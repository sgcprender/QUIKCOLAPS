#if CSI
using CSiAPIv1;

namespace Quikcolaps.Bridge;

/// <summary>
/// Unlocking before a write. A locked model (one with analysis results) refuses edits, so the
/// commands that write (apply, assign-sections) unlock it themselves with --commit and report it;
/// a dry run only says what --commit would do.
///
/// SetModelIsLocked(false) (measured, CLAUDE.md): answered 1 on the AP copy and 0 on AP2, and
/// unlocked both times, so the return code is logged and only the read-back decides. Unlocking
/// deletes the analysis results but keeps the steel design sections.
/// </summary>
internal static class ModelLock
{
    public enum Action { None, WouldUnlock, Unlock }

    /// <summary>What a command does about the lock: nothing when unlocked; unlock only with --commit.</summary>
    public static Action Plan(bool locked, bool commit) => !locked ? Action.None : commit ? Action.Unlock : Action.WouldUnlock;

    /// <summary>Unlocks when needed (commit only) and throws unless GetModelIsLocked reads false afterwards.</summary>
    public static void EnsureUnlocked(cSapModel sap, bool commit, string command)
    {
        var locked = sap.GetModelIsLocked();
        switch (Plan(locked, commit))
        {
            case Action.None:
                Console.Error.WriteLine("lock      unlocked");
                return;
            case Action.WouldUnlock:
                Console.Error.WriteLine($"lock      locked: {command} --commit unlocks it first, which deletes the analysis results");
                return;
        }
        var ret = sap.SetModelIsLocked(false);
        if (sap.GetModelIsLocked())
            throw new InvalidOperationException($"the model is locked and SetModelIsLocked(false) (returned {ret}) left it locked; nothing written");
        Console.Error.WriteLine($"lock      was locked; unlocked (SetModelIsLocked returned {ret}, read back unlocked); analysis results deleted");
    }
}
#endif
