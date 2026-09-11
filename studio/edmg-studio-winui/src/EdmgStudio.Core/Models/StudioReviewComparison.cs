namespace EdmgStudio.Core.Models;

public sealed record ReviewComparisonArtifact(
    string Path,
    string Name,
    string Kind,
    string Variant,
    string ReviewState,
    string Engine,
    string ModelId,
    string Seed,
    long? SizeBytes);

public sealed record ReviewMetadataDifference(
    string Label,
    IReadOnlyList<string> Values,
    bool IsDifferent);

public sealed record ReviewAnnotation(
    double Position,
    string Note)
{
    public ReviewAnnotation Normalize() => new(
        Math.Clamp(double.IsFinite(Position) ? Position : 0, 0, 1),
        Note.Trim());
}

public static class StudioReviewComparison
{
    public static string? KeepReference(string? referencePath, IEnumerable<string>? selectedPaths)
    {
        string[] selected = NormalizePaths(selectedPaths);
        string? normalizedReference = NormalizePath(referencePath);
        return selected.FirstOrDefault(path =>
                   string.Equals(path, normalizedReference, StringComparison.OrdinalIgnoreCase))
               ?? selected.FirstOrDefault();
    }

    public static string? MoveActive(
        IEnumerable<string>? selectedPaths,
        string? activePath,
        int offset)
    {
        string[] selected = NormalizePaths(selectedPaths);
        if (selected.Length == 0)
        {
            return null;
        }

        int current = Array.FindIndex(selected, path =>
            string.Equals(path, NormalizePath(activePath), StringComparison.OrdinalIgnoreCase));
        current = current < 0 ? 0 : current;
        int next = ((current + offset) % selected.Length + selected.Length) % selected.Length;
        return selected[next];
    }

    public static IReadOnlyList<ReviewMetadataDifference> CompareMetadata(
        IEnumerable<ReviewComparisonArtifact>? artifacts)
    {
        ReviewComparisonArtifact[] selected = (artifacts ?? []).Take(4).ToArray();
        if (selected.Length == 0)
        {
            return [];
        }

        return
        [
            CreateDifference("Variant", selected.Select(item => item.Variant)),
            CreateDifference("Type", selected.Select(item => item.Kind)),
            CreateDifference("Review", selected.Select(item => item.ReviewState)),
            CreateDifference("Engine", selected.Select(item => item.Engine)),
            CreateDifference("Model", selected.Select(item => item.ModelId)),
            CreateDifference("Seed", selected.Select(item => item.Seed)),
            CreateDifference("Size", selected.Select(item => FormatSize(item.SizeBytes)))
        ];
    }

    private static ReviewMetadataDifference CreateDifference(string label, IEnumerable<string> values)
    {
        string[] normalized = values.Select(value => string.IsNullOrWhiteSpace(value) ? "-" : value.Trim()).ToArray();
        return new ReviewMetadataDifference(
            label,
            normalized,
            normalized.Distinct(StringComparer.OrdinalIgnoreCase).Skip(1).Any());
    }

    private static string FormatSize(long? bytes) => bytes is null
        ? "-"
        : bytes.Value >= 1024 * 1024
            ? $"{bytes.Value / (1024d * 1024d):0.##} MB"
            : bytes.Value >= 1024
                ? $"{bytes.Value / 1024d:0.##} KB"
                : $"{bytes.Value} B";

    private static string[] NormalizePaths(IEnumerable<string>? paths) =>
        (paths ?? [])
            .Select(NormalizePath)
            .Where(path => path is not null)
            .Cast<string>()
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(StudioReviewSelection.MaximumComparisonArtifacts)
            .ToArray();

    private static string? NormalizePath(string? path) =>
        string.IsNullOrWhiteSpace(path) ? null : path.Trim();
}
