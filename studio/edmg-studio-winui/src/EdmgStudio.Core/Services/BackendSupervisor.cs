using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Services;

public interface IBackendEndpointProvider
{
    Uri CurrentBackendUri { get; }
}

public sealed class BackendSupervisor : IBackendEndpointProvider, IAsyncDisposable
{
    private static readonly TimeSpan ProbeTimeout = TimeSpan.FromMilliseconds(1500);
    private static readonly TimeSpan ProbeInterval = TimeSpan.FromMilliseconds(300);

    private readonly BackendConfiguration _configuration;
    private readonly BackendLaunchSpecFactory _specFactory;
    private readonly HttpClient _probeClient;
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    private readonly CancellationTokenSource _lifetimeCancellation = new();
    private readonly object _statusLock = new();
    private readonly object _logLock = new();
    private readonly List<Task> _logTasks = [];

    private Process? _ownedProcess;
    private WindowsProcessJob? _ownedJob;
    private CancellationTokenSource? _logCancellation;
    private BackendStatus _status;
    private bool _stopping;

    public BackendSupervisor(BackendConfiguration configuration, HttpMessageHandler? probeHandler = null)
    {
        _configuration = configuration;
        _specFactory = new BackendLaunchSpecFactory(configuration);
        _probeClient = probeHandler is null ? new HttpClient() : new HttpClient(probeHandler, disposeHandler: false);
        _probeClient.Timeout = Timeout.InfiniteTimeSpan;
        _status = new BackendStatus(
            BackendLifecycleState.Stopped,
            configuration.Mode == RequestedBackendMode.External ? BackendMode.External : BackendMode.Attached,
            configuration.BackendUri,
            "Backend has not been started.",
            AcceleratorProfile: configuration.AcceleratorProfile);
    }

    public event EventHandler<BackendStatus>? StatusChanged;

    public BackendStatus Status
    {
        get
        {
            lock (_statusLock)
            {
                return _status;
            }
        }
    }

    public Uri CurrentBackendUri => Status.CurrentBackendUri;

    public async Task<BackendStatus> StartAsync(CancellationToken cancellationToken = default)
    {
        using var startupCancellation = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            _lifetimeCancellation.Token);
        var startupToken = startupCancellation.Token;
        await _lifecycleGate.WaitAsync(startupToken).ConfigureAwait(false);
        try
        {
            if (Status.IsReady)
            {
                return Status;
            }

            _stopping = false;
            Publish(Status with
            {
                State = BackendLifecycleState.Resolving,
                Message = "Resolving the Studio backend.",
                FailureCode = null,
                Detail = null
            });

            if (_configuration.ValidationErrors.Count > 0)
            {
                return PublishFailure(
                    "INVALID_BACKEND_CONFIGURATION",
                    "The Studio backend configuration is invalid.",
                    string.Join(Environment.NewLine, _configuration.ValidationErrors));
            }

            if (_configuration.Mode == RequestedBackendMode.Managed && _configuration.HasPendingMigration)
            {
                return PublishFailure(
                    "STORAGE_MIGRATION_REQUIRED",
                    "A pending Studio storage migration must finish before the managed backend starts.",
                    _configuration.PendingMigrationDetail ?? "Open the existing Studio client to complete the pending migration safely.");
            }

            if (_configuration.Mode == RequestedBackendMode.External)
            {
                return await ConnectExternalAsync(startupToken).ConfigureAwait(false);
            }

            var packagedDirectory = _specFactory.FindPackagedBackendDirectory();
            if (packagedDirectory is not null)
            {
                return await StartPackagedAsync(packagedDirectory, startupToken).ConfigureAwait(false);
            }

            Publish(Status with
            {
                State = BackendLifecycleState.CheckingExisting,
                Mode = BackendMode.Attached,
                Message = $"Checking {_configuration.BackendUri}."
            });

            if (await IsHealthyAsync(_configuration.BackendUri, startupToken).ConfigureAwait(false))
            {
                return Publish(Status with
                {
                    State = BackendLifecycleState.Ready,
                    Mode = BackendMode.Attached,
                    Message = "Connected to the existing Studio backend.",
                    LastHealthCheck = DateTimeOffset.UtcNow
                });
            }

            var sourceDirectory = _specFactory.FindSourceBackendDirectory();
            if (sourceDirectory is null)
            {
                return PublishFailure(
                    "BACKEND_NOT_FOUND",
                    "No packaged backend or source backend was found.",
                    "Set EDMG_STUDIO_BACKEND_SOURCE_DIR or configure External mode with a reachable backend URL.");
            }

            if (await IsPortOccupiedAsync(_configuration.Host, _configuration.Port, startupToken).ConfigureAwait(false))
            {
                return PublishFailure(
                    "PORT_CONFLICT",
                    $"Port {_configuration.Port} is already in use by a service that is not a healthy EDMG backend.",
                    "Stop the conflicting service or configure another backend port. No foreign process was terminated.");
            }

            var sourceSpec = _specFactory.CreateSourceSpec(sourceDirectory, _configuration.Host, _configuration.Port);
            return await StartManagedAsync(sourceSpec, _configuration.BackendUri, _configuration.SourceReadyTimeout, startupToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            await StopOwnedProcessAsync(CancellationToken.None).ConfigureAwait(false);
            throw;
        }
        catch (OperationCanceledException) when (_lifetimeCancellation.IsCancellationRequested)
        {
            await StopOwnedProcessAsync(CancellationToken.None).ConfigureAwait(false);
            return Publish(Status with
            {
                State = BackendLifecycleState.Stopped,
                Message = "Backend startup was canceled because the Studio client is closing.",
                OwnedProcessId = null
            });
        }
        catch (Exception exception)
        {
            await StopOwnedProcessAsync(CancellationToken.None).ConfigureAwait(false);
            return PublishFailure("BACKEND_START_FAILED", "The Studio backend could not be started.", exception.Message);
        }
        finally
        {
            _lifecycleGate.Release();
        }
    }

