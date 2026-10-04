using System.Collections.Immutable;
using System.Diagnostics;
using System.Text.Json;

namespace EdmgStudio.Core.Audio;

public interface IJuceAudioEngineHostConnection : IAsyncDisposable
{
  event EventHandler<JuceProtocolEnvelope>? MessageReceived;
  event EventHandler<Exception>? ProtocolFailed;
  event EventHandler<int?>? Exited;

  Task<JuceHandshakeResponse> StartAsync(JuceHandshakeRequest request, CancellationToken cancellationToken = default);
  Task SendAsync(JuceProtocolEnvelope envelope, CancellationToken cancellationToken = default);
  Task StopAsync(CancellationToken cancellationToken = default);
}

public sealed class JuceAudioEngineClient : IAsyncDisposable
{
  private readonly Func<IJuceAudioEngineHostConnection> _connectionFactory;
  private readonly string _clientBuildIdentity;
  private readonly int _maximumRestarts;
  private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
  private readonly object _statusGate = new();
  private readonly object _pendingGate = new();
  private readonly Dictionary<string, TaskCompletionSource<JuceProtocolEnvelope>> _pendingRequests = new(StringComparer.Ordinal);
  private IJuceAudioEngineHostConnection? _connection;
  private JuceAudioEngineStatus _status;
  private long _nextCommandSequence;
  private long _lastReceivedSequence;
  private bool _stopping;
  private bool _disposed;

  public JuceAudioEngineClient(
      Func<IJuceAudioEngineHostConnection> connectionFactory,
      string clientBuildIdentity,
      int maximumRestarts = 1)
  {
    ArgumentNullException.ThrowIfNull(connectionFactory);
    ArgumentException.ThrowIfNullOrWhiteSpace(clientBuildIdentity);
    ArgumentOutOfRangeException.ThrowIfNegative(maximumRestarts);
    _connectionFactory = connectionFactory;
    _clientBuildIdentity = clientBuildIdentity.Trim();
    _maximumRestarts = maximumRestarts;
    _status = NewStatus(JuceAudioEngineLifecycleState.Stopped, "JUCE audio engine is stopped.");
  }

  public event EventHandler<JuceAudioEngineStatus>? StatusChanged;
  public event EventHandler<JuceProtocolEnvelope>? MessageReceived;

  public JuceAudioEngineStatus Status
  {
    get
    {
      lock (_statusGate)
      {
        return _status;
      }
    }
  }

  public async Task<JuceAudioEngineStatus> StartAsync(CancellationToken cancellationToken = default)
  {
    await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
    try
    {
      ThrowIfDisposed();
      if (Status.State == JuceAudioEngineLifecycleState.ReadyWithoutDevice)
      {
        return Status;
      }

      _stopping = false;
      await StopConnectionAsync(cancellationToken).ConfigureAwait(false);
      Publish(NewStatus(JuceAudioEngineLifecycleState.Starting, "Starting the JUCE audio-engine host.", restartCount: Status.RestartCount));
      return await StartConnectionAsync(cancellationToken).ConfigureAwait(false);
    }
    catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
    {
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      Publish(NewStatus(JuceAudioEngineLifecycleState.Stopped, "JUCE audio-engine startup was canceled.", restartCount: Status.RestartCount));
      throw;
    }
    catch (FileNotFoundException exception)
    {
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      return Publish(NewStatus(JuceAudioEngineLifecycleState.Unavailable, exception.Message,
          failureCode: "JUCE_HOST_UNAVAILABLE", restartCount: Status.RestartCount));
    }
    catch (Exception exception)
    {
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      return Publish(NewStatus(JuceAudioEngineLifecycleState.Failed, exception.Message,
          failureCode: "JUCE_HOST_START_FAILED", restartCount: Status.RestartCount));
    }
    finally
    {
      _ = _lifecycleGate.Release();
    }
  }

