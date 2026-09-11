namespace EdmgStudio.Core.Models;

public sealed record StudioLaunchRequest(string? ProjectId, string Destination)
{
    public const string ProjectArgumentPrefix = "--project=";

    public static StudioLaunchRequest? Parse(string? arguments)
    {
        if (string.IsNullOrWhiteSpace(arguments))
        {
            return null;
        }

        foreach (string token in Tokenize(arguments))
        {
            if (!token.StartsWith(ProjectArgumentPrefix, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string encodedProjectId = token[ProjectArgumentPrefix.Length..];
            string projectId;
            try
            {
                projectId = Uri.UnescapeDataString(encodedProjectId);
            }
            catch (UriFormatException)
            {
                return null;
            }

            if (string.IsNullOrWhiteSpace(projectId) || projectId.Length > 256)
            {
                return null;
            }

            return new StudioLaunchRequest(projectId, "workspace");
        }

        return null;
    }

    public static string ForProject(string projectId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectId);
        return ProjectArgumentPrefix + Uri.EscapeDataString(projectId.Trim());
    }

    private static IEnumerable<string> Tokenize(string arguments) =>
        arguments.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(token => token.Trim('"'));
}
