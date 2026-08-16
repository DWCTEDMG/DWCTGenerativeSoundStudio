using System.Text.Json;

namespace EdmgStudio.Core.Services;

public enum RequestedBackendMode
{
    Managed,
    External
}

public sealed record BackendConfiguration(
    RequestedBackendMode Mode,
    string Host,
    int Port,
    Uri BackendUri,
    string AcceleratorProfile,
    string? SourceDirectory,
    StudioPaths Paths,
    string Source)
{
    private static readonly IReadOnlyDictionary<string, string> AiSettingEnvironmentMap =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["mode"] = "EDMG_AI_MODE",
            ["provider"] = "EDMG_AI_PROVIDER",
            ["aiBaseUrl"] = "EDMG_AI_BASE_URL",
            ["ollamaUrl"] = "EDMG_AI_OLLAMA_URL",
            ["ollamaModel"] = "EDMG_AI_OLLAMA_MODEL",
            ["openaiCompatBaseUrl"] = "EDMG_AI_OPENAI_COMPAT_BASE_URL",
            ["openaiCompatModel"] = "EDMG_AI_OPENAI_COMPAT_MODEL",
            ["nvidiaBaseUrl"] = "EDMG_AI_NVIDIA_BASE_URL",
            ["nvidiaModel"] = "EDMG_AI_NVIDIA_MODEL"
        };

    public IReadOnlyDictionary<string, string> ManagedEnvironment { get; init; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    public IReadOnlyList<string> ValidationErrors { get; init; } = [];
    public string BackendModeSource { get; init; } = "defaults";
    public string BackendAddressSource { get; init; } = "defaults";
    public string? ConfiguredBackendUrl { get; init; }
    public bool HasPendingMigration { get; init; }
    public string? PendingMigrationDetail { get; init; }
    public TimeSpan SourceReadyTimeout { get; init; } = TimeSpan.FromSeconds(15);
    public TimeSpan PackagedReadyTimeout { get; init; } = TimeSpan.FromSeconds(120);

    public static BackendConfiguration Load()
    {
        var values = new MutableConfiguration();
        var sources = new List<string>();
        var studioRoot = FindSourceStudioRoot();

        if (TryReadRuntimeDefaults(studioRoot, values))
        {
            sources.Add("runtime-defaults");
        }

        if (TryReadLauncherEnvironment(studioRoot, values))
        {
            sources.Add("launcher_env");
        }

        var bootstrapPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "EDMG Studio",
            "bootstrap.json");
        if (TryReadBootstrap(bootstrapPath, values))
        {
            sources.Add("bootstrap");
        }

        if (ApplyEnvironment(values))
        {
            sources.Add("environment");
        }

        if (ApplyCommandLine(values))
        {
            sources.Add("command-line");
        }

        return CreateConfiguration(values, sources);
    }

    public static BackendConfiguration LoadFromBootstrap(string bootstrapPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(bootstrapPath);
        var values = new MutableConfiguration();
        var sources = new List<string>();
        if (TryReadBootstrap(Path.GetFullPath(bootstrapPath), values))
        {
            sources.Add("bootstrap");
        }

        return CreateConfiguration(values, sources);
    }

    private static BackendConfiguration CreateConfiguration(
        MutableConfiguration values,
        IReadOnlyCollection<string> sources)
    {
        var validationErrors = new List<string>();
        string acceleratorProfile;
        try
        {
            acceleratorProfile = NormalizeAcceleratorProfile(values.AcceleratorProfile);
        }
        catch (ArgumentException exception)
        {
            acceleratorProfile = values.AcceleratorProfile?.Trim() ?? string.Empty;
            validationErrors.Add(exception.Message);
        }

        var mode = NormalizeMode(values.Mode, values.SpawnBackend);
        var host = NormalizeHost(values.Host);
        var port = NormalizePort(values.Port);
        var localUri = ManagedBackendUri(host, port);
        var configuredBackendUrl = values.Url?.Trim();
        var normalizedExternalUri = NormalizeBackendUri(configuredBackendUrl);
        if (mode == RequestedBackendMode.External && normalizedExternalUri is null)
        {
            validationErrors.Add(
                string.IsNullOrWhiteSpace(configuredBackendUrl)
                    ? "External backend mode requires a backend URL starting with http:// or https://."
                    : $"The configured external backend URL '{configuredBackendUrl}' is invalid. Use an absolute http:// or https:// URL.");
        }

        var backendUri = mode == RequestedBackendMode.External
            ? normalizedExternalUri ?? localUri
            : localUri;
        var timeoutOverride = ParseReadyTimeout(values.ReadyTimeoutMilliseconds, validationErrors);
        var paths = StudioPaths.Create(values.StudioHome, values.StorageOverrides);
        return new BackendConfiguration(
            mode,
            host,
            port,
            backendUri,
            acceleratorProfile,
            NormalizeDirectory(values.SourceDirectory),
            paths,
            sources.Count == 0 ? "defaults" : string.Join(" → ", sources))
        {
            ManagedEnvironment = new Dictionary<string, string>(values.ManagedEnvironment, StringComparer.OrdinalIgnoreCase),
            ValidationErrors = validationErrors,
            BackendModeSource = values.ModeSource,
            BackendAddressSource = values.AddressSource,
            ConfiguredBackendUrl = mode == RequestedBackendMode.External ? configuredBackendUrl : null,
            HasPendingMigration = values.HasPendingMigration,
            PendingMigrationDetail = values.PendingMigrationDetail,
            SourceReadyTimeout = timeoutOverride ?? TimeSpan.FromSeconds(15),
            PackagedReadyTimeout = timeoutOverride ?? TimeSpan.FromSeconds(120)
        };
    }

    public static string NormalizeAcceleratorProfile(string? value)
    {
        var normalized = (value ?? string.Empty).Trim().ToLowerInvariant();
        normalized = normalized switch
        {
            "nvidia" => "cuda",
            "amd" => "directml",
            "" => "cpu",
            _ => normalized
        };

        if (normalized is not ("cpu" or "directml" or "cuda"))
        {
            throw new ArgumentException(
                $"Unsupported accelerator profile '{value}'. Choose cpu, directml, or cuda.",
                nameof(value));
        }

        return normalized;
    }

    public static Uri? NormalizeBackendUri(string? value)
    {
        if (!Uri.TryCreate((value ?? string.Empty).Trim(), UriKind.Absolute, out var parsed) ||
            (!string.Equals(parsed.Scheme, Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase) &&
             !string.Equals(parsed.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase)))
        {
            return null;
        }

        var builder = new UriBuilder(parsed)
        {
            Query = string.Empty,
            Fragment = string.Empty
        };

        var path = builder.Path.TrimEnd('/');
        if (path.EndsWith("/health", StringComparison.OrdinalIgnoreCase))
        {
            path = path[..^"/health".Length];
        }
        else if (path.EndsWith("/v1", StringComparison.OrdinalIgnoreCase))
        {
            path = path[..^"/v1".Length];
        }

        builder.Path = string.IsNullOrWhiteSpace(path) ? "/" : $"{path.TrimEnd('/')}/";
        return builder.Uri;
    }

    public static Uri ManagedBackendUri(string bindHost, int port)
    {
        var clientHost = bindHost.Trim() switch
        {
            "0.0.0.0" => "127.0.0.1",
            "::" => "::1",
            var host => host
        };
        return new UriBuilder(Uri.UriSchemeHttp, clientHost, port).Uri;
    }

    private static RequestedBackendMode NormalizeMode(string? value, bool? spawnBackend)
    {
        if (spawnBackend == false)
        {
            return RequestedBackendMode.External;
        }

        return (value ?? string.Empty).Trim().ToLowerInvariant() switch
        {
            "external" or "remote" or "connect" => RequestedBackendMode.External,
            _ => RequestedBackendMode.Managed
        };
    }

    private static string NormalizeHost(string? value)
    {
        var candidate = (value ?? string.Empty).Trim();
        return string.IsNullOrWhiteSpace(candidate) ? "127.0.0.1" : candidate;
    }

    private static int NormalizePort(string? value) =>
        int.TryParse(value, out var parsed) && parsed is >= 1 and <= 65535 ? parsed : 7863;

    private static TimeSpan? ParseReadyTimeout(string? value, ICollection<string> validationErrors)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        if (int.TryParse(value, out var milliseconds) && milliseconds is >= 1000 and <= 600_000)
        {
            return TimeSpan.FromMilliseconds(milliseconds);
        }

        validationErrors.Add("EDMG_STUDIO_BACKEND_READY_TIMEOUT_MS must be between 1000 and 600000 milliseconds.");
        return null;
    }

    private static string? NormalizeDirectory(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        try
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(value.Trim()));
        }
        catch
        {
            return null;
        }
    }

    private static bool TryReadRuntimeDefaults(string? studioRoot, MutableConfiguration values)
    {
        var candidates = new List<string>
        {
            Path.Combine(AppContext.BaseDirectory, "runtime-defaults.json"),
            Path.Combine(AppContext.BaseDirectory, "resources", "runtime-defaults.json"),
            Path.Combine(AppContext.BaseDirectory, "electron-resources", "runtime-defaults.json")
        };
        if (!string.IsNullOrWhiteSpace(studioRoot))
        {
            candidates.Add(Path.Combine(studioRoot, "electron-resources", "runtime-defaults.json"));
        }

        var path = candidates.FirstOrDefault(File.Exists);
        if (path is null)
        {
            return false;
        }

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;
            if (!root.TryGetProperty("backend", out var backend) || backend.ValueKind != JsonValueKind.Object)
            {
                return false;
            }

            values.Host = ReadString(backend, "host") ?? values.Host;
            values.Port = ReadStringOrNumber(backend, "port") ?? values.Port;
            values.Url = ReadString(backend, "url") ?? values.Url;
            values.AddressSource = "runtime-defaults";
            if (backend.TryGetProperty("spawnBackend", out var spawn) && spawn.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                values.SpawnBackend = spawn.GetBoolean();
                values.Mode = spawn.GetBoolean() ? "managed" : "external";
                values.ModeSource = "runtime-defaults";
            }

            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool TryReadLauncherEnvironment(string? studioRoot, MutableConfiguration values)
    {
        if (string.IsNullOrWhiteSpace(studioRoot))
        {
            return false;
        }

        var path = Path.Combine(studioRoot, "launcher_env.json");
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            ApplyFlatEnvironmentObject(document.RootElement, values, "launcher_env");
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool TryReadBootstrap(string path, MutableConfiguration values)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var root = document.RootElement;

            if (root.TryGetProperty("backendSettings", out var backend) && backend.ValueKind == JsonValueKind.Object)
            {
                values.Mode = ReadString(backend, "mode") ?? values.Mode;
                values.Host = ReadString(backend, "host") ?? values.Host;
                values.Port = ReadStringOrNumber(backend, "port") ?? values.Port;
                values.Url = ReadString(backend, "url") ?? values.Url;
                values.ModeSource = "bootstrap";
                values.AddressSource = "bootstrap";
            }

            values.StudioHome = ReadString(root, "studioHome") ?? values.StudioHome;
            if (root.TryGetProperty("storageSettings", out var storage) && storage.ValueKind == JsonValueKind.Object)
            {
                foreach (var key in StudioPaths.OverrideKeys)
                {
                    var configured = ReadString(storage, key);
                    if (!string.IsNullOrWhiteSpace(configured))
                    {
                        values.StorageOverrides[key] = configured;
                    }
                }
            }

            if (root.TryGetProperty("aiSettings", out var ai) && ai.ValueKind == JsonValueKind.Object)
            {
                foreach (var pair in AiSettingEnvironmentMap)
                {
                    var configured = ReadString(ai, pair.Key);
                    if (!string.IsNullOrWhiteSpace(configured))
                    {
                        values.ManagedEnvironment[pair.Value] = configured;
                    }
                }
            }

            if (root.TryGetProperty("pendingMigration", out var pending) && pending.ValueKind == JsonValueKind.Object)
            {
                values.HasPendingMigration = true;
                values.PendingMigrationDetail =
                    $"Storage migration requested at {ReadString(pending, "requestedAt") ?? "an unknown time"}. " +
                    "Complete it with the existing Studio client before starting a managed backend.";
            }

            return true;
        }
        catch
        {
            return false;
        }
    }

    private static void ApplyFlatEnvironmentObject(JsonElement root, MutableConfiguration values, string source)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        foreach (var property in root.EnumerateObject())
        {
            if (!property.Name.All(character => char.IsUpper(character) || char.IsDigit(character) || character == '_'))
            {
                continue;
            }

            var text = property.Value.ValueKind switch
            {
                JsonValueKind.String => property.Value.GetString(),
                JsonValueKind.Number => property.Value.GetRawText(),
                JsonValueKind.True => "1",
                JsonValueKind.False => "0",
                _ => null
            };
            if (string.IsNullOrWhiteSpace(text))
            {
                continue;
            }

            values.ManagedEnvironment[property.Name] = text;
            ApplyKnownEnvironmentValue(property.Name, text, values, source);
        }
    }

    private static bool ApplyEnvironment(MutableConfiguration values)
    {
        var changed = false;
        foreach (var name in KnownEnvironmentNames)
        {
            var value = Environment.GetEnvironmentVariable(name);
            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            changed = true;
            values.ManagedEnvironment[name] = value;
            ApplyKnownEnvironmentValue(name, value, values, "environment");
        }

        return changed;
    }

    private static bool ApplyCommandLine(MutableConfiguration values)
    {
        var arguments = Environment.GetCommandLineArgs().Skip(1).ToArray();
        var changed = false;
        for (var index = 0; index < arguments.Length; index++)
        {
            var argument = arguments[index];
            if (!argument.StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }

            var separator = argument.IndexOf('=');
            var name = separator >= 0 ? argument[..separator] : argument;
            string? value = separator >= 0 ? argument[(separator + 1)..] : null;
            if (value is null && index + 1 < arguments.Length && !arguments[index + 1].StartsWith("--", StringComparison.Ordinal))
            {
                value = arguments[++index];
            }

            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            switch (name)
            {
                case "--backend-mode": values.Mode = value; values.ModeSource = "command-line"; changed = true; break;
                case "--backend-host": values.Host = value; values.AddressSource = "command-line"; changed = true; break;
                case "--backend-port": values.Port = value; values.AddressSource = "command-line"; changed = true; break;
                case "--backend-url": values.Url = value; values.AddressSource = "command-line"; changed = true; break;
                case "--spawn-backend": values.SpawnBackend = value.Trim() is not ("0" or "false" or "False"); values.ModeSource = "command-line"; changed = true; break;
                case "--accelerator-profile": values.AcceleratorProfile = value; changed = true; break;
                case "--backend-source": values.SourceDirectory = value; changed = true; break;
                case "--backend-ready-timeout-ms": values.ReadyTimeoutMilliseconds = value; changed = true; break;
            }
        }

        return changed;
    }

    private static void ApplyKnownEnvironmentValue(
        string name,
        string value,
        MutableConfiguration values,
        string source)
    {
        switch (name)
        {
            case "EDMG_STUDIO_BACKEND_MODE": values.Mode = value; values.ModeSource = source; break;
            case "EDMG_STUDIO_BACKEND_HOST": values.Host = value; values.AddressSource = source; break;
            case "EDMG_STUDIO_BACKEND_PORT": values.Port = value; values.AddressSource = source; break;
            case "EDMG_STUDIO_BACKEND_URL": values.Url = value; values.AddressSource = source; break;
            case "EDMG_STUDIO_SPAWN_BACKEND": values.SpawnBackend = value.Trim() is not ("0" or "false" or "False"); values.ModeSource = source; break;
            case "EDMG_BACKEND_ACCELERATOR_PROFILE": values.AcceleratorProfile = value; break;
            case "EDMG_STUDIO_BACKEND_SOURCE_DIR": values.SourceDirectory = value; break;
            case "EDMG_STUDIO_HOME": values.StudioHome = value; break;
            case "EDMG_STUDIO_BACKEND_READY_TIMEOUT_MS": values.ReadyTimeoutMilliseconds = value; break;
            case "EDMG_STUDIO_DATA_DIR": values.StorageOverrides["dataDir"] = value; break;
            case "EDMG_STUDIO_MODELS_DIR": values.StorageOverrides["modelsDir"] = value; break;
            case "EDMG_STUDIO_CACHE_DIR": values.StorageOverrides["cacheRoot"] = value; break;
            case "EDMG_STUDIO_LOGS_DIR": values.StorageOverrides["logsDir"] = value; break;
            case "EDMG_STUDIO_EXTERNAL_DIR": values.StorageOverrides["externalDir"] = value; break;
        }
    }

    private static readonly string[] KnownEnvironmentNames =
    [
        "EDMG_STUDIO_BACKEND_MODE", "EDMG_STUDIO_BACKEND_HOST", "EDMG_STUDIO_BACKEND_PORT",
        "EDMG_STUDIO_BACKEND_URL", "EDMG_STUDIO_SPAWN_BACKEND", "EDMG_BACKEND_ACCELERATOR_PROFILE",
        "EDMG_STUDIO_BACKEND_SOURCE_DIR", "EDMG_STUDIO_BACKEND_READY_TIMEOUT_MS",
        "EDMG_STUDIO_HOME", "EDMG_STUDIO_DATA_DIR", "EDMG_STUDIO_MODELS_DIR", "EDMG_STUDIO_CACHE_DIR",
        "EDMG_STUDIO_LOGS_DIR", "EDMG_STUDIO_EXTERNAL_DIR", "EDMG_BACKEND_AUTH_TOKEN",
        "EDMG_AI_MODE", "EDMG_AI_PROVIDER", "EDMG_AI_BASE_URL", "EDMG_AI_OLLAMA_URL",
        "EDMG_AI_OLLAMA_MODEL", "EDMG_AI_OPENAI_COMPAT_BASE_URL", "EDMG_AI_OPENAI_COMPAT_MODEL",
        "EDMG_AI_NVIDIA_BASE_URL", "EDMG_AI_NVIDIA_MODEL"
    ];

    private static string? FindSourceStudioRoot()
    {
        foreach (var start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
        {
            var current = new DirectoryInfo(Path.GetFullPath(start));
            for (var depth = 0; current is not null && depth < 12; depth++, current = current.Parent)
            {
                if (Directory.Exists(Path.Combine(current.FullName, "python_backend")) &&
                    File.Exists(Path.Combine(current.FullName, "package.json")))
                {
                    return current.FullName;
                }

                var candidate = Path.Combine(current.FullName, "studio", "edmg-studio");
                if (Directory.Exists(Path.Combine(candidate, "python_backend")) &&
                    File.Exists(Path.Combine(candidate, "package.json")))
                {
                    return candidate;
                }
            }
        }

        return null;
    }

    private static string? ReadString(JsonElement parent, string propertyName) =>
        parent.TryGetProperty(propertyName, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static string? ReadStringOrNumber(JsonElement parent, string propertyName)
    {
        if (!parent.TryGetProperty(propertyName, out var value))
        {
            return null;
        }

        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString(),
            JsonValueKind.Number => value.GetRawText(),
            _ => null
        };
    }

    private sealed class MutableConfiguration
    {
        public string Mode { get; set; } = "managed";
        public string Host { get; set; } = "127.0.0.1";
        public string Port { get; set; } = "7863";
        public string Url { get; set; } = string.Empty;
        public string ModeSource { get; set; } = "defaults";
        public string AddressSource { get; set; } = "defaults";
        public bool? SpawnBackend { get; set; }
        public string? AcceleratorProfile { get; set; } = "cpu";
        public string? SourceDirectory { get; set; }
        public string? StudioHome { get; set; }
        public string? ReadyTimeoutMilliseconds { get; set; }
        public bool HasPendingMigration { get; set; }
        public string? PendingMigrationDetail { get; set; }
        public Dictionary<string, string> StorageOverrides { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, string> ManagedEnvironment { get; } = new(StringComparer.OrdinalIgnoreCase);
    }
}

public sealed record StudioPaths(
    string StudioHome,
    string DataDirectory,
    string ModelsDirectory,
    string CacheDirectory,
    string LogsDirectory,
    string ExternalDirectory)
{
    internal static readonly string[] OverrideKeys = ["dataDir", "modelsDir", "cacheRoot", "logsDir", "externalDir"];

    public IReadOnlyList<string> PreparationWarnings { get; init; } = [];

    public static StudioPaths Create(string? studioHome, IReadOnlyDictionary<string, string>? overrides = null)
    {
        var dataOverride = ResolveOverride(overrides, "dataDir");
        var home = ResolvePath(studioHome) ??
                   (dataOverride is null ? null : Directory.GetParent(dataOverride)?.FullName) ??
                   Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "EDMG Studio");

        var paths = new StudioPaths(
            home,
            dataOverride ?? Path.Combine(home, "data"),
            ResolveOverride(overrides, "modelsDir") ?? Path.Combine(home, "models"),
            ResolveOverride(overrides, "cacheRoot") ?? Path.Combine(home, "cache"),
            ResolveOverride(overrides, "logsDir") ?? Path.Combine(home, "logs"),
            ResolveOverride(overrides, "externalDir") ?? Path.Combine(home, "external"));

        return paths.PrepareDirectories();
    }

    public IReadOnlyDictionary<string, string> BuildManagedEnvironment()
    {
        var cache = CacheDirectory;
        return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["EDMG_STUDIO_HOME"] = StudioHome,
            ["EDMG_STUDIO_DATA_DIR"] = DataDirectory,
            ["EDMG_STUDIO_MODELS_DIR"] = ModelsDirectory,
            ["EDMG_STUDIO_CACHE_DIR"] = CacheDirectory,
            ["EDMG_STUDIO_LOGS_DIR"] = LogsDirectory,
            ["EDMG_STUDIO_EXTERNAL_DIR"] = ExternalDirectory,
            ["OLLAMA_MODELS"] = Path.Combine(ModelsDirectory, "ollama"),
            ["PIP_CACHE_DIR"] = Path.Combine(cache, "pip"),
            ["XDG_CACHE_HOME"] = Path.Combine(cache, "xdg"),
            ["HF_HOME"] = Path.Combine(cache, "huggingface"),
            ["HF_HUB_CACHE"] = Path.Combine(cache, "huggingface", "hub"),
            ["HF_XET_CACHE"] = Path.Combine(cache, "huggingface", "xet"),
            ["HF_ASSETS_CACHE"] = Path.Combine(cache, "huggingface", "assets"),
            ["HUGGINGFACE_HUB_CACHE"] = Path.Combine(cache, "huggingface", "hub"),
            ["HUGGINGFACE_ASSETS_CACHE"] = Path.Combine(cache, "huggingface", "assets"),
            ["TRANSFORMERS_CACHE"] = Path.Combine(cache, "transformers"),
            ["TORCH_HOME"] = Path.Combine(cache, "torch"),
            ["NLTK_DATA"] = Path.Combine(cache, "nltk_data"),
            ["WHISPER_CACHE_DIR"] = Path.Combine(cache, "whisper"),
            ["MPLCONFIGDIR"] = Path.Combine(cache, "matplotlib"),
            ["TMP"] = Path.Combine(cache, "tmp"),
            ["TEMP"] = Path.Combine(cache, "tmp"),
            ["MPLBACKEND"] = "Agg"
        };
    }

    private StudioPaths PrepareDirectories()
    {
        var warnings = new List<string>();
        foreach (var path in new[] { StudioHome, DataDirectory, ModelsDirectory, LogsDirectory, ExternalDirectory })
        {
            TryCreate(path, warnings);
        }

        var active = this;
        try
        {
            Directory.CreateDirectory(CacheDirectory);
        }
        catch (Exception exception)
        {
            var fallback = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "EDMG Studio",
                "cache-fallback");
            try
            {
                Directory.CreateDirectory(fallback);
                warnings.Add($"Cache path '{CacheDirectory}' is unavailable ({exception.Message}). Using '{fallback}' for cache only.");
                active = this with { CacheDirectory = fallback };
            }
            catch (Exception fallbackException)
            {
                warnings.Add($"Neither cache path '{CacheDirectory}' nor the local fallback could be prepared: {fallbackException.Message}");
            }
        }

        foreach (var path in active.BuildManagedEnvironment().Values
                     .Where(Path.IsPathRooted)
                     .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            TryCreate(path, warnings);
        }

        return active with { PreparationWarnings = warnings };
    }

    private static void TryCreate(string path, ICollection<string> warnings)
    {
        try
        {
            Directory.CreateDirectory(path);
        }
        catch (Exception exception)
        {
            warnings.Add($"Storage path '{path}' could not be prepared: {exception.Message}");
        }
    }

    private static string? ResolveOverride(IReadOnlyDictionary<string, string>? overrides, string key) =>
        overrides is not null && overrides.TryGetValue(key, out var value) ? ResolvePath(value) : null;

    private static string? ResolvePath(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        try
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(value.Trim()));
        }
        catch
        {
            return null;
        }
    }
}
