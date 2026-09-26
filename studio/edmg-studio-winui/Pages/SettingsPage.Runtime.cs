using System.Text.Json;
using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage
{
    private RuntimeSettings _runtimePolicy = new();
    private RuntimeStatusResponse? _runtimeStatus;

    private async Task RefreshExecutionPlaneAsync()
    {
        try
        {
            ExecutionProfile profile = await _apiClient.GetExecutionProfileAsync();
            ExecutionProfileComboBox.SelectedItem = ExecutionProfileComboBox.Items.OfType<ComboBoxItem>()
                .FirstOrDefault(item => string.Equals(item.Tag?.ToString(), profile.RuntimeProfile, StringComparison.Ordinal));
            ApplyExecutionInventory(await _apiClient.GetExecutionInventoryAsync());
        }
        catch (Exception ex) { ExecutionReadinessText.Text = $"Execution status unavailable: {ex.Message}"; }
    }

    private void ApplyExecutionInventory(ExecutionInventory inventory)
    {
        ExecutionReadinessPresentation view = ExecutionPlanePresentation.Describe(inventory);
        ExecutionReadinessText.Text = $"{view.Title}: {view.Detail} Distro: {inventory.Wsl.Distribution ?? "not configured"}.";
    }

    private async void SaveExecutionProfile_Click(object sender, RoutedEventArgs e)
    {
        string profile = (ExecutionProfileComboBox.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "standard";
        await _apiClient.SaveExecutionProfileAsync(new ExecutionProfile { RuntimeProfile = profile });
        await RefreshExecutionPlaneAsync();
    }

    private async void ProbeWslExecution_Click(object sender, RoutedEventArgs e) =>
        ApplyExecutionInventory(await _apiClient.ProbeWslExecutionAsync());

    private async Task RefreshRuntimeAsync()
    {
        try
        {
            ApplyRuntimeStatus(await _apiClient.GetRuntimeStatusAsync());
        }
        catch (Exception ex)
        {
            RuntimeEvidenceText.Text = $"Runtime status unavailable: {ex.Message}";
        }
    }

    private void ApplyRuntimeStatus(RuntimeStatusResponse status)
    {
        _runtimeStatus = status;
        RuntimeStateText.Text = $"Installed: {YesNo(status.Installed)}   Available: {YesNo(status.Available)}   Healthy: {YesNo(status.Healthy)}   Compatible: {YesNo(status.Compatible)}   Accelerating now: {YesNo(status.Accelerating)}";
        RuntimeEvidenceText.Text = $"State: {status.State}; TensorRT: {status.TensorRtVersion ?? "not reported"}; PyTorch CUDA: {YesNo(status.PytorchCudaAvailable)}; GPUs in last receipt: {status.Gpus.Count}; validated cache: {FormatBytes(status.CacheBytes)}; supported components: {status.SupportedComponentCount}. Diagnostics are a prior test receipt, not live inference proof.";
        PopulateRuntimeTargets(status);
        RuntimeComponentStatus[] compatible = status.Components
            .Where(component => component.OptimizationEligible || component.ValidatedEngineCount > 0)
            .ToArray();
        int fallbackOnlyCount = status.Components.Count - compatible.Length;
        RuntimeComponentsText.Text = string.Join(Environment.NewLine,
            compatible.Select(component =>
                $"{component.ModelFamily} / {component.Component}: {component.Status}; {component.ValidatedEngineCount} validated engine(s); optimize {(component.OptimizationEligible ? "available" : component.OptimizationReason ?? "unavailable")}.")
            .Append(fallbackOnlyCount > 0
                ? $"{fallbackOnlyCount} other components remain on their existing validated providers; they are not TensorRT targets and do not require selection here."
                : "All reported components are TensorRT targets."));
        RuntimeStatusText.Text = string.Join(Environment.NewLine, status.Engines.Select(engine => JsonSerializer.Serialize(engine, StudioJson.Options)));
        _runtimePolicy = status.Settings;
        RuntimeMode.SelectedItem = _runtimePolicy.Mode;
        RuntimeEnabled.IsChecked = _runtimePolicy.Enabled;
        RuntimeBuild.IsChecked = _runtimePolicy.AutoBuild;
        RuntimeFallback.IsChecked = _runtimePolicy.AllowFallback;
        RuntimeStrict.IsChecked = _runtimePolicy.Strict;
        RuntimePrecision.SelectedItem = _runtimePolicy.Precision;
        RuntimeCacheLimit.Value = _runtimePolicy.CacheLimitGb;
        RuntimePackage.Text = _runtimePolicy.PackagePath;
        UpdateRuntimeActionState();
    }

    private void PopulateRuntimeTargets(RuntimeStatusResponse status)
    {
        string? selected = (RuntimeComponent.SelectedItem as ComboBoxItem)?.Tag?.ToString();
        RuntimeComponent.Items.Clear();
        foreach (RuntimeComponentStatus component in status.Components.Where(value =>
                     value.ModelFamily == "sd15" && (value.OptimizationEligible || value.ValidatedEngineCount > 0)))
        {
            RuntimeComponent.Items.Add(new ComboBoxItem
            {
                Content = $"SD1.5 — {FormatRuntimeComponent(component.Component)}",
                Tag = component.Component
            });
        }

        RuntimeComponent.SelectedItem = RuntimeComponent.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(item.Tag?.ToString(), selected, StringComparison.OrdinalIgnoreCase));
        if (RuntimeComponent.SelectedItem is null && RuntimeComponent.Items.Count > 0)
        {
            RuntimeComponent.SelectedIndex = 0;
        }
    }

    private static string FormatRuntimeComponent(string component) => component switch
    {
        "unet" => "UNet",
        "vae_decoder" => "VAE decoder",
        _ => component.Replace('_', ' ')
    };

    private void UpdateRuntimeActionState()
    {
        string selected = (RuntimeComponent.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "unet";
        RuntimeComponentStatus? component = _runtimeStatus?.Components.FirstOrDefault(value =>
            value.ModelFamily == "sd15" && value.Component == selected);
        bool runtimeReady = _runtimeStatus is { Available: true, Compatible: true, Settings.Enabled: true };
        bool canOptimize = runtimeReady && component?.OptimizationEligible == true;
        bool hasEngineRecord = !string.IsNullOrWhiteSpace(component?.LastEngineId)
            && !string.Equals(component.LastEngineState, "missing", StringComparison.OrdinalIgnoreCase);
        RuntimeOptimizeButton.IsEnabled = canOptimize;
        RuntimeOptimizeAllButton.IsEnabled = runtimeReady
            && _runtimeStatus?.Components.Any(value => value.ModelFamily == "sd15" && value.OptimizationEligible) == true;
        RuntimeRebuildButton.IsEnabled = canOptimize && hasEngineRecord;
        RuntimeValidateButton.IsEnabled = canOptimize
            && component?.ValidatedEngineCount > 0
            && string.Equals(component.LastEngineState, "ready", StringComparison.OrdinalIgnoreCase);
    }

    private void RuntimeComponent_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        // SelectedIndex is applied while InitializeComponent is still connecting fields.
        // Command-bar controls declared after this ComboBox are not available until the page loads.
        if (!IsLoaded) return;
        UpdateRuntimeActionState();
    }

    private static string YesNo(bool value) => value ? "Yes" : "No";

    private static string FormatBytes(long bytes) =>
        bytes < 1024 * 1024 ? $"{bytes / 1024d:0.#} KB" : $"{bytes / (1024d * 1024d):0.#} MB";

    private async void RefreshRuntime_Click(object sender, RoutedEventArgs e) => await RefreshRuntimeAsync();

    private async void SaveRuntime_Click(object sender, RoutedEventArgs e)
    {
        var policy = _runtimePolicy with
        {
            Mode = RuntimeMode.SelectedItem?.ToString() ?? "auto",
            Enabled = RuntimeEnabled.IsChecked == true,
            AutoBuild = RuntimeBuild.IsChecked == true,
            AllowFallback = RuntimeFallback.IsChecked == true,
            Strict = RuntimeStrict.IsChecked == true,
            Precision = RuntimePrecision.SelectedItem?.ToString() ?? "auto",
            CacheLimitGb = double.IsFinite(RuntimeCacheLimit.Value) ? RuntimeCacheLimit.Value : 100,
            PackagePath = RuntimePackage.Text.Trim(),
        };
        try
        {
            ApplyRuntimeStatus(await _apiClient.SaveRuntimeSettingsAsync(policy));
            ShowStatus("Runtime settings saved for subsequent renders.", InfoBarSeverity.Success);
        }
        catch (Exception ex) { ShowStatus(ex.Message, InfoBarSeverity.Error); }
    }

    private async Task StartRuntimeJobAsync(string operation)
    {
        try
        {
            var request = new RuntimeJobRequest(
                operation,
                double.IsFinite(RuntimeDevice.Value) ? (int)RuntimeDevice.Value : 0,
                RuntimePrecision.SelectedItem?.ToString() == "fp32" ? "fp32" : "fp16",
                Component: (RuntimeComponent.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "unet");
            RuntimeJobResponse result = await _apiClient.StartRuntimeJobAsync(request);
            await App.Services.JobsActivity.RefreshAsync();
            ShowStatus($"Runtime job queued: {result.JobId}. Follow progress in the job queue.", InfoBarSeverity.Success);
        }
        catch (Exception ex) { ShowStatus(ex.Message, InfoBarSeverity.Error); }
    }

    private async void DiagnoseRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("diagnose");
    private async void OptimizeRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("optimize");
    private async void OptimizeAllRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("optimize_all");
    private async void RebuildRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("rebuild");
    private async void ValidateRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("validate");

    private async void ClearRuntimeEngine_Click(object sender, RoutedEventArgs e)
    {
        try { await _apiClient.ClearRuntimeEngineAsync(RuntimeEngineId.Text.Trim()); await RefreshRuntimeAsync(); }
        catch (Exception ex) { ShowStatus(ex.Message, InfoBarSeverity.Error); }
    }
}
