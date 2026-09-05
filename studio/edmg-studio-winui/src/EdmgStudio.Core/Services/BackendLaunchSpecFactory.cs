using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Services;

public sealed class BackendLaunchSpecFactory
{
    private static readonly string[] CapabilityExtras = ["core", "audio", "asr", "internal-video", "aws"];
    private const string RequiredUvVersion = "0.11.28";

    private readonly BackendConfiguration _configuration;
    private readonly string? _installationLocatorPath;

    public BackendLaunchSpecFactory(
        BackendConfiguration configuration,
        string? installationLocatorPath = null)
    {
        _configuration = configuration;
        _installationLocatorPath = installationLocatorPath;
    }

    public string? FindPackagedBackendDirectory()
    {
        var candidates = new List<string>
        {
            Path.Combine(AppContext.BaseDirectory, "backend"),
            Path.Combine(AppContext.BaseDirectory, "resources", "backend"),
            Path.Combine(AppContext.BaseDirectory, "electron-resources", "backend")
        };

        var installedBackend = BackendInstallationLocator.TryResolveBackendDirectory(_installationLocatorPath);
        if (!string.IsNullOrWhiteSpace(installedBackend))
        {
            candidates.Add(installedBackend);
        }

        return candidates.FirstOrDefault(IsValidPackagedBackendDirectory);
    }

    public string? FindSourceBackendDirectory()
    {
        if (!string.IsNullOrWhiteSpace(_configuration.SourceDirectory) &&
            File.Exists(Path.Combine(_configuration.SourceDirectory, "pyproject.toml")))
        {
            return _configuration.SourceDirectory;
        }

        foreach (var start in new[] { Environment.CurrentDirectory, AppContext.BaseDirectory })
        {
            var current = new DirectoryInfo(Path.GetFullPath(start));
            for (var depth = 0; current is not null && depth < 12; depth++, current = current.Parent)
            {
                var repositoryCandidate = Path.Combine(current.FullName, "studio", "edmg-studio", "python_backend");
                if (File.Exists(Path.Combine(repositoryCandidate, "pyproject.toml")))
                {
                    return repositoryCandidate;
                }

                var siblingCandidate = Path.Combine(current.FullName, "python_backend");
                if (File.Exists(Path.Combine(siblingCandidate, "pyproject.toml")))
                {
                    return siblingCandidate;
                }
            }
        }

        return null;
    }

    public BackendLaunchSpec CreateSourceSpec(string sourceDirectory, string host, int port)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(sourceDirectory);
        var profile = BackendConfiguration.NormalizeAcceleratorProfile(_configuration.AcceleratorProfile);
        var uv = ResolveUvExecutable();

        var arguments = new List<string>
        {
            "run",
            "--frozen",
            "--no-default-groups",
            "--python",
            "3.12",
            "--extra",
            profile
        };

        foreach (var extra in CapabilityExtras)
        {
            arguments.Add("--extra");
            arguments.Add(extra);
        }

        arguments.AddRange(["python", "-m", "edmg_studio_backend", "serve", "--host", host, "--port", port.ToString()]);

