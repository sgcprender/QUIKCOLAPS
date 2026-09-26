#if CSI
using System.Text.Json;
using System.Text.Json.Nodes;
using CSiAPIv1;

namespace Quikcolaps.Bridge;

internal static class Json
{
    public static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public static void Write(string path, object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        File.WriteAllText(path, JsonSerializer.Serialize(value, Options));
        Console.Error.WriteLine($"wrote     {Path.GetFullPath(path)}");
    }

    public static JsonNode Read(string path) =>
        JsonNode.Parse(File.ReadAllText(path)) ?? throw new InvalidOperationException($"{path} is empty");

    /// <summary>Scenarios the user did not reject, from scenarios.json (ap/docs/schema/scenario.schema.json).</summary>
    public static IEnumerable<JsonNode> ActiveScenarios(JsonNode doc)
    {
        var rejected = (doc["candidates"]?.AsArray() ?? new JsonArray())
            .Where(c => (string?)c?["status"] == "rejected")
            .Select(c => (string?)c?["location_id"])
            .ToHashSet();
        return (doc["scenarios"]?.AsArray() ?? new JsonArray())
            .Where(s => s is not null && !rejected.Contains((string?)s["location_id"]))!;
    }

    public static List<string> Strings(JsonNode? arr) =>
        arr?.AsArray().Select(x => (string?)x ?? "").Where(x => x.Length > 0).ToList() ?? new List<string>();
}

/// <summary>
/// Runs a block with the model's present units set to kN, m, °C and puts them back afterwards,
/// so everything the bridge exchanges with Python is SI (see ap/docs/decisions.md, D11).
/// Present units only change what the API reports and accepts; the model data is unchanged.
/// </summary>
internal static class Si
{
    public static T With<T>(cSapModel sap, Func<T> body)
    {
        var original = sap.GetPresentUnits();
        sap.SetPresentUnits(eUnits.kN_m_C);
        try { return body(); }
        finally { sap.SetPresentUnits(original); }
    }
}
#endif
