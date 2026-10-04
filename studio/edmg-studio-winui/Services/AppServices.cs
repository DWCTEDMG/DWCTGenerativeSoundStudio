using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Media;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.RemoteControl;
using EdmgStudio.Core.Runtime;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Graphics;
using System.Net;
using System.Text;
using System.Threading.Channels;

namespace EdmgStudio.WinUI.Services;

public sealed class AppServices : IAsyncDisposable
{
  private readonly object _previewSessionsSync = new();
  private readonly HashSet<PreviewRendererSession> _previewSessions = [];
  private readonly HashSet<VideoPlaybackSession> _videoPlaybackSessions = [];
  private readonly HttpClient _apiHttpClient;
  private bool _isDisposing;

  private AppServices(
      BackendConfiguration configuration,
      BackendSupervisor backendSupervisor,
      StudioApiClient apiClient,
      HttpClient apiHttpClient,
      StudioProjectMediaClient projectMediaClient,
      StudioJobsActivityService jobsActivity,
      StudioSessionService session,
      ITransportService transport,
      IAudioEngine audioEngine,
      JuceAudioEngineClient juceAudioEngine,
      AudioPreviewEngineSelection audioPreviewEngineSelection,
      StudioCommandDispatcher commands,
      StudioRemoteControlService remoteControl,
      WindowsMidiInputService midiInput,
      ILocalRuntimeOrchestrator localRuntime,
      IVst3HostSession vst3Host)
  {
    Configuration = configuration;
    BackendSupervisor = backendSupervisor;
    ApiClient = apiClient;
    _apiHttpClient = apiHttpClient;
    ProjectMediaClient = projectMediaClient;
    JobsActivity = jobsActivity;
    Session = session;
    Transport = transport;
    AudioEngine = audioEngine;
    JuceAudioEngine = juceAudioEngine;
    AudioPreviewEngineSelection = audioPreviewEngineSelection;
    Commands = commands;
    RemoteControl = remoteControl;
    MidiInput = midiInput;
    LocalRuntime = localRuntime;
    Vst3Host = vst3Host;
    Transport.StateChanged += OnTransportStateChanged;
  }

  public BackendConfiguration Configuration { get; private set; }
  public BackendSupervisor BackendSupervisor { get; }
  public StudioApiClient ApiClient { get; }
  public StudioProjectMediaClient ProjectMediaClient { get; }
  public StudioJobsActivityService JobsActivity { get; }
  public StudioSessionService Session { get; }
  public ITransportService Transport { get; }
  public IAudioEngine AudioEngine { get; }
  public JuceAudioEngineClient JuceAudioEngine { get; }
  public AudioPreviewEngineSelection AudioPreviewEngineSelection { get; }
  public StudioCommandDispatcher Commands { get; }
  public StudioRemoteControlService RemoteControl { get; }
  public WindowsMidiInputService MidiInput { get; }
  public ILocalRuntimeOrchestrator LocalRuntime { get; }
  public IVst3HostSession Vst3Host { get; }

  public async Task<BackendStatus> SwitchBackendAsync(
      RequestedBackendMode mode,
      Uri? externalBackendUri = null,
      CancellationToken cancellationToken = default)
  {
    if (mode == RequestedBackendMode.External)
    {
      if (externalBackendUri is null)
      {
        throw new ArgumentException("Remote backend URL is required.", nameof(externalBackendUri));
      }

      BackendSettingsStore.SaveExternalBackend(externalBackendUri);
    }
    else
    {
      BackendSettingsStore.ResetToManaged();
    }

    BackendConfiguration configuration = BackendConfiguration.Load(requirePackagedBackend: WindowsPackageIdentity.IsPackaged);
    WindowsBackendTokenProvider tokenProvider = new(new EnvironmentBackendTokenProvider());
    string? launchToken = await tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
    if (!string.IsNullOrWhiteSpace(launchToken))
    {
      Dictionary<string, string> managedEnvironment = new(configuration.ManagedEnvironment, StringComparer.OrdinalIgnoreCase)
      {
        ["EDMG_BACKEND_AUTH_TOKEN"] = launchToken
      };
      configuration = configuration with { ManagedEnvironment = managedEnvironment };
    }

    Configuration = configuration;
    return await BackendSupervisor.ApplyConfigurationAsync(configuration, cancellationToken).ConfigureAwait(false);
  }

