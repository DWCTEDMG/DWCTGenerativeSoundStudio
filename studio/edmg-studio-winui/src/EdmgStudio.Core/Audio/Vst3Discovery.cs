using System.Collections.Immutable;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Audio;

public enum Vst3CapabilityState { Unavailable, ScannerReady, HostReady, ProcessingReady }
public enum Vst3ScanStatus { Success, Unsupported, Failed, TimedOut, MalformedResponse, Quarantined }

public static class Vst3ModuleDiscovery
{
    public static ImmutableArray<string> StandardWindowsRoots()
    {
        if (!OperatingSystem.IsWindows()) return [];
        string? programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string? localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return new[]
        {
            string.IsNullOrWhiteSpace(programFiles) ? null : Path.Combine(programFiles, "Common Files", "VST3"),
            string.IsNullOrWhiteSpace(localAppData) ? null : Path.Combine(localAppData, "Programs", "Common", "VST3")
        }.Where(path => !string.IsNullOrWhiteSpace(path) && Directory.Exists(path))
         .Select(path => Path.GetFullPath(path!))
         .Distinct(StringComparer.OrdinalIgnoreCase)
         .ToImmutableArray();
    }

    public static ImmutableArray<string> EnumerateModules(IEnumerable<string> roots)
    {
        ArgumentNullException.ThrowIfNull(roots);
        var modules = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string rawRoot in roots.Where(value => !string.IsNullOrWhiteSpace(value)))
        {
            string root = Path.GetFullPath(Environment.ExpandEnvironmentVariables(rawRoot.Trim()));
            if (IsVst3Module(root)) { modules.Add(root); continue; }
            if (!Directory.Exists(root)) continue;
            foreach (string entry in EnumerateDirectory(root))
                if (IsVst3Module(entry)) modules.Add(Path.GetFullPath(entry));
        }
        return modules.ToImmutableArray();
    }

    private static bool IsVst3Module(string path) =>
        string.Equals(Path.GetExtension(path), ".vst3", StringComparison.OrdinalIgnoreCase) &&
        (File.Exists(path) || Directory.Exists(path));

    private static IEnumerable<string> EnumerateDirectory(string root)
    {
        var pending = new Stack<string>();
        pending.Push(root);
        while (pending.Count > 0)
        {
            string directory = pending.Pop();
            IEnumerable<string> entries;
            try { entries = Directory.EnumerateFileSystemEntries(directory).ToArray(); }
            catch (UnauthorizedAccessException) { continue; }
            catch (IOException) { continue; }
            foreach (string entry in entries)
            {
                FileAttributes attributes;
                try { attributes = File.GetAttributes(entry); }
                catch (UnauthorizedAccessException) { continue; }
                catch (IOException) { continue; }
                if ((attributes & FileAttributes.ReparsePoint) != 0) continue;
                if (IsVst3Module(entry)) { yield return entry; continue; }
                if ((attributes & FileAttributes.Directory) != 0) pending.Push(entry);
            }
        }
    }
}

public sealed record Vst3ModuleFingerprint(
    string ModulePath,
    long Length,
    long LastWriteUtcTicks,
    string Sha256);

public sealed record Vst3PluginMetadata(
    string PluginId,
    string Name,
    string Vendor,
    string Version,
    string Category,
    int AudioInputs,
    int AudioOutputs,
    bool HasEditor,
    bool SupportsPresets,
    int ReportedLatencySamples,
    int EventInputBuses = 0,
    int EventOutputBuses = 0,
    int ParameterCount = 0,
    string Architecture = "x64",
    string Capabilities = "audio");

public sealed record Vst3ScanResponse(
    int SchemaVersion,
    Vst3ModuleFingerprint Fingerprint,
    ImmutableArray<Vst3PluginMetadata> Plugins,
    string Status = "success");

public sealed record Vst3ScanResult(
    Vst3ScanStatus Status,
    Vst3ModuleFingerprint Fingerprint,
    ImmutableArray<Vst3PluginMetadata> Plugins,
    string? Diagnostic);

public sealed record Vst3CacheEntry(
    Vst3ModuleFingerprint Fingerprint,
    ImmutableArray<Vst3PluginMetadata> Plugins,
    DateTimeOffset ScannedAtUtc);

public sealed record Vst3QuarantineEntry(
    Vst3ModuleFingerprint Fingerprint,
    string Reason,
    int FailureCount,
    DateTimeOffset LastFailureAtUtc);

public sealed record Vst3Catalog(
    int SchemaVersion,
    ImmutableArray<Vst3CacheEntry> Cache,
    ImmutableArray<Vst3QuarantineEntry> Quarantine)
{
    public static Vst3Catalog Empty { get; } = new(1, [], []);
}

