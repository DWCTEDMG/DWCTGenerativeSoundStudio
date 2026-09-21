using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage
{
    private JsonObject _runtimePolicy = new();

    private async Task RefreshRuntimeAsync()
    {
        try
        {
            JsonElement status = await _apiClient.GetRuntimeStatusAsync();
            RuntimeStatusText.Text = JsonSerializer.Serialize(status, new JsonSerializerOptions { WriteIndented = true });
            _runtimePolicy = JsonNode.Parse(status.GetProperty("settings").GetRawText())!.AsObject();
            RuntimeMode.SelectedItem = _runtimePolicy["mode"]?.GetValue<string>();
            RuntimeEnabled.IsChecked = _runtimePolicy["enabled"]?.GetValue<bool>() ?? true;
            RuntimeBuild.IsChecked = _runtimePolicy["auto_build"]?.GetValue<bool>() ?? true;
            RuntimeFallback.IsChecked = _runtimePolicy["allow_fallback"]?.GetValue<bool>() ?? true;
            RuntimeStrict.IsChecked = _runtimePolicy["strict"]?.GetValue<bool>() ?? false;
            RuntimePrecision.SelectedItem = _runtimePolicy["precision"]?.GetValue<string>();
            RuntimeCacheLimit.Value = _runtimePolicy["cache_limit_gb"]?.GetValue<double>() ?? 100;
            RuntimePackage.Text = _runtimePolicy["package_path"]?.GetValue<string>() ?? "";
        }
        catch (Exception ex) { RuntimeStatusText.Text = $"Runtime status unavailable: {ex.Message}"; }
    }

    private async void RefreshRuntime_Click(object sender, RoutedEventArgs e) => await RefreshRuntimeAsync();

    private async void SaveRuntime_Click(object sender, RoutedEventArgs e)
    {
        _runtimePolicy["mode"] = RuntimeMode.SelectedItem?.ToString() ?? "auto";
        _runtimePolicy["enabled"] = RuntimeEnabled.IsChecked == true;
        _runtimePolicy["auto_build"] = RuntimeBuild.IsChecked == true;
        _runtimePolicy["allow_fallback"] = RuntimeFallback.IsChecked == true;
        _runtimePolicy["strict"] = RuntimeStrict.IsChecked == true;
        _runtimePolicy["precision"] = RuntimePrecision.SelectedItem?.ToString() ?? "auto";
        _runtimePolicy["cache_limit_gb"] = double.IsFinite(RuntimeCacheLimit.Value) ? RuntimeCacheLimit.Value : 100;
        _runtimePolicy["package_path"] = RuntimePackage.Text.Trim();
        try
        {
            await _apiClient.SaveRuntimeSettingsAsync(_runtimePolicy);
            await RefreshRuntimeAsync();
            ShowStatus("Runtime settings saved for subsequent renders.", InfoBarSeverity.Success);
        }
        catch (Exception ex) { ShowStatus(ex.Message, InfoBarSeverity.Error); }
    }

    private async Task StartRuntimeJobAsync(string operation)
    {
        try
        {
            var request = new JsonObject { ["operation"] = operation,
                ["device"] = double.IsFinite(RuntimeDevice.Value) ? (int)RuntimeDevice.Value : 0,
                ["precision"] = RuntimePrecision.SelectedItem?.ToString() == "fp32" ? "fp32" : "fp16" };
            var result = await _apiClient.StartRuntimeJobAsync(request);
            ShowStatus($"Runtime job queued: {result.GetProperty("job_id").GetString()}. Follow progress in the job queue.", InfoBarSeverity.Success);
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
