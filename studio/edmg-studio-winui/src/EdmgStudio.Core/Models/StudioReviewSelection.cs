namespace EdmgStudio.Core.Models;

public static class StudioReviewSelection
{
    public const int MaximumComparisonArtifacts = 4;

    public static IReadOnlyList<string> AddRecent(
        IEnumerable<string>? currentPaths,
        string artifactPath,
        int maximumCount = MaximumComparisonArtifacts)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(artifactPath);
        ArgumentOutOfRangeException.ThrowIfLessThan(maximumCount, 1);

        var normalizedPath = artifactPath.Trim();
        var result = (currentPaths ?? [])
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Select(path => path.Trim())
            .Where(path => !string.Equals(path, normalizedPath, StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Append(normalizedPath)
            .TakeLast(maximumCount)
            .ToArray();

        return result;
    }

    public static IReadOnlyList<string> KeepAvailable(
        IEnumerable<string>? currentPaths,
        IEnumerable<string> availablePaths,
        int maximumCount = MaximumComparisonArtifacts)
    {
        ArgumentNullException.ThrowIfNull(availablePaths);
        ArgumentOutOfRangeException.ThrowIfLessThan(maximumCount, 1);

        var available = new HashSet<string>(
            availablePaths
                .Where(path => !string.IsNullOrWhiteSpace(path))
                .Select(path => path.Trim()),
            StringComparer.OrdinalIgnoreCase);

        return (currentPaths ?? [])
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Select(path => path.Trim())
            .Where(available.Contains)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .TakeLast(maximumCount)
            .ToArray();
    }
}
