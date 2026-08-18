using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Services;
using Microsoft.Windows.AppLifecycle;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage;
using Windows.System;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SetupPage : Page, IStudioRefreshable
{
    private static readonly TimeSpan ActivePollInterval = TimeSpan.FromSeconds(1);
    private static readonly TimeSpan IdlePollInterval = TimeSpan.FromSeconds(15);

    private readonly ObservableCollection<SetupTaskView> _tasks = [];
    private string _baseStorageStatus = string.Empty;
    private CancellationTokenSource? _lifetimeCts;
    private bool _refreshing;
    private bool _requestingAction;
    private bool _hadActiveTasks;

    public SetupPage()
    {
        InitializeComponent();
        SetupTasksItems.ItemsSource = _tasks;
        PopulateStaticConfiguration();
        Loaded += SetupPage_Loaded;
        Unloaded += SetupPage_Unloaded;
    }

    private void PopulateStaticConfiguration()
    {
        var configuration = App.Services.Configuration;
        var paths = configuration.Paths;
        StudioHomeText.Text = $"Studio home: {paths.StudioHome}";
        DataPathText.Text = $"Data: {paths.DataDirectory}";
        ModelsPathText.Text = $"Models: {paths.ModelsDirectory}";
        CachePathText.Text = $"Cache: {paths.CacheDirectory}";
        LogsPathText.Text = $"Logs: {paths.LogsDirectory}";
        _baseStorageStatus = paths.PreparationWarnings.Count == 0
            ? "Storage paths are ready."
            : string.Join(Environment.NewLine, paths.PreparationWarnings);
        StorageStatusText.Text = _baseStorageStatus;

        BackendModeText.Text = $"Mode: {configuration.Mode} · accelerator: {configuration.AcceleratorProfile}";
        BackendAddressText.Text = $"Address: {configuration.BackendUri}";
        BackendSourceText.Text =
            $"Configuration: {configuration.Source} · mode from {configuration.BackendModeSource} · address from {configuration.BackendAddressSource}";
        BackendValidationText.Text = configuration.ValidationErrors.Count == 0
            ? string.Empty
            : string.Join(Environment.NewLine, configuration.ValidationErrors);
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            _lifetimeCts?.Token ?? CancellationToken.None);
        await RefreshPageAsync(refreshDiagnostics: true, linkedCts.Token);
    }

    private async void SetupPage_Loaded(object sender, RoutedEventArgs e)
    {
        _lifetimeCts?.Cancel();
        _lifetimeCts?.Dispose();
        var lifetimeCts = new CancellationTokenSource();
        _lifetimeCts = lifetimeCts;

        try
        {
            await RefreshPageAsync(refreshDiagnostics: true, lifetimeCts.Token);
            _ = PollTasksAsync(lifetimeCts.Token);
        }
        catch (OperationCanceledException) when (lifetimeCts.IsCancellationRequested)
        {
        }
    }

    private void SetupPage_Unloaded(object sender, RoutedEventArgs e)
    {
        _lifetimeCts?.Cancel();
        _lifetimeCts?.Dispose();
        _lifetimeCts = null;
    }

    private async Task RefreshPageAsync(bool refreshDiagnostics, CancellationToken cancellationToken)
    {
        if (_refreshing)
        {
            return;
        }

        _refreshing = true;
        RefreshButton.IsEnabled = false;
        SetupInfoBar.IsOpen = false;
        SetupProgress.IsActive = true;
        BackendReadinessText.Text = "Backend: checking...";

        try
        {
            await App.Services.BackendSupervisor.RefreshHealthAsync(cancellationToken);
            var snapshot = App.Services.BackendSupervisor.Status;
            UpdateBackendSnapshot(snapshot);

            var setup = await App.Services.ApiClient.GetSetupStatusAsync(
                refresh: refreshDiagnostics,
                includeOptional: true,
                cancellationToken: cancellationToken);
            UpdateSetupStatus(setup);
            UpdateTasks(setup.Tasks);
        }
        catch (StudioApiException exception)
        {
            ShowError(StudioPageHelpers.GetErrorMessage(exception));
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        finally
        {
            _refreshing = false;
            RefreshButton.IsEnabled = true;
            SetupProgress.IsActive = false;
        }
    }

    private async Task PollTasksAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var isActive = _tasks.Any(task => task.CanCancel);
            try
            {
                var response = await App.Services.ApiClient.GetSetupTasksAsync(cancellationToken);
                var becameIdle = _hadActiveTasks && !response.Active;
                _hadActiveTasks = response.Active;
                isActive = response.Active;
                UpdateTasks(response.Tasks);

                if (becameIdle)
                {
                    var setup = await App.Services.ApiClient.GetSetupStatusAsync(
                        refresh: true,
                        includeOptional: true,
                        cancellationToken: cancellationToken);
                    UpdateSetupStatus(setup);
                }
            }
            catch (StudioApiException exception)
            {
                ShowError(StudioPageHelpers.GetErrorMessage(exception));
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }

            try
            {
                await Task.Delay(isActive ? ActivePollInterval : IdlePollInterval, cancellationToken);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
        }
    }

    private void UpdateBackendSnapshot(BackendStatus snapshot)
    {
        BackendReadinessText.Text = snapshot.State switch
        {
            BackendLifecycleState.Ready => $"Backend: connected to {snapshot.CurrentBackendUri}",
            BackendLifecycleState.Starting => "Backend: starting the managed runtime...",
            BackendLifecycleState.WaitingForHealth => "Backend: waiting for the health endpoint...",
            BackendLifecycleState.Unavailable => "Backend: unavailable",
            BackendLifecycleState.Failed => "Backend: failed to start",
            _ => $"Backend: {snapshot.State}",
        };
        BackendModeText.Text =
            $"Mode: {snapshot.Mode} · accelerator: {App.Services.Configuration.AcceleratorProfile} · owned process: {(snapshot.OwnsProcess ? "yes" : "no")}";
        BackendAddressText.Text = $"Address: {snapshot.CurrentBackendUri}";
        BackendValidationText.Text = snapshot.State is BackendLifecycleState.Failed or BackendLifecycleState.Unavailable
            ? snapshot.Detail ?? snapshot.Message
            : App.Services.Configuration.ValidationErrors.Count == 0
                ? string.Empty
                : string.Join(Environment.NewLine, App.Services.Configuration.ValidationErrors);
    }

    private void UpdateSetupStatus(SetupStatusResponse setup)
    {
        BundleReadinessText.Text =
            $"Backend bundle: {DescribeDiagnostic(setup.BackendBundle, "ok", "ready")} · toolchain: {DescribeDiagnostic(setup.Toolchain, "ready", "ok")}";
        FfmpegReadinessText.Text = "FFmpeg: " + DescribeReadinessSection(setup.SystemReadiness, "ffmpeg");
        AiReadinessText.Text = "AI path: " + DescribeDiagnostic(setup.AiConfig, "ok", "ready");
        ModelReadinessText.Text = "AI model: " + DescribeReadinessSection(setup.SystemReadiness, "model");
        ComfyReadinessText.Text = "ComfyUI: " + DescribeDiagnostic(setup.ComfyUi, "ok", "available", "running");
        EdmgReadinessText.Text = "EDMG Core: " + DescribeDiagnostic(setup.Edmg, "available", "ok");
        SevenZipReadinessText.Text = "7-Zip: " + DescribeDiagnostic(setup.SevenZip, "ok", "available");

        var profile = ReadString(setup.Toolchain, "accelerator_profile")
            ?? ReadString(setup.Toolchain, "profile");
        SelectTaggedItem(AcceleratorProfileComboBox, profile);

        var model = ReadString(setup.Ollama, "model");
        if (!string.IsNullOrWhiteSpace(model))
        {
            OllamaModelTextBox.Text = model;
        }

        var storageSummary = BuildStorageSummary(setup);
        StorageStatusText.Text = storageSummary.StartsWith(
            "Storage paths are managed",
            StringComparison.Ordinal)
            ? _baseStorageStatus
            : $"{_baseStorageStatus}{Environment.NewLine}{storageSummary}";
    }

    private void UpdateTasks(IEnumerable<SetupTaskDto> tasks)
    {
        var ordered = tasks
            .OrderByDescending(task => task.IsActive)
            .ThenByDescending(task => task.StartedAt ?? 0)
            .Select(task => new SetupTaskView(task))
            .ToList();

        _tasks.Clear();
        foreach (var task in ordered)
        {
            _tasks.Add(task);
        }

        var activeCount = ordered.Count(task => task.CanCancel);
        TasksSummaryText.Text = ordered.Count == 0
            ? "No installer tasks have been reported."
            : activeCount > 0
                ? $"{activeCount} active of {ordered.Count} reported task(s). Active tasks refresh every second."
                : $"{ordered.Count} completed task(s). Idle polling runs every 15 seconds.";
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await RefreshAsync();
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async void RefreshTasks_Click(object sender, RoutedEventArgs e)
    {
        await RefreshTasksNowAsync();
    }

    private async Task RefreshTasksNowAsync()
    {
        var cancellationToken = _lifetimeCts?.Token ?? CancellationToken.None;
        try
        {
            var response = await App.Services.ApiClient.GetSetupTasksAsync(cancellationToken);
            _hadActiveTasks = response.Active;
            UpdateTasks(response.Tasks);
        }
        catch (StudioApiException ex)
        {
            ShowError(StudioPageHelpers.GetErrorMessage(ex));
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private async void RetryBackend_Click(object sender, RoutedEventArgs e)
    {
        await RunSupervisorActionAsync(
            "Backend start requested.",
            cancellationToken => App.Services.BackendSupervisor.StartAsync(cancellationToken));
    }

    private async Task RunSupervisorActionAsync(
        string successMessage,
        Func<CancellationToken, Task> action)
    {
        var cancellationToken = _lifetimeCts?.Token ?? CancellationToken.None;
        try
        {
            SetupInfoBar.IsOpen = false;
            await action(cancellationToken);
            await RefreshPageAsync(refreshDiagnostics: false, cancellationToken);
            ShowSuccess(successMessage);
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private async void SaveToken_Click(object sender, RoutedEventArgs e)
    {
        var token = BackendTokenBox.Password.Trim();

        try
        {
            WindowsBackendTokenProvider.Save(string.IsNullOrWhiteSpace(token) ? null : token);
            BackendTokenBox.Password = string.Empty;
            ShowSuccess(string.IsNullOrWhiteSpace(token)
                ? "The saved backend token was cleared. Environment-provided tokens are unchanged."
                : "The backend token was stored securely. Restart Studio to apply the credential.");
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }
    }

    private async void ClearToken_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            WindowsBackendTokenProvider.Save(null);
            BackendTokenBox.Password = string.Empty;
            ShowSuccess("The saved backend token was cleared. Environment-provided tokens are unchanged. Restart Studio to apply the change.");
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }

        await Task.CompletedTask;
    }

    private async void ResetBackend_Click(object sender, RoutedEventArgs e)
    {
        var configuration = App.Services.Configuration;
        var confirmation = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Reset to the managed Python backend?",
            Content =
                "Studio will replace only the saved backend target with http://127.0.0.1:7863. " +
                "Storage, models, accelerator settings, Foundry configuration, and other bootstrap settings are preserved.\n\n" +
                $"Current target: {configuration.ConfiguredBackendUrl ?? configuration.BackendUri.ToString()}",
            PrimaryButtonText = "Reset and restart",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await confirmation.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            BackendSettingsStore.ResetToManaged();
            var restartResult = AppInstance.Restart("--backend-reset");
            if (!string.Equals(restartResult.ToString(), "RestartPending", StringComparison.Ordinal))
            {
                ShowError($"The target was reset, but Studio could not restart ({restartResult}). Close and reopen Studio.");
            }
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }
    }

    private async void OpenStudioHome_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var folder = await StorageFolder.GetFolderFromPathAsync(App.Services.Configuration.Paths.StudioHome);
            await Launcher.LaunchFolderAsync(folder);
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException or UnauthorizedAccessException)
        {
            ShowError(ex.Message);
        }
    }

    private void OpenWorkspace_Click(object sender, RoutedEventArgs e)
    {
        App.Services.Session.SetLastWorkflowDestination("workspace");
        App.Navigate("workspace");
    }

    private async void InstallFullSetup_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync(
            "Full setup",
            token => App.Services.ApiClient.InstallFullSetupAsync(
                GetSelectedTag(AcceleratorProfileComboBox, "cpu"),
                GetComfyPort(),
                OllamaModelTextBox.Text,
                token));

    private async void InstallBackend_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync(
            "Backend profile synchronization",
            token => App.Services.ApiClient.InstallBackendAsync(
                GetSelectedTag(AcceleratorProfileComboBox, "cpu"),
                token));

    private async void InstallSevenZip_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync("7-Zip installation", App.Services.ApiClient.InstallSevenZipAsync);

    private async void InstallEdmg_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync(
            "EDMG Core installation",
            token => App.Services.ApiClient.InstallEdmgCoreAsync(
                backend: GetSelectedTag(AcceleratorProfileComboBox, "cpu"),
                cancellationToken: token));

    private async void InstallOllama_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync("Managed Ollama installation", App.Services.ApiClient.InstallManagedOllamaAsync);

    private async void DownloadRunOllama_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync("Ollama download and run", App.Services.ApiClient.DownloadAndRunOllamaAsync);

    private async void StartOllama_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync("Managed Ollama start", App.Services.ApiClient.StartManagedOllamaAsync);

    private async void PullOllamaModel_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync(
            "Ollama model pull",
            token => App.Services.ApiClient.PullOllamaModelAsync(OllamaModelTextBox.Text, token));

    private async void InstallComfyUi_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync(
            "Portable ComfyUI installation",
            token => App.Services.ApiClient.InstallPortableComfyUiAsync(
                GetSelectedTag(ComfyFlavorComboBox, "cpu"),
                token));

    private async void StartComfyUi_Click(object sender, RoutedEventArgs e) =>
        await QueueSetupActionAsync(
            "Portable ComfyUI start",
            token => App.Services.ApiClient.StartPortableComfyUiAsync(
                "auto",
                GetComfyPort(),
                token));

    private async void StopComfyUi_Click(object sender, RoutedEventArgs e)
    {
        if (_requestingAction)
        {
            return;
        }

        var cancellationToken = _lifetimeCts?.Token ?? CancellationToken.None;
        _requestingAction = true;
        StudioPageHelpers.SetControlsEnabled(ActionsCard, enabled: false);
        SetupInfoBar.IsOpen = false;
        try
        {
            var response = await App.Services.ApiClient.StopPortableComfyUiAsync(cancellationToken);
            if (!response.Ok)
            {
                throw new InvalidOperationException("The backend did not confirm that ComfyUI was stopped.");
            }

            ShowSuccess("Portable ComfyUI stop requested.");
            var setup = await App.Services.ApiClient.GetSetupStatusAsync(
                refresh: true,
                includeOptional: true,
                cancellationToken: cancellationToken);
            UpdateSetupStatus(setup);
        }
        catch (StudioApiException ex)
        {
            ShowError(StudioPageHelpers.GetErrorMessage(ex));
        }
        catch (ArgumentException ex)
        {
            ShowError(ex.Message);
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        finally
        {
            StudioPageHelpers.SetControlsEnabled(ActionsCard, enabled: true);
            _requestingAction = false;
        }
    }

    private async Task QueueSetupActionAsync(
        string actionName,
        Func<CancellationToken, Task<SetupTaskActionResponse>> action)
    {
        if (_requestingAction)
        {
            return;
        }

        var cancellationToken = _lifetimeCts?.Token ?? CancellationToken.None;
        _requestingAction = true;
        StudioPageHelpers.SetControlsEnabled(ActionsCard, enabled: false);
        SetupInfoBar.IsOpen = false;
        try
        {
            var response = await action(cancellationToken);
            if (!response.Ok || string.IsNullOrWhiteSpace(response.Task.Id))
            {
                throw new InvalidOperationException($"The backend did not queue {actionName.ToLowerInvariant()}.");
            }

            _hadActiveTasks = response.Task.IsActive;
            ShowSuccess($"{actionName} queued as task {response.Task.Id}.");
            await RefreshTasksNowAsync();
        }
        catch (StudioApiException ex)
        {
            ShowError(StudioPageHelpers.GetErrorMessage(ex));
        }
        catch (ArgumentException ex)
        {
            ShowError(ex.Message);
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        finally
        {
            StudioPageHelpers.SetControlsEnabled(ActionsCard, enabled: true);
            _requestingAction = false;
        }
    }

    private async void CancelTask_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string taskId } || string.IsNullOrWhiteSpace(taskId))
        {
            return;
        }

        var cancellationToken = _lifetimeCts?.Token ?? CancellationToken.None;
        try
        {
            var response = await App.Services.ApiClient.CancelSetupTaskAsync(taskId, cancellationToken);
            if (!response.Ok)
            {
                throw new InvalidOperationException($"The backend did not accept cancellation for task {taskId}.");
            }

            ShowSuccess($"Cancellation requested for {response.Task.Name}.");
            await RefreshTasksNowAsync();
        }
        catch (StudioApiException ex)
        {
            ShowError(StudioPageHelpers.GetErrorMessage(ex));
        }
        catch (InvalidOperationException ex)
        {
            ShowError(ex.Message);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
    }

    private int GetComfyPort()
    {
        if (double.IsNaN(ComfyPortNumberBox.Value)
            || ComfyPortNumberBox.Value < 1
            || ComfyPortNumberBox.Value > 65535)
        {
            throw new ArgumentOutOfRangeException(
                nameof(ComfyPortNumberBox),
                "ComfyUI port must be between 1 and 65535.");
        }

        return checked((int)ComfyPortNumberBox.Value);
    }

    private static string GetSelectedTag(ComboBox comboBox, string fallback) =>
        comboBox.SelectedItem is ComboBoxItem { Tag: string tag } && !string.IsNullOrWhiteSpace(tag)
            ? tag
            : fallback;

    private static void SelectTaggedItem(ComboBox comboBox, string? tag)
    {
        if (string.IsNullOrWhiteSpace(tag))
        {
            return;
        }

        foreach (var item in comboBox.Items.OfType<ComboBoxItem>())
        {
            if (string.Equals(item.Tag as string, tag, StringComparison.OrdinalIgnoreCase))
            {
                comboBox.SelectedItem = item;
                return;
            }
        }
    }

    private static string DescribeReadinessSection(JsonElement readiness, string name)
    {
        if (readiness.ValueKind != JsonValueKind.Object
            || !readiness.TryGetProperty(name, out var section))
        {
            return "not reported";
        }

        return DescribeDiagnostic(section, "ok", "ready", "available", "present");
    }

    private static string DescribeDiagnostic(JsonElement section, params string[] flags)
    {
        if (section.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return "not reported";
        }

        if (section.ValueKind == JsonValueKind.True)
        {
            return "ready";
        }

        if (section.ValueKind == JsonValueKind.False)
        {
            return "needs attention";
        }

        if (section.ValueKind != JsonValueKind.Object)
        {
            return section.ToString();
        }

        foreach (var flag in flags)
        {
            if (section.TryGetProperty(flag, out var value)
                && value.ValueKind is JsonValueKind.True or JsonValueKind.False)
            {
                return value.GetBoolean() ? "ready" : "needs attention";
            }
        }

        return ReadString(section, "status")
            ?? ReadString(section, "hint")
            ?? "reported";
    }

    private static string? ReadString(JsonElement section, string name) =>
        section.ValueKind == JsonValueKind.Object
        && section.TryGetProperty(name, out var value)
        && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static string BuildStorageSummary(SetupStatusResponse setup)
    {
        var candidates = new[]
        {
            ReadString(setup.Ollama, "managed_models_dir"),
            ReadString(setup.ComfyUi, "install_dir"),
            ReadString(setup.Edmg, "install_dir"),
        }.Where(value => !string.IsNullOrWhiteSpace(value)).ToArray();

        return candidates.Length == 0
            ? "Storage paths are managed by the shell and were not reported by setup diagnostics."
            : string.Join(Environment.NewLine, candidates);
    }

    private void ShowSuccess(string message)
    {
        SetupInfoBar.Severity = InfoBarSeverity.Success;
        SetupInfoBar.Title = "Setup";
        SetupInfoBar.Message = message;
        SetupInfoBar.IsOpen = true;
    }

    private void ShowError(string message)
    {
        SetupInfoBar.Severity = InfoBarSeverity.Error;
        SetupInfoBar.Title = "Setup failed";
        SetupInfoBar.Message = message;
        SetupInfoBar.IsOpen = true;
    }
}

