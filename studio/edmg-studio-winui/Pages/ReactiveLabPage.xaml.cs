using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class ReactiveLabPage : Page
{
    private const string EmptyPayload = """
        {
          "metadata": {
            "createdAt": "",
            "preset": "cinematic",
            "sensitivity": 1.0,
            "smoothing": 0.28,
            "fps": 24,
            "source": "audio-file",
            "totalFrames": 0,
            "scaling": { "zoom": 1, "rotation": 1, "translation": 1, "color": 1 },
            "beatCount": 0,
            "minCutFrames": 8,
            "renderMode": "smooth",
            "scheduleStride": 4
          },
          "keyframes": [],
          "beat_markers": [],
          "cue_events": [],
          "sections": [],
          "repair_suggestions": [],
          "schedules": {},
          "handoff_manifest": {}
        }
        """;

    public ReactiveLabPage()
    {
        InitializeComponent();
        PayloadJsonBox.Text = EmptyPayload;
        Loaded += ReactiveLabPage_Loaded;
    }

    private async void ReactiveLabPage_Loaded(object sender, RoutedEventArgs e)
    {
        Loaded -= ReactiveLabPage_Loaded;
        await LoadProjectAsync(loadPayload: true);
    }

    private async void LoadLastPayload_Click(object sender, RoutedEventArgs e) =>
        await LoadProjectAsync(loadPayload: true);

    private async Task LoadProjectAsync(bool loadPayload)
    {
        var projectId = App.Services.Session.ActiveProjectId;
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ProjectSummaryText.Text = "No active project. Select one in Projects before applying a reactive bundle.";
            ShowStatus("Select an active project first.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            var response = await App.Services.ApiClient.GetProjectAsync(projectId);
            var project = response.Project;
            ProjectSummaryText.Text = $"{project.Name} • {StudioPageHelpers.ShortId(project.Id)} • variant {App.Services.Session.SelectedVariantIndex + 1}";
            if (loadPayload && project.Meta.TryGetProperty("last_reactive_lab", out var last) &&
                last.ValueKind == JsonValueKind.Object)
            {
                PayloadJsonBox.Text = StudioPageHelpers.FormatJson(last);
                LoadMetadata(last);
            }
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

    private async void ApplyReactive_Click(object sender, RoutedEventArgs e)
    {
        var projectId = App.Services.Session.ActiveProjectId;
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ShowStatus("Select an active project first.", InfoBarSeverity.Warning);
            return;
        }

        JsonObject? payload;
        try
        {
            payload = JsonNode.Parse(PayloadJsonBox.Text) as JsonObject;
        }
        catch (JsonException ex)
        {
            ShowStatus($"Reactive JSON is invalid: {ex.Message}", InfoBarSeverity.Warning);
            return;
        }

        if (payload is null)
        {
            ShowStatus("Reactive JSON must have an object at its root.", InfoBarSeverity.Warning);
            return;
        }

        var metadata = payload["metadata"] as JsonObject ?? new JsonObject();
        metadata["preset"] = SelectedText(PresetCombo);
        metadata["renderMode"] = SelectedText(RenderModeCombo);
        metadata["fps"] = (int)FpsBox.Value;
        metadata["sensitivity"] = SensitivityBox.Value;
        metadata["smoothing"] = SmoothingBox.Value;
        metadata["scheduleStride"] = (int)ScheduleStrideBox.Value;
        payload["metadata"] = metadata;
        payload["overwrite_motion_track"] = OverwriteMotionCheckBox.IsChecked == true;
        payload["overwrite_camera"] = OverwriteCameraCheckBox.IsChecked == true;

        foreach (var requiredArray in new[] { "keyframes", "beat_markers", "cue_events", "sections", "repair_suggestions" })
        {
            payload[requiredArray] ??= new JsonArray();
        }
        payload["schedules"] ??= new JsonObject();
        payload["handoff_manifest"] ??= new JsonObject();

        SetBusy(true);
        try
        {
            await App.Services.ApiClient.ApplyReactiveLabAsync(projectId, ToJsonElement(payload));
            PayloadJsonBox.Text = payload.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            ShowStatus("Reactive bundle applied. The backend updated canonical motion, camera, timeline, and Visual DNA state.", InfoBarSeverity.Success);
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

    private void LoadMetadata(JsonElement payload)
    {
        if (!payload.TryGetProperty("metadata", out var metadata) || metadata.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        SelectText(PresetCombo, ReadString(metadata, "preset"));
        SelectText(RenderModeCombo, ReadString(metadata, "renderMode"));
        ReadNumber(metadata, "fps", value => FpsBox.Value = value);
        ReadNumber(metadata, "sensitivity", value => SensitivityBox.Value = value);
        ReadNumber(metadata, "smoothing", value => SmoothingBox.Value = value);
        ReadNumber(metadata, "scheduleStride", value => ScheduleStrideBox.Value = value);
    }

    private static void ReadNumber(JsonElement source, string property, Action<double> assign)
    {
        if (source.TryGetProperty(property, out var value) && value.TryGetDouble(out var number))
        {
            assign(number);
        }
    }

    private static string ReadString(JsonElement source, string property) =>
        source.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;

    private static string SelectedText(ComboBox combo) =>
        (combo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? string.Empty;

    private static void SelectText(ComboBox combo, string value)
    {
        for (var index = 0; index < combo.Items.Count; index++)
        {
            if (combo.Items[index] is ComboBoxItem item &&
                string.Equals(item.Content?.ToString(), value, StringComparison.Ordinal))
            {
                combo.SelectedIndex = index;
                return;
            }
        }
    }

    private static JsonElement ToJsonElement(JsonObject value)
    {
        using var document = JsonDocument.Parse(value.ToJsonString());
        return document.RootElement.Clone();
    }

    private void SetBusy(bool isBusy)
    {
        BusyIndicator.Visibility = isBusy ? Visibility.Visible : Visibility.Collapsed;
        StudioPageHelpers.SetControlsEnabled(this, !isBusy);
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Title = severity == InfoBarSeverity.Success ? "Reactive apply complete" : "Reactive Lab";
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");
    private void OpenRender_Click(object sender, RoutedEventArgs e) => App.Navigate("render");
}