    public async Task<BackendStatus> RefreshHealthAsync(CancellationToken cancellationToken = default)
    {
        var healthy = await IsHealthyAsync(CurrentBackendUri, cancellationToken).ConfigureAwait(false);
        if (healthy)
        {
            return Publish(Status with
            {
                State = BackendLifecycleState.Ready,
                Message = "Studio backend is ready.",
                LastHealthCheck = DateTimeOffset.UtcNow,
                FailureCode = null,
                Detail = null
            });
        }

        return Publish(Status with
        {
            State = _ownedProcess is null ? BackendLifecycleState.Unavailable : BackendLifecycleState.Failed,
            Message = "Studio backend is not responding.",
            Detail = $"No valid health response was received from {CurrentBackendUri}.",
            FailureCode = "BACKEND_UNAVAILABLE",
            LastHealthCheck = DateTimeOffset.UtcNow
        });
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        _lifetimeCancellation.Cancel();
        await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_ownedProcess is null)
            {
                Publish(Status with
                {
                    State = BackendLifecycleState.Stopped,
                    Message = "Studio client stopped. The attached or external backend was left running."
                });
                return;
            }

            _stopping = true;
            Publish(Status with { State = BackendLifecycleState.Stopping, Message = "Stopping the managed Studio backend." });
            await StopOwnedProcessAsync(cancellationToken).ConfigureAwait(false);
            Publish(Status with
            {
                State = BackendLifecycleState.Stopped,
                Message = "Managed Studio backend stopped.",
                OwnedProcessId = null
            });
        }
        finally
        {
            _stopping = false;
            _lifecycleGate.Release();
        }
    }

    private async Task<BackendStatus> ConnectExternalAsync(CancellationToken cancellationToken)
    {
        Publish(Status with
        {
            State = BackendLifecycleState.CheckingExisting,
            Mode = BackendMode.External,
            CurrentBackendUri = _configuration.BackendUri,
            Message = $"Checking external backend {_configuration.BackendUri}."
        });

        var healthy = await IsHealthyAsync(_configuration.BackendUri, cancellationToken).ConfigureAwait(false);
        return healthy
            ? Publish(Status with
            {
                State = BackendLifecycleState.Ready,
                Mode = BackendMode.External,
                Message = "Connected to the external Studio backend.",
                LastHealthCheck = DateTimeOffset.UtcNow
            })
            : Publish(Status with
            {
                State = BackendLifecycleState.Unavailable,
                Mode = BackendMode.External,
                Message = "The configured external backend is unavailable.",
                Detail = $"Check the backend URL and network access: {_configuration.BackendUri}",
                FailureCode = "EXTERNAL_BACKEND_UNAVAILABLE",
                LastHealthCheck = DateTimeOffset.UtcNow
            });
    }

    private async Task<BackendStatus> StartPackagedAsync(string backendDirectory, CancellationToken cancellationToken)
    {
        var totalDeadline = DateTimeOffset.UtcNow + _configuration.PackagedReadyTimeout;
        Exception? lastError = null;

        for (var attempt = 1; attempt <= 3; attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var port = _configuration.Port;
            if (attempt > 1 || await IsPortOccupiedAsync(_configuration.Host, port, cancellationToken).ConfigureAwait(false))
            {
                port = GetAvailablePort(_configuration.Host);
            }

            var uri = BackendConfiguration.ManagedBackendUri(_configuration.Host, port);
            var spec = _specFactory.CreatePackagedSpec(backendDirectory, _configuration.Host, port);
            var remaining = totalDeadline - DateTimeOffset.UtcNow;
            if (remaining <= TimeSpan.Zero)
            {
                break;
            }

            var attemptTimeout = remaining < TimeSpan.FromSeconds(40) ? remaining : TimeSpan.FromSeconds(40);
            try
            {
                var result = await StartManagedAsync(spec, uri, attemptTimeout, cancellationToken).ConfigureAwait(false);
                if (result.IsReady)
                {
                    return result;
                }

                lastError = new InvalidOperationException(result.Detail ?? result.Message);
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception) when (attempt < 3)
            {
                lastError = exception;
            }

            await StopOwnedProcessAsync(CancellationToken.None).ConfigureAwait(false);
        }

        return PublishFailure(
            "PACKAGED_BACKEND_START_FAILED",
            "The packaged Studio backend did not become ready after three safe attempts.",
            lastError?.Message ?? "Review the backend logs for the current launch.");
    }

    private async Task<BackendStatus> StartManagedAsync(
        BackendLaunchSpec spec,
        Uri endpoint,
        TimeSpan readinessTimeout,
        CancellationToken cancellationToken)
    {
        await StopOwnedProcessAsync(CancellationToken.None).ConfigureAwait(false);
        Directory.CreateDirectory(Path.GetDirectoryName(spec.StdoutLogPath)!);
        File.WriteAllText(spec.StdoutLogPath, string.Empty);
        File.WriteAllText(spec.StderrLogPath, string.Empty);

        Publish(Status with
        {
            State = BackendLifecycleState.Starting,
            Mode = spec.Mode,
            CurrentBackendUri = endpoint,
            Message = spec.Mode == BackendMode.ManagedSource
                ? "Starting the source Studio backend."
                : "Starting the packaged Studio backend.",
            AcceleratorProfile = spec.AcceleratorProfile,
            StdoutLogPath = spec.StdoutLogPath,
            StderrLogPath = spec.StderrLogPath,
            FailureCode = null,
            Detail = null
        });

        var process = new Process
        {
            StartInfo = spec.CreateProcessStartInfo(),
            EnableRaisingEvents = true
        };

        if (!process.Start())
        {
            process.Dispose();
            return PublishFailure("PROCESS_START_FAILED", "The backend process did not start.", spec.FileName);
        }

        WindowsProcessJob? job = null;
        if (OperatingSystem.IsWindows())
        {
            try
            {
                job = WindowsProcessJob.CreateKillOnClose();
                job.Assign(process);
            }
            catch (Exception exception)
            {
                job?.Dispose();
                try
                {
                    if (!process.HasExited)
                    {
                        process.Kill(entireProcessTree: true);
                    }
                }
                catch
                {
                }

                process.Dispose();
                return PublishFailure(
                    "PROCESS_CONTAINMENT_FAILED",
                    "The managed backend could not be started safely.",
                    exception.Message);
            }
        }

        _ownedJob = job;
        _ownedProcess = process;
        _logCancellation = new CancellationTokenSource();
        lock (_logLock)
        {
            _logTasks.Add(PumpLogAsync(process.StandardOutput, spec.StdoutLogPath, _logCancellation.Token));
            _logTasks.Add(PumpLogAsync(process.StandardError, spec.StderrLogPath, _logCancellation.Token));
        }
        process.Exited += (_, _) => _ = HandleOwnedProcessExitAsync(process);

        Publish(Status with
        {
            State = BackendLifecycleState.WaitingForHealth,
            Message = "Waiting for the Studio backend health check.",
            OwnedProcessId = process.Id,
            StartedAt = DateTimeOffset.UtcNow
        });

        var deadline = DateTimeOffset.UtcNow + readinessTimeout;
        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (process.HasExited)
            {
                break;
            }

            if (await IsHealthyAsync(endpoint, cancellationToken).ConfigureAwait(false) &&
                (job is null || job.OwnsTcpListener(endpoint.Port)))
            {
                return Publish(Status with
                {
                    State = BackendLifecycleState.Ready,
                    Message = "Studio backend is ready.",
                    LastHealthCheck = DateTimeOffset.UtcNow,
                    FailureCode = null,
                    Detail = null
                });
            }

            await Task.Delay(ProbeInterval, cancellationToken).ConfigureAwait(false);
        }

        return Publish(Status with
        {
            State = BackendLifecycleState.Failed,
            Message = "The managed backend did not become ready.",
            Detail = BuildFailureDetail(spec),
            FailureCode = process.HasExited ? "BACKEND_EXITED" : "BACKEND_HEALTH_TIMEOUT",
            LastHealthCheck = DateTimeOffset.UtcNow
        });
    }

    private async Task<bool> IsHealthyAsync(Uri endpoint, CancellationToken cancellationToken)
    {
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(ProbeTimeout);
            using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(endpoint, "health"));
            using var response = await _probeClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token)
                .ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return false;
            }

            await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token).ConfigureAwait(false);
            var health = await JsonSerializer.DeserializeAsync<HealthResponse>(stream, StudioJson.Options, timeout.Token)
                .ConfigureAwait(false);
            return health?.Ok == true;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return false;
        }
        catch
        {
            return false;
        }
    }

    private static async Task<bool> IsPortOccupiedAsync(string host, int port, CancellationToken cancellationToken)
    {
        try
        {
            using var client = new TcpClient();
            await client.ConnectAsync(host, port, cancellationToken).AsTask().WaitAsync(TimeSpan.FromMilliseconds(500), cancellationToken)
                .ConfigureAwait(false);
            return true;
        }
        catch
        {
            cancellationToken.ThrowIfCancellationRequested();
            return false;
        }
    }

    private static int GetAvailablePort(string host)
    {
        var bindAddress = host.Trim() switch
        {
            "::" => IPAddress.IPv6Any,
            "::1" => IPAddress.IPv6Loopback,
            "0.0.0.0" => IPAddress.Any,
            "127.0.0.1" or "localhost" => IPAddress.Loopback,
            _ when IPAddress.TryParse(host, out var parsed) => parsed,
            _ => IPAddress.Loopback
        };
        var listener = new TcpListener(bindAddress, 0);
        listener.Start();
        try
        {
            return ((IPEndPoint)listener.LocalEndpoint).Port;
        }
        finally
        {
            listener.Stop();
        }
    }

    private async Task StopOwnedProcessAsync(CancellationToken cancellationToken)
    {
        var process = Interlocked.Exchange(ref _ownedProcess, null);
        var job = Interlocked.Exchange(ref _ownedJob, null);
        if (process is null)
        {
            job?.Dispose();
            return;
        }

        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(cancellationToken).WaitAsync(TimeSpan.FromSeconds(10), cancellationToken)
                    .ConfigureAwait(false);
            }
        }
        catch (InvalidOperationException)
        {
        }
        catch (TimeoutException)
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        finally
        {
            _logCancellation?.Cancel();
            _logCancellation?.Dispose();
            _logCancellation = null;
            await DrainLogTasksAsync().ConfigureAwait(false);
            process.Dispose();
            job?.Dispose();
        }
    }

    private async Task HandleOwnedProcessExitAsync(Process process)
    {
        try
        {
            if (_stopping || !ReferenceEquals(Interlocked.CompareExchange(ref _ownedProcess, null, process), process))
            {
                return;
            }

            var wasReady = Status.IsReady;
            var exitCode = SafeExitCode(process);
            Interlocked.Exchange(ref _ownedJob, null)?.Dispose();
            _logCancellation?.Cancel();
            _logCancellation?.Dispose();
            _logCancellation = null;
            await DrainLogTasksAsync().ConfigureAwait(false);
            Publish(Status with
            {
                State = BackendLifecycleState.Failed,
                Message = wasReady
                    ? "The managed backend stopped unexpectedly."
                    : "The managed backend exited before becoming ready.",
                Detail = $"Exit code: {exitCode}",
                FailureCode = "BACKEND_EXITED",
                OwnedProcessId = null,
                LastHealthCheck = DateTimeOffset.UtcNow
            });
            process.Dispose();
        }
        catch
        {
            // Process-exit cleanup must not surface an unobserved exception on the UI thread.
        }
    }

    private async Task DrainLogTasksAsync()
    {
        Task[] tasks;
        lock (_logLock)
        {
            tasks = _logTasks.ToArray();
            _logTasks.Clear();
        }

        if (tasks.Length == 0)
        {
            return;
        }

        try
        {
            await Task.WhenAll(tasks).WaitAsync(TimeSpan.FromSeconds(2)).ConfigureAwait(false);
        }
        catch
        {
            // Log pumping is best effort; process lifecycle remains authoritative.
        }
    }

    private static async Task PumpLogAsync(StreamReader reader, string path, CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite, 4096, useAsync: true);
            await using var writer = new StreamWriter(stream) { AutoFlush = true };
            while (!cancellationToken.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is null)
                {
                    break;
                }

                await writer.WriteLineAsync(line.AsMemory(), cancellationToken).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (ObjectDisposedException)
        {
        }
    }

    private string BuildFailureDetail(BackendLaunchSpec spec)
    {
        var stderr = ReadTail(spec.StderrLogPath, 40);
        var stdout = ReadTail(spec.StdoutLogPath, 40);
        var tail = string.Join(Environment.NewLine, stderr.Concat(stdout).TakeLast(40));
        return string.IsNullOrWhiteSpace(tail)
            ? $"No health response was received from {Status.CurrentBackendUri}. Review {spec.StderrLogPath}."
            : tail;
    }

    private static IReadOnlyList<string> ReadTail(string path, int count)
    {
        try
        {
            return File.ReadLines(path).Where(line => !string.IsNullOrWhiteSpace(line)).TakeLast(count).ToArray();
        }
        catch
        {
            return [];
        }
    }

    private BackendStatus PublishFailure(string code, string message, string detail)
    {
        return Publish(Status with
        {
            State = BackendLifecycleState.Failed,
            Message = message,
            Detail = detail,
            FailureCode = code,
            LastHealthCheck = DateTimeOffset.UtcNow
        });
    }

    private BackendStatus Publish(BackendStatus status)
    {
        lock (_statusLock)
        {
            _status = status;
        }

        StatusChanged?.Invoke(this, status);
        return status;
    }

    private static int? SafeExitCode(Process process)
    {
        try
        {
            return process.HasExited ? process.ExitCode : null;
        }
        catch
        {
            return null;
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync(CancellationToken.None).ConfigureAwait(false);
        _probeClient.Dispose();
        _lifetimeCancellation.Dispose();
        _lifecycleGate.Dispose();
    }
}
