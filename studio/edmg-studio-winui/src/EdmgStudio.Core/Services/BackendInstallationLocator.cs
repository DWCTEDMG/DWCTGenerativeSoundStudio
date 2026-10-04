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
    string path = string.IsNullOrWhiteSpace(locatorPath) ? DefaultPath : locatorPath;
    if (!File.Exists(path))
    {
      return null;
    }

    try
    {
      using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
      JsonElement root = document.RootElement;
      if (!root.TryGetProperty("schemaVersion", out JsonElement schemaVersion) ||
          schemaVersion.ValueKind != JsonValueKind.Number ||
          schemaVersion.GetInt32() != 1 ||
          !root.TryGetProperty("installRoot", out JsonElement installRootValue) ||
          installRootValue.ValueKind != JsonValueKind.String)
      {
        return null;
      }

      string? installRoot = installRootValue.GetString()?.Trim();
      if (string.IsNullOrWhiteSpace(installRoot) ||
          !Path.IsPathFullyQualified(installRoot))
      {
        return null;
      }

      string normalizedRoot = Path.GetFullPath(installRoot);
      if (!Directory.Exists(normalizedRoot))
      {
        return null;
      }

      string backendDirectory = Path.Combine(normalizedRoot, "resources", "backend");
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
