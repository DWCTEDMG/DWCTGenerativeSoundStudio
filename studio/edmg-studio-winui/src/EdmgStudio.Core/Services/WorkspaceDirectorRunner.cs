using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Services;

/// <summary>Runs the managed Director to a reviewable draft without applying it.</summary>
public sealed class WorkspaceDirectorRunner(StudioApiClient api)
{
    public async Task<JsonElement> WaitForReviewAsync(
        string projectId, string jobId, long expectedRevision,
        Action<StudioJob>? progress = null, CancellationToken cancellationToken = default,
        TimeSpan? pollInterval = null)
    {
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            StudioJobListResponse jobs = await api.GetProjectJobsAsync(projectId, cancellationToken);
            StudioJob job = jobs.Jobs.FirstOrDefault(item => item.Id == jobId)
                ?? throw new InvalidOperationException("The Director job is no longer available. Refresh the project to recover its saved draft.");
            progress?.Invoke(job);
            if (job.Status == "succeeded")
                return await api.ReviewDirectorDraftAsync(projectId, jobId,
                    new DirectorApplyRequest(expectedRevision), cancellationToken);
            if (!job.IsActive)
                throw new InvalidOperationException(job.Error ?? $"Director job {job.Status}. The saved project is retained.");
            await Task.Delay(pollInterval ?? TimeSpan.FromSeconds(2), cancellationToken);
        }
    }
}
