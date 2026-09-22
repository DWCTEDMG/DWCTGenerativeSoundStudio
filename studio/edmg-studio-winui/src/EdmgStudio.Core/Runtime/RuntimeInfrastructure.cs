using System.Collections.Immutable;
using System.Diagnostics;
using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json;

namespace EdmgStudio.Core.Runtime;

public sealed class WslCommandRunner : IWslCommandRunner
{
    private readonly string? _distro;

    public WslCommandRunner(string? distro = null) => _distro = string.IsNullOrWhiteSpace(distro) ? null : distro.Trim();

    public async Task<CommandResult> RunAsync(string command, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(command);
        if (timeout <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(timeout));
        using var process = CreateProcess(command);
        try
        {
            if (!process.Start()) throw new InvalidOperationException("wsl.exe did not start.");
        }
        catch (Exception exception) when (exception is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            throw new InvalidOperationException("WSL is unavailable. Install WSL and a Linux distribution, then retry.", exception);
        }

        Task<string> stdout = process.StandardOutput.ReadToEndAsync(cancellationToken);
        Task<string> stderr = process.StandardError.ReadToEndAsync(cancellationToken);
        using var timeoutCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCancellation.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(timeoutCancellation.Token).ConfigureAwait(false);
            return new CommandResult(process.ExitCode, await stdout.ConfigureAwait(false), await stderr.ConfigureAwait(false), false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            if (!process.HasExited) process.Kill(true);
            return new CommandResult(-1, await stdout.ConfigureAwait(false), await stderr.ConfigureAwait(false), true);
        }
    }

    public async Task<DetachedCommandResult> StartDetachedAsync(string command, string logPath, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(logPath);
        string script = $"mkdir -p -- {ShellQuote(Path.GetDirectoryName(logPath)?.Replace('\\', '/') ?? ".")} && nohup setsid bash -lc {ShellQuote("exec " + command)} > {ShellQuote(logPath.Replace('\\', '/'))} 2>&1 < /dev/null & echo $!";
        CommandResult result = await RunAsync(script, timeout, cancellationToken).ConfigureAwait(false);
        if (!result.Succeeded || !int.TryParse(result.StandardOutput.Trim().Split('\n').LastOrDefault(), NumberStyles.None, CultureInfo.InvariantCulture, out int pid) || pid <= 0)
        {
            throw new InvalidOperationException($"WSL server launch failed: {result.StandardError.Trim()}");
        }
        return new DetachedCommandResult(pid, logPath);
    }

    public static string ShellQuote(string value) => $"'{value.Replace("'", "'\"'\"'", StringComparison.Ordinal)}'";

    private Process CreateProcess(string command)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "wsl.exe",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        if (_distro is not null)
        {
            startInfo.ArgumentList.Add("--distribution");
            startInfo.ArgumentList.Add(_distro);
        }
        startInfo.ArgumentList.Add("--");
        startInfo.ArgumentList.Add("bash");
        startInfo.ArgumentList.Add("-lc");
        startInfo.ArgumentList.Add(command);
        return new Process { StartInfo = startInfo };
    }
}

public sealed class GpuDiscoveryService(IWslCommandRunner runner) : IGpuDiscoveryService
{
    private const string Query = "nvidia-smi --query-gpu=index,name,memory.total,memory.free,driver_version --format=csv,noheader,nounits";

    public async Task<GpuTopology> DetectAsync(CancellationToken cancellationToken = default)
    {
        CommandResult result = await runner.RunAsync(Query, TimeSpan.FromSeconds(10), cancellationToken).ConfigureAwait(false);
        if (!result.Succeeded) return GpuTopology.Unavailable;
        return Parse(result.StandardOutput);
    }

    public static GpuTopology Parse(string csv)
    {
        var gpus = ImmutableArray.CreateBuilder<GpuInfo>();
        foreach (string line in csv.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            string[] fields = line.Split(',', StringSplitOptions.TrimEntries);
            if (fields.Length != 5 || !int.TryParse(fields[0], CultureInfo.InvariantCulture, out int index) || !long.TryParse(fields[2], CultureInfo.InvariantCulture, out long total) || !long.TryParse(fields[3], CultureInfo.InvariantCulture, out long free))
            {
                throw new FormatException($"Unexpected nvidia-smi row: {line}");
            }
            gpus.Add(new GpuInfo(index, fields[1], total, free, fields[4]));
        }
        return new GpuTopology(gpus.Count > 0, gpus.ToImmutable());
    }
}

public sealed class RuntimeHealthService : IRuntimeHealthService, IDisposable
{
    private readonly HttpClient _client;
    private readonly bool _ownsClient;

    public RuntimeHealthService(HttpClient? client = null)
    {
        _client = client ?? new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        _ownsClient = client is null;
    }

