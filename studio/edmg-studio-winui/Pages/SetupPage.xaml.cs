using System.Text.Json;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage;
using Windows.System;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SetupPage : Page, IStudioRefreshable
{
    private bool _refreshing;

    public SetupPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
        PopulateStaticConfiguration();
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_refreshing)
        {
            return;
        }

        _refreshing = true;
        SetupProgress.IsActive = true;
        SetupInfoBar.IsOpen = false;
        try
        {
            var supervisor = App.Services.BackendSupervisor;
            var backend = await supervisor.RefreshHealthAsync(cancellationToken);
            if (!backend.IsReady && backend.State is not (
                    EdmgStudio.Core.Models.BackendLifecycleState.Resolving or
                    EdmgStudio.Core.Models.BackendLifecycleState.Starting or
                    EdmgStudio.Core.Models.BackendLifecycleState.WaitingForHealth))
            {
                backend = await supervisor.StartAsync(cancellationToken);
            }
            BackendReadinessText.Text = backend.IsReady
                ? $"Backend: ready ({backend.Mode})"
                : $"Backend: {backend.State} — {backend.Message}";

            if (!backend.IsReady)
            {
                BundleReadinessText.Text = "Backend bundle: unavailable until the backend connects";
                FfmpegReadinessText.Text = "FFmpeg: unavailable until the backend connects";
                AiReadinessText.Text = "AI path: unavailable until the backend connects";
                ModelReadinessText.Text = "AI model: unavailable until the backend connects";
                ShowStatus("Backend needs attention", backend.Detail ?? backend.Message, InfoBarSeverity.Warning);
                return;
            }

            var setup = await App.Services.ApiClient.GetSetupStatusAsync(cancellationToken);
            PopulateReadiness(setup);
        }
        catch (Exception exception)
        {
            ShowStatus("Setup status could not be loaded", exception.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetupProgress.IsActive = false;
            _refreshing = false;
        }
    }

    private void PopulateStaticConfiguration()
    {
        var configuration = App.Services.Configuration;
        var paths = configuration.Paths;
        StudioHomeText.Text = $"Studio home: {paths.StudioHome}";
        DataPathText.Text = $"Project data: {paths.DataDirectory}";
        ModelsPathText.Text = $"Models: {paths.ModelsDirectory}";
        CachePathText.Text = $"Shared cache: {paths.CacheDirectory}";
        LogsPathText.Text = $"Logs: {paths.LogsDirectory}";
        StorageStatusText.Text = paths.PreparationWarnings.Count == 0
            ? "Storage paths are available."
            : string.Join(Environment.NewLine, paths.PreparationWarnings);
        BackendModeText.Text = $"Configured mode: {configuration.Mode} · accelerator: {configuration.AcceleratorProfile}";
        BackendAddressText.Text = $"Address: {configuration.BackendUri.ToString().TrimEnd('/')}";
        BackendSourceText.Text = $"Configuration source: {configuration.Source}";
        if (configuration.HasPendingMigration)
        {
            StorageStatusText.Text = configuration.PendingMigrationDetail ?? "A pending storage migration requires attention.";
        }
    }

    private void PopulateReadiness(JsonElement setup)
    {
        var bundleOk = ReadNestedBool(setup, "backend_bundle", "ok");
        var ffmpegOk = ReadNestedBool(setup, "ffmpeg", "ok");
        var ollamaRequired = ReadNestedBool(setup, "ai_config", "ollama_required");
        var modelRequired = ReadNestedBool(setup, "ai_config", "model_required");
        var ollamaOk = ReadNestedBool(setup, "ollama", "ok");
        var modelPresent = ReadNestedBool(setup, "ollama", "model_present");

        BundleReadinessText.Text = $"Backend bundle/toolchain: {ReadyLabel(bundleOk)}";
        FfmpegReadinessText.Text = $"FFmpeg: {ReadyLabel(ffmpegOk)}";
        AiReadinessText.Text = ollamaRequired
            ? $"Ollama: {ReadyLabel(ollamaOk)}"
            : "AI path: Ollama optional for the active provider";
        ModelReadinessText.Text = modelRequired
            ? $"Required AI model: {ReadyLabel(modelPresent)}"
            : "AI model: no Ollama model required for the active provider";

        var ready = ReadNestedBool(setup, "system_readiness", "ready") ||
                    (bundleOk && ffmpegOk && (!ollamaRequired || (ollamaOk && (!modelRequired || modelPresent))));
        ShowStatus(
            ready ? "Studio is ready" : "Setup is incomplete",
            ready
                ? "The active backend reports the required runtime dependencies as ready."
                : "Review the missing dependency states. Installation actions remain available in the existing Studio client during this migration milestone.",
            ready ? InfoBarSeverity.Success : InfoBarSeverity.Warning);
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();
    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");

    private async void OpenStudioHome_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var folder = await StorageFolder.GetFolderFromPathAsync(App.Services.Configuration.Paths.StudioHome);
            await Launcher.LaunchFolderAsync(folder);
        }
        catch (Exception exception)
        {
            ShowStatus("Studio Home could not be opened", exception.Message, InfoBarSeverity.Error);
        }
    }

    private async void SaveToken_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(BackendTokenBox.Password))
        {
            ShowStatus("No token entered", "Enter the matching backend access token before saving.", InfoBarSeverity.Warning);
            return;
        }

        try
        {
            WindowsBackendTokenProvider.Save(BackendTokenBox.Password);
            BackendTokenBox.Password = string.Empty;
            ShowStatus("Backend token saved", "The token is protected by Windows Credential Locker and is not written to Studio logs.", InfoBarSeverity.Success);
            await RefreshAsync();
        }
        catch (Exception exception)
        {
            ShowStatus("Backend token could not be saved", exception.Message, InfoBarSeverity.Error);
        }
    }

    private async void ClearToken_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            WindowsBackendTokenProvider.Save(null);
            BackendTokenBox.Password = string.Empty;
            ShowStatus("Saved backend token cleared", "Environment-provided tokens, if any, are unchanged.", InfoBarSeverity.Informational);
            await RefreshAsync();
        }
        catch (Exception exception)
        {
            ShowStatus("Saved token could not be cleared", exception.Message, InfoBarSeverity.Error);
        }
    }

    private void ShowStatus(string title, string message, InfoBarSeverity severity)
    {
        SetupInfoBar.Title = title;
        SetupInfoBar.Message = message;
        SetupInfoBar.Severity = severity;
        SetupInfoBar.IsOpen = true;
    }

    private static bool ReadNestedBool(JsonElement root, string parent, string property) =>
        root.ValueKind == JsonValueKind.Object &&
        root.TryGetProperty(parent, out var parentValue) &&
        parentValue.ValueKind == JsonValueKind.Object &&
        parentValue.TryGetProperty(property, out var value) &&
        value.ValueKind is JsonValueKind.True;

    private static string ReadyLabel(bool value) => value ? "ready" : "missing or unavailable";
}
