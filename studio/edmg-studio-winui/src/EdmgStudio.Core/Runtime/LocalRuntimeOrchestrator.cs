using System.Collections.Immutable;
using System.Diagnostics;
using System.Runtime.ExceptionServices;

namespace EdmgStudio.Core.Runtime;

public sealed class LocalRuntimeOrchestrator : ILocalRuntimeOrchestrator
{
    private readonly Dictionary<LocalRuntimeType, ILocalInferenceRuntime> _runtimes;
    private readonly IWslCommandRunner _runner;
    private readonly IGpuDiscoveryService _gpuDiscovery;
    private readonly IRuntimeHealthService _health;
    private readonly IRuntimeProfileResolver _profiles;
    private readonly LocalRuntimeSettingsStore _settingsStore;
    private readonly SemaphoreSlim _lifecycleLock = new(1, 1);
    private readonly CancellationTokenSource _lifetimeCancellation = new();
    private readonly TimeSpan _pollInterval;
    private RuntimeLaunchResult? _activeLaunch;
    private GpuTopology _topology = GpuTopology.Unavailable;
    private bool _disposed;

    public LocalRuntimeOrchestrator(
        IEnumerable<ILocalInferenceRuntime> runtimes,
        IWslCommandRunner runner,
        IGpuDiscoveryService gpuDiscovery,
        IRuntimeHealthService health,
        IRuntimeProfileResolver profiles,
        LocalRuntimeSettingsStore settingsStore,
        TimeSpan? pollInterval = null)
    {
        _runtimes = runtimes.ToDictionary(runtime => runtime.RuntimeType);
        _runner = runner;
        _gpuDiscovery = gpuDiscovery;
        _health = health;
        _profiles = profiles;
        _settingsStore = settingsStore;
        _pollInterval = pollInterval ?? TimeSpan.FromMilliseconds(500);
        Settings = settingsStore.Load();
    }

