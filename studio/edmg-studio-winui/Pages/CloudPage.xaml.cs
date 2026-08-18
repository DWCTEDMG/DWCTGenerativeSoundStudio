using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class CloudPage : Page
{
    public CloudPage()
    {
        InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        LoadFoundrySettings();
        await LoadHuggingFaceSettingsAsync();
    }

    private void OpenSettings_Click(object sender, RoutedEventArgs e) =>
        App.Navigate("settings");

    private void LoadFoundrySettings()
    {
        try
        {
            FoundryProjectSettings settings = BackendSettingsStore.LoadFoundrySettings();
            FoundryProjectText.Text = $"Project: {settings.ProjectName}";
            FoundrySubscriptionText.Text = $"Subscription: {settings.SubscriptionName}";
            FoundryEndpointText.Text = $"Endpoint: {settings.ProjectEndpoint.AbsoluteUri}";
        }
        catch (Exception exception) when (
            exception is InvalidDataException or IOException or UnauthorizedAccessException or ArgumentException)
        {
            FoundryProjectText.Text = "Project metadata unavailable";
            FoundrySubscriptionText.Text = "Subscription: —";
            FoundryEndpointText.Text = "Endpoint: —";
            ShowStatus($"Foundry metadata: {exception.Message}", InfoBarSeverity.Warning);
        }
    }

    private async void AwsTest_Click(object sender, RoutedEventArgs e) =>
        await RunActionAsync(
            "AWS credential test",
            () => App.Services.ApiClient.TestAwsCloudAsync(
                CreatePayload(("bucket", NullIfWhiteSpace(AwsBucketTextBox.Text)))));

    private async void AwsBundle_Click(object sender, RoutedEventArgs e) =>
        await RunActionAsync(
            "AWS bundle creation",
            () => App.Services.ApiClient.BundleAwsCloudAsync(
                CreatePayload(
                    ("bucket", NullIfWhiteSpace(AwsBucketTextBox.Text)),
                    ("key", NullIfWhiteSpace(AwsBundleKeyTextBox.Text)))));

    private async void AzureTest_Click(object sender, RoutedEventArgs e) =>
        await RunActionAsync(
            "Azure storage test",
            () => App.Services.ApiClient.TestAzureCloudAsync(
                CreatePayload(
                    ("container", NullIfWhiteSpace(AzureContainerTextBox.Text)),
                    ("prefix", NullIfWhiteSpace(AzurePrefixTextBox.Text)))));

    private async void ReloadHf_Click(object sender, RoutedEventArgs e) =>
        await LoadHuggingFaceSettingsAsync();

    private async void SaveHf_Click(object sender, RoutedEventArgs e)
    {
        var storageMode = HfStorageModeComboBox.SelectedIndex == 1 ? "cloud_only" : "local_cache";
        var payload = CreatePayload(
            ("enabled", HfEnabledToggle.IsOn),
            ("bucket", NullIfWhiteSpace(HfBucketTextBox.Text)),
            ("prefix", NullIfWhiteSpace(HfPrefixTextBox.Text)),
            ("storage_mode", storageMode));

        await RunActionAsync(
            "Hugging Face settings update",
            () => App.Services.ApiClient.SaveHuggingFaceCloudSettingsAsync(payload),
            ApplyHuggingFacePayload);
    }

    private async void TestHf_Click(object sender, RoutedEventArgs e) =>
        await RunActionAsync(
            "Hugging Face bucket test",
            () => App.Services.ApiClient.TestHuggingFaceCloudAsync(
                CreatePayload(
                    ("bucket", NullIfWhiteSpace(HfBucketTextBox.Text)),
                    ("prefix", NullIfWhiteSpace(HfPrefixTextBox.Text)))));

    private async void LightningBundle_Click(object sender, RoutedEventArgs e) =>
        await RunActionAsync(
            "Lightning bundle creation",
            () => App.Services.ApiClient.BundleLightningCloudAsync(
                CreatePayload(("output_dir", LightningOutputTextBox.Text.Trim()))));

    private async Task LoadHuggingFaceSettingsAsync()
    {
        try
        {
            SetBusy(true);
            var payload = await App.Services.ApiClient.GetHuggingFaceCloudSettingsAsync();
            ApplyHuggingFacePayload(payload);
            ShowStatus("Hugging Face settings loaded.", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            HfProviderTextBlock.Text = "Settings unavailable from the current backend.";
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task RunActionAsync(
        string actionName,
        Func<Task<JsonElement>> action,
        Action<JsonElement>? onSuccess = null)
    {
        try
        {
            SetBusy(true);
            var result = await action();
            ResultTextBox.Text = FormatJson(result);
            onSuccess?.Invoke(result);
            ShowStatus($"{actionName} completed.", InfoBarSeverity.Success);
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

    private void ApplyHuggingFacePayload(JsonElement payload)
    {
        var settings = payload.ValueKind == JsonValueKind.Object
            && payload.TryGetProperty("settings", out var settingsElement)
            && settingsElement.ValueKind == JsonValueKind.Object
                ? settingsElement
                : default;

        if (settings.ValueKind == JsonValueKind.Object)
        {
            HfEnabledToggle.IsOn = GetBoolean(settings, "enabled");
            HfBucketTextBox.Text = GetString(settings, "bucket");
            HfPrefixTextBox.Text = GetString(settings, "prefix");
            HfStorageModeComboBox.SelectedIndex =
                string.Equals(GetString(settings, "storage_mode"), "cloud_only", StringComparison.Ordinal)
                    ? 1
                    : 0;
        }

        var provider = GetString(payload, "active_provider");
        var status = payload.ValueKind == JsonValueKind.Object && payload.TryGetProperty("status", out var statusValue)
            ? Summarize(statusValue)
            : "status not reported";
        HfProviderTextBlock.Text =
            $"Active provider: {(string.IsNullOrWhiteSpace(provider) ? "not reported" : provider)} · {status}";
    }

    private void SetBusy(bool isBusy) =>
        StudioPageHelpers.SetControlsEnabled(this, !isBusy);

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private static JsonElement CreatePayload(params (string Name, object? Value)[] properties)
    {
        var payload = new JsonObject();
        foreach (var (name, value) in properties)
        {
            payload[name] = value switch
            {
                null => null,
                bool boolean => JsonValue.Create(boolean),
                string text => JsonValue.Create(text),
                _ => throw new InvalidOperationException($"Unsupported cloud payload value for '{name}'."),
            };
        }

        using var document = JsonDocument.Parse(payload.ToJsonString());
        return document.RootElement.Clone();
    }

    private static string? NullIfWhiteSpace(string value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static bool GetBoolean(JsonElement value, string propertyName) =>
        value.ValueKind == JsonValueKind.Object
        && value.TryGetProperty(propertyName, out var property)
        && property.ValueKind == JsonValueKind.True;

    private static string GetString(JsonElement value, string propertyName) =>
        value.ValueKind == JsonValueKind.Object
        && value.TryGetProperty(propertyName, out var property)
        && property.ValueKind == JsonValueKind.String
            ? property.GetString() ?? string.Empty
            : string.Empty;

    private static string Summarize(JsonElement value) =>
        value.ValueKind switch
        {
            JsonValueKind.Object when value.TryGetProperty("ok", out var ok) => $"ok: {ok}",
            JsonValueKind.Object => $"{value.EnumerateObject().Count()} status fields",
            JsonValueKind.Array => $"{value.GetArrayLength()} status items",
            JsonValueKind.Null or JsonValueKind.Undefined => "status not reported",
            _ => value.ToString(),
        };

    private static string FormatJson(JsonElement value) =>
        JsonSerializer.Serialize(value, EdmgStudio.Core.Models.StudioJsonContext.Default.JsonElement);
}
