namespace EdmgStudio.Core.Media;

public sealed record MediaToolPaths(string FfmpegPath, string FfprobePath);

public static class MediaToolLocator
{
    public const string FfmpegEnvironmentVariable = "EDMG_FFMPEG_PATH";
    public const string FfprobeEnvironmentVariable = "EDMG_FFPROBE_PATH";

    public static MediaToolPaths Locate(string? applicationBaseDirectory = null)
    {
        string baseDirectory = Path.GetFullPath(applicationBaseDirectory ?? AppContext.BaseDirectory);
        string? configuredFfmpeg = NormalizeConfiguredPath(Environment.GetEnvironmentVariable(FfmpegEnvironmentVariable));
        string? configuredFfprobe = NormalizeConfiguredPath(Environment.GetEnvironmentVariable(FfprobeEnvironmentVariable));

        configuredFfmpeg ??= FindCandidate(baseDirectory, "ffmpeg.exe");
        configuredFfprobe ??= FindCandidate(baseDirectory, "ffprobe.exe");

        configuredFfmpeg ??= FindSibling(configuredFfprobe, "ffmpeg.exe");
        configuredFfprobe ??= FindSibling(configuredFfmpeg, "ffprobe.exe");

        return new MediaToolPaths(
            configuredFfmpeg ?? "ffmpeg",
            configuredFfprobe ?? "ffprobe");
    }

    private static string? NormalizeConfiguredPath(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        string expanded = Environment.ExpandEnvironmentVariables(value.Trim().Trim('"'));
        if (!File.Exists(expanded))
        {
            throw new FileNotFoundException($"The configured media tool does not exist: {expanded}", expanded);
        }

        return Path.GetFullPath(expanded);
    }

    private static string? FindCandidate(string baseDirectory, string fileName)
    {
        foreach (string directory in EnumerateSearchDirectories(baseDirectory))
        {
            string candidate = Path.Combine(directory, fileName);
            if (File.Exists(candidate))
            {
                return Path.GetFullPath(candidate);
            }
        }

        return null;
    }

    private static string? FindSibling(string? toolPath, string siblingName)
    {
        if (string.IsNullOrWhiteSpace(toolPath) || !Path.IsPathFullyQualified(toolPath))
        {
            return null;
        }

        string? directory = Path.GetDirectoryName(toolPath);
        if (string.IsNullOrWhiteSpace(directory))
        {
            return null;
        }

        string candidate = Path.Combine(directory, siblingName);
        return File.Exists(candidate) ? Path.GetFullPath(candidate) : null;
    }

    private static IEnumerable<string> EnumerateSearchDirectories(string baseDirectory)
    {
        yield return Path.Combine(baseDirectory, "bin");
        yield return baseDirectory;

        DirectoryInfo? current = new(baseDirectory);
        for (int depth = 0; current is not null && depth < 8; depth++, current = current.Parent)
        {
            yield return Path.Combine(current.FullName, "studio", "edmg-studio", "electron-resources", "bin");
            yield return Path.Combine(current.FullName, "edmg-studio", "electron-resources", "bin");
            yield return Path.Combine(current.FullName, "electron-resources", "bin");
        }
    }
}