public sealed class SetupTaskView
{
    public SetupTaskView(SetupTaskDto task)
    {
        Id = task.Id;
        Name = string.IsNullOrWhiteSpace(task.Name) ? "Setup task" : task.Name;
        CanCancel = task.IsActive && !task.CancelRequested;
        ProgressPercent = Math.Clamp((task.Progress ?? 0) * 100, 0, 100);
        StatusText = task.CancelRequested
            ? $"{task.Status} · cancellation requested"
            : task.Status;
        DetailText = !string.IsNullOrWhiteSpace(task.Error)
            ? task.Error
            : !string.IsNullOrWhiteSpace(task.LastLog)
                ? task.LastLog
                : "No task log is available.";
        CancelAutomationId = "CancelSetupTask_" + SanitizeAutomationId(task.Id);
        ProgressAutomationName = string.Create(
            CultureInfo.InvariantCulture,
            $"{Name} progress {ProgressPercent:0} percent");
    }

    public string Id { get; }

    public string Name { get; }

    public string StatusText { get; }

    public string DetailText { get; }

    public double ProgressPercent { get; }

    public bool CanCancel { get; }

    public string CancelAutomationId { get; }

    public string ProgressAutomationName { get; }

    private static string SanitizeAutomationId(string value)
    {
        var characters = value
            .Select(character => char.IsLetterOrDigit(character) ? character : '_')
            .ToArray();
        return characters.Length == 0 ? "Unknown" : new string(characters);
    }
}
