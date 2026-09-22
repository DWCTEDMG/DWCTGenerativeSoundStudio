using System.Collections.Immutable;

namespace EdmgStudio.Core.Runtime;

public enum RuntimeState
{
    Stopped,
    Detecting,
    Starting,
    LoadingModel,
    Ready,
    Degraded,
    Stopping,
    Failed
}

public enum LocalRuntimeType
{
    Auto,
    LlamaCpp,
    TensorRtLlm
}

public sealed record GpuInfo(
    int Index,
    string Name,
    long TotalMemoryMiB,
    long FreeMemoryMiB,
    string DriverVersion);

public sealed record GpuTopology(bool CudaAvailable, ImmutableArray<GpuInfo> Gpus)
{
    public static GpuTopology Unavailable { get; } = new(false, []);
    public int GpuCount => Gpus.Length;
    public long TotalMemoryMiB => Gpus.Sum(gpu => gpu.TotalMemoryMiB);
    public long FreeMemoryMiB => Gpus.Sum(gpu => gpu.FreeMemoryMiB);
}

public sealed record RuntimeOwnership(
    bool StartedByStudio,
    int? WindowsProcessId,
    int? WslProcessId,
    DateTimeOffset StartedAt)
{
    public static RuntimeOwnership External { get; } = new(false, null, null, DateTimeOffset.MinValue);
}

public sealed record RuntimeStatus(
    RuntimeState State,
    LocalRuntimeType Runtime,
    string? Model,
    Uri? Endpoint,
    string Acceleration,
    ImmutableArray<string> GpuNames,
    int GpuCount,
    string? Error,
    DateTimeOffset LastUpdated,
    bool StartedByStudio,
    string? LogPath = null)
{
    public static RuntimeStatus Stopped { get; } = new(
        RuntimeState.Stopped,
        LocalRuntimeType.Auto,
        null,
        null,
        "Not detected",
        [],
        0,
        null,
        DateTimeOffset.UtcNow,
        false);
}

public sealed record RuntimeHealthResult(
    bool IsReachable,
    bool IsReady,
    string? Model,
    string? Version,
    string? Error);

public sealed record CommandResult(int ExitCode, string StandardOutput, string StandardError, bool TimedOut)
{
    public bool Succeeded => ExitCode == 0 && !TimedOut;
}

public sealed record DetachedCommandResult(int WslProcessId, string LogPath);

public sealed record RuntimeLaunchResult(
    LocalRuntimeType Runtime,
    string Model,
    Uri Endpoint,
    RuntimeOwnership Ownership,
    string LogPath);

public sealed record LocalRuntimeSettings
{
    public bool Enabled { get; init; } = true;
    public bool AutoStart { get; init; } = true;
    public bool StopOnExit { get; init; } = true;
    public LocalRuntimeType PreferredRuntime { get; init; } = LocalRuntimeType.Auto;
    public bool CudaEnabled { get; init; } = true;
    public bool MultiGpuEnabled { get; init; } = true;
    public string? WslDistro { get; init; }
    public string LlamaExecutable { get; init; } = "~/.llama-app/llama";
    public string LlamaModel { get; init; } = "Qwen/Qwen3-4B-GGUF:Q4_K_M";
    public int LlamaPort { get; init; } = 8080;
    public string GpuLayers { get; init; } = "all";
    public string SplitMode { get; init; } = "layer";
    public string? TensorSplit { get; init; }
    public bool Fit { get; init; } = true;
    public int ContextSize { get; init; } = 8192;
    public string TensorRtExecutable { get; init; } = "trtllm-serve";
    public string? TensorRtModel { get; init; }
    public string TensorRtModelFormat { get; init; } = "engine";
    public int TensorRtPort { get; init; } = 8081;
    public int? TensorParallelSize { get; init; }
    public ImmutableArray<int> DeviceList { get; init; } = [];
    public ImmutableArray<string> AdditionalArguments { get; init; } = [];
    public TimeSpan StartupTimeout { get; init; } = TimeSpan.FromMinutes(3);
}

public sealed record ResolvedRuntimeProfile(
    string Id,
    LocalRuntimeType RuntimeType,
    string Model,
    string ModelFormat,
    int Port,
    bool Cuda,
    ImmutableArray<int> GpuDevices,
    bool MultiGpu,
    string SplitMode,
    string? TensorSplit,
    int TensorParallelSize,
    string GpuLayers,
    bool Fit,
    int ContextSize,
    ImmutableArray<string> AdditionalArguments);

public interface IWslCommandRunner
{
    Task<CommandResult> RunAsync(string command, TimeSpan timeout, CancellationToken cancellationToken = default);
    Task<DetachedCommandResult> StartDetachedAsync(string command, string logPath, TimeSpan timeout, CancellationToken cancellationToken = default);
}

public interface IGpuDiscoveryService
{
    Task<GpuTopology> DetectAsync(CancellationToken cancellationToken = default);
}

public interface IRuntimeHealthService
{
    Task<RuntimeHealthResult> ProbeAsync(Uri endpoint, LocalRuntimeType runtime, CancellationToken cancellationToken = default);
}

public interface IRuntimeProfileResolver
{
    ResolvedRuntimeProfile Resolve(LocalRuntimeSettings settings, GpuTopology topology, string? profileId = null);
}

public interface ILocalInferenceRuntime
{
    LocalRuntimeType RuntimeType { get; }
    Task<bool> IsInstalledAsync(CancellationToken cancellationToken = default);
    Task<RuntimeLaunchResult> StartAsync(ResolvedRuntimeProfile profile, CancellationToken cancellationToken = default);
    Task StopAsync(RuntimeOwnership ownership, CancellationToken cancellationToken = default);
}

public interface ILocalRuntimeOrchestrator : IAsyncDisposable
{
    RuntimeStatus CurrentStatus { get; }
    LocalRuntimeSettings Settings { get; }
    event EventHandler<RuntimeStatus>? StatusChanged;
    Task InitializeAsync(CancellationToken cancellationToken = default);
    Task<RuntimeStatus> GetStatusAsync(CancellationToken cancellationToken = default);
    Task StartAsync(string? profileId = null, CancellationToken cancellationToken = default);
    Task StopAsync(CancellationToken cancellationToken = default);
    Task RestartAsync(CancellationToken cancellationToken = default);
    Task<RuntimeHealthResult> TestAsync(CancellationToken cancellationToken = default);
    Task<string> ReadRecentLogAsync(int lineCount = 300, CancellationToken cancellationToken = default);
    void UpdateSettings(LocalRuntimeSettings settings);
}
