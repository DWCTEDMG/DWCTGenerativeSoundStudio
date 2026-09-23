using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.RemoteControl;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.System;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage : Page
{
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
    private const string Vst3ScanRootsSettingKey = "Vst3.ScanRoots";
    private JsonObject? _renderProviderSettings;
    private bool _initializingAppearance;
    private bool _midiEventsSubscribed;

    public SettingsPage()
    {
        InitializeComponent();
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
        ApplyLocalRuntimeStatus(App.Services.LocalRuntime.CurrentStatus);
        await RefreshAsync();
        await RefreshRuntimeAsync();
    }

    private void SettingsPage_Unloaded(object sender, RoutedEventArgs e)
    {
        UnsubscribeLocalRuntimeEvents();
        if (!_midiEventsSubscribed) return;
        App.Services.MidiInput.MessageLearned -= MidiInput_MessageLearned;
        App.Services.MidiInput.StatusChanged -= MidiInput_StatusChanged;
        _midiEventsSubscribed = false;
    }

    private void SubscribeMidiEvents()
    {
        if (_midiEventsSubscribed) return;
        App.Services.MidiInput.MessageLearned += MidiInput_MessageLearned;
        App.Services.MidiInput.StatusChanged += MidiInput_StatusChanged;
        _midiEventsSubscribed = true;
    }
    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

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
            Task<(string Text, string? Error)> readinessTask =
                ProbeTextAsync("READINESS", () => _apiClient.GetSystemReadinessAsync());
            Task<(string Text, string? Error)> hardwareTask =
                ProbeTextAsync("HARDWARE", () => _apiClient.GetHardwareAsync());
            Task<(string Text, string? Error)> metricsTask =
                ProbeTextAsync("METRICS", () => _apiClient.GetBaselineMetricsAsync());
            Task<(string Text, string? Error)> securityTask =
                ProbeTextAsync("SECURITY AND PREVIEW LIMITS", () => _apiClient.GetSecurityStatusAsync());
            await Task.WhenAll(renderTask, transcriptionTask, secretsTask, readinessTask, hardwareTask, metricsTask, securityTask);

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
                readinessTask.Result.Error,
                hardwareTask.Result.Error,
                metricsTask.Result.Error,
                securityTask.Result.Error,
            ];
            string[] availableFailures = failures.Where(value => !string.IsNullOrWhiteSpace(value)).Select(value => value!).ToArray();
            ShowStatus(
                availableFailures.Length == 0
                    ? "Settings and diagnostics loaded."
                    : $"Settings loaded with unavailable probes: {string.Join(" | ", availableFailures)}",
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
        _renderProviderSettings = (render["settings"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject();
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
            var store = new Vst3CatalogStore();
            var scanner = new Vst3ScannerClient(scannerPath, store);
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
        if (App.MainWindowInstance is null) return;
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.ComputerFolder };
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance.WindowHandle);
        StorageFolder? folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;
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
        var scanner = new Vst3ScannerClient(scannerPath, new Vst3CatalogStore());
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
                if (result.Status == Vst3ScanStatus.Success) succeeded++;
                else if (result.Status == Vst3ScanStatus.Unsupported) unsupported++;
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

    private string[] ParseVst3ScanRoots() => Vst3ScanRootsTextBox.Text
        .Split(["\r\n", "\n"], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Select(Environment.ExpandEnvironmentVariables)
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .ToArray();

    private static string LoadVst3ScanRoots()
    {
        if (ApplicationData.Current.LocalSettings.Values[Vst3ScanRootsSettingKey] is string saved)
            return saved;
        return string.Join(Environment.NewLine, Vst3ModuleDiscovery.StandardWindowsRoots());
    }

    private void SaveVst3ScanRoots()
    {
        try { ApplicationData.Current.LocalSettings.Values[Vst3ScanRootsSettingKey] = string.Join(Environment.NewLine, ParseVst3ScanRoots()); }
        catch (Exception exception) when (exception is UnauthorizedAccessException or IOException)
        {
            ShowStatus($"VST3 scan roots could not be saved: {exception.Message}", InfoBarSeverity.Warning);
        }
    }

    private async void ClearVst3QuarantineButton_Click(object sender, RoutedEventArgs e)
    {
        var confirmation = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Clear VST3 quarantine?",
            Content = "All quarantined modules will be eligible for the next explicit scan. Unsafe plugins are not loaded by this action.",
            PrimaryButtonText = "Clear",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await confirmation.ShowAsync() != ContentDialogResult.Primary) return;
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
            var persisted = BackendSettingsStore.LoadDesktopBackendSettings();
            BackendModeComboBox.SelectedIndex = persisted.Mode == RequestedBackendMode.External ? 1 : 0;
            RemoteBackendUrlTextBox.Text = persisted.ExternalBackendUri?.AbsoluteUri.TrimEnd('/') ?? string.Empty;
            RemoteBackendUrlTextBox.IsEnabled = persisted.Mode == RequestedBackendMode.External;

            var active = App.Services.BackendSupervisor.Status;
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
        var external = BackendModeComboBox.SelectedItem is ComboBoxItem { Tag: string tag }
                       && string.Equals(tag, "external", StringComparison.OrdinalIgnoreCase);
        if (!external)
        {
            await SwitchBackendAsync(RequestedBackendMode.Managed, null);
            return;
        }

        if (!Uri.TryCreate(RemoteBackendUrlTextBox.Text.Trim(), UriKind.Absolute, out var backendUri))
        {
            ShowStatus("Enter an absolute http:// or https:// remote backend URL.", InfoBarSeverity.Warning);
            return;
        }

        await SwitchBackendAsync(RequestedBackendMode.External, backendUri);
    }

    private async void UseManagedBackendButton_Click(object sender, RoutedEventArgs e) =>
        await SwitchBackendAsync(RequestedBackendMode.Managed, null);

    private async Task SwitchBackendAsync(RequestedBackendMode mode, Uri? externalBackendUri)
    {
        SetBusy(true);
        try
        {
            var status = await App.Services.SwitchBackendAsync(mode, externalBackendUri);
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
            var settings = new FoundryProjectSettings(
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
        var route = VideoRouteComboBox.SelectedItem as string ?? "auto";
        var payload = _renderProviderSettings?.DeepClone().AsObject() ?? new JsonObject();
        var video = payload["video"] as JsonObject ?? new JsonObject();
        video["preference"] = route;
        video["auto_prefer_gpu"] = PreferGpuCheckBox.IsChecked == true;
        video["cosmos_fallback"] = CloudFallbackCheckBox.IsChecked == true;
        video["allow_proxy_renders"] = false;
        payload["video"] = video;
        await RunSaveAsync(() => _apiClient.SaveRenderProvidersAsync(payload), "Video provider settings saved. Proxy rendering remains disabled.");
    }

    private async void SaveTranscriptionButton_Click(object sender, RoutedEventArgs e)
    {
        var payload = new JsonObject
        {
            ["provider"] = TranscriptionProviderComboBox.SelectedItem as string ?? "faster_whisper",
            ["device"] = TranscriptionDeviceComboBox.SelectedItem as string ?? "auto",
            ["compute_type"] = ComputeTypeComboBox.SelectedItem as string ?? "auto",
            ["model"] = TranscriptionModelTextBox.Text.Trim()
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

        var confirmation = new ContentDialog
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
            var textBox = new TextBox
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
            var combo = new ComboBox { Header = $"Quick Control {assignment.Slot}", Tag = assignment.Slot, DisplayMemberPath = "Name" };
            combo.ItemsSource = StudioCommandRegistry.Commands;
            combo.SelectedItem = StudioCommandRegistry.Commands.Single(command => command.Id == assignment.CommandId);
            QuickControlItems.Items.Add(combo);
        }
        MidiCommandComboBox.ItemsSource = StudioCommandRegistry.Commands;
        MidiCommandComboBox.SelectedIndex = 0;
        MidiStatusText.Text = document.MidiBindings.Length == 0
            ? "No MIDI mappings configured."
            : $"{document.MidiBindings.Length} MIDI mapping(s) configured.";
        if (!string.IsNullOrWhiteSpace(App.Services.RemoteControl.LoadWarning))
            ShowStatus(App.Services.RemoteControl.LoadWarning, InfoBarSeverity.Warning);
    }

    private void SaveKeyBindings_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var bindings = KeyBindingItems.Items.OfType<TextBox>()
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
            if (MidiCommandComboBox.SelectedItem is not StudioCommandDescriptor) throw new InvalidOperationException("Choose a command to learn.");
            App.Services.MidiInput.BeginLearn();
        }
        catch (InvalidOperationException exception) { ShowStatus(exception.Message, InfoBarSeverity.Warning); }
    }

    private void MidiInput_MessageLearned(object? sender, StudioMidiMessage message) => DispatcherQueue.TryEnqueue(() =>
    {
        if (MidiCommandComboBox.SelectedItem is not StudioCommandDescriptor command) return;
        try
        {
            StudioRemoteControlDocument current = App.Services.RemoteControl.Document;
            var binding = new StudioMidiBinding(command.Id, message.DeviceId, message.MessageKind, message.Channel, message.Number);
            App.Services.RemoteControl.Replace(current with { MidiBindings = current.MidiBindings.Add(binding) });
            LoadRemoteControlSettings();
            MidiStatusText.Text = $"Mapped {message.MessageKind} channel {message.Channel}, number {message.Number} to {command.Name}.";
        }
        catch (Exception exception) when (exception is InvalidDataException or IOException or UnauthorizedAccessException)
        {
            ShowStatus(exception.Message, InfoBarSeverity.Error);
        }
    });

    private void MidiInput_StatusChanged(object? sender, string status) => DispatcherQueue.TryEnqueue(() => MidiStatusText.Text = status);

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
            var assignments = QuickControlItems.Items.OfType<ComboBox>()
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
            var picker = new FileOpenPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
            picker.FileTypeFilter.Add(".json");
            WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
            StorageFile? file = await picker.PickSingleFileAsync();
            if (file is null) return;
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
            var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary, SuggestedFileName = "edmg-remote-control" };
            picker.FileTypeChoices.Add("JSON document", [".json"]);
            WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
            StorageFile? file = await picker.PickSaveFileAsync();
            if (file is null) return;
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
            var picker = new FileSavePicker
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
                await Launcher.LaunchFolderAsync(folder, new FolderLauncherOptions { ItemsToSelect = { file } });
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
        foreach (var item in comboBox.Items.OfType<string>())
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