public sealed record Vst3ScannerProcessResult(int ExitCode, string StandardOutput, string StandardError);

public interface IVst3ScannerProcessRunner
{
    Task<Vst3ScannerProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken);
}

public sealed class Vst3ScannerProcessRunner : IVst3ScannerProcessRunner
{
    public async Task<Vst3ScannerProcessResult> RunAsync(
        ProcessStartInfo startInfo,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        if (!process.Start()) throw new InvalidOperationException("The VST3 scanner did not start.");
        Task<string> stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        Task<string> stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        using var timeoutCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCancellation.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(timeoutCancellation.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            Kill(process);
            throw new TimeoutException($"The VST3 scanner exceeded its {timeout.TotalSeconds:0.#} second timeout.");
        }
        catch (OperationCanceledException)
        {
            Kill(process);
            throw;
        }
        return new(process.ExitCode, await stdoutTask.ConfigureAwait(false), await stderrTask.ConfigureAwait(false));
    }

    private static void Kill(Process process)
    {
        try
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
        }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }
    }
}

public static class Vst3ModuleFingerprinting
{
    public static async Task<Vst3ModuleFingerprint> CreateAsync(
        string modulePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(modulePath);
        string path = Path.GetFullPath(modulePath);
        if (File.Exists(path))
        {
            var info = new FileInfo(path);
            await using var stream = OpenRead(path);
            byte[] fileHash = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
            return new(path, info.Length, info.LastWriteTimeUtc.Ticks, Convert.ToHexString(fileHash).ToLowerInvariant());
        }
        if (!Directory.Exists(path)) throw new FileNotFoundException("The VST3 module does not exist.", path);

        string[] files = EnumerateBundleFiles(path)
            .OrderBy(file => Path.GetRelativePath(path, file).Replace('\\', '/'), StringComparer.OrdinalIgnoreCase)
            .ToArray();
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        long length = 0;
        long lastWriteTicks = new DirectoryInfo(path).LastWriteTimeUtc.Ticks;
        byte[] buffer = new byte[128 * 1024];
        foreach (string file in files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var info = new FileInfo(file);
            string relativePath = Path.GetRelativePath(path, file).Replace('\\', '/');
            Append(hash, relativePath);
            Append(hash, info.Length);
            Append(hash, info.LastWriteTimeUtc.Ticks);
            length = checked(length + info.Length);
            lastWriteTicks = Math.Max(lastWriteTicks, info.LastWriteTimeUtc.Ticks);
            await using var stream = OpenRead(file);
            int read;
            while ((read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false)) > 0)
                hash.AppendData(buffer.AsSpan(0, read));
        }
        return new(path, length, lastWriteTicks, Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant());
    }

    private static IEnumerable<string> EnumerateBundleFiles(string root)
    {
        var pending = new Stack<string>();
        pending.Push(root);
        while (pending.Count > 0)
        {
            string directory = pending.Pop();
            if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException($"VST3 bundle contains a directory reparse point: {directory}");
            foreach (string entry in Directory.EnumerateFileSystemEntries(directory))
            {
                FileAttributes attributes = File.GetAttributes(entry);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException($"VST3 bundle contains a reparse point: {entry}");
                if ((attributes & FileAttributes.Directory) != 0) pending.Push(entry);
                else yield return entry;
            }
        }
    }

    private static FileStream OpenRead(string path) => new(
        path, FileMode.Open, FileAccess.Read, FileShare.Read, 128 * 1024,
        FileOptions.Asynchronous | FileOptions.SequentialScan);

    private static void Append(IncrementalHash hash, string value)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(value);
        Append(hash, bytes.Length);
        hash.AppendData(bytes);
    }

    private static void Append(IncrementalHash hash, long value) =>
        hash.AppendData(BitConverter.GetBytes(value));
}

