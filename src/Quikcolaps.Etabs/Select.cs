#if CSI
namespace Quikcolaps.Etabs;

/// <summary>
/// Which running instance to talk to.
///
/// Several can be open at once, and the running-object table lists them in launch order, so taking
/// the first reads whichever model happened to start first. A model named by the caller is matched
/// by filename stem — a model being edited in place reports the program's own extension rather than
/// the model's. With no name, the instance nominated for the API is used; with several running and
/// none nominated, nothing is chosen, because guessing reads one model and writes another.
/// </summary>
public static class Select
{
    public static Instance Instance(string? modelName, Action<string>? log = null)
    {
        var running = Attach.Running(log);
        if (running.Count == 0)
            throw new InvalidOperationException("no running instance answered — start ETABS and open a model");

        if (!string.IsNullOrWhiteSpace(modelName))
        {
            var hits = running.Where(i => Stem(i.ModelPath).Contains(modelName, StringComparison.OrdinalIgnoreCase)).ToList();
            if (hits.Count == 1) return hits[0];
            var open = string.Join("\n  ", running.Select(i => i.ModelPath));
            throw new InvalidOperationException(hits.Count == 0
                ? $"no running instance has a model named like '{modelName}' open. Open:\n  {open}"
                : $"{hits.Count} running instances match '{modelName}' — name it more fully. Open:\n  {open}");
        }

        var nominated = Attach.Nominated(log);
        if (nominated is not null && Attach.Answers(nominated, out var path) && path.Length > 0)
            return running.FirstOrDefault(i => Stem(i.ModelPath).Equals(Stem(path), StringComparison.OrdinalIgnoreCase))
                   ?? new Instance("(registered active object)", 0, nominated, path);

        if (running.Count == 1) return running[0];
        throw new InvalidOperationException(
            $"{running.Count} instances are running and none is set as the active instance for the API — " +
            "name the model, or choose Tools > Set as Active Instance for API in the one you want");
    }

    private static string Stem(string path) => Path.GetFileNameWithoutExtension(path ?? "");
}
#endif
