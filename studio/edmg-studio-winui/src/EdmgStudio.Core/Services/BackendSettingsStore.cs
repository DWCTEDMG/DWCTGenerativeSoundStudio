using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Services;

public sealed record FoundryProjectSettings(
    string ProjectName,
    string SubscriptionName,
    Uri ProjectEndpoint)
{
    public static FoundryProjectSettings Default { get; } = new(
        "jonlong-1185",
        "Azuredwct",
        new Uri("https://jonlong-1185-resource.services.ai.azure.com/api/projects/jonlong-1185"));
}

public static class BackendSettingsStore
{
    public static string GetDefaultBootstrapPath() =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "EDMG Studio",
            "bootstrap.json");

    public static void ResetToManaged(string? bootstrapPath = null, string host = "127.0.0.1", int port = 7863)
    {
        if (string.IsNullOrWhiteSpace(host))
        {
            throw new ArgumentException("Managed backend host is required.", nameof(host));
        }

        if (port is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(port), "Managed backend port must be between 1 and 65535.");
        }

        var path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
        var root = ReadRoot(path);

        root["backendSettings"] = new JsonObject
        {
            ["mode"] = "managed",
            ["host"] = host.Trim(),
            ["port"] = port.ToString(),
            ["url"] = string.Empty
        };
        root["updatedAt"] = DateTimeOffset.UtcNow.ToString("O");

        WriteAtomically(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);
    }

    public static FoundryProjectSettings LoadFoundrySettings(string? bootstrapPath = null)
    {
        var path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
        var root = ReadRoot(path);
        if (root["aiSettings"] is not JsonObject aiSettings)
        {
            return FoundryProjectSettings.Default;
        }

        var defaults = FoundryProjectSettings.Default;
        var projectName = ReadOptionalString(aiSettings, "foundryProjectName") ?? defaults.ProjectName;
        var subscriptionName = ReadOptionalString(aiSettings, "foundrySubscription") ?? defaults.SubscriptionName;
        var endpointText = ReadOptionalString(aiSettings, "foundryProjectEndpoint");
        if (endpointText is null)
        {
            return new FoundryProjectSettings(projectName, subscriptionName, defaults.ProjectEndpoint);
        }

        return new FoundryProjectSettings(
            projectName,
            subscriptionName,
            ValidateEndpoint(endpointText, nameof(FoundryProjectSettings.ProjectEndpoint)));
    }

    public static void SaveFoundrySettings(
        FoundryProjectSettings settings,
        string? bootstrapPath = null)
    {
        ArgumentNullException.ThrowIfNull(settings);
        var projectName = RequireValue(settings.ProjectName, "Foundry project name");
        var subscriptionName = RequireValue(settings.SubscriptionName, "Foundry subscription name");
        var endpoint = ValidateEndpoint(settings.ProjectEndpoint?.OriginalString, nameof(settings.ProjectEndpoint));
        var path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
        var root = ReadRoot(path);
        var aiSettings = root["aiSettings"] as JsonObject ?? new JsonObject();
        aiSettings["foundryProjectName"] = projectName;
        aiSettings["foundrySubscription"] = subscriptionName;
        aiSettings["foundryProjectEndpoint"] = endpoint.AbsoluteUri.TrimEnd('/');
        root["aiSettings"] = aiSettings;
        root["updatedAt"] = DateTimeOffset.UtcNow.ToString("O");

        WriteAtomically(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);
    }

    private static JsonObject ReadRoot(string path)
    {
        if (!File.Exists(path))
        {
            return new JsonObject();
        }

        try
        {
            return JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                ?? throw new InvalidDataException("The Studio bootstrap file must contain a JSON object.");
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException(
                "The Studio bootstrap file is malformed. It was not changed so the existing configuration can be recovered safely.",
                exception);
        }
    }

    private static string? ReadOptionalString(JsonObject source, string propertyName)
    {
        if (source[propertyName] is not JsonValue value ||
            !value.TryGetValue<string>(out var text) ||
            string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        return text.Trim();
    }

    private static string RequireValue(string? value, string displayName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{displayName} is required.");
        }

        return value.Trim();
    }

    private static Uri ValidateEndpoint(string? value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value) ||
            !Uri.TryCreate(value.Trim(), UriKind.Absolute, out var endpoint) ||
            endpoint.Scheme is not ("http" or "https") ||
            string.IsNullOrWhiteSpace(endpoint.Host) ||
            !string.IsNullOrEmpty(endpoint.UserInfo))
        {
            throw new ArgumentException(
                "Foundry project endpoint must be an absolute http:// or https:// URL without embedded credentials.",
                parameterName);
        }

        return endpoint;
    }

    private static void WriteAtomically(string path, string content)
    {
        var directory = Path.GetDirectoryName(path)
            ?? throw new InvalidOperationException("The bootstrap path has no parent directory.");
        Directory.CreateDirectory(directory);
        var temporaryPath = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var stream = new FileStream(
                       temporaryPath,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None,
                       4096,
                       FileOptions.WriteThrough))
            using (var writer = new StreamWriter(stream, new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false)))
            {
                writer.Write(content);
                writer.Flush();
                stream.Flush(flushToDisk: true);
            }

            File.Move(temporaryPath, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }
}
