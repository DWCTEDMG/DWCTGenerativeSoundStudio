using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class SettingsPage : Page
{
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
    private JsonObject? _renderProviderSettings;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += SettingsPage_Loaded;
    }

    private async void SettingsPage_Loaded(object sender, RoutedEventArgs e) => await RefreshAsync();
    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async Task RefreshAsync()
    {
        SetBusy(true);
        try
        {
            var renderTask = _apiClient.GetRenderProvidersAsync();
            var transcriptionTask = _apiClient.GetTranscriptionSettingsAsync();
            var secretsTask = _apiClient.GetSecretStatusAsync();
            var readinessTask = _apiClient.GetSystemReadinessAsync();
            var hardwareTask = _apiClient.GetHardwareAsync();
            var metricsTask = _apiClient.GetBaselineMetricsAsync();
            await Task.WhenAll(renderTask, transcriptionTask, secretsTask, readinessTask, hardwareTask, metricsTask);

            var render = StudioPageHelpers.ToObject(await renderTask);
            _renderProviderSettings = (render["settings"] as JsonObject)?.DeepClone().AsObject() ?? new JsonObject();
            var video = _renderProviderSettings["video"] as JsonObject;
            SelectComboValue(VideoRouteComboBox, video?["preference"]?.GetValue<string>() ?? "auto");
            PreferGpuCheckBox.IsChecked = video?["auto_prefer_gpu"]?.GetValue<bool?>() ?? true;
            CloudFallbackCheckBox.IsChecked = video?["cosmos_fallback"]?.GetValue<bool?>() ?? true;

            var transcription = StudioPageHelpers.ToObject(await transcriptionTask);
            var settings = transcription["settings"] as JsonObject ?? transcription;
            SelectComboValue(TranscriptionProviderComboBox, settings["provider"]?.GetValue<string>() ?? "faster_whisper");
            SelectComboValue(TranscriptionDeviceComboBox, settings["device"]?.GetValue<string>() ?? "auto");
            SelectComboValue(ComputeTypeComboBox, settings["compute_type"]?.GetValue<string>() ?? "auto");
            TranscriptionModelTextBox.Text = settings["model"]?.GetValue<string>() ?? "turbo";

            SecretStatusText.Text = StudioPageHelpers.FormatJson(await secretsTask);
            DiagnosticsTextBox.Text =
                $"READINESS{Environment.NewLine}{StudioPageHelpers.FormatJson(await readinessTask)}{Environment.NewLine}{Environment.NewLine}" +
                $"HARDWARE{Environment.NewLine}{StudioPageHelpers.FormatJson(await hardwareTask)}{Environment.NewLine}{Environment.NewLine}" +
                $"METRICS{Environment.NewLine}{StudioPageHelpers.FormatJson(await metricsTask)}";
            ShowStatus("Settings and diagnostics loaded.", InfoBarSeverity.Success);
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
