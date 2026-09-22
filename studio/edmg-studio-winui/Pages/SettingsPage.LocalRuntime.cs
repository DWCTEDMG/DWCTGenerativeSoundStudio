using System.Collections.Immutable;
using EdmgStudio.Core.Runtime;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage
{
    private bool _localRuntimeEventsSubscribed;
    private bool _loadingLocalRuntimeSettings;

    private void LoadLocalRuntimeSettings()
    {
        _loadingLocalRuntimeSettings = true;
        try
        {
            LocalRuntimeSettings settings = App.Services.LocalRuntime.Settings;
            LocalRuntimeEnabled.IsChecked = settings.Enabled;
            LocalRuntimeAutoStart.IsChecked = settings.AutoStart;
            LocalRuntimeStopOnExit.IsChecked = settings.StopOnExit;
            LocalRuntimeCuda.IsChecked = settings.CudaEnabled;
            LocalRuntimeMultiGpu.IsChecked = settings.MultiGpuEnabled;
            SelectTaggedComboValue(LocalRuntimeChoice, settings.PreferredRuntime.ToString());
            SelectTaggedComboValue(LocalRuntimeSplitMode, settings.SplitMode);
            LocalRuntimeDevices.Text = string.Join(',', settings.DeviceList);
            LocalRuntimeTensorSplit.Text = settings.TensorSplit ?? string.Empty;
            LocalRuntimeTensorParallel.Value = settings.TensorParallelSize ?? double.NaN;
            LocalRuntimeContext.Value = settings.ContextSize;
            LocalRuntimeLlamaPort.Value = settings.LlamaPort;
            LocalRuntimeTensorRtPort.Value = settings.TensorRtPort;
            ApplyLocalRuntimeStatus(App.Services.LocalRuntime.CurrentStatus);
        }
        finally
        {
            _loadingLocalRuntimeSettings = false;
        }
    }

    private void SubscribeLocalRuntimeEvents()
    {
        if (_localRuntimeEventsSubscribed) return;
        App.Services.LocalRuntime.StatusChanged += LocalRuntime_StatusChanged;
        _localRuntimeEventsSubscribed = true;
    }

    private void UnsubscribeLocalRuntimeEvents()
    {
        if (!_localRuntimeEventsSubscribed) return;
        App.Services.LocalRuntime.StatusChanged -= LocalRuntime_StatusChanged;
        _localRuntimeEventsSubscribed = false;
    }

    private void LocalRuntime_StatusChanged(object? sender, RuntimeStatus status)
    {
        DispatcherQueue.TryEnqueue(() => ApplyLocalRuntimeStatus(status));
    }

    private void ApplyLocalRuntimeStatus(RuntimeStatus status)
    {
        LocalRuntimeStateText.Text = status.State switch
        {
            RuntimeState.Ready => "Ready",
            RuntimeState.LoadingModel => "Loading model...",
            RuntimeState.Detecting => "Detecting WSL and CUDA...",
            RuntimeState.Starting => "Starting runtime...",
            RuntimeState.Stopping => "Stopping runtime...",
            RuntimeState.Failed => "Runtime failed",
            _ => status.State.ToString()
        };
        string runtime = status.Runtime switch
        {
            LocalRuntimeType.LlamaCpp => "llama.cpp",
            LocalRuntimeType.TensorRtLlm => "TensorRT-LLM",
            _ => "Auto"
        };
        LocalRuntimeDetailsText.Text = string.Join(Environment.NewLine, new[]
        {
            $"Runtime     {runtime}",
            $"Model       {status.Model ?? "Not loaded"}",
            $"Compute     {status.Acceleration}",
            $"GPU         {(status.GpuNames.IsDefaultOrEmpty ? "Not detected" : string.Join(", ", status.GpuNames))}",
            $"GPUs        {status.GpuCount}",
            $"Endpoint    {status.Endpoint?.ToString() ?? "Not active"}",
            $"Ownership   {(status.StartedByStudio ? "Studio" : "External or none")}",
            $"Updated     {status.LastUpdated.ToLocalTime():g}"
        });
        LocalRuntimeErrorText.Text = status.Error ?? string.Empty;
        LocalRuntimeErrorText.Visibility = string.IsNullOrWhiteSpace(status.Error) ? Visibility.Collapsed : Visibility.Visible;
        bool busy = status.State is RuntimeState.Detecting or RuntimeState.Starting or RuntimeState.LoadingModel or RuntimeState.Stopping;
        LocalRuntimeStartButton.IsEnabled = !busy && status.State != RuntimeState.Ready;
        LocalRuntimeStopButton.IsEnabled = !busy && status.StartedByStudio;
        LocalRuntimeRestartButton.IsEnabled = !busy && status.StartedByStudio;
        LocalRuntimeProgress.IsActive = busy;
    }

    private async void LocalRuntimeStart_Click(object sender, RoutedEventArgs e) => await RunLocalRuntimeActionAsync(() => App.Services.LocalRuntime.StartAsync(), "Local Director runtime is ready.");
    private async void LocalRuntimeStop_Click(object sender, RoutedEventArgs e) => await RunLocalRuntimeActionAsync(() => App.Services.LocalRuntime.StopAsync(), "Studio-owned local runtime stopped.");
    private async void LocalRuntimeRestart_Click(object sender, RoutedEventArgs e) => await RunLocalRuntimeActionAsync(() => App.Services.LocalRuntime.RestartAsync(), "Local Director runtime restarted.");

    private async void LocalRuntimeRefresh_Click(object sender, RoutedEventArgs e)
    {
        await RunLocalRuntimeActionAsync(async () => { await App.Services.LocalRuntime.GetStatusAsync(); }, "Local runtime status refreshed.");
    }

    private async void LocalRuntimeTest_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            RuntimeHealthResult result = await App.Services.LocalRuntime.TestAsync();
            ShowStatus(result.IsReady ? $"Local inference endpoint is ready with model {result.Model}." : result.Error ?? "Local inference endpoint is not ready.", result.IsReady ? InfoBarSeverity.Success : InfoBarSeverity.Warning);
        }
        catch (HttpRequestException exception)
        {
            ShowStatus(exception.Message, InfoBarSeverity.Error);
        }
    }

    private async void LocalRuntimeOpenLogs_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            string log = await App.Services.LocalRuntime.ReadRecentLogAsync();
            var dialog = new ContentDialog
            {
                Title = "Local Director runtime log",
                Content = new ScrollViewer
                {
                    MaxHeight = 520,
                    Content = new TextBox { Text = log, IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.NoWrap, FontFamily = new Microsoft.UI.Xaml.Media.FontFamily("Consolas") }
                },
                CloseButtonText = "Close",
                XamlRoot = XamlRoot
            };
            await dialog.ShowAsync();
        }
        catch (InvalidOperationException exception)
        {
            ShowStatus(exception.Message, InfoBarSeverity.Error);
        }
    }

    private void LocalRuntimeSave_Click(object sender, RoutedEventArgs e)
    {
        if (_loadingLocalRuntimeSettings) return;
        try
        {
            LocalRuntimeSettings current = App.Services.LocalRuntime.Settings;
            LocalRuntimeSettings updated = current with
            {
                Enabled = LocalRuntimeEnabled.IsChecked == true,
                AutoStart = LocalRuntimeAutoStart.IsChecked == true,
                StopOnExit = LocalRuntimeStopOnExit.IsChecked == true,
                PreferredRuntime = ParseRuntimeType((LocalRuntimeChoice.SelectedItem as ComboBoxItem)?.Tag?.ToString()),
                CudaEnabled = LocalRuntimeCuda.IsChecked == true,
                MultiGpuEnabled = LocalRuntimeMultiGpu.IsChecked == true,
                DeviceList = ParseDevices(LocalRuntimeDevices.Text),
                SplitMode = (LocalRuntimeSplitMode.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "layer",
                TensorSplit = NullIfWhiteSpace(LocalRuntimeTensorSplit.Text),
                TensorParallelSize = ReadOptionalPositive(LocalRuntimeTensorParallel.Value),
                ContextSize = ReadPositive(LocalRuntimeContext.Value, "Context size"),
                LlamaPort = ReadPort(LocalRuntimeLlamaPort.Value, "llama.cpp port"),
                TensorRtPort = ReadPort(LocalRuntimeTensorRtPort.Value, "TensorRT-LLM port")
            };
            App.Services.LocalRuntime.UpdateSettings(updated);
            ShowStatus("Local Director runtime settings saved. Restart the runtime to apply profile changes.", InfoBarSeverity.Success);
        }
        catch (Exception exception) when (exception is ArgumentException or InvalidOperationException)
        {
            ShowStatus(exception.Message, InfoBarSeverity.Error);
        }
    }

    private async Task RunLocalRuntimeActionAsync(Func<Task> action, string successMessage)
    {
        try
        {
            await action();
            ShowStatus(successMessage, InfoBarSeverity.Success);
        }
        catch (Exception exception) when (exception is InvalidOperationException or TimeoutException or HttpRequestException)
        {
            ShowStatus(exception.Message, InfoBarSeverity.Error);
        }
    }

    private static LocalRuntimeType ParseRuntimeType(string? value) => Enum.TryParse(value, true, out LocalRuntimeType runtime) ? runtime : LocalRuntimeType.Auto;
    private static string? NullIfWhiteSpace(string? value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    private static int ReadPositive(double value, string name) => !double.IsNaN(value) && value is > 0 and <= int.MaxValue ? checked((int)value) : throw new ArgumentException($"{name} must be positive.");
    private static int ReadPort(double value, string name) => !double.IsNaN(value) && value is >= 1 and <= 65535 ? checked((int)value) : throw new ArgumentException($"{name} must be between 1 and 65535.");
    private static int? ReadOptionalPositive(double value) => double.IsNaN(value) ? null : ReadPositive(value, "Tensor parallel size");

    private static ImmutableArray<int> ParseDevices(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return [];
        var builder = ImmutableArray.CreateBuilder<int>();
        foreach (string token in value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (!int.TryParse(token, out int index) || index < 0) throw new ArgumentException("GPU devices must be comma-separated non-negative indexes.");
            if (!builder.Contains(index)) builder.Add(index);
        }
        return builder.ToImmutable();
    }

    private static void SelectTaggedComboValue(ComboBox comboBox, string value)
    {
        comboBox.SelectedItem = comboBox.Items.OfType<ComboBoxItem>().FirstOrDefault(item => string.Equals(item.Tag?.ToString(), value, StringComparison.OrdinalIgnoreCase)) ?? comboBox.Items[0];
    }
}
