using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public sealed record TimelineRecoveryCandidate(string Source, string? SnapshotName);

public static class TimelineRecovery
{
    public static bool TrySelectCrashRecovery(
        JsonObject? recoveryDocument,
        out TimelineRecoveryCandidate candidate)
    {
        candidate = new TimelineRecoveryCandidate("journal", null);
        if (recoveryDocument?["needs_recovery"]?.GetValue<bool>() != true ||
            recoveryDocument["candidates"] is not JsonArray candidates)
        {
            return false;
        }

        JsonObject? journal = candidates
            .OfType<JsonObject>()
            .FirstOrDefault(item =>
                string.Equals(
                    item["kind"]?.GetValue<string>(),
                    "journal",
                    StringComparison.OrdinalIgnoreCase));
        if (journal is not null)
        {
            return true;
        }

        JsonObject? snapshot = candidates
            .OfType<JsonObject>()
            .FirstOrDefault(item =>
                string.Equals(
                    item["kind"]?.GetValue<string>(),
                    "snapshot",
                    StringComparison.OrdinalIgnoreCase) &&
                !string.IsNullOrWhiteSpace(item["path"]?.GetValue<string>()));
        if (snapshot is null)
        {
            return false;
        }

        candidate = new TimelineRecoveryCandidate(
            "snapshot",
            Path.GetFileName(snapshot["path"]!.GetValue<string>()));
        return true;
    }
}
