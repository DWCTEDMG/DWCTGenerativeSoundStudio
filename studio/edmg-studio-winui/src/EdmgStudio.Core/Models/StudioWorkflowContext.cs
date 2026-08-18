namespace EdmgStudio.Core.Models;

public sealed record StudioWorkflowContext(
    string? ActiveProjectId = null,
    int SelectedVariant = 0,
    string? SelectedArtifactPath = null,
    string? SelectedJobId = null,
    string? SelectedJobProjectId = null,
    string? SourceAssetPath = null,
    double? TimelineFocusSeconds = null,
    string? RenderContext = null,
    string? LastWorkflowDestination = null)
{
    public StudioWorkflowContext Normalize()
    {
        string? projectId = NormalizeText(ActiveProjectId);
        string? jobProjectId = NormalizeText(SelectedJobProjectId);
        string? jobId = NormalizeText(SelectedJobId);

        if (jobId is null)
        {
            jobProjectId = null;
        }

        return this with
        {
            ActiveProjectId = projectId,
            SelectedVariant = Math.Max(0, SelectedVariant),
            SelectedArtifactPath = NormalizeText(SelectedArtifactPath),
            SelectedJobId = jobId,
            SelectedJobProjectId = jobProjectId,
            SourceAssetPath = NormalizeText(SourceAssetPath),
            TimelineFocusSeconds = NormalizeTimelineFocus(TimelineFocusSeconds),
            RenderContext = NormalizeText(RenderContext),
            LastWorkflowDestination = NormalizeText(LastWorkflowDestination)
        };
    }

    public StudioWorkflowContext WithActiveProject(string? projectId)
    {
        string? normalizedProjectId = NormalizeText(projectId);
        StudioWorkflowContext current = Normalize();
        if (string.Equals(current.ActiveProjectId, normalizedProjectId, StringComparison.Ordinal))
        {
            return current;
        }

        return current with
        {
            ActiveProjectId = normalizedProjectId,
            SelectedVariant = 0,
            SelectedArtifactPath = null,
            SelectedJobId = null,
            SelectedJobProjectId = null,
            SourceAssetPath = null,
            TimelineFocusSeconds = null,
            RenderContext = null
        };
    }

    public StudioWorkflowContext WithSelectedJob(string? projectId, string? jobId)
    {
        string? normalizedJobId = NormalizeText(jobId);
        return Normalize() with
        {
            SelectedJobId = normalizedJobId,
            SelectedJobProjectId = normalizedJobId is null ? null : NormalizeText(projectId)
        };
    }

    public static string? NormalizeText(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static double? NormalizeTimelineFocus(double? value) =>
        value is >= 0 && double.IsFinite(value.Value) ? value : null;
}