    public RuntimeStatus CurrentStatus { get; private set; } = RuntimeStatus.Stopped;
    public LocalRuntimeSettings Settings { get; private set; }
    public event EventHandler<RuntimeStatus>? StatusChanged;

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        if (!Settings.Enabled)
        {
            Publish(RuntimeStatus.Stopped with { Error = "Local Director runtime is disabled.", LastUpdated = DateTimeOffset.UtcNow });
            return;
        }
        if (Settings.AutoStart) await StartAsync(cancellationToken: cancellationToken).ConfigureAwait(false);
        else await GetStatusAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<RuntimeStatus> GetStatusAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await _lifecycleLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_activeLaunch is null) return CurrentStatus;
            RuntimeHealthResult health = await _health.ProbeAsync(_activeLaunch.Endpoint, _activeLaunch.Runtime, cancellationToken).ConfigureAwait(false);
            Publish(CreateStatus(
                health.IsReady ? RuntimeState.Ready : health.IsReachable ? RuntimeState.Degraded : RuntimeState.Failed,
                _activeLaunch.Runtime,
                health.Model ?? _activeLaunch.Model,
                _activeLaunch.Endpoint,
                health.Error,
                _activeLaunch.Ownership,
                _activeLaunch.LogPath));
            return CurrentStatus;
        }
        finally
        {
            _lifecycleLock.Release();
        }
    }

    public async Task StartAsync(string? profileId = null, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        if (!Settings.Enabled) throw new InvalidOperationException("Local Director runtime orchestration is disabled in Studio settings.");
        using var linkedCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _lifetimeCancellation.Token);
        await _lifecycleLock.WaitAsync(linkedCancellation.Token).ConfigureAwait(false);
        try
        {
            if (_activeLaunch is not null && CurrentStatus.State == RuntimeState.Ready) return;
            Publish(CreateStatus(RuntimeState.Detecting, Settings.PreferredRuntime, null, null, null, RuntimeOwnership.External, null));
            _topology = await _gpuDiscovery.DetectAsync(linkedCancellation.Token).ConfigureAwait(false);
            ResolvedRuntimeProfile profile = _profiles.Resolve(Settings, _topology, profileId);
            Uri endpoint = new($"http://127.0.0.1:{profile.Port}/");
            RuntimeHealthResult existing = await _health.ProbeAsync(endpoint, profile.RuntimeType, linkedCancellation.Token).ConfigureAwait(false);
            if (existing.IsReady)
            {
                _activeLaunch = new RuntimeLaunchResult(profile.RuntimeType, existing.Model ?? profile.Model, endpoint, RuntimeOwnership.External, string.Empty);
                Publish(CreateStatus(RuntimeState.Ready, profile.RuntimeType, _activeLaunch.Model, endpoint, null, RuntimeOwnership.External, null));
                return;
            }
            if (existing.IsReachable) throw new InvalidOperationException($"Port {profile.Port} is occupied by a service that is not a ready {profile.RuntimeType} endpoint.");
            if (!_runtimes.TryGetValue(profile.RuntimeType, out ILocalInferenceRuntime? runtime)) throw new InvalidOperationException($"The {profile.RuntimeType} provider is not registered.");
            if (!await runtime.IsInstalledAsync(linkedCancellation.Token).ConfigureAwait(false)) throw new InvalidOperationException(profile.RuntimeType == LocalRuntimeType.LlamaCpp ? "llama.cpp is not installed in the selected WSL distribution." : "TensorRT-LLM is not installed in the selected WSL distribution.");

            Publish(CreateStatus(RuntimeState.Starting, profile.RuntimeType, profile.Model, endpoint, null, RuntimeOwnership.External, null));
            RuntimeLaunchResult launched = await runtime.StartAsync(profile, linkedCancellation.Token).ConfigureAwait(false);
            _activeLaunch = launched;
            Publish(CreateStatus(RuntimeState.LoadingModel, profile.RuntimeType, profile.Model, endpoint, null, launched.Ownership, launched.LogPath));
            RuntimeHealthResult ready = await WaitUntilReadyAsync(launched, linkedCancellation.Token).ConfigureAwait(false);
            Publish(CreateStatus(RuntimeState.Ready, profile.RuntimeType, ready.Model ?? profile.Model, endpoint, null, launched.Ownership, launched.LogPath));
        }
        catch (Exception exception)
        {
            RuntimeLaunchResult? failedLaunch = _activeLaunch;
            if (failedLaunch?.Ownership.StartedByStudio == true && _runtimes.TryGetValue(failedLaunch.Runtime, out ILocalInferenceRuntime? runtime))
            {
                try { await runtime.StopAsync(failedLaunch.Ownership, CancellationToken.None).ConfigureAwait(false); }
                catch (Exception stopException) { exception = new AggregateException(exception, stopException); }
                _activeLaunch = null;
            }
            Publish(CurrentStatus with
            {
                State = exception is OperationCanceledException ? RuntimeState.Stopped : RuntimeState.Failed,
                Error = exception is OperationCanceledException ? "Runtime startup was canceled." : exception.Message,
                LastUpdated = DateTimeOffset.UtcNow
            });
            if (exception is OperationCanceledException) throw;
            ExceptionDispatchInfo.Capture(exception).Throw();
            throw new UnreachableException();
        }
        finally
        {
            _lifecycleLock.Release();
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await StopCoreAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task RestartAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        await StopCoreAsync(cancellationToken).ConfigureAwait(false);
        await StartAsync(cancellationToken: cancellationToken).ConfigureAwait(false);
    }

    public void UpdateSettings(LocalRuntimeSettings settings)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(settings);
        _settingsStore.Save(settings);
        Settings = settings;
    }

    public async Task<string> ReadRecentLogAsync(int lineCount = 300, CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        if (lineCount is < 1 or > 5000) throw new ArgumentOutOfRangeException(nameof(lineCount));
        if (string.IsNullOrWhiteSpace(CurrentStatus.LogPath)) return "No Studio-owned runtime log is available. External runtimes keep their own logs.";
        CommandResult result = await _runner.RunAsync($"tail -n {lineCount} -- {WslCommandRunner.ShellQuote(CurrentStatus.LogPath)}", TimeSpan.FromSeconds(10), cancellationToken).ConfigureAwait(false);
        if (!result.Succeeded) throw new InvalidOperationException($"Unable to read runtime log: {result.StandardError.Trim()}");
        return result.StandardOutput;
    }

    public async Task<RuntimeHealthResult> TestAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        if (CurrentStatus.Endpoint is null) return new RuntimeHealthResult(false, false, null, null, "No local runtime endpoint is active.");
        return await _health.ProbeAsync(CurrentStatus.Endpoint, CurrentStatus.Runtime, cancellationToken).ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;
        _lifetimeCancellation.Cancel();
        if (Settings.StopOnExit)
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            try { await StopCoreAsync(timeout.Token).ConfigureAwait(false); }
            catch (OperationCanceledException) when (timeout.IsCancellationRequested) { }
        }
        _disposed = true;
        _lifetimeCancellation.Dispose();
        _lifecycleLock.Dispose();
        if (_health is IDisposable disposable) disposable.Dispose();
    }

    private async Task StopCoreAsync(CancellationToken cancellationToken)
    {
        await _lifecycleLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            RuntimeLaunchResult? launch = _activeLaunch;
            if (launch is null)
            {
                Publish(RuntimeStatus.Stopped with { LastUpdated = DateTimeOffset.UtcNow });
                return;
            }
            if (!launch.Ownership.StartedByStudio)
            {
                Publish(CreateStatus(RuntimeState.Ready, launch.Runtime, launch.Model, launch.Endpoint, "External runtime was left running.", launch.Ownership, null));
                return;
            }
            Publish(CreateStatus(RuntimeState.Stopping, launch.Runtime, launch.Model, launch.Endpoint, null, launch.Ownership, launch.LogPath));
            await _runtimes[launch.Runtime].StopAsync(launch.Ownership, cancellationToken).ConfigureAwait(false);
            _activeLaunch = null;
            Publish(RuntimeStatus.Stopped with { Runtime = launch.Runtime, LastUpdated = DateTimeOffset.UtcNow, LogPath = launch.LogPath });
        }
        finally
        {
            _lifecycleLock.Release();
        }
    }

    private async Task<RuntimeHealthResult> WaitUntilReadyAsync(RuntimeLaunchResult launch, CancellationToken cancellationToken)
    {
        DateTimeOffset deadline = DateTimeOffset.UtcNow + Settings.StartupTimeout;
        RuntimeHealthResult last = new(false, false, null, null, null);
        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            last = await _health.ProbeAsync(launch.Endpoint, launch.Runtime, cancellationToken).ConfigureAwait(false);
            if (last.IsReady) return last;
            await Task.Delay(_pollInterval, cancellationToken).ConfigureAwait(false);
        }
        throw new TimeoutException($"{launch.Runtime} timed out while loading {launch.Model}. {last.Error}".Trim());
    }

    private RuntimeStatus CreateStatus(RuntimeState state, LocalRuntimeType runtime, string? model, Uri? endpoint, string? error, RuntimeOwnership ownership, string? logPath) => new(
        state,
        runtime,
        model,
        endpoint,
        _topology.CudaAvailable ? "CUDA" : "Unavailable",
        [.. _topology.Gpus.Select(gpu => gpu.Name)],
        _topology.GpuCount,
        error,
        DateTimeOffset.UtcNow,
        ownership.StartedByStudio,
        logPath);

    private void Publish(RuntimeStatus status)
    {
        CurrentStatus = status;
        StatusChanged?.Invoke(this, status);
    }

    private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(_disposed, this);
}