  internal bool TryTrackPreviewSession(PreviewRendererSession session)
  {
    ArgumentNullException.ThrowIfNull(session);
    lock (_previewSessionsSync)
    {
      return !_isDisposing && _previewSessions.Add(session);
    }
  }

  internal void UntrackPreviewSession(PreviewRendererSession session)
  {
    lock (_previewSessionsSync)
    {
      _ = _previewSessions.Remove(session);
    }
  }

  internal bool TryTrackVideoPlaybackSession(VideoPlaybackSession session)
  {
    ArgumentNullException.ThrowIfNull(session);
    lock (_previewSessionsSync)
    {
      return !_isDisposing && _videoPlaybackSessions.Add(session);
    }
  }

  internal void UntrackVideoPlaybackSession(VideoPlaybackSession session)
  {
    lock (_previewSessionsSync)
    {
      _ = _videoPlaybackSessions.Remove(session);
    }
  }

  public static async Task<AppServices> CreateAsync(CancellationToken cancellationToken = default)
  {
    BackendConfiguration configuration = BackendConfiguration.Load(requirePackagedBackend: WindowsPackageIdentity.IsPackaged);
    WindowsBackendTokenProvider tokenProvider = new(new EnvironmentBackendTokenProvider());
    string? launchToken = await tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
    if (!string.IsNullOrWhiteSpace(launchToken))
    {
      Dictionary<string, string> managedEnvironment = new(configuration.ManagedEnvironment, StringComparer.OrdinalIgnoreCase)
      {
        ["EDMG_BACKEND_AUTH_TOKEN"] = launchToken
      };
      configuration = configuration with { ManagedEnvironment = managedEnvironment };
    }

    cancellationToken.ThrowIfCancellationRequested();
    BackendSupervisor supervisor = new(configuration);

    // Convert transport-level connection failures into a normal HTTP 503 response.
    // StudioApiClient already converts non-success HTTP responses into StudioApiException,
    // which the WinUI pages know how to display without letting an async event handler
    // crash the shell when the local backend is still starting or temporarily offline.
    HttpClient apiHttpClient = new(new BackendAvailabilityHandler())
    {
      Timeout = Timeout.InfiniteTimeSpan
    };
    StudioApiClient apiClient = new(supervisor, tokenProvider, apiHttpClient);
    StudioProjectMediaClient projectMediaClient = new(apiClient, new StudioApiSignedMediaUrlResolver(apiClient));
    StudioJobsActivityService jobsActivity = new(apiClient);

    TransportService transport = new();
    string vst3HostPath = Path.Combine(AppContext.BaseDirectory, "EdmgStudio.Vst3Host.exe");
    IVst3HostSession vst3Host = File.Exists(vst3HostPath)
        ? new NativeVst3HostSession(vst3HostPath)
        : new UnavailableVst3HostSession();
    WindowsAudioEngine audioEngine = new(vst3Host);
    string juceHostPath = Path.Combine(AppContext.BaseDirectory, "EdmgStudio.JuceAudioHost.exe");
    string clientBuildIdentity = $"edmg-studio-winui/{typeof(AppServices).Assembly.GetName().Version}";
    JuceAudioEngineClient juceAudioEngine = new(
        () => new ProcessJuceAudioEngineHostConnection(juceHostPath),
        clientBuildIdentity);
    AudioPreviewEngineSelection audioPreviewEngineSelection = new(
        new WindowsAudioPreviewEnginePreferenceStore(),
        () => File.Exists(juceHostPath));
    StudioCommandDispatcher commands = new();
    string mappingsPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "EDMG Studio", "remote-control.json");
    StudioRemoteControlService remoteControl = new(new StudioRemoteControlStore(mappingsPath));
    WindowsMidiInputService midiInput = new(commands, remoteControl);
    LocalRuntimeSettingsStore localRuntimeSettingsStore = new();
    LocalRuntimeSettings localRuntimeSettings = localRuntimeSettingsStore.Load();
    WslCommandRunner wslRunner = new(localRuntimeSettings.WslDistro);
    LocalRuntimeOrchestrator localRuntime = new(
            [
                new LlamaCppRuntime(wslRunner, localRuntimeSettings.LlamaExecutable),
                new TensorRtLlmRuntime(wslRunner, localRuntimeSettings.TensorRtExecutable)
            ],
            wslRunner,
            new GpuDiscoveryService(wslRunner),
            new RuntimeHealthService(),
            new RuntimeProfileResolver(),
            localRuntimeSettingsStore);
    return new AppServices(
        configuration,
        supervisor,
        apiClient,
        apiHttpClient,
        projectMediaClient,
        jobsActivity,
        new StudioSessionService(),
        transport,
        audioEngine,
        juceAudioEngine,
        audioPreviewEngineSelection,
        commands,
        remoteControl,
        midiInput,
        localRuntime,
        vst3Host);
  }

  public async ValueTask DisposeAsync()
  {
    List<Exception>? failures = null;
    PreviewRendererSession[] previewSessions;
    VideoPlaybackSession[] videoPlaybackSessions;
    lock (_previewSessionsSync)
    {
      if (_isDisposing)
      {
        return;
      }

      _isDisposing = true;
      videoPlaybackSessions = [.. _videoPlaybackSessions];
      _videoPlaybackSessions.Clear();
      previewSessions = [.. _previewSessions];
      _previewSessions.Clear();
    }

    foreach (VideoPlaybackSession session in videoPlaybackSessions)
    {
      try
      {
        await session.DisposeAsync();
      }
      catch (Exception exception)
      {
        (failures ??= []).Add(exception);
      }
    }

    foreach (PreviewRendererSession session in previewSessions)
    {
      try
      {
        await session.DisposeAsync();
      }
      catch (Exception exception)
      {
        (failures ??= []).Add(exception);
      }
    }

    Transport.StateChanged -= OnTransportStateChanged;
    try
    {
      await JuceAudioEngine.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      await Vst3Host.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      await LocalRuntime.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      await JobsActivity.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      await MidiInput.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      await AudioEngine.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      await BackendSupervisor.DisposeAsync();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      ProjectMediaClient.Dispose();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      ApiClient.Dispose();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    try
    {
      _apiHttpClient.Dispose();
    }
    catch (Exception exception)
    {
      (failures ??= []).Add(exception);
    }

    if (failures is not null)
    {
      throw new AggregateException("One or more application services failed to shut down cleanly.", failures);
    }
  }

  private void OnTransportStateChanged(object? sender, TransportState state)
  {
    if (AudioPreviewEngineSelection.SelectedEngine != AudioPreviewEngine.AudioGraph)
    {
      return;
    }
    ValueTask enqueue = AudioEngine.EnqueueTransportStateAsync(state);
    if (!enqueue.IsCompletedSuccessfully)
    {
      _ = ObserveTransportEnqueueAsync(enqueue);
    }
  }

  private static async Task ObserveTransportEnqueueAsync(ValueTask enqueue)
  {
    try
    {
      await enqueue.ConfigureAwait(false);
    }
    catch (ObjectDisposedException)
    {
    }
    catch (ChannelClosedException)
    {
    }
  }
}