  public async Task SendAsync(string kind, object payload, CancellationToken cancellationToken = default)
  {
    _ = await SendCoreAsync(kind, payload, correlationId: null, cancellationToken).ConfigureAwait(false);
  }

  public async Task<TResponse> RequestAsync<TResponse>(
      string kind,
      object payload,
      string expectedResponseKind,
      TimeSpan? timeout = null,
      CancellationToken cancellationToken = default)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(expectedResponseKind);
    string correlationId = Guid.NewGuid().ToString("N");
    TaskCompletionSource<JuceProtocolEnvelope> completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    lock (_pendingGate)
    {
      _pendingRequests.Add(correlationId, completion);
    }

    try
    {
      _ = await SendCoreAsync(kind, payload, correlationId, cancellationToken).ConfigureAwait(false);
      using CancellationTokenSource requestTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
      requestTimeout.CancelAfter(timeout ?? TimeSpan.FromSeconds(5));
      JuceProtocolEnvelope response = await completion.Task.WaitAsync(requestTimeout.Token).ConfigureAwait(false);
      if (string.Equals(response.Kind, JuceAudioEngineProtocol.ErrorEvent, StringComparison.Ordinal))
      {
        JuceProtocolError error = JuceAudioEngineProtocol.ParsePayload<JuceProtocolError>(response);
        throw new InvalidOperationException($"{error.Code}: {error.Message}");
      }
      if (!string.Equals(response.Kind, expectedResponseKind, StringComparison.Ordinal))
      {
        throw new InvalidDataException($"JUCE host returned '{response.Kind}' instead of '{expectedResponseKind}'.");
      }
      return JuceAudioEngineProtocol.ParsePayload<TResponse>(response);
    }
    finally
    {
      lock (_pendingGate)
      {
        _pendingRequests.Remove(correlationId);
      }
    }
  }

  private async Task<JuceProtocolEnvelope> SendCoreAsync(
      string kind,
      object payload,
      string? correlationId,
      CancellationToken cancellationToken)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(kind);
    ArgumentNullException.ThrowIfNull(payload);
    IJuceAudioEngineHostConnection connection = _connection
        ?? throw new InvalidOperationException("The JUCE audio-engine host is not connected.");
    if (Status.State != JuceAudioEngineLifecycleState.ReadyWithoutDevice)
    {
      throw new InvalidOperationException("The JUCE audio-engine host is not ready for commands.");
    }

    JuceProtocolEnvelope envelope = JuceAudioEngineProtocol.CreateEnvelope(
        Interlocked.Increment(ref _nextCommandSequence), correlationId ?? Guid.NewGuid().ToString("N"), kind, payload);
    await connection.SendAsync(envelope, cancellationToken).ConfigureAwait(false);
    return envelope;
  }

  public async Task StopAsync(CancellationToken cancellationToken = default)
  {
    await _lifecycleGate.WaitAsync(cancellationToken).ConfigureAwait(false);
    try
    {
      if (_disposed || Status.State == JuceAudioEngineLifecycleState.Stopped)
      {
        return;
      }

      _stopping = true;
      Publish(NewStatus(JuceAudioEngineLifecycleState.ShuttingDown, "Stopping the JUCE audio-engine host.", restartCount: Status.RestartCount));
      await StopConnectionAsync(cancellationToken).ConfigureAwait(false);
      Publish(NewStatus(JuceAudioEngineLifecycleState.Stopped, "JUCE audio engine is stopped.", restartCount: Status.RestartCount));
    }
    finally
    {
      _stopping = false;
      _ = _lifecycleGate.Release();
    }
  }

  private async Task<JuceAudioEngineStatus> StartConnectionAsync(CancellationToken cancellationToken)
  {
    IJuceAudioEngineHostConnection connection = _connectionFactory();
    _connection = connection;
    Interlocked.Exchange(ref _lastReceivedSequence, 0);
    connection.MessageReceived += OnMessageReceived;
    connection.ProtocolFailed += OnProtocolFailed;
    connection.Exited += OnExited;

    string token = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(32));
    JuceHandshakeResponse response = await connection.StartAsync(
        new JuceHandshakeRequest(JuceAudioEngineProtocol.Version, JuceAudioEngineProtocol.Version, _clientBuildIdentity, token),
        cancellationToken).ConfigureAwait(false);
    JuceAudioEngineProtocol.ValidateHandshakeResponse(response);
    string expectedArchitecture = Environment.Is64BitProcess ? "x64" : "x86";
    bool hasRequiredFeatures = response.FeatureFlags.Contains(JuceAudioEngineProtocol.LifecycleFeature, StringComparer.Ordinal);
    if (response.ProtocolVersion != JuceAudioEngineProtocol.Version || !response.Compatible ||
        !string.Equals(response.Architecture, expectedArchitecture, StringComparison.Ordinal) ||
        !hasRequiredFeatures)
    {
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      return Publish(NewStatus(
          JuceAudioEngineLifecycleState.Incompatible,
          response.Diagnostic ?? $"JUCE host protocol, architecture, or required features are incompatible. Expected protocol {JuceAudioEngineProtocol.Version} on {expectedArchitecture} with lifecycle support.",
          response.HostBuildIdentity,
          "JUCE_PROTOCOL_INCOMPATIBLE",
          restartCount: Status.RestartCount));
    }

    if (!string.Equals(response.EngineState, "ready_without_device", StringComparison.Ordinal))
    {
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      return Publish(NewStatus(
          JuceAudioEngineLifecycleState.Failed,
          "JUCE host did not enter the required no-device ready state.",
          response.HostBuildIdentity,
          "JUCE_INVALID_HOST_STATE",
          restartCount: Status.RestartCount));
    }

    return Publish(NewStatus(
        JuceAudioEngineLifecycleState.ReadyWithoutDevice,
        "JUCE host is compatible and ready without an audio device.",
        response.HostBuildIdentity,
        restartCount: Status.RestartCount));
  }

  private void OnMessageReceived(object? sender, JuceProtocolEnvelope envelope)
  {
    try
    {
      JuceAudioEngineProtocol.ValidateEnvelope(envelope);
    }
    catch (InvalidDataException exception)
    {
      Publish(Status with { State = JuceAudioEngineLifecycleState.Failed, Message = exception.Message, FailureCode = "JUCE_PROTOCOL_ERROR", ChangedAt = DateTimeOffset.UtcNow });
      return;
    }

    while (true)
    {
      long previous = Interlocked.Read(ref _lastReceivedSequence);
      if (envelope.Sequence <= previous)
      {
        Publish(current => current with
        {
          DroppedStaleMessages = current.DroppedStaleMessages + 1,
          ChangedAt = DateTimeOffset.UtcNow
        });
        return;
      }

      if (Interlocked.CompareExchange(ref _lastReceivedSequence, envelope.Sequence, previous) == previous)
      {
        break;
      }
    }

    TaskCompletionSource<JuceProtocolEnvelope>? completion;
    lock (_pendingGate)
    {
      _pendingRequests.TryGetValue(envelope.CorrelationId, out completion);
    }
    if (completion is not null)
    {
      _ = completion.TrySetResult(envelope);
      return;
    }

    MessageReceived?.Invoke(this, envelope);
  }

  private void OnProtocolFailed(object? sender, Exception exception)
  {
    if (_stopping || _disposed)
    {
      return;
    }

    Publish(current => current with
    {
      State = JuceAudioEngineLifecycleState.Failed,
      Message = exception.Message,
      FailureCode = "JUCE_PROTOCOL_ERROR",
      ChangedAt = DateTimeOffset.UtcNow
    });
  }

  private void OnExited(object? sender, int? exitCode)
  {
    if (_stopping || _disposed)
    {
      return;
    }

    _ = RecoverAfterExitAsync(exitCode);
  }

  private async Task RecoverAfterExitAsync(int? exitCode)
  {
    await _lifecycleGate.WaitAsync().ConfigureAwait(false);
    try
    {
      if (_stopping || _disposed)
      {
        return;
      }

      int restartCount = Status.RestartCount;
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      if (restartCount >= _maximumRestarts)
      {
        Publish(NewStatus(JuceAudioEngineLifecycleState.Failed,
            $"JUCE host exited unexpectedly{FormatExitCode(exitCode)}; restart limit reached.",
            failureCode: "JUCE_HOST_EXITED", restartCount: restartCount));
        return;
      }

      restartCount++;
      Publish(NewStatus(JuceAudioEngineLifecycleState.Restarting,
          $"JUCE host exited unexpectedly{FormatExitCode(exitCode)}; restarting.",
          restartCount: restartCount));
      await StartConnectionAsync(CancellationToken.None).ConfigureAwait(false);
    }
    catch (Exception exception)
    {
      await StopConnectionAsync(CancellationToken.None).ConfigureAwait(false);
      Publish(NewStatus(JuceAudioEngineLifecycleState.Failed, exception.Message,
          failureCode: "JUCE_HOST_RESTART_FAILED", restartCount: Status.RestartCount));
    }
    finally
    {
      _ = _lifecycleGate.Release();
    }
  }

  private async Task StopConnectionAsync(CancellationToken cancellationToken)
  {
    IJuceAudioEngineHostConnection? connection = _connection;
    _connection = null;
    lock (_pendingGate)
    {
      foreach (TaskCompletionSource<JuceProtocolEnvelope> completion in _pendingRequests.Values)
      {
        _ = completion.TrySetException(new IOException("The JUCE audio-engine connection closed before responding."));
      }
      _pendingRequests.Clear();
    }
    if (connection is null)
    {
      return;
    }

    connection.MessageReceived -= OnMessageReceived;
    connection.ProtocolFailed -= OnProtocolFailed;
    connection.Exited -= OnExited;
    try
    {
      await connection.StopAsync(cancellationToken).ConfigureAwait(false);
    }
    finally
    {
      await connection.DisposeAsync().ConfigureAwait(false);
    }
  }

  private JuceAudioEngineStatus Publish(JuceAudioEngineStatus status) => Publish(_ => status);

  private JuceAudioEngineStatus Publish(Func<JuceAudioEngineStatus, JuceAudioEngineStatus> update)
  {
    JuceAudioEngineStatus status;
    lock (_statusGate)
    {
      _status = update(_status);
      status = _status;
    }

    StatusChanged?.Invoke(this, status);
    return status;
  }

  private static JuceAudioEngineStatus NewStatus(
      JuceAudioEngineLifecycleState state,
      string message,
      string? buildIdentity = null,
      string? failureCode = null,
      bool fallbackSafe = true,
      int restartCount = 0)
  {
    return new(state, message, DateTimeOffset.UtcNow, buildIdentity, failureCode, fallbackSafe, restartCount);
  }

  private static string FormatExitCode(int? exitCode) => exitCode is null ? string.Empty : $" with code {exitCode}";

  private void ThrowIfDisposed()
  {
    ObjectDisposedException.ThrowIf(_disposed, this);
  }

  public async ValueTask DisposeAsync()
  {
    if (_disposed)
    {
      return;
    }

    await StopAsync().ConfigureAwait(false);
    _disposed = true;
    _lifecycleGate.Dispose();
  }
}

