using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.RemoteControl;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.System;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage : Page
{
  private void NavigateSettings_Click(object sender, RoutedEventArgs e)
  {
    if (sender is Button { Tag: string destination })
    {
      App.Navigate(destination);
    }
  }
  private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
  private const string Vst3ScanRootsSettingKey = "Vst3.ScanRoots";
  private JsonObject? _renderProviderSettings;
  private bool _initializingAppearance;
  private bool _midiEventsSubscribed;
  private bool _juceEventsSubscribed;
  private bool _juceDeviceOpen;
  private bool _initializingAudioPreviewEngine;
  private long _juceProjectRevision;
  private string _hfWebhookId = "";

  public SettingsPage()
  {
    InitializeComponent();
    InitializeAudioPreviewEngine();
    var audioPreferences = WindowsAudioPreviewEnginePreferenceStore.ReadPreferences();
    JuceSampleRateComboBox.SelectedItem = audioPreferences.SampleRate;
    JuceBufferSizeComboBox.SelectedItem = audioPreferences.BufferFrames;
    InitializeAppearance();
    LoadBackendSettings();
    LoadLocalRuntimeSettings();
    Loaded += SettingsPage_Loaded;
    Unloaded += SettingsPage_Unloaded;
    LoadRemoteControlSettings();
    Vst3ScanRootsTextBox.Text = LoadVst3ScanRoots();
  }

  private async void SettingsPage_Loaded(object sender, RoutedEventArgs e)
  {
    SubscribeMidiEvents();
    SubscribeLocalRuntimeEvents();
    SubscribeJuceEvents();
    ApplyLocalRuntimeStatus(App.Services.LocalRuntime.CurrentStatus);
    ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
    await RefreshAsync();
    await RefreshRuntimeAsync();
    await RefreshExecutionPlaneAsync();
    await RunHuggingFaceActionAsync(this, async () => ApplyHuggingFaceSettings(await _apiClient.GetHuggingFaceServicesAsync()));
  }

  private void SettingsPage_Unloaded(object sender, RoutedEventArgs e)
  {
    UnsubscribeLocalRuntimeEvents();
    UnsubscribeJuceEvents();
    if (!_midiEventsSubscribed)
    {
      return;
    }

    App.Services.MidiInput.MessageLearned -= MidiInput_MessageLearned;
    App.Services.MidiInput.StatusChanged -= MidiInput_StatusChanged;
    _midiEventsSubscribed = false;
  }

  private void SubscribeMidiEvents()
  {
    if (_midiEventsSubscribed)
    {
      return;
    }

    App.Services.MidiInput.MessageLearned += MidiInput_MessageLearned;
    App.Services.MidiInput.StatusChanged += MidiInput_StatusChanged;
    _midiEventsSubscribed = true;
  }

  private void SubscribeJuceEvents()
  {
    if (_juceEventsSubscribed)
    {
      return;
    }

    App.Services.JuceAudioEngine.StatusChanged += JuceAudioEngine_StatusChanged;
    App.Services.JuceAudioEngine.MessageReceived += JuceAudioEngine_MessageReceived;
    _juceEventsSubscribed = true;
  }

  private void UnsubscribeJuceEvents()
  {
    if (!_juceEventsSubscribed)
    {
      return;
    }

    App.Services.JuceAudioEngine.StatusChanged -= JuceAudioEngine_StatusChanged;
    App.Services.JuceAudioEngine.MessageReceived -= JuceAudioEngine_MessageReceived;
    _juceEventsSubscribed = false;
  }

  private void JuceAudioEngine_StatusChanged(object? sender, JuceAudioEngineStatus status)
  {
    _ = DispatcherQueue.TryEnqueue(() => ApplyJuceStatus(status));
  }

  private void ApplyJuceStatus(JuceAudioEngineStatus status)
  {
    JuceLifecycleText.Text = $"{status.State}: {status.Message}";
    JuceIdentityText.Text = $"Protocol {JuceAudioEngineProtocol.Version} · Host {status.BuildIdentity ?? "not connected"} · Restarts {status.RestartCount} · Stale messages dropped {status.DroppedStaleMessages}";
    string device = _juceDeviceOpen
        ? $"open at {JuceSampleRateComboBox.SelectedItem ?? 48_000} Hz / {JuceBufferSizeComboBox.SelectedItem ?? 512} frames"
        : "closed";
    JuceRuntimeDiagnosticsText.Text = $"Capability: experimental prepared-Timeline host · Device: {device} · Graph latency: unavailable · Callback load: unavailable · Xruns: unavailable";
    bool transition = status.State is JuceAudioEngineLifecycleState.Starting or JuceAudioEngineLifecycleState.Restarting or JuceAudioEngineLifecycleState.ShuttingDown;
    bool ready = status.State == JuceAudioEngineLifecycleState.ReadyWithoutDevice;
    StartJuceButton.IsEnabled = !transition && !ready;
    RestartJuceButton.IsEnabled = !transition && ready;
    StopJuceButton.IsEnabled = !transition && status.State != JuceAudioEngineLifecycleState.Stopped;
    RefreshJuceDevicesButton.IsEnabled = !transition && ready;
    OpenJuceDeviceButton.IsEnabled = !transition && ready && JuceDeviceComboBox.SelectedItem is JuceAudioDeviceDescriptor;
    CloseJuceDeviceButton.IsEnabled = !transition && ready && _juceDeviceOpen;
    PlayJuceToneButton.IsEnabled = !transition && ready && _juceDeviceOpen;
    StopJuceToneButton.IsEnabled = !transition && ready && _juceDeviceOpen;
    if (!ready)
    {
      _juceDeviceOpen = false;
    }
  }

  private void JuceAudioEngine_MessageReceived(object? sender, JuceProtocolEnvelope envelope)
  {
    _ = DispatcherQueue.TryEnqueue(() =>
        JuceDeviceStatusText.Text = $"Host event {envelope.Kind} received at sequence {envelope.Sequence}.");
  }

  private void InitializeAudioPreviewEngine()
  {
    _initializingAudioPreviewEngine = true;
    try
    {
      SelectAudioPreviewEngine(App.Services.AudioPreviewEngineSelection.SelectedEngine);
      ApplyAudioPreviewEngineStatus("Selection is stored locally and does not modify project data.");
    }
    finally
    {
      _initializingAudioPreviewEngine = false;
    }
  }

  private void AudioPreviewEngineComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
  {
    if (_initializingAudioPreviewEngine ||
        AudioPreviewEngineComboBox.SelectedItem is not ComboBoxItem item ||
        !Enum.TryParse(item.Tag?.ToString(), ignoreCase: true, out AudioPreviewEngine requested))
    {
      return;
    }

    ApplyAudioPreviewEngineSelection(requested);
  }

  private void ReturnToAudioGraphButton_Click(object sender, RoutedEventArgs e)
  {
    ApplyAudioPreviewEngineSelection(AudioPreviewEngine.AudioGraph);
  }

  private void ApplyAudioPreviewEngineSelection(AudioPreviewEngine requested)
  {
    AudioPreviewEngineSelectionResult result = App.Services.AudioPreviewEngineSelection.Select(
        requested, App.Services.Transport.State.Mode);
    _initializingAudioPreviewEngine = true;
    try
    {
      SelectAudioPreviewEngine(result.SelectedEngine);
    }
    finally
    {
      _initializingAudioPreviewEngine = false;
    }
    ApplyAudioPreviewEngineStatus(result.Message);
  }

  private void SelectAudioPreviewEngine(AudioPreviewEngine engine)
  {
    AudioPreviewEngineComboBox.SelectedItem = AudioPreviewEngineComboBox.Items.OfType<ComboBoxItem>()
        .First(item => string.Equals(item.Tag?.ToString(), engine.ToString(), StringComparison.OrdinalIgnoreCase));
  }

  private void ApplyAudioPreviewEngineStatus(string detail)
  {
    AudioPreviewEngine engine = App.Services.AudioPreviewEngineSelection.SelectedEngine;
    string role = engine == AudioPreviewEngine.AudioGraph
        ? "AudioGraph is selected for application Timeline playback."
        : "JUCE is selected for Timeline output. The host and saved device are configured when Timeline prepares playback.";
    AudioPreviewEngineStatusText.Text = $"{role} {detail}";
    ReturnToAudioGraphButton.IsEnabled = engine != AudioPreviewEngine.AudioGraph &&
        App.Services.Transport.State.Mode == TransportMode.Stopped;
  }

  private async void StartJuceButton_Click(object sender, RoutedEventArgs e)
  {
    ApplyJuceStatus(await App.Services.JuceAudioEngine.StartAsync());
  }

  private async void RestartJuceButton_Click(object sender, RoutedEventArgs e)
  {
    await App.Services.JuceAudioEngine.StopAsync();
    ApplyJuceStatus(await App.Services.JuceAudioEngine.StartAsync());
  }

  private async void StopJuceButton_Click(object sender, RoutedEventArgs e)
  {
    await App.Services.JuceAudioEngine.StopAsync();
    ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
  }

  private async void RefreshJuceDevicesButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      JuceAudioDeviceDescriptor[] devices = await App.Services.JuceAudioEngine.RequestAsync<JuceAudioDeviceDescriptor[]>(
          JuceAudioEngineProtocol.ListDevicesCommand, new { }, JuceAudioEngineProtocol.DeviceListEvent);
      JuceDeviceComboBox.ItemsSource = devices;
      JuceDeviceComboBox.SelectedItem = devices.FirstOrDefault(device => device.Id == WindowsAudioPreviewEnginePreferenceStore.ReadPreferences().DeviceId)
          ?? devices.FirstOrDefault(device => device.IsDefaultOutput) ?? devices.FirstOrDefault();
      JuceDeviceStatusText.Text = devices.Length == 0
          ? "The JUCE host reported no output devices."
          : $"Discovered {devices.Length} output device(s); none was opened automatically.";
      ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
    }
    catch (Exception exception) when (exception is InvalidOperationException or InvalidDataException or OperationCanceledException)
    {
      JuceDeviceStatusText.Text = $"Device discovery failed: {exception.Message}";
    }
  }

  private void JuceDeviceComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
  {
    if (OpenJuceDeviceButton is not null)
      ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
  }

  private void SaveJuceSettingsButton_Click(object sender, RoutedEventArgs e)
  {
    if (App.Services.Transport.State.Mode != TransportMode.Stopped)
    {
      JuceDeviceStatusText.Text = "Stop playback or recording before saving output settings.";
      return;
    }
    try
    {
      var saved = WindowsAudioPreviewEnginePreferenceStore.ReadPreferences();
      WindowsAudioPreviewEnginePreferenceStore.WritePreferences(saved with
      {
        Engine = App.Services.AudioPreviewEngineSelection.SelectedEngine,
        DeviceId = (JuceDeviceComboBox.SelectedItem as JuceAudioDeviceDescriptor)?.Id ?? saved.DeviceId,
        SampleRate = JuceSampleRateComboBox.SelectedItem is int rate ? rate : 48000,
        BufferFrames = JuceBufferSizeComboBox.SelectedItem is int frames ? frames : 512
      });
      JuceDeviceStatusText.Text = "JUCE settings saved. Timeline uses the saved output and buffer on its next preparation; its sample rate follows the project.";
    }
    catch (Exception exception)
    {
      JuceDeviceStatusText.Text = $"Could not save JUCE settings: {exception.Message}";
    }
  }

  private async void OpenJuceDeviceButton_Click(object sender, RoutedEventArgs e)
  {
    if (JuceDeviceComboBox.SelectedItem is not JuceAudioDeviceDescriptor device)
    {
      JuceDeviceStatusText.Text = "Select an output device first.";
      return;
    }

    try
    {
      int sampleRate = JuceSampleRateComboBox.SelectedItem is int selectedRate ? selectedRate : 48_000;
      int bufferFrames = JuceBufferSizeComboBox.SelectedItem is int selectedBuffer ? selectedBuffer : 512;
      JuceAudioDeviceConfiguration configuration = new(device.Id, sampleRate, bufferFrames, 2, ExclusiveMode: false);
      JuceAudioDeviceConfigurationResult result = await App.Services.JuceAudioEngine.RequestAsync<JuceAudioDeviceConfigurationResult>(
          JuceAudioEngineProtocol.ConfigureDeviceCommand, configuration, JuceAudioEngineProtocol.DeviceConfiguredEvent);
      _juceDeviceOpen = result.Configured;
      JuceDeviceStatusText.Text = result.Configured
          ? $"Opened {device.Name} at {result.SampleRate} Hz / {result.BufferFrames} frames for generated-tone proof only."
          : $"Device open failed: {result.Diagnostic}";
      ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
    }
    catch (Exception exception) when (exception is InvalidOperationException or InvalidDataException or OperationCanceledException)
    {
      _juceDeviceOpen = false;
      JuceDeviceStatusText.Text = $"Device open failed: {exception.Message}";
      ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
    }
  }

  private async void CloseJuceDeviceButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      _ = await App.Services.JuceAudioEngine.RequestAsync<JuceAudioDeviceConfigurationResult>(
          JuceAudioEngineProtocol.CloseDeviceCommand, new { }, JuceAudioEngineProtocol.DeviceClosedEvent);
      _juceDeviceOpen = false;
      JuceDeviceStatusText.Text = "JUCE output device closed; AudioGraph remains unchanged.";
      ApplyJuceStatus(App.Services.JuceAudioEngine.Status);
    }
    catch (Exception exception) when (exception is InvalidOperationException or InvalidDataException or OperationCanceledException)
    {
      JuceDeviceStatusText.Text = $"Device close failed: {exception.Message}";
    }
  }

  private async void PlayJuceToneButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      int sampleRate = JuceSampleRateComboBox.SelectedItem is int selectedRate ? selectedRate : 48_000;
      long revision = Interlocked.Increment(ref _juceProjectRevision);
      _ = await App.Services.JuceAudioEngine.RequestAsync<JuceTransportPosition>(
          JuceAudioEngineProtocol.ConfigureTransportCommand,
          new JuceTransportConfiguration(revision, sampleRate, sampleRate * 2L),
          JuceAudioEngineProtocol.TransportConfiguredEvent);
      JuceTransportPosition position = await App.Services.JuceAudioEngine.RequestAsync<JuceTransportPosition>(
          JuceAudioEngineProtocol.TransportCommand, new JuceTransportCommand("play"),
          JuceAudioEngineProtocol.TransportPositionEvent);
      JuceDeviceStatusText.Text = $"Generated 440 Hz proof started at sample {position.PositionSamples}; this is not Timeline playback.";
    }
    catch (Exception exception) when (exception is InvalidOperationException or InvalidDataException or OperationCanceledException)
    {
      JuceDeviceStatusText.Text = $"Tone proof failed: {exception.Message}";
    }
  }

  private async void StopJuceToneButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      JuceTransportPosition position = await App.Services.JuceAudioEngine.RequestAsync<JuceTransportPosition>(
          JuceAudioEngineProtocol.TransportCommand, new JuceTransportCommand("stop"),
          JuceAudioEngineProtocol.TransportPositionEvent);
      JuceDeviceStatusText.Text = $"Generated-tone proof stopped at sample {position.PositionSamples}.";
    }
    catch (Exception exception) when (exception is InvalidOperationException or InvalidDataException or OperationCanceledException)
    {
      JuceDeviceStatusText.Text = $"Tone stop failed: {exception.Message}";
    }
  }

  private async void RefreshButton_Click(object sender, RoutedEventArgs e)
  {
    await RefreshAsync();
  }

  private async Task RefreshAsync()
  {
    SetBusy(true);
    try
    {
      Task<string?> renderTask = ProbeAndApplyAsync(
          "Render routing",
          () => _apiClient.GetRenderProvidersAsync(),
          ApplyRenderProviderSettings);
      Task<string?> transcriptionTask = ProbeAndApplyAsync(
          "Transcription",
          () => _apiClient.GetTranscriptionSettingsAsync(),
          ApplyTranscriptionSettings);
      Task<string?> secretsTask = ProbeAndApplyAsync(
          "Secrets",
          () => _apiClient.GetSecretStatusAsync(),
          value => SecretStatusText.Text = StudioPageHelpers.FormatJson(value));
      Task<string?> directorTask = ProbeAndApplyAsync(
          "AI Director",
          () => _apiClient.GetDirectorRuntimeSettingsAsync(),
          ApplyDirectorSettings);
      Task<(string Text, string? Error)> readinessTask =
          ProbeTextAsync("READINESS", () => _apiClient.GetSystemReadinessAsync());
      Task<(string Text, string? Error)> hardwareTask =
          ProbeTextAsync("HARDWARE", () => _apiClient.GetHardwareAsync());
      Task<(string Text, string? Error)> metricsTask =
          ProbeTextAsync("METRICS", () => _apiClient.GetBaselineMetricsAsync());
      Task<(string Text, string? Error)> securityTask =
          ProbeTextAsync("SECURITY AND PREVIEW LIMITS", () => _apiClient.GetSecurityStatusAsync());
      await Task.WhenAll(renderTask, transcriptionTask, secretsTask, directorTask, readinessTask, hardwareTask, metricsTask, securityTask);

      DiagnosticsTextBox.Text =
          $"{securityTask.Result.Text}{Environment.NewLine}{Environment.NewLine}" +
          $"{readinessTask.Result.Text}{Environment.NewLine}{Environment.NewLine}" +
          $"{hardwareTask.Result.Text}{Environment.NewLine}{Environment.NewLine}" +
          metricsTask.Result.Text;
      LoadBackendSettings();
      LoadFoundrySettings();
      LoadVst3Status();

      string?[] failures =
      [
          renderTask.Result,
                transcriptionTask.Result,
                secretsTask.Result,
                directorTask.Result,
                readinessTask.Result.Error,
                hardwareTask.Result.Error,
                metricsTask.Result.Error,
                securityTask.Result.Error,
            ];
      string[] availableFailures = failures.Where(value => !string.IsNullOrWhiteSpace(value)).Select(value => value!).ToArray();
      ShowStatus(
          availableFailures.Length == 0
              ? "Settings and diagnostics loaded."
              : availableFailures.All(failure => failure.Contains("Studio backend is unavailable", StringComparison.OrdinalIgnoreCase))
                  ? "Studio backend is unavailable. Backend settings and diagnostics could not refresh. Local audio settings remain available. Reconnect, then Refresh."
                  : $"Some settings could not refresh: {string.Join(" | ", availableFailures.Distinct())}",
          availableFailures.Length == 0 ? InfoBarSeverity.Success : InfoBarSeverity.Warning);
    }
    catch (Exception exception)
    {
      ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
    }
    finally
    {
      SetBusy(false);
    }
  }

  private void ApplyRenderProviderSettings(JsonElement value)
  {
    JsonObject render = StudioPageHelpers.ToObject(value);
    _renderProviderSettings = (render["settings"] as JsonObject)?.DeepClone().AsObject() ?? [];
    JsonObject? video = _renderProviderSettings["video"] as JsonObject;
    SelectComboValue(VideoRouteComboBox, video?["preference"]?.GetValue<string>() ?? "auto");
    PreferGpuCheckBox.IsChecked = video?["auto_prefer_gpu"]?.GetValue<bool?>() ?? true;
    CloudFallbackCheckBox.IsChecked = video?["cosmos_fallback"]?.GetValue<bool?>() ?? true;
  }

  private void ApplyTranscriptionSettings(JsonElement value)
  {
    JsonObject transcription = StudioPageHelpers.ToObject(value);
    JsonObject settings = transcription["settings"] as JsonObject ?? transcription;
    SelectComboValue(TranscriptionProviderComboBox, settings["provider"]?.GetValue<string>() ?? "faster_whisper");
    SelectComboValue(TranscriptionDeviceComboBox, settings["device"]?.GetValue<string>() ?? "auto");
    SelectComboValue(ComputeTypeComboBox, settings["compute_type"]?.GetValue<string>() ?? "auto");
    TranscriptionModelTextBox.Text = settings["model"]?.GetValue<string>() ?? "turbo";
    TranscriptVerificationCheckBox.IsChecked = settings["verification_enabled"]?.GetValue<bool?>() ?? false;
    SeparateVocalsCheckBox.IsChecked = settings["separate_vocals"]?.GetValue<bool?>() ?? false;
  }

  private void ApplyDirectorSettings(JsonElement value)
  {
    JsonObject response = StudioPageHelpers.ToObject(value);
    JsonObject settings = response["settings"] as JsonObject ?? response;
    DirectorSpecialistEnabled.IsChecked = settings["specialist_enabled"]?.GetValue<bool?>() ?? true;
    SelectComboValue(DirectorQualityCombo, settings["default_quality"]?.GetValue<string>() ?? "standard");
    SelectComboValue(DirectorSpecialistRouting, settings["specialist_routing"]?.GetValue<string>() ?? "automatic");
    SelectComboValue(DirectorPrimaryExecution, settings["primary_execution"]?.GetValue<string>() ?? "local");
    SelectComboValue(DirectorSpecialistExecution, settings["specialist_execution"]?.GetValue<string>() ?? "local");
    DirectorPrimaryEndpoint.Text = settings["primary_endpoint"]?.GetValue<string>() ?? "https://integrate.api.nvidia.com/v1";
    DirectorPrimaryServerModel.Text = settings["primary_server_model"]?.GetValue<string>() ?? "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning";
    DirectorSpecialistEndpoint.Text = settings["specialist_endpoint"]?.GetValue<string>() ?? "https://integrate.api.nvidia.com/v1";
    DirectorSpecialistServerModel.Text = settings["specialist_server_model"]?.GetValue<string>() ?? "nvidia/cosmos-reason2-8b";
    DirectorConfigurationStatus.Text = "Local catalog entries and server configurations coexist. Save selects the route; configuration alone does not prove server availability. Generated plans still require review/apply.";
  }

  private void UseNvidiaHostedNemotron_Click(object sender, RoutedEventArgs e)
  {
    SelectComboValue(DirectorPrimaryExecution, "server");
    DirectorPrimaryEndpoint.Text = "https://integrate.api.nvidia.com/v1";
    DirectorPrimaryServerModel.Text = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning";
    DirectorConfigurationStatus.Text = "NVIDIA-hosted Nemotron selected. Save AI Director settings to apply. Uses your NVIDIA API key; availability and valid Director plans still require verification.";
  }

  private void UseHuggingFaceNemotron_Click(object sender, RoutedEventArgs e)
  {
    SelectComboValue(DirectorPrimaryExecution, "server");
    DirectorPrimaryEndpoint.Text = HfNemotronEndpoint.Text.Trim();
    DirectorPrimaryServerModel.Text = "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4";
    DirectorConfigurationStatus.Text = "Hugging Face Nemotron selected. Save AI Director settings to apply. Save your Hugging Face credential in the hosted services section; generated plans still require review/apply.";
  }

  private void ApplyHuggingFaceSettings(JsonElement settings)
  {
    HfNamespace.Text = settings.GetProperty("namespace").GetString() ?? "";
    HfNemotronEndpoint.Text = settings.GetProperty("nemotron_endpoint").GetString() ?? "";
    HfHunyuanEndpoint.Text = settings.GetProperty("hunyuan_endpoint").GetString() ?? "";
    HfWebhookUrl.Text = settings.GetProperty("webhook_url").GetString() ?? "";
    _hfWebhookId = settings.GetProperty("webhook_id").GetString() ?? "";
    HfServicesStatus.Text = $"Credential available: {settings.GetProperty("has_token").GetBoolean()}. Webhook secret saved: {settings.GetProperty("has_webhook_secret").GetBoolean()}. Webhook ID: {(_hfWebhookId.Length == 0 ? "not registered" : _hfWebhookId)}. Configuration does not prove inference readiness.";
  }

  private async Task SaveHuggingFaceSettingsAsync()
  {
    JsonObject payload = new()
    {
      ["namespace"] = HfNamespace.Text.Trim(),
      ["nemotron_endpoint"] = HfNemotronEndpoint.Text.Trim(),
      ["hunyuan_endpoint"] = HfHunyuanEndpoint.Text.Trim(),
      ["webhook_url"] = HfWebhookUrl.Text.Trim(),
      ["webhook_id"] = _hfWebhookId,
      ["hf_token"] = HfToken.Password,
      ["webhook_secret"] = HfWebhookSecret.Password,
    };
    ApplyHuggingFaceSettings(await _apiClient.SaveHuggingFaceServicesAsync(JsonSerializer.SerializeToElement(payload)));
    HfToken.Password = "";
    HfWebhookSecret.Password = "";
  }

  private async Task RunHuggingFaceActionAsync(object sender, Func<Task> action)
  {
    HfServicesPanel.IsEnabled = false;
    try { await action(); }
    catch (Exception exception) when (exception is StudioApiException or HttpRequestException or JsonException or IOException or FormatException or UnauthorizedAccessException)
    {
      HfServicesStatus.Text = StudioPageHelpers.GetErrorMessage(exception);
      ShowStatus(HfServicesStatus.Text, InfoBarSeverity.Error);
    }
    finally { HfServicesPanel.IsEnabled = true; }
  }

  private async void LoadHuggingFace_Click(object sender, RoutedEventArgs e) =>
      await RunHuggingFaceActionAsync(sender, async () => ApplyHuggingFaceSettings(await _apiClient.GetHuggingFaceServicesAsync()));

  private async void SaveHuggingFace_Click(object sender, RoutedEventArgs e) =>
      await RunHuggingFaceActionAsync(sender, SaveHuggingFaceSettingsAsync);

  private async void DiscoverHuggingFaceMcp_Click(object sender, RoutedEventArgs e) =>
      await RunHuggingFaceActionAsync(sender, async () =>
      {
        await SaveHuggingFaceSettingsAsync();
        HfServicesStatus.Text = "Discovering MCP tools...";
        JsonElement result = await _apiClient.DiscoverHuggingFaceMcpToolsAsync(SelectedTag(HfMcpServer, "hub"));
        HfMcpTools.Text = result.GetProperty("url").GetString() + Environment.NewLine +
            string.Join(Environment.NewLine, result.GetProperty("tools").EnumerateArray().Select(tool => tool.GetProperty("name").GetString()));
        HfServicesStatus.Text = "MCP tools discovered. Discovery does not run generation or qualify inference.";
      });

  private async void RegisterHuggingFaceWebhook_Click(object sender, RoutedEventArgs e) =>
      await RunHuggingFaceActionAsync(sender, async () =>
      {
        await SaveHuggingFaceSettingsAsync();
        JsonElement result = await _apiClient.RegisterHuggingFaceWebhookAsync();
        _hfWebhookId = result.GetProperty("id").GetString() ?? "";
        HfServicesStatus.Text = $"Repository webhook {_hfWebhookId} registered. Check delivery in Hugging Face's webhook dashboard.";
      });

  private async void GenerateHuggingFacePreview_Click(object sender, RoutedEventArgs e) =>
      await RunHuggingFaceActionAsync(sender, async () =>
      {
        FileSavePicker picker = new() { SuggestedStartLocation = PickerLocationId.VideosLibrary, SuggestedFileName = "hunyuan-studio-preview" };
        picker.FileTypeChoices.Add("MP4 video", [".mp4"]);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
        StorageFile? file = await picker.PickSaveFileAsync();
        if (file is null) return;
        await SaveHuggingFaceSettingsAsync();
        HfServicesStatus.Text = "Generating hosted Hunyuan preview. GPU cold starts may take several minutes...";
        JsonObject request = new() { ["prompt"] = HfPreviewPrompt.Text.Trim(), ["seed"] = 42, ["frames"] = 17, ["steps"] = 20 };
        JsonElement result = await _apiClient.GenerateHuggingFacePreviewAsync(JsonSerializer.SerializeToElement(request));
        await FileIO.WriteBytesAsync(file, Convert.FromBase64String(result.GetProperty("video_base64").GetString() ?? ""));
        HfServicesStatus.Text = $"Saved {result.GetProperty("frames")} frames at {result.GetProperty("fps")} fps to {file.Path}. Import this MP4 into your project to use it in Timeline.";
      });

  private async void SaveDirectorSettings_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      JsonObject payload = new()
      {
        ["primary_provider"] = "nemotron",
        ["primary_execution"] = SelectedTag(DirectorPrimaryExecution, "local"),
        ["primary_endpoint"] = DirectorPrimaryEndpoint.Text.Trim(),
        ["primary_server_model"] = DirectorPrimaryServerModel.Text.Trim(),
        ["specialist_execution"] = SelectedTag(DirectorSpecialistExecution, "local"),
        ["specialist_endpoint"] = DirectorSpecialistEndpoint.Text.Trim(),
        ["specialist_server_model"] = DirectorSpecialistServerModel.Text.Trim(),
        ["default_quality"] = SelectedTag(DirectorQualityCombo, "standard"),
        ["specialist_enabled"] = DirectorSpecialistEnabled.IsChecked == true,
        ["specialist_routing"] = SelectedTag(DirectorSpecialistRouting, "automatic"),
      };
      ApplyDirectorSettings(await _apiClient.SaveDirectorRuntimeSettingsAsync(JsonSerializer.SerializeToElement(payload)));
      ShowStatus("AI Director settings saved.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is StudioApiException or HttpRequestException or JsonException)
    {
      ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
    }
  }

  private static string SelectedTag(ComboBox comboBox, string fallback)
  {
    return (comboBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? fallback;
  }

  private static async Task<string?> ProbeAndApplyAsync(
        string name,
        Func<Task<JsonElement>> loadAsync,
        Action<JsonElement> apply)
  {
    try
    {
      apply(await loadAsync());
      return null;
    }
    catch (Exception exception) when (
        exception is StudioApiException or HttpRequestException or JsonException)
    {
      return $"{name}: {StudioPageHelpers.GetErrorMessage(exception)}";
    }
  }

  private static async Task<(string Text, string? Error)> ProbeTextAsync(
      string name,
      Func<Task<JsonElement>> loadAsync)
  {
    try
    {
      return ($"{name}{Environment.NewLine}{StudioPageHelpers.FormatJson(await loadAsync())}", null);
    }
    catch (Exception exception) when (
        exception is StudioApiException or HttpRequestException or JsonException)
    {
      string error = StudioPageHelpers.GetErrorMessage(exception);
      return ($"{name}{Environment.NewLine}Unavailable: {error}", $"{name}: {error}");
    }
  }

  private void LoadFoundrySettings()
  {
    try
    {
      FoundryProjectSettings settings = BackendSettingsStore.LoadFoundrySettings();
      FoundryProjectTextBox.Text = settings.ProjectName;
      FoundrySubscriptionTextBox.Text = settings.SubscriptionName;
      FoundryEndpointTextBox.Text = settings.ProjectEndpoint.AbsoluteUri;
    }
    catch (Exception exception) when (
        exception is InvalidDataException or IOException or UnauthorizedAccessException or ArgumentException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private void LoadVst3Status()
  {
    try
    {
      string scannerPath = Path.Combine(AppContext.BaseDirectory, "EdmgStudio.Vst3Scanner.exe");
      Vst3CatalogStore store = new();
      Vst3ScannerClient scanner = new(scannerPath, store);
      Vst3Catalog catalog = store.Load();
      Vst3HostCapabilities host = App.Services.Vst3Host.Capabilities;
      Vst3CapabilityText.Text = scanner.CapabilityState == Vst3CapabilityState.ScannerReady && host.State == Vst3CapabilityState.HostReady
          ? "Native scanner and crash-isolated VST3 worker are ready for float32 effect processing, parameters, state, and latency."
          : scanner.CapabilityState == Vst3CapabilityState.ScannerReady
              ? $"Scanner ready. Host unavailable: {host.Diagnostic}"
              : host.State == Vst3CapabilityState.HostReady
                  ? "Host ready. Scanner unavailable: EdmgStudio.Vst3Scanner.exe is not installed; discovery is disabled."
                  : $"VST3 unavailable. Scanner: EdmgStudio.Vst3Scanner.exe is not installed. Host: {host.Diagnostic}";
      Vst3CatalogText.Text = $"Cached modules: {catalog.Cache.Length} · Quarantined modules: {catalog.Quarantine.Length} · Active worker capability: {host.State}";
      IEnumerable<string> modules = catalog.Cache.Select(entry =>
          $"READY · {entry.Fingerprint.ModulePath} · {entry.Plugins.Length} effect class(es)");
      IEnumerable<string> quarantine = catalog.Quarantine.Select(entry =>
          $"QUARANTINED · {entry.Fingerprint.ModulePath} · failures {entry.FailureCount} · {entry.Reason}");
      Vst3CatalogDetailsText.Text = string.Join(Environment.NewLine, modules.Concat(quarantine).DefaultIfEmpty("No modules have been explicitly scanned."));
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      Vst3CapabilityText.Text = "VST3 discovery unavailable.";
      Vst3CatalogText.Text = exception.Message;
      Vst3CatalogDetailsText.Text = string.Empty;
    }
  }

  private void RefreshVst3Button_Click(object sender, RoutedEventArgs e)
  {
    LoadVst3Status();
    ShowStatus("VST3 capability and catalog status refreshed.", InfoBarSeverity.Success);
  }

  private async void BrowseVst3RootButton_Click(object sender, RoutedEventArgs e)
  {
    if (App.MainWindowInstance is null)
    {
      return;
    }

    FolderPicker picker = new() { SuggestedStartLocation = PickerLocationId.ComputerFolder };
    picker.FileTypeFilter.Add("*");
    WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance.WindowHandle);
    StorageFolder? folder = await picker.PickSingleFolderAsync();
    if (folder is null)
    {
      return;
    }

    string[] roots = ParseVst3ScanRoots().Append(folder.Path).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    Vst3ScanRootsTextBox.Text = string.Join(Environment.NewLine, roots);
    SaveVst3ScanRoots();
  }

  private async void ScanVst3Button_Click(object sender, RoutedEventArgs e)
  {
    string[] roots = ParseVst3ScanRoots();
    if (roots.Length == 0)
    {
      ShowStatus("Add at least one VST3 folder or module path.", InfoBarSeverity.Warning);
      return;
    }
    SaveVst3ScanRoots();
    string scannerPath = Path.Combine(AppContext.BaseDirectory, "EdmgStudio.Vst3Scanner.exe");
    Vst3ScannerClient scanner = new(scannerPath, new Vst3CatalogStore());
    ImmutableArray<string> modules = Vst3ModuleDiscovery.EnumerateModules(roots);
    if (modules.Length == 0)
    {
      ShowStatus("No .vst3 modules were found in the requested roots.", InfoBarSeverity.Warning);
      return;
    }
    int succeeded = 0;
    int unsupported = 0;
    foreach (string module in modules)
    {
      try
      {
        Vst3ScanResult result = await scanner.ScanAsync(module, TimeSpan.FromSeconds(20), force: true);
        if (result.Status == Vst3ScanStatus.Success)
        {
          succeeded++;
        }
        else if (result.Status == Vst3ScanStatus.Unsupported)
        {
          unsupported++;
        }
      }
      catch (Exception exception) when (exception is FileNotFoundException or DirectoryNotFoundException or IOException or UnauthorizedAccessException)
      {
        ShowStatus($"VST3 scan could not inspect '{module}': {exception.Message}", InfoBarSeverity.Warning);
      }
    }
    LoadVst3Status();
    int failed = modules.Length - succeeded - unsupported;
    ShowStatus($"VST3 scan finished: {succeeded} ready, {unsupported} unsupported, {failed} failed. Failures are quarantined with details below.",
        failed == 0 ? InfoBarSeverity.Success : InfoBarSeverity.Warning);
  }

  private string[] ParseVst3ScanRoots()
  {
    return Vst3ScanRootsTextBox.Text
      .Split(["\r\n", "\n"], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
      .Select(Environment.ExpandEnvironmentVariables)
      .Distinct(StringComparer.OrdinalIgnoreCase)
      .ToArray();
  }

  private static string LoadVst3ScanRoots()
  {
    return WindowsPackageIdentity.IsPackaged &&
            ApplicationData.Current.LocalSettings.Values[Vst3ScanRootsSettingKey] is string saved
          ? saved
          : string.Join(Environment.NewLine, Vst3ModuleDiscovery.StandardWindowsRoots());
  }

  private void SaveVst3ScanRoots()
  {
    if (!WindowsPackageIdentity.IsPackaged)
    {
      return;
    }

    try { ApplicationData.Current.LocalSettings.Values[Vst3ScanRootsSettingKey] = string.Join(Environment.NewLine, ParseVst3ScanRoots()); }
    catch (Exception exception) when (exception is InvalidOperationException or UnauthorizedAccessException or IOException)
    {
      ShowStatus($"VST3 scan roots could not be saved: {exception.Message}", InfoBarSeverity.Warning);
    }
  }

  private async void ClearVst3QuarantineButton_Click(object sender, RoutedEventArgs e)
  {
    ContentDialog confirmation = new()
    {
      XamlRoot = XamlRoot,
      Title = "Clear VST3 quarantine?",
      Content = "All quarantined modules will be eligible for the next explicit scan. Unsafe plugins are not loaded by this action.",
      PrimaryButtonText = "Clear",
      CloseButtonText = "Cancel",
      DefaultButton = ContentDialogButton.Close
    };
    if (await confirmation.ShowAsync() != ContentDialogResult.Primary)
    {
      return;
    }

    try
    {
      new Vst3CatalogStore().ClearQuarantine();
      LoadVst3Status();
      ShowStatus("VST3 quarantine cleared.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private void InitializeAppearance()
  {
    _initializingAppearance = true;
    string current = StudioAppearanceService.CurrentThemeId;
    AppearanceThemeComboBox.SelectedIndex = StudioAppearanceService.ThemeIds
        .Select((id, index) => (id, index))
        .First(item => item.id == current)
        .index;
    _initializingAppearance = false;
  }

  private void LoadBackendSettings()
  {
    try
    {
      DesktopBackendSettings persisted = BackendSettingsStore.LoadDesktopBackendSettings();
      BackendModeComboBox.SelectedIndex = persisted.Mode == RequestedBackendMode.External ? 1 : 0;
      RemoteBackendUrlTextBox.Text = persisted.ExternalBackendUri?.AbsoluteUri.TrimEnd('/') ?? string.Empty;
      RemoteBackendUrlTextBox.IsEnabled = persisted.Mode == RequestedBackendMode.External;

      BackendStatus active = App.Services.BackendSupervisor.Status;
      ActiveBackendText.Text =
          $"Active: {active.CurrentBackendUri.AbsoluteUri.TrimEnd('/')} · {active.State.ToString().ToLowerInvariant()}";
    }
    catch (Exception exception) when (
        exception is InvalidDataException or IOException or UnauthorizedAccessException or ArgumentException)
    {
      ActiveBackendText.Text = exception.Message;
    }
  }

  private void AppearanceThemeComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
  {
    if (_initializingAppearance ||
        AppearanceThemeComboBox.SelectedItem is not ComboBoxItem { Tag: string themeId })
    {
      return;
    }

    StudioAppearanceService.ApplyTheme(themeId, App.MainWindowInstance?.Content as FrameworkElement ?? this);
    ShowStatus($"Appearance changed to {themeId}.", InfoBarSeverity.Success);
  }

  private void BackendModeComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
  {
    RemoteBackendUrlTextBox.IsEnabled =
        BackendModeComboBox.SelectedItem is ComboBoxItem { Tag: string tag }
        && string.Equals(tag, "external", StringComparison.OrdinalIgnoreCase);
  }

  private async void ApplyBackendButton_Click(object sender, RoutedEventArgs e)
  {
    bool external = BackendModeComboBox.SelectedItem is ComboBoxItem { Tag: string tag }
                   && string.Equals(tag, "external", StringComparison.OrdinalIgnoreCase);
    if (!external)
    {
      await SwitchBackendAsync(RequestedBackendMode.Managed, null);
      return;
    }

    if (!Uri.TryCreate(RemoteBackendUrlTextBox.Text.Trim(), UriKind.Absolute, out Uri? backendUri))
    {
      ShowStatus("Enter an absolute http:// or https:// remote backend URL.", InfoBarSeverity.Warning);
      return;
    }

    await SwitchBackendAsync(RequestedBackendMode.External, backendUri);
  }

  private async void UseManagedBackendButton_Click(object sender, RoutedEventArgs e)
  {
    await SwitchBackendAsync(RequestedBackendMode.Managed, null);
  }

  private async Task SwitchBackendAsync(RequestedBackendMode mode, Uri? externalBackendUri)
  {
    SetBusy(true);
    try
    {
      BackendStatus status = await App.Services.SwitchBackendAsync(mode, externalBackendUri);
      LoadBackendSettings();
      status = await App.Services.BackendSupervisor.StartAsync();
      LoadBackendSettings();
      ShowStatus(
          status.IsReady
              ? $"Backend connected: {status.CurrentBackendUri.AbsoluteUri.TrimEnd('/')}"
              : status.Detail ?? status.Message,
          status.IsReady ? InfoBarSeverity.Success : InfoBarSeverity.Warning);
      await RefreshAsync();
    }
    catch (Exception exception) when (
        exception is ArgumentException or InvalidDataException or IOException or UnauthorizedAccessException or HttpRequestException)
    {
      ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
    }
    finally
    {
      SetBusy(false);
    }
  }

  private void SaveFoundryButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      FoundryProjectSettings settings = new(
                FoundryProjectTextBox.Text,
                FoundrySubscriptionTextBox.Text,
                new Uri(FoundryEndpointTextBox.Text.Trim(), UriKind.Absolute));
      BackendSettingsStore.SaveFoundrySettings(settings);
      LoadFoundrySettings();
      ShowStatus("Foundry project metadata saved.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (
        exception is InvalidDataException or IOException or UnauthorizedAccessException or ArgumentException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private async void SaveRouteButton_Click(object sender, RoutedEventArgs e)
  {
    string route = VideoRouteComboBox.SelectedItem as string ?? "auto";
    JsonObject payload = _renderProviderSettings?.DeepClone().AsObject() ?? [];
    JsonObject video = payload["video"] as JsonObject ?? [];
    video["preference"] = route;
    video["auto_prefer_gpu"] = PreferGpuCheckBox.IsChecked == true;
    video["cosmos_fallback"] = CloudFallbackCheckBox.IsChecked == true;
    video["allow_proxy_renders"] = false;
    payload["video"] = video;
    await RunSaveAsync(() => _apiClient.SaveRenderProvidersAsync(payload), "Video provider settings saved. Proxy rendering remains disabled.");
  }

  private async void SaveTranscriptionButton_Click(object sender, RoutedEventArgs e)
  {
    JsonObject payload = new()
    {
      ["provider"] = TranscriptionProviderComboBox.SelectedItem as string ?? "faster_whisper",
      ["device"] = TranscriptionDeviceComboBox.SelectedItem as string ?? "auto",
      ["compute_type"] = ComputeTypeComboBox.SelectedItem as string ?? "auto",
      ["model"] = TranscriptionModelTextBox.Text.Trim(),
      ["verification_enabled"] = TranscriptVerificationCheckBox.IsChecked == true,
      ["separate_vocals"] = SeparateVocalsCheckBox.IsChecked == true
    };
    await RunSaveAsync(() => _apiClient.SaveTranscriptionSettingsAsync(payload), "Transcription settings saved.");
  }

  private async void SaveSecretButton_Click(object sender, RoutedEventArgs e)
  {
    if (SecretNameComboBox.SelectedItem is not string name || string.IsNullOrWhiteSpace(SecretValueBox.Password))
    {
      ShowStatus("Choose a secret and enter its new value.", InfoBarSeverity.Warning);
      return;
    }
    await RunSaveAsync(() => _apiClient.SetSecretAsync(name, SecretValueBox.Password), "Secret updated securely.");
    SecretValueBox.Password = string.Empty;
  }

  private async void ClearSecretButton_Click(object sender, RoutedEventArgs e)
  {
    if (SecretNameComboBox.SelectedItem is not string name)
    {
      return;
    }

    ContentDialog confirmation = new()
    {
      XamlRoot = XamlRoot,
      Title = "Clear secret?",
      Content = $"Clear the stored value for {name}? Features that use this credential will remain unavailable until it is saved again.",
      PrimaryButtonText = "Clear",
      CloseButtonText = "Cancel",
      DefaultButton = ContentDialogButton.Close,
    };
    if (await confirmation.ShowAsync() != ContentDialogResult.Primary)
    {
      return;
    }

    await RunSaveAsync(() => _apiClient.ClearSecretAsync(name), "Secret cleared.");
  }

  private async Task RunSaveAsync(Func<Task> operation, string successMessage)
  {
    SetBusy(true);
    try
    {
      await operation();
      ShowStatus(successMessage, InfoBarSeverity.Success);
    }
    catch (Exception ex)
    {
      ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
    }
    finally
    {
      SetBusy(false);
    }
  }

  private void LoadRemoteControlSettings()
  {
    StudioRemoteControlDocument document = App.Services.RemoteControl.Document;
    KeyBindingItems.Items.Clear();
    foreach (StudioCommandDescriptor command in StudioCommandRegistry.Commands)
    {
      TextBox textBox = new()
      {
        Header = command.Name,
        Tag = command.Id,
        Text = document.KeyBindings.FirstOrDefault(binding => binding.CommandId == command.Id)?.Chord.DisplayText ?? string.Empty,
        PlaceholderText = "Unassigned"
      };
      KeyBindingItems.Items.Add(textBox);
    }
    QuickControlItems.Items.Clear();
    foreach (StudioQuickControl assignment in document.QuickControls.OrderBy(item => item.Slot))
    {
      ComboBox combo = new()
      {
        Header = $"Quick Control {assignment.Slot}",
        Tag = assignment.Slot,
        DisplayMemberPath = "Name",
        ItemsSource = StudioCommandRegistry.Commands,
        SelectedItem = StudioCommandRegistry.Commands.Single(command => command.Id == assignment.CommandId)
      };
      QuickControlItems.Items.Add(combo);
    }
    MidiCommandComboBox.ItemsSource = StudioCommandRegistry.Commands;
    MidiCommandComboBox.SelectedIndex = 0;
    MidiStatusText.Text = document.MidiBindings.Length == 0
        ? "No MIDI mappings configured."
        : $"{document.MidiBindings.Length} MIDI mapping(s) configured.";
    if (!string.IsNullOrWhiteSpace(App.Services.RemoteControl.LoadWarning))
    {
      ShowStatus(App.Services.RemoteControl.LoadWarning, InfoBarSeverity.Warning);
    }
  }

  private void SaveKeyBindings_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      ImmutableArray<StudioKeyBinding> bindings = KeyBindingItems.Items.OfType<TextBox>()
                .Where(textBox => !string.IsNullOrWhiteSpace(textBox.Text))
                .Select(textBox => new StudioKeyBinding((string)textBox.Tag, StudioKeyChord.Parse(textBox.Text)))
                .ToImmutableArray();
      StudioRemoteControlDocument current = App.Services.RemoteControl.Document;
      App.Services.RemoteControl.Replace(current with { KeyBindings = bindings });
      LoadRemoteControlSettings();
      ShowStatus("Keybindings saved.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private async void RefreshMidiButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      MidiDeviceComboBox.ItemsSource = await App.Services.MidiInput.DiscoverAsync();
      MidiDeviceComboBox.SelectedIndex = MidiDeviceComboBox.Items.Count > 0 ? 0 : -1;
      MidiStatusText.Text = MidiDeviceComboBox.Items.Count == 0 ? "No MIDI input devices found." : $"Found {MidiDeviceComboBox.Items.Count} MIDI input device(s).";
    }
    catch (Exception exception) { ShowStatus(exception.Message, InfoBarSeverity.Error); }
  }

  private async void ConnectMidiButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      await App.Services.MidiInput.SelectDeviceAsync((MidiDeviceComboBox.SelectedItem as MidiInputDeviceDescriptor)?.Id);
    }
    catch (Exception exception) { ShowStatus(exception.Message, InfoBarSeverity.Error); }
  }

  private void LearnMidiButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      if (MidiCommandComboBox.SelectedItem is not StudioCommandDescriptor)
      {
        throw new InvalidOperationException("Choose a command to learn.");
      }

      App.Services.MidiInput.BeginLearn();
    }
    catch (InvalidOperationException exception) { ShowStatus(exception.Message, InfoBarSeverity.Warning); }
  }

  private void MidiInput_MessageLearned(object? sender, StudioMidiMessage message)
  {
    _ = DispatcherQueue.TryEnqueue(() =>
  {
    if (MidiCommandComboBox.SelectedItem is not StudioCommandDescriptor command)
    {
      return;
    }

    try
    {
      StudioRemoteControlDocument current = App.Services.RemoteControl.Document;
      StudioMidiBinding binding = new(command.Id, message.DeviceId, message.MessageKind, message.Channel, message.Number);
      App.Services.RemoteControl.Replace(current with { MidiBindings = current.MidiBindings.Add(binding) });
      LoadRemoteControlSettings();
      MidiStatusText.Text = $"Mapped {message.MessageKind} channel {message.Channel}, number {message.Number} to {command.Name}.";
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  });
  }

  private void MidiInput_StatusChanged(object? sender, string status)
  {
    _ = DispatcherQueue.TryEnqueue(() => MidiStatusText.Text = status);
  }

  private void ClearMidiButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      StudioRemoteControlDocument current = App.Services.RemoteControl.Document;
      App.Services.RemoteControl.Replace(current with { MidiBindings = [] });
      LoadRemoteControlSettings();
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private void SaveQuickControls_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      ImmutableArray<StudioQuickControl> assignments = QuickControlItems.Items.OfType<ComboBox>()
                .Select(combo => new StudioQuickControl((int)combo.Tag, ((StudioCommandDescriptor)combo.SelectedItem).Id))
                .ToImmutableArray();
      StudioRemoteControlDocument current = App.Services.RemoteControl.Document;
      App.Services.RemoteControl.Replace(current with { QuickControls = assignments });
      ShowStatus("Quick Controls saved.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private async void ImportRemoteControl_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      FileOpenPicker picker = new() { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
      picker.FileTypeFilter.Add(".json");
      WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
      StorageFile? file = await picker.PickSingleFileAsync();
      if (file is null)
      {
        return;
      }

      App.Services.RemoteControl.Replace(StudioRemoteControlCodec.Deserialize(await FileIO.ReadTextAsync(file)));
      LoadRemoteControlSettings();
      ShowStatus("Remote-control mappings imported.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private async void ExportRemoteControl_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      FileSavePicker picker = new() { SuggestedStartLocation = PickerLocationId.DocumentsLibrary, SuggestedFileName = "edmg-remote-control" };
      picker.FileTypeChoices.Add("JSON document", [".json"]);
      WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
      StorageFile? file = await picker.PickSaveFileAsync();
      if (file is null)
      {
        return;
      }

      await FileIO.WriteTextAsync(file, StudioRemoteControlCodec.Serialize(App.Services.RemoteControl.Document));
      ShowStatus("Remote-control mappings exported.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private void ResetRemoteControl_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      App.Services.RemoteControl.Reset();
      LoadRemoteControlSettings();
      ShowStatus("Remote-control mappings reset to defaults.", InfoBarSeverity.Success);
    }
    catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(exception.Message, InfoBarSeverity.Error);
    }
  }

  private async void CreateSupportBundleButton_Click(object sender, RoutedEventArgs e)
  {
    try
    {
      SetBusy(true);
      byte[] bundle = await _apiClient.CreateSupportBundleAsync();
      FileSavePicker picker = new()
      {
        SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        SuggestedFileName = $"edmg-studio-support-{DateTimeOffset.Now:yyyyMMdd-HHmmss}"
      };
      picker.FileTypeChoices.Add("ZIP archive", [".zip"]);
      WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
      StorageFile? file = await picker.PickSaveFileAsync();
      if (file is null)
      {
        return;
      }

      await FileIO.WriteBytesAsync(file, bundle);
      ShowStatus("Support bundle saved. Review the ZIP before sharing it.", InfoBarSeverity.Success);
      StorageFolder? folder = await file.GetParentAsync();
      if (folder is not null)
      {
        _ = await Launcher.LaunchFolderAsync(folder, new FolderLauncherOptions { ItemsToSelect = { file } });
      }
    }
    catch (Exception exception) when (exception is HttpRequestException or IOException or UnauthorizedAccessException)
    {
      ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
    }
    finally
    {
      SetBusy(false);
    }
  }

  private static void SelectComboValue(ComboBox comboBox, string value)
  {
    foreach (string item in comboBox.Items.OfType<string>())
    {
      if (string.Equals(item, value, StringComparison.OrdinalIgnoreCase))
      {
        comboBox.SelectedItem = item;
        return;
      }
    }
  }

  private void SetBusy(bool value)
  {
    BusyRing.IsActive = value;
    RefreshButton.IsEnabled = !value;
    SettingsScroller.IsEnabled = !value;
  }

  private void ShowStatus(string message, InfoBarSeverity severity)
  {
    StatusInfoBar.Message = message;
    StatusInfoBar.Severity = severity;
    StatusInfoBar.IsOpen = true;
  }
}