[System.Diagnostics.DebuggerNonUserCode]
internal sealed class BackendAvailabilityHandler : DelegatingHandler
{
  public BackendAvailabilityHandler()
      : base(new SocketsHttpHandler())
  {
  }

  protected override async Task<HttpResponseMessage> SendAsync(
      HttpRequestMessage request,
      CancellationToken cancellationToken)
  {
    try
    {
      return await base.SendAsync(request, cancellationToken).ConfigureAwait(false);
    }
    catch (OperationCanceledException exception) when (!cancellationToken.IsCancellationRequested)
    {
      return CreateUnavailableResponse(request, exception);
    }
    catch (HttpRequestException exception) when (!cancellationToken.IsCancellationRequested)
    {
      return CreateUnavailableResponse(request, exception);
    }
  }

  private static HttpResponseMessage CreateUnavailableResponse(
      HttpRequestMessage request,
      Exception exception)
  {
    CrashLogger.Write(
        $"Studio API transport could not reach {request.RequestUri}; returning a nonfatal 503 response.",
        exception);

    const string body =
        "{\"error\":{\"code\":\"BACKEND_UNAVAILABLE\",\"message\":\"Studio backend is unavailable.\",\"hint\":\"Wait for the managed backend to finish starting, then retry.\"}}";

    return new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
    {
      RequestMessage = request,
      ReasonPhrase = "Studio backend unavailable",
      Content = new StringContent(body, Encoding.UTF8, "application/json")
    };
  }
}
