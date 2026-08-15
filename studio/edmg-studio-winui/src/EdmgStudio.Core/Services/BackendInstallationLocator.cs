using System.Text.Json;

namespace EdmgStudio.Core.Services;

public static class BackendInstallationLocator
{
    public static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "EDMG Studio",
        "installation.json");

    public static string? TryResolveBackendDirectory(string? locatorPath = null)
    {
        var path = string.IsNullOrWhiteSpace(locatorPath) ? DefaultPath : locatorPath;
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (!root.TryGetProperty("schemaVersion", out var schemaVersion) ||
                schemaVersion.ValueKind != JsonValueKind.Number ||
                schemaVersion.GetInt32() != 1 ||
                !root.TryGetProperty("installRoot", out var installRootValue) ||
                installRootValue.ValueKind != JsonValueKind.String)
            {
                return null;
            }

            var installRoot = installRootValue.GetString()?.Trim();
            if (string.IsNullOrWhiteSpace(installRoot) ||
                !Path.IsPathFullyQualified(installRoot))
            {
                return null;
            }

            var normalizedRoot = Path.GetFullPath(installRoot);
            if (!Directory.Exists(normalizedRoot))
            {
                return null;
            }

            var backendDirectory = Path.Combine(normalizedRoot, "resources", "backend");
            return Directory.Exists(backendDirectory) ? backendDirectory : null;
        }
        catch (Exception exception) when (
            exception is IOException or
            UnauthorizedAccessException or
            JsonException or
            ArgumentException or
            NotSupportedException)
        {
            return null;
        }
    }
}