public sealed class ProcessJuceAudioEngineHostConnection : IJuceAudioEngineHostConnection
{
  private const int MaximumDiagnosticCharacters = 4096;
  private readonly string _hostPath;
  private readonly TimeSpan _timeout;
  private readonly SemaphoreSlim _writeGate = new(1, 1);
  private readonly object _diagnosticGate = new();
  private Process? _process;
  private CancellationTokenSource? _readerCancellation;
  private Task? _readerTask;
  private Task? _errorReaderTask;
  private string _diagnostic = string.Empty;
  private bool _stopping;

  public ProcessJuceAudioEngineHostConnection(string hostPath, TimeSpan? timeout = null)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(hostPath);
    _hostPath = Path.GetFullPath(hostPath);
    _timeout = timeout ?? TimeSpan.FromSeconds(5);
  }

  public event EventHandler<JuceProtocolEnvelope>? MessageReceived;
  public event EventHandler<Exception>? ProtocolFailed;
  public event EventHandler<int?>? Exited;

  public async Task<JuceHandshakeResponse> StartAsync(JuceHandshakeRequest request, CancellationToken cancellationToken = default)
  {
    if (!File.Exists(_hostPath))
    {
      throw new FileNotFoundException("JUCE audio-engine host was not found.", _hostPath);
    }

    ProcessStartInfo startInfo = new(_hostPath)
    {
      UseShellExecute = false,
      CreateNoWindow = true,
      RedirectStandardInput = true,
      RedirectStandardOutput = true,
      RedirectStandardError = true
    };
    startInfo.Environment["EDMG_JUCE_SESSION_TOKEN"] = request.SessionToken;
    _process = Process.Start(startInfo) ?? throw new InvalidOperationException("JUCE audio-engine host did not start.");
    _process.EnableRaisingEvents = true;
    _process.Exited += OnProcessExited;
    _errorReaderTask = ReadDiagnosticsAsync(_process);

    using CancellationTokenSource timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
    timeout.CancelAfter(_timeout);
    await WriteLineAsync(_process, JuceAudioEngineProtocol.Serialize(request), timeout.Token).ConfigureAwait(false);
    string? response = await _process.StandardOutput.ReadLineAsync(timeout.Token).ConfigureAwait(false);
    JuceHandshakeResponse handshake = JuceAudioEngineProtocol.Parse<JuceHandshakeResponse>(
        response ?? throw new InvalidDataException("JUCE host returned no handshake response."));

    _readerCancellation = new CancellationTokenSource();
    _readerTask = ReadEventsAsync(_process, _readerCancellation.Token);
    return handshake;
  }

  public async Task SendAsync(JuceProtocolEnvelope envelope, CancellationToken cancellationToken = default)
  {
    JuceAudioEngineProtocol.ValidateEnvelope(envelope);
    Process process = _process ?? throw new InvalidOperationException("JUCE host is not running.");
    await WriteLineAsync(process, JuceAudioEngineProtocol.Serialize(envelope), cancellationToken).ConfigureAwait(false);
  }

  private async Task WriteLineAsync(Process process, string message, CancellationToken cancellationToken)
  {
    await _writeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
    try
    {
      if (process.HasExited)
      {
        throw new InvalidOperationException($"JUCE host exited before the command was sent. {GetDiagnostic()}".Trim());
      }

      await process.StandardInput.WriteLineAsync(message.AsMemory(), cancellationToken).ConfigureAwait(false);
      await process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
    }
    finally
    {
      _ = _writeGate.Release();
    }
  }

  public async Task StopAsync(CancellationToken cancellationToken = default)
  {
    Process? process = _process;
    if (process is null)
    {
      return;
    }

    _stopping = true;
    _readerCancellation?.Cancel();
    if (!process.HasExited)
    {
      process.StandardInput.Close();
      using CancellationTokenSource timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
      timeout.CancelAfter(_timeout);
      try
      {
        await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
      }
      catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
      {
        process.Kill(entireProcessTree: true);
        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
      }
    }
  }

  private async Task ReadEventsAsync(Process process, CancellationToken cancellationToken)
  {
    try
    {
      while (!cancellationToken.IsCancellationRequested)
      {
        string? line = await process.StandardOutput.ReadLineAsync(cancellationToken).ConfigureAwait(false);
        if (line is null)
        {
          break;
        }
        MessageReceived?.Invoke(this, JuceAudioEngineProtocol.Parse<JuceProtocolEnvelope>(line));
      }
    }
    catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
    {
    }
    catch (Exception exception) when (exception is InvalidDataException or JsonException)
    {
      ProtocolFailed?.Invoke(this, exception);
    }
  }

  private async Task ReadDiagnosticsAsync(Process process)
  {
    while (await process.StandardError.ReadLineAsync().ConfigureAwait(false) is { } line)
    {
      string sanitized = line.Replace(Environment.NewLine, " ", StringComparison.Ordinal).Trim();
      if (sanitized.Length == 0)
      {
        continue;
      }

      lock (_diagnosticGate)
      {
        string combined = string.IsNullOrEmpty(_diagnostic) ? sanitized : $"{_diagnostic} | {sanitized}";
        _diagnostic = combined.Length <= MaximumDiagnosticCharacters
            ? combined
            : combined[^MaximumDiagnosticCharacters..];
      }
    }
  }

  private string GetDiagnostic()
  {
    lock (_diagnosticGate)
    {
      return _diagnostic;
    }
  }

  private void OnProcessExited(object? sender, EventArgs args)
  {
    if (!_stopping)
    {
      Exited?.Invoke(this, _process?.ExitCode);
    }
  }

  public async ValueTask DisposeAsync()
  {
    await StopAsync().ConfigureAwait(false);
    if (_readerTask is not null)
    {
      try { await _readerTask.ConfigureAwait(false); }
      catch (OperationCanceledException) { }
    }
    if (_errorReaderTask is not null)
    {
      await _errorReaderTask.ConfigureAwait(false);
    }
    _readerCancellation?.Dispose();
    _process?.Dispose();
    _writeGate.Dispose();
  }
}

