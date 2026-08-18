namespace EdmgStudio.Core.Models;

public static class StudioNavigationDestination
{
    public const string Default = "dashboard";

    private static readonly string[] KnownDestinations =
    [
        Default,
        "projects",
        "workspace",
        "timeline",
        "render",
        "queue",
        "review",
        "outputs",
        "models",
        "cloud",
        "directorLab",
        "plannerLab",
        "reactiveLab",
        "studioForge",
        "migration",
        "settings",
        "setup",
    ];

    public static bool IsKnown(string? destination) =>
        KnownDestinations.Any(known =>
            string.Equals(known, destination?.Trim(), StringComparison.OrdinalIgnoreCase));

    public static bool IsRestorable(string? destination) =>
        IsKnown(destination) &&
        !string.Equals(destination?.Trim(), "setup", StringComparison.OrdinalIgnoreCase);

    public static string NormalizeOrDefault(string? destination)
    {
        string? normalized = KnownDestinations.FirstOrDefault(known =>
            string.Equals(known, destination?.Trim(), StringComparison.OrdinalIgnoreCase));
        return normalized ?? Default;
    }

    public static string NormalizeRestorableOrDefault(string? destination) =>
        IsRestorable(destination) ? NormalizeOrDefault(destination) : Default;
}
