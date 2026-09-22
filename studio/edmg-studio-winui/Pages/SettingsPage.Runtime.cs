using System.Text.Json;
using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage
{
    private RuntimeSettings _runtimePolicy = new();

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
        RuntimeStateText.Text = $"Installed: {YesNo(status.Installed)}   Available: {YesNo(status.Available)}   Healthy: {YesNo(status.Healthy)}   Compatible: {YesNo(status.Compatible)}   Accelerating now: {YesNo(status.Accelerating)}";
        RuntimeEvidenceText.Text = $"State: {status.State}; TensorRT: {status.TensorRtVersion ?? "not reported"}; PyTorch CUDA: {YesNo(status.PytorchCudaAvailable)}; GPUs in last receipt: {status.Gpus.Count}; validated cache: {FormatBytes(status.CacheBytes)}; supported components: {status.SupportedComponentCount}. Diagnostics are a prior test receipt, not live inference proof.";
        RuntimeComponentsText.Text = string.Join(Environment.NewLine, status.Components.Select(component =>
            $"{component.ModelFamily} / {component.Component}: {component.Status}; {component.ValidatedEngineCount} validated engine(s); fallback {component.FallbackRuntime}; optimize {(component.OptimizationEligible ? "available" : component.OptimizationReason ?? "unavailable")}."));
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
                RuntimePrecision.SelectedItem?.ToString() == "fp32" ? "fp32" : "fp16");
            RuntimeJobResponse result = await _apiClient.StartRuntimeJobAsync(request);
            await App.Services.JobsActivity.RefreshAsync();
            ShowStatus($"Runtime job queued: {result.JobId}. Follow progress in the job queue.", InfoBarSeverity.Success);
        }
        catch (Exception ex) { ShowStatus(ex.Message, InfoBarSeverity.Error); }
    }

    private async void DiagnoseRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("diagnose");
    private async void OptimizeRuntime_Click(object sender, RoutedEventArgs e) => await StartRuntimeJobAsync("optimize");

    private async void ClearRuntimeEngine_Click(object sender, RoutedEventArgs e)
    {
        try { await _apiClient.ClearRuntimeEngineAsync(RuntimeEngineId.Text.Trim()); await RefreshRuntimeAsync(); }
        catch (Exception ex) { ShowStatus(ex.Message, InfoBarSeverity.Error); }
    }
}
