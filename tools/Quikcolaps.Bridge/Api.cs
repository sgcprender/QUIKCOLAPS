#if CSI
namespace Quikcolaps.Bridge;

/// <summary>
/// The bridge's copy of <c>ColumnStack.Check</c>, which is internal to Quikcolaps.Etabs and so not
/// visible here; that library is not modified on this branch (ap/docs/decisions.md D14).
/// </summary>
internal static class Api
{
    public static void Check(int ret, string call)
    {
        if (ret != 0) throw new InvalidOperationException($"{call} returned {ret}");
    }
}
#endif
