using System.Text.Json;

namespace EdmgStudio.Core.Models;

public enum RenderQueueHealth
{
    Neutral,
    Active,
    Complete,
    Attention
}

public enum RenderQueueFilter
{
    All,
    Active,
    Queued,
    Completed,
    Attention
}

public sealed record RenderQueueJobSummary(
    StudioJob Job,
    string Title,
    string StatusLabel,
    string StageLabel,
    string ProgressLabel,
    string EtaLabel,
    string ElapsedLabel,
    string PriorityLabel,
    string DestinationLabel,
    string Recommendation,
    double Percent,
    RenderQueueHealth Health)
{
    public bool Matches(RenderQueueFilter filter) => filter switch
    {
        RenderQueueFilter.Active => Job.IsActive,
        RenderQueueFilter.Queued => Job.Status is "queued" or "paused",
        RenderQueueFilter.Completed => Job.Status == "succeeded",
        RenderQueueFilter.Attention => Health == RenderQueueHealth.Attention,
        _ => true
    };

    public static RenderQueueJobSummary Create(StudioJob job, DateTimeOffset? now = null)
    {
        ArgumentNullException.ThrowIfNull(job);
        DateTimeOffset currentTime = now ?? DateTimeOffset.UtcNow;
        double percent = Math.Clamp(job.Progress?.Percent ?? 0, 0, 100);
        string status = FormatLabel(job.Status);
        string stage = job.Progress?.Message ?? job.Progress?.Stage ?? status;
        TimeSpan? elapsed = GetElapsed(job, currentTime);
        TimeSpan? eta = EstimateRemaining(job, percent, currentTime);

        return new RenderQueueJobSummary(
            job,
            $"{FormatLabel(job.Type)} · {ShortId(job.Id)}",
            status,
            stage,
            BuildProgressLabel(job, percent),
            eta is null ? "ETA calculating" : $"ETA {FormatDuration(eta.Value)}",
            elapsed is null ? "Not started" : $"Elapsed {FormatDuration(elapsed.Value)}",
            FormatPriority(job.Priority),
            FindDestination(job),
            RecommendationFor(job),
            percent,
            HealthFor(job));
    }

    private static TimeSpan? GetElapsed(StudioJob job, DateTimeOffset now)
    {
        if (!DateTimeOffset.TryParse(job.StartedAt, out DateTimeOffset started))
        {
            return null;
        }

        DateTimeOffset end = DateTimeOffset.TryParse(job.FinishedAt, out DateTimeOffset finished)
            ? finished
            : now;
        return end >= started ? end - started : null;
    }

    private static TimeSpan? EstimateRemaining(StudioJob job, double percent, DateTimeOffset now)
    {
        if (job.Status != "running" || percent <= 0 || percent >= 100 ||
            !DateTimeOffset.TryParse(job.StartedAt, out DateTimeOffset started))
        {
            return null;
        }

        double seconds = (now - started).TotalSeconds * (100 - percent) / percent;
        if (!double.IsFinite(seconds) || seconds < 0)
        {
            return null;
        }

        return TimeSpan.FromSeconds(Math.Min(seconds, TimeSpan.FromDays(7).TotalSeconds));
    }

    private static string BuildProgressLabel(StudioJob job, double percent)
    {
        if (job.Progress?.Current is double current && job.Progress.Total is double total && total > 0)
        {
            return $"{percent:0}% · {current:0}/{total:0}";
        }

        return job.IsActive ? $"{percent:0}%" : FormatLabel(job.Status);
    }

    private static RenderQueueHealth HealthFor(StudioJob job) => job.Status switch
    {
        "failed" or "canceled" => RenderQueueHealth.Attention,
        "running" => RenderQueueHealth.Active,
        "succeeded" => RenderQueueHealth.Complete,
        _ => RenderQueueHealth.Neutral
    };

    private static string RecommendationFor(StudioJob job) => job.Status switch
    {
        "failed" when job.Type.Contains("internal", StringComparison.OrdinalIgnoreCase) =>
            "Inspect the log, then resume from checkpoint or restart clean.",
        "failed" => "Inspect diagnostics, then retry when the dependency is ready.",
        "canceled" => "Retry to queue a fresh attempt with the same render settings.",
        "paused" => "Resume when resources are available, or adjust its priority.",
        "queued" => "Adjust priority to change when this job is claimed.",
        "running" => "Rendering is active. Cancellation completes after the current step.",
        "succeeded" => "Open Outputs or Review to inspect the completed artifact.",
        _ => "Monitor this job for updated status and diagnostics."
    };

    private static string FindDestination(StudioJob job)
    {
        foreach (JsonElement? source in new[] { job.Result, job.Payload })
        {
            if (source is not JsonElement element || element.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            foreach (string property in new[] { "output_path", "artifact_path", "output_dir", "destination", "path" })
            {
                if (element.TryGetProperty(property, out JsonElement value) &&
                    value.ValueKind == JsonValueKind.String &&
                    !string.IsNullOrWhiteSpace(value.GetString()))
                {
                    return value.GetString()!;
                }
            }
        }

        return "Project outputs";
    }

    private static string FormatPriority(int priority) => priority switch
    {
        >= 100 => "Urgent",
        >= 50 => "High",
        <= -50 => "Low",
        _ => "Normal"
    };

    private static string FormatDuration(TimeSpan value) => value.TotalHours >= 1
        ? $"{value:h\\:mm\\:ss}"
        : $"{value:mm\\:ss}";

    private static string FormatLabel(string value) => value.Replace('_', ' ');

    private static string ShortId(string value) => value.Length <= 8 ? value : value[..8];
}

public sealed record RenderQueueSnapshot(
    int TotalCount,
    int ActiveCount,
    int QueuedCount,
    int RunningCount,
    int CompletedCount,
    int AttentionCount,
    double ActiveProgress,
    string Summary)
{
    public static RenderQueueSnapshot Create(IEnumerable<StudioJob> jobs)
    {
        StudioJob[] items = jobs?.ToArray() ?? [];
        StudioJob[] active = items.Where(job => job.IsActive).ToArray();
        int queued = items.Count(job => job.Status is "queued" or "paused");
        int running = items.Count(job => job.Status == "running");
        int completed = items.Count(job => job.Status == "succeeded");
        int attention = items.Count(job => job.Status is "failed" or "canceled");
        double progress = active.Length == 0
            ? 0
            : active.Average(job => Math.Clamp(job.Progress?.Percent ?? 0, 0, 100));
        string summary = active.Length > 0
            ? $"{running} running · {queued} waiting · {progress:0}% average"
            : attention > 0
                ? $"No active jobs · {attention} need attention"
                : "Queue is idle";

        return new RenderQueueSnapshot(
            items.Length,
            active.Length,
            queued,
            running,
            completed,
            attention,
            progress,
            summary);
    }
}