public sealed class DeterministicJuceAudioEngineHost : IJuceAudioEngineHostConnection
{
  private readonly JuceHandshakeResponse _handshake;
  private bool _started;

  public DeterministicJuceAudioEngineHost(JuceHandshakeResponse? handshake = null)
  {
    _handshake = handshake ?? new JuceHandshakeResponse(
        JuceAudioEngineProtocol.Version,
        "deterministic-host",
        Environment.Is64BitProcess ? "x64" : "x86",
        ImmutableArray.Create(
            JuceAudioEngineProtocol.LifecycleFeature,
            JuceAudioEngineProtocol.DeviceEnumerationFeature,
            JuceAudioEngineProtocol.GeneratedToneTransportFeature),
        "ready_without_device",
        true);
  }

  public event EventHandler<JuceProtocolEnvelope>? MessageReceived;
  public event EventHandler<Exception>? ProtocolFailed;
  public event EventHandler<int?>? Exited;
  public List<JuceProtocolEnvelope> Commands { get; } = [];

  public Task<JuceHandshakeResponse> StartAsync(JuceHandshakeRequest request, CancellationToken cancellationToken = default)
  {
    cancellationToken.ThrowIfCancellationRequested();
    if (string.IsNullOrWhiteSpace(request.SessionToken))
    {
      throw new InvalidDataException("A session token is required.");
    }
    _started = true;
    return Task.FromResult(_handshake);
  }

  public Task SendAsync(JuceProtocolEnvelope envelope, CancellationToken cancellationToken = default)
  {
    cancellationToken.ThrowIfCancellationRequested();
    if (!_started)
    {
      throw new InvalidOperationException("Deterministic JUCE host is not started.");
    }
    JuceAudioEngineProtocol.ValidateEnvelope(envelope);
    Commands.Add(envelope);
    return Task.CompletedTask;
  }

  public Task StopAsync(CancellationToken cancellationToken = default)
  {
    cancellationToken.ThrowIfCancellationRequested();
    _started = false;
    return Task.CompletedTask;
  }

  public void Emit(JuceProtocolEnvelope envelope) => MessageReceived?.Invoke(this, envelope);

  public void FailProtocol(Exception exception) => ProtocolFailed?.Invoke(this, exception);

  public void Crash(int? exitCode = -1)
  {
    _started = false;
    Exited?.Invoke(this, exitCode);
  }

  public ValueTask DisposeAsync()
  {
    _started = false;
    return ValueTask.CompletedTask;
  }
}
