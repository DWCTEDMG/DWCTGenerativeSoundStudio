namespace EdmgStudio.Core.Models;

public enum StudioTaskbarProgressState
{
    None,
    Indeterminate,
    Normal,
    Paused,
    Error
}

public sealed record StudioTaskbarProgress(StudioTaskbarProgressState State, double Percent)
{
    public static StudioTaskbarProgress None { get; } = new(StudioTaskbarProgressState.None, 0);

    public static StudioTaskbarProgress Create(IEnumerable<StudioJob>? jobs)
    {
        StudioJob[] items = (jobs ?? []).ToArray();
        StudioJob? running = items
            .Where(job => job.Status == "running")
            .OrderByDescending(job => job.Priority)
            .ThenBy(job => job.CreatedAt, StringComparer.Ordinal)
            .FirstOrDefault();
        if (running is not null)
        {
            double? percent = running.Progress?.Percent;
            return percent is >= 0 and <= 100
                ? new(StudioTaskbarProgressState.Normal, percent.Value)
                : new(StudioTaskbarProgressState.Indeterminate, 0);
        }

        StudioJob? paused = items.FirstOrDefault(job => job.Status == "paused");
        if (paused is not null)
        {
            return new(StudioTaskbarProgressState.Paused, Math.Clamp(paused.Progress?.Percent ?? 0, 0, 100));
        }

        if (items.Any(job => job.Status == "queued"))
        {
            return new(StudioTaskbarProgressState.Indeterminate, 0);
        }

        return items.Any(job => job.Status == "failed")
            ? new(StudioTaskbarProgressState.Error, 100)
            : None;
    }
}

public sealed record StudioShellActivity(
    StudioJob? FeaturedJob,
    int ActiveJobCount,
    int FailedJobCount,
    int ReviewItemCount,
    int ModelAttentionCount)
{
    public static StudioShellActivity Create(
        IEnumerable<StudioJob>? jobs,
        ModelCatalogueResponse? catalogue,
        ISet<string>? reviewedJobIds = null)
    {
        StudioJob[] allJobs = (jobs ?? [])
            .OrderByDescending(job => ParseTimestamp(job.UpdatedAt ?? job.CreatedAt))
            .ToArray();
        StudioJob? featured = allJobs.FirstOrDefault(job => job.IsActive);
        int active = allJobs.Count(job => job.IsActive);
        int failed = allJobs.Count(job => job.Status.Equals("failed", StringComparison.OrdinalIgnoreCase));
        int review = allJobs.Count(job =>
            job.Status.Equals("succeeded", StringComparison.OrdinalIgnoreCase)
            && IsRenderJob(job)
            && (reviewedJobIds is null || !reviewedJobIds.Contains(job.Id)));
        int modelAttention = (catalogue?.Catalog ?? [])
            .Concat(catalogue?.User ?? [])
            .Count(NeedsAttention);

        return new StudioShellActivity(featured, active, failed, review, modelAttention);
    }

    private static bool IsRenderJob(StudioJob job) =>
        job.Type.Contains("render", StringComparison.OrdinalIgnoreCase)
        || job.Type.Contains("video", StringComparison.OrdinalIgnoreCase);

    private static bool NeedsAttention(ModelCatalogueEntry entry) =>
        entry.PackageStatus is { Installed: true, RuntimeReady: false }
        || (entry.PackageStatus?.Blockers?.Count ?? 0) > 0;

    private static DateTimeOffset ParseTimestamp(string? value) =>
        DateTimeOffset.TryParse(value, out DateTimeOffset parsed) ? parsed : DateTimeOffset.MinValue;
}
