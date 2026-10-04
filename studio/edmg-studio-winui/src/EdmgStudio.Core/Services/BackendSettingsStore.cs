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

public sealed record DesktopBackendSettings(
    RequestedBackendMode Mode,
    Uri? ExternalBackendUri,
    string Host,
    int Port);

public static class BackendSettingsStore
{
  public static string GetDefaultBootstrapPath()
  {
    return Path.Combine(
          Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
          "EDMG Studio",
          "bootstrap.json");
  }

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

    string path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
    JsonObject root = ReadRoot(path);

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

  public static void SaveExternalBackend(Uri backendUri, string? bootstrapPath = null)
  {
    ArgumentNullException.ThrowIfNull(backendUri);
    Uri normalized = BackendConfiguration.NormalizeBackendUri(backendUri.AbsoluteUri)
        ?? throw new ArgumentException(
            "Remote backend URL must be an absolute http:// or https:// URL.",
            nameof(backendUri));

    if (!string.IsNullOrWhiteSpace(normalized.UserInfo))
    {
      throw new ArgumentException("Remote backend URL must not include embedded credentials.", nameof(backendUri));
    }

    string path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
    JsonObject root = ReadRoot(path);
    root["backendSettings"] = new JsonObject
    {
      ["mode"] = "external",
      ["host"] = "127.0.0.1",
      ["port"] = "7863",
      ["url"] = normalized.AbsoluteUri.TrimEnd('/')
    };
    root["updatedAt"] = DateTimeOffset.UtcNow.ToString("O");

    WriteAtomically(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);
  }

  public static DesktopBackendSettings LoadDesktopBackendSettings(string? bootstrapPath = null)
  {
    string path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
    JsonObject root = ReadRoot(path);
    if (root["backendSettings"] is not JsonObject backend)
    {
      return new DesktopBackendSettings(RequestedBackendMode.Managed, null, "127.0.0.1", 7863);
    }

    RequestedBackendMode mode = string.Equals(ReadOptionalString(backend, "mode"), "external", StringComparison.OrdinalIgnoreCase)
        ? RequestedBackendMode.External
        : RequestedBackendMode.Managed;
    Uri? externalUri = BackendConfiguration.NormalizeBackendUri(ReadOptionalString(backend, "url"));
    string host = ReadOptionalString(backend, "host") ?? "127.0.0.1";
    string? portText = ReadOptionalString(backend, "port");
    int port = int.TryParse(portText, out int parsed) && parsed is >= 1 and <= 65535 ? parsed : 7863;
    return new DesktopBackendSettings(mode, externalUri, host, port);
  }

  public static FoundryProjectSettings LoadFoundrySettings(string? bootstrapPath = null)
  {
    string path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
    JsonObject root = ReadRoot(path);
    if (root["aiSettings"] is not JsonObject aiSettings)
    {
      return FoundryProjectSettings.Default;
    }

    FoundryProjectSettings defaults = FoundryProjectSettings.Default;
    string projectName = ReadOptionalString(aiSettings, "foundryProjectName") ?? defaults.ProjectName;
    string subscriptionName = ReadOptionalString(aiSettings, "foundrySubscription") ?? defaults.SubscriptionName;
    string? endpointText = ReadOptionalString(aiSettings, "foundryProjectEndpoint");
    return endpointText is null
          ? new FoundryProjectSettings(projectName, subscriptionName, defaults.ProjectEndpoint)
          : new FoundryProjectSettings(
            projectName,
            subscriptionName,
            ValidateEndpoint(endpointText, nameof(FoundryProjectSettings.ProjectEndpoint)));
  }

  public static void SaveFoundrySettings(
        FoundryProjectSettings settings,
        string? bootstrapPath = null)
  {
    ArgumentNullException.ThrowIfNull(settings);
    string projectName = RequireValue(settings.ProjectName, "Foundry project name");
    string subscriptionName = RequireValue(settings.SubscriptionName, "Foundry subscription name");
    Uri endpoint = ValidateEndpoint(settings.ProjectEndpoint?.OriginalString, nameof(settings.ProjectEndpoint));
    string path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
    JsonObject root = ReadRoot(path);
    JsonObject aiSettings = root["aiSettings"] as JsonObject ?? [];
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
      return [];
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
    return source[propertyName] is not JsonValue value ||
            !value.TryGetValue<string>(out string? text) ||
            string.IsNullOrWhiteSpace(text)
          ? null
          : text.Trim();
  }

  private static string RequireValue(string? value, string displayName)
  {
    return string.IsNullOrWhiteSpace(value) ? throw new ArgumentException($"{displayName} is required.") : value.Trim();
  }

  private static Uri ValidateEndpoint(string? value, string parameterName)
  {
    return string.IsNullOrWhiteSpace(value) ||
            !Uri.TryCreate(value.Trim(), UriKind.Absolute, out Uri? endpoint) ||
            endpoint.Scheme is not ("http" or "https") ||
            string.IsNullOrWhiteSpace(endpoint.Host) ||
            !string.IsNullOrEmpty(endpoint.UserInfo)
          ? throw new ArgumentException(
                "Foundry project endpoint must be an absolute http:// or https:// URL without embedded credentials.",
                parameterName)
          : endpoint;
  }

  private static void WriteAtomically(string path, string content)
  {
    string directory = Path.GetDirectoryName(path)
            ?? throw new InvalidOperationException("The bootstrap path has no parent directory.");
    _ = Directory.CreateDirectory(directory);
    string temporaryPath = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
    try
    {
      using (FileStream stream = new(
                 temporaryPath,
                 FileMode.CreateNew,
                 FileAccess.Write,
                 FileShare.None,
                 4096,
                 FileOptions.WriteThrough))
      using (StreamWriter writer = new(stream, new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false)))
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
