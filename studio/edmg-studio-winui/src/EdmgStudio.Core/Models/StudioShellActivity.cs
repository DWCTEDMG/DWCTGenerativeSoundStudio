namespace EdmgStudio.Core.Models;

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