        return CreateSpec(
            BackendMode.ManagedSource,
            uv,
            arguments,
            sourceDirectory,
            host,
            port,
            profile,
            includeSourceSettings: true);
    }

    public BackendLaunchSpec CreatePackagedSpec(string backendDirectory, string host, int port)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(backendDirectory);
        var executable = Path.Combine(backendDirectory, "edmg-studio-backend.exe");
        if (!File.Exists(executable))
        {
            throw new FileNotFoundException("The packaged EDMG backend executable is missing.", executable);
        }

        var profile = ReadPackagedProfile(backendDirectory) ?? "packaged";
        return CreateSpec(
            BackendMode.ManagedPackaged,
            executable,
            ["serve", "--host", host, "--port", port.ToString()],
            backendDirectory,
            host,
            port,
            profile,
            includeSourceSettings: false);
    }

    private static string ResolveUvExecutable()
    {
        var explicitUv = Environment.GetEnvironmentVariable("EDMG_UV_BIN")?.Trim();
        if (!string.IsNullOrWhiteSpace(explicitUv))
        {
            return explicitUv;
        }

        if (OperatingSystem.IsWindows())
        {
            var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrWhiteSpace(localAppData))
            {
                var managedUv = Path.Combine(
                    localAppData,
                    "EDMG Studio",
                    "toolchain",
                    "uv",
                    RequiredUvVersion,
                    "uv.exe");
                if (File.Exists(managedUv))
                {
                    return managedUv;
                }
            }
        }

        return "uv";
    }

    private BackendLaunchSpec CreateSpec(
        BackendMode mode,
        string fileName,
        IReadOnlyList<string> arguments,
        string workingDirectory,
        string host,
        int port,
        string profile,
        bool includeSourceSettings)
    {
        var environment = new Dictionary<string, string>(_configuration.Paths.BuildManagedEnvironment(), StringComparer.OrdinalIgnoreCase)
        {
            ["EDMG_STUDIO_BACKEND_HOST"] = host,
            ["EDMG_STUDIO_BACKEND_PORT"] = port.ToString()
        };

        foreach (var pair in _configuration.ManagedEnvironment)
        {
            environment[pair.Key] = pair.Value;
        }

        var ffmpeg = ResolveFfmpegPath(workingDirectory, mode);
        if (!string.IsNullOrWhiteSpace(ffmpeg))
        {
            environment["EDMG_FFMPEG_PATH"] = ffmpeg;
        }

        if (includeSourceSettings)
        {
            environment["EDMG_BACKEND_ACCELERATOR_PROFILE"] = profile;
            environment["NVIDIA_TENSORRT_DISABLE_INTERNAL_PIP"] = "1";
        }

        var backendLogDirectory = Path.Combine(_configuration.Paths.LogsDirectory, "backend");
        Directory.CreateDirectory(backendLogDirectory);

        return new BackendLaunchSpec(
            mode,
            fileName,
            arguments,
            workingDirectory,
            environment,
            Path.Combine(backendLogDirectory, "backend-stdout.log"),
            Path.Combine(backendLogDirectory, "backend-stderr.log"),
            profile);
    }

    private string? ResolveFfmpegPath(string workingDirectory, BackendMode mode)
    {
        var explicitPath = Environment.GetEnvironmentVariable("EDMG_FFMPEG_PATH")?.Trim();
        if (!string.IsNullOrWhiteSpace(explicitPath) &&
            (!Path.IsPathRooted(explicitPath) || File.Exists(explicitPath)))
        {
            return explicitPath;
        }

        var candidates = new List<string>();
        if (mode == BackendMode.ManagedPackaged)
        {
            var resourceRoot = Directory.GetParent(workingDirectory)?.FullName ?? AppContext.BaseDirectory;
            candidates.Add(Path.Combine(resourceRoot, "bin", "ffmpeg.exe"));
            candidates.Add(Path.Combine(resourceRoot, "electron-resources", "bin", "ffmpeg.exe"));
        }
        else
        {
            var studioRoot = Directory.GetParent(workingDirectory)?.FullName;
            if (studioRoot is not null)
            {
                candidates.Add(Path.Combine(studioRoot, "electron-resources", "bin", "ffmpeg.exe"));
            }
        }

        return candidates.FirstOrDefault(File.Exists) ?? "ffmpeg";
    }

    private static string? ReadPackagedProfile(string backendDirectory)
    {
        var manifest = Path.Combine(backendDirectory, "backend-bundle-manifest.json");
        try
        {
            using var document = System.Text.Json.JsonDocument.Parse(File.ReadAllText(manifest));
            return document.RootElement.TryGetProperty("acceleratorProfile", out var profile)
                ? profile.GetString()
                : null;
        }
        catch
        {
            return null;
        }
    }

    private static bool IsValidPackagedBackendDirectory(string candidate)
    {
        var executable = Path.Combine(candidate, "edmg-studio-backend.exe");
        var manifestPath = Path.Combine(candidate, "backend-bundle-manifest.json");
        if (!File.Exists(executable) || !File.Exists(manifestPath))
        {
            return false;
        }

        try
        {
            using var document = System.Text.Json.JsonDocument.Parse(File.ReadAllText(manifestPath));
            var root = document.RootElement;
            var ok = root.TryGetProperty("ok", out var okValue) && okValue.ValueKind == System.Text.Json.JsonValueKind.True;
            var platform = root.TryGetProperty("platform", out var platformValue) ? platformValue.GetString() : null;
            var layout = root.TryGetProperty("bundleLayout", out var layoutValue) ? layoutValue.GetString() : null;
            var entryPoint = root.TryGetProperty("backendEntryPoint", out var entryValue) ? entryValue.GetString() : null;
            var profile = root.TryGetProperty("acceleratorProfile", out var profileValue) ? profileValue.GetString() : null;
            var entriesPresent = root.TryGetProperty("bundleEntries", out var entries) &&
                                 entries.ValueKind == System.Text.Json.JsonValueKind.Array &&
                                 entries.GetArrayLength() > 0;
            return ok &&
                   string.Equals(platform, "win32", StringComparison.OrdinalIgnoreCase) &&
                   string.Equals(layout, "onedir", StringComparison.OrdinalIgnoreCase) &&
                   string.Equals(entryPoint, "edmg-studio-backend.exe", StringComparison.OrdinalIgnoreCase) &&
                   profile is "cpu" or "directml" or "cuda" &&
                   entriesPresent &&
                   Directory.Exists(Path.Combine(candidate, "_internal"));
        }
        catch
        {
            return false;
        }
    }
}