public sealed class Vst3CatalogStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };
    private readonly string _path;

    public Vst3CatalogStore(string? path = null)
    {
        _path = Path.GetFullPath(path ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "EDMG Studio", "vst3-catalog.json"));
    }

    public Vst3Catalog Load()
    {
        if (!File.Exists(_path)) return Vst3Catalog.Empty;
        try
        {
            Vst3Catalog? catalog = JsonSerializer.Deserialize<Vst3Catalog>(File.ReadAllText(_path), JsonOptions);
            if (catalog is null || catalog.SchemaVersion != 1 || catalog.Cache.IsDefault || catalog.Quarantine.IsDefault)
                throw new InvalidDataException("The VST3 catalog has an unsupported or incomplete schema.");
            return catalog;
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("The VST3 catalog is malformed and was not changed.", exception);
        }
    }

    public bool TryGetCached(Vst3ModuleFingerprint fingerprint, out Vst3CacheEntry? entry)
    {
        entry = Load().Cache.FirstOrDefault(candidate => candidate.Fingerprint == fingerprint);
        return entry is not null;
    }

    public bool IsQuarantined(Vst3ModuleFingerprint fingerprint) =>
        Load().Quarantine.Any(entry => entry.Fingerprint == fingerprint);

    public void RecordSuccess(Vst3ScanResponse response)
    {
        ArgumentNullException.ThrowIfNull(response);
        Vst3Catalog catalog = Load();
        Save(catalog with
        {
            Cache = catalog.Cache.Where(entry => !SamePath(entry.Fingerprint, response.Fingerprint)).Append(
                new Vst3CacheEntry(response.Fingerprint, response.Plugins, DateTimeOffset.UtcNow)).ToImmutableArray(),
            Quarantine = catalog.Quarantine.Where(entry => !SamePath(entry.Fingerprint, response.Fingerprint)).ToImmutableArray()
        });
    }

    public void RecordFailure(Vst3ModuleFingerprint fingerprint, string reason)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(reason);
        Vst3Catalog catalog = Load();
        Vst3QuarantineEntry? current = catalog.Quarantine.FirstOrDefault(entry => entry.Fingerprint == fingerprint);
        Save(catalog with
        {
            Cache = catalog.Cache.Where(entry => !SamePath(entry.Fingerprint, fingerprint)).ToImmutableArray(),
            Quarantine = catalog.Quarantine.Where(entry => !SamePath(entry.Fingerprint, fingerprint)).Append(
                new Vst3QuarantineEntry(fingerprint, reason.Trim(), checked((current?.FailureCount ?? 0) + 1), DateTimeOffset.UtcNow)).ToImmutableArray()
        });
    }

    public void ClearQuarantine(string? modulePath = null)
    {
        Vst3Catalog catalog = Load();
        ImmutableArray<Vst3QuarantineEntry> remaining = string.IsNullOrWhiteSpace(modulePath)
            ? []
            : catalog.Quarantine.Where(entry => !string.Equals(
                entry.Fingerprint.ModulePath, Path.GetFullPath(modulePath), StringComparison.OrdinalIgnoreCase)).ToImmutableArray();
        Save(catalog with { Quarantine = remaining });
    }

    private void Save(Vst3Catalog catalog)
    {
        string? directory = Path.GetDirectoryName(_path);
        if (directory is null) throw new InvalidOperationException("The VST3 catalog path has no parent directory.");
        Directory.CreateDirectory(directory);
        string temporaryPath = Path.Combine(directory, $".{Path.GetFileName(_path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            File.WriteAllText(temporaryPath, JsonSerializer.Serialize(catalog, JsonOptions) + Environment.NewLine);
            File.Move(temporaryPath, _path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }

    private static bool SamePath(Vst3ModuleFingerprint left, Vst3ModuleFingerprint right) =>
        string.Equals(left.ModulePath, right.ModulePath, StringComparison.OrdinalIgnoreCase);
}

public sealed class Vst3ScannerClient(
    string scannerPath,
    Vst3CatalogStore catalog,
    IVst3ScannerProcessRunner? processRunner = null)
{
    private readonly IVst3ScannerProcessRunner _processRunner = processRunner ?? new Vst3ScannerProcessRunner();

    public Vst3CapabilityState CapabilityState => File.Exists(scannerPath)
        ? Vst3CapabilityState.ScannerReady
        : Vst3CapabilityState.Unavailable;

    public async Task<Vst3ScanResult> ScanAsync(
        string modulePath,
        TimeSpan timeout,
        bool force = false,
        CancellationToken cancellationToken = default)
    {
        if (timeout <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(timeout));
        Vst3ModuleFingerprint fingerprint = await Vst3ModuleFingerprinting.CreateAsync(modulePath, cancellationToken);
        if (!force && catalog.IsQuarantined(fingerprint))
            return new(Vst3ScanStatus.Quarantined, fingerprint, [], "The unchanged module is quarantined. Clear quarantine or force a rescan.");
        if (!force && catalog.TryGetCached(fingerprint, out Vst3CacheEntry? cached))
            return cached!.Plugins.IsEmpty
                ? new(Vst3ScanStatus.Unsupported, fingerprint, [], "The module exposes no supported VST3 audio-effect classes.")
                : new(Vst3ScanStatus.Success, fingerprint, cached.Plugins, null);
        if (!File.Exists(scannerPath))
            return new(Vst3ScanStatus.Failed, fingerprint, [], "The native VST3 scanner is not installed.");

        try
        {
            Vst3ScannerProcessResult processResult = await _processRunner.RunAsync(
                CreateStartInfo(fingerprint), timeout, cancellationToken).ConfigureAwait(false);
            if (processResult.ExitCode != 0)
                return Failure(Vst3ScanStatus.Failed, $"The VST3 scanner exited with code {processResult.ExitCode}: {Normalize(processResult.StandardError)}");
            Vst3ScanResponse response;
            try
            {
                response = ParseResponse(processResult.StandardOutput, fingerprint);
            }
            catch (InvalidDataException exception)
            {
                return Failure(Vst3ScanStatus.MalformedResponse, exception.Message);
            }
            catalog.RecordSuccess(response);
            return response.Status == "unsupported"
                ? new(Vst3ScanStatus.Unsupported, fingerprint, [], "The module exposes no supported VST3 audio-effect classes.")
                : new(Vst3ScanStatus.Success, fingerprint, response.Plugins, null);
        }
        catch (System.ComponentModel.Win32Exception exception)
        {
            return new(Vst3ScanStatus.Failed, fingerprint, [], $"The VST3 scanner could not start: {exception.Message}");
        }
        catch (TimeoutException exception)
        {
            return Failure(Vst3ScanStatus.TimedOut, exception.Message);
        }

        Vst3ScanResult Failure(Vst3ScanStatus status, string diagnostic)
        {
            catalog.RecordFailure(fingerprint, diagnostic);
            return new(status, fingerprint, [], diagnostic);
        }
    }

    public static Vst3ScanResponse ParseResponse(string json, Vst3ModuleFingerprint expectedFingerprint)
    {
        if (string.IsNullOrWhiteSpace(json) || json.Length > 4 * 1024 * 1024)
            throw new InvalidDataException("The VST3 scanner returned an empty or oversized response.");
        try
        {
            Vst3ScanResponse? response = JsonSerializer.Deserialize<Vst3ScanResponse>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
                MaxDepth = 32
            });
            if (response is null || response.SchemaVersion != 1 || response.Plugins.IsDefault ||
                response.Fingerprint != expectedFingerprint ||
                response.Status is not ("success" or "unsupported") ||
                (response.Status == "success" && response.Plugins.IsEmpty) ||
                (response.Status == "unsupported" && !response.Plugins.IsEmpty) ||
                response.Plugins.Select(plugin => plugin.PluginId).Distinct(StringComparer.Ordinal).Count() != response.Plugins.Length ||
                response.Plugins.Any(plugin =>
                    string.IsNullOrWhiteSpace(plugin.PluginId) || string.IsNullOrWhiteSpace(plugin.Name) ||
                    plugin.AudioInputs < 0 || plugin.AudioOutputs < 0 || plugin.ReportedLatencySamples < 0 ||
                    plugin.EventInputBuses < 0 || plugin.EventOutputBuses < 0 || plugin.ParameterCount < 0 ||
                    !string.Equals(plugin.Architecture, "x64", StringComparison.OrdinalIgnoreCase)))
                throw new InvalidDataException("The VST3 scanner returned an invalid or mismatched response.");
            return response;
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("The VST3 scanner returned malformed JSON.", exception);
        }
    }

    private ProcessStartInfo CreateStartInfo(Vst3ModuleFingerprint fingerprint)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = scannerPath,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        startInfo.ArgumentList.Add("--scan-module");
        startInfo.ArgumentList.Add("--module");
        startInfo.ArgumentList.Add(fingerprint.ModulePath);
        startInfo.ArgumentList.Add("--fingerprint-path");
        startInfo.ArgumentList.Add(fingerprint.ModulePath);
        startInfo.ArgumentList.Add("--fingerprint-length");
        startInfo.ArgumentList.Add(fingerprint.Length.ToString(System.Globalization.CultureInfo.InvariantCulture));
        startInfo.ArgumentList.Add("--fingerprint-ticks");
        startInfo.ArgumentList.Add(fingerprint.LastWriteUtcTicks.ToString(System.Globalization.CultureInfo.InvariantCulture));
        startInfo.ArgumentList.Add("--fingerprint-sha256");
        startInfo.ArgumentList.Add(fingerprint.Sha256);
        startInfo.ArgumentList.Add("--format");
        startInfo.ArgumentList.Add("json-v1");
        return startInfo;
    }

    private static string Normalize(string value) =>
        string.IsNullOrWhiteSpace(value) ? "No diagnostic output was produced." : value.Trim();
}
