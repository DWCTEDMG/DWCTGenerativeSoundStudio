namespace EdmgStudio.Core.Services;

public sealed record ManagedProjectPathResolution(
    bool IsAvailable,
    string? FullPath,
    string ErrorMessage)
{
    public static ManagedProjectPathResolution Available(string fullPath) =>
        new(true, fullPath, string.Empty);

    public static ManagedProjectPathResolution Unavailable(string errorMessage) =>
        new(false, null, errorMessage);
}

public static class ManagedProjectPathResolver
{
    public static ManagedProjectPathResolution Resolve(
        RequestedBackendMode backendMode,
        string dataDirectory,
        string projectId,
        string projectRelativePath)
    {
        if (backendMode != RequestedBackendMode.Managed)
        {
            return ManagedProjectPathResolution.Unavailable(
                "Server-side folders cannot be opened for an external backend.");
        }

        if (!IsValidProjectId(projectId))
        {
            return ManagedProjectPathResolution.Unavailable("The active project ID is not valid.");
        }

        if (string.IsNullOrWhiteSpace(projectRelativePath))
        {
            return ManagedProjectPathResolution.Unavailable("The project-relative path is empty.");
        }

        try
        {
            if (Path.IsPathRooted(projectRelativePath))
            {
                return ManagedProjectPathResolution.Unavailable(
                    "Only project-relative paths can be opened.");
            }

            string projectRoot = Path.GetFullPath(Path.Combine(dataDirectory, "projects", projectId));
            string candidate = Path.GetFullPath(Path.Combine(projectRoot, projectRelativePath));
            string relativeToProject = Path.GetRelativePath(projectRoot, candidate);
            if (Path.IsPathRooted(relativeToProject) ||
                relativeToProject.Equals("..", StringComparison.Ordinal) ||
                relativeToProject.StartsWith($"..{Path.DirectorySeparatorChar}", StringComparison.Ordinal) ||
                relativeToProject.StartsWith($"..{Path.AltDirectorySeparatorChar}", StringComparison.Ordinal))
            {
                return ManagedProjectPathResolution.Unavailable(
                    "The path resolves outside the active project.");
            }

            return ManagedProjectPathResolution.Available(candidate);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return ManagedProjectPathResolution.Unavailable("The project path is malformed.");
        }
    }

    private static bool IsValidProjectId(string projectId)
    {
        if (string.IsNullOrWhiteSpace(projectId) ||
            projectId is "." or ".." ||
            Path.IsPathRooted(projectId) ||
            projectId.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            return false;
        }

        return !projectId.Contains(Path.DirectorySeparatorChar) &&
               !projectId.Contains(Path.AltDirectorySeparatorChar);
    }
}