    public async Task<RuntimeHealthResult> ProbeAsync(Uri endpoint, LocalRuntimeType runtime, CancellationToken cancellationToken = default)
    {
        try
        {
            using HttpResponseMessage health = await _client.GetAsync(new Uri(endpoint, "health"), cancellationToken).ConfigureAwait(false);
            if (!health.IsSuccessStatusCode) return new RuntimeHealthResult(true, false, null, null, $"Health returned {(int)health.StatusCode}.");
            string? model = await ReadFirstModelAsync(endpoint, cancellationToken).ConfigureAwait(false);
            string? version = runtime == LocalRuntimeType.TensorRtLlm ? await ReadVersionAsync(endpoint, cancellationToken).ConfigureAwait(false) : null;
            return new RuntimeHealthResult(true, model is not null, model, version, model is null ? "The model endpoint returned no models." : null);
        }
        catch (HttpRequestException exception)
        {
            return new RuntimeHealthResult(false, false, null, null, exception.Message);
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return new RuntimeHealthResult(false, false, null, null, "Runtime health probe timed out.");
        }
        catch (JsonException exception)
        {
            return new RuntimeHealthResult(true, false, null, null, $"Runtime returned malformed model metadata: {exception.Message}");
        }
    }

    private async Task<string?> ReadFirstModelAsync(Uri endpoint, CancellationToken cancellationToken)
    {
        using HttpResponseMessage response = await _client.GetAsync(new Uri(endpoint, "v1/models"), cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode) return null;
        using JsonDocument json = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(cancellationToken), cancellationToken: cancellationToken).ConfigureAwait(false);
        return json.RootElement.TryGetProperty("data", out JsonElement data) && data.ValueKind == JsonValueKind.Array && data.GetArrayLength() > 0 && data[0].TryGetProperty("id", out JsonElement id) ? id.GetString() : null;
    }

    private async Task<string?> ReadVersionAsync(Uri endpoint, CancellationToken cancellationToken)
    {
        using HttpResponseMessage response = await _client.GetAsync(new Uri(endpoint, "version"), cancellationToken).ConfigureAwait(false);
        return response.IsSuccessStatusCode ? (await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false)).Trim() : null;
    }

    public void Dispose()
    {
        if (_ownsClient) _client.Dispose();
    }
}

public sealed class RuntimeProfileResolver : IRuntimeProfileResolver
{
    public ResolvedRuntimeProfile Resolve(LocalRuntimeSettings settings, GpuTopology topology, string? profileId = null)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ImmutableArray<int> devices = settings.DeviceList.IsDefaultOrEmpty
            ? [.. topology.Gpus.Select(gpu => gpu.Index)]
            : settings.DeviceList;
        if (devices.Any(index => topology.Gpus.All(gpu => gpu.Index != index))) throw new InvalidOperationException("A selected GPU is not available in WSL.");
        if (settings.CudaEnabled && !topology.CudaAvailable) throw new InvalidOperationException("CUDA is unavailable because no NVIDIA GPU is visible inside WSL.");
        if (!settings.MultiGpuEnabled && devices.Length > 1) devices = [devices[0]];

        LocalRuntimeType type = settings.PreferredRuntime;
        if (type == LocalRuntimeType.Auto) type = string.IsNullOrWhiteSpace(settings.TensorRtModel) ? LocalRuntimeType.LlamaCpp : LocalRuntimeType.TensorRtLlm;
        string model = type == LocalRuntimeType.TensorRtLlm ? settings.TensorRtModel ?? throw new InvalidOperationException("A TensorRT model or engine is required.") : settings.LlamaModel;
        string format = type == LocalRuntimeType.TensorRtLlm ? settings.TensorRtModelFormat : "gguf";
        if (type == LocalRuntimeType.TensorRtLlm && format.Equals("gguf", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("GGUF models are not compatible with TensorRT-LLM.");
        int tp = settings.TensorParallelSize ?? Math.Max(1, devices.Length);
        if (type == LocalRuntimeType.TensorRtLlm && (tp > Math.Max(1, devices.Length) || devices.Length > 0 && devices.Length % tp != 0)) throw new InvalidOperationException("Tensor parallel size must fit the selected GPU topology.");
        return new ResolvedRuntimeProfile(
            profileId ?? "default",
            type,
            model,
            format,
            type == LocalRuntimeType.TensorRtLlm ? settings.TensorRtPort : settings.LlamaPort,
            settings.CudaEnabled,
            devices,
            devices.Length > 1,
            settings.SplitMode,
            settings.TensorSplit,
            type == LocalRuntimeType.TensorRtLlm ? tp : 1,
            settings.GpuLayers,
            settings.Fit,
            settings.ContextSize,
            settings.AdditionalArguments);
    }
}
