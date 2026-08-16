using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class AiPlannerLabPage : Page
{
    private const string EmptyAnalysis = """
        {
          "basicInfo": {},
          "emotions": [],
          "themes": [],
          "visualImagery": [],
          "spectralFeatures": {},
          "energyCurve": []
        }
        """;

    private const string EmptyPlan = """
        {
          "scenes": [],
          "scenePlan": [],
          "direction": {},
          "renderManifest": {},
          "repairSuggestions": [],
          "approval": {}
        }
        """;

    public AiPlannerLabPage()
    {
        InitializeComponent();
        AnalysisJsonBox.Text = EmptyAnalysis;
        PlanJsonBox.Text = EmptyPlan;
        Loaded += AiPlannerLabPage_Loaded;
    }

    private async void AiPlannerLabPage_Loaded(object sender, RoutedEventArgs e)
    {
        Loaded -= AiPlannerLabPage_Loaded;
        await LoadProjectSummaryAsync(loadPayload: true);
    }

    private async void LoadLastPayload_Click(object sender, RoutedEventArgs e) =>
        await LoadProjectSummaryAsync(loadPayload: true);

    private async Task LoadProjectSummaryAsync(bool loadPayload)
    {
        var projectId = App.Services.Session.ActiveProjectId;
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ProjectSummaryText.Text = "No active project. Select one in Projects before importing a Planner payload.";
            ShowStatus("Select an active project first.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            var response = await App.Services.ApiClient.GetProjectAsync(projectId);
            var project = response.Project;
            ProjectSummaryText.Text = $"{project.Name} • {StudioPageHelpers.ShortId(project.Id)} • variant {App.Services.Session.SelectedVariantIndex + 1}";
            if (loadPayload && project.Meta.TryGetProperty("last_planner_lab", out var last) &&
                last.ValueKind == JsonValueKind.Object)
            {
                if (last.TryGetProperty("analysis", out var analysis))
                {
                    AnalysisJsonBox.Text = StudioPageHelpers.FormatJson(analysis);
                }

                if (last.TryGetProperty("plan", out var plan))
                {
                    PlanJsonBox.Text = StudioPageHelpers.FormatJson(plan);
                }

                if (last.TryGetProperty("settings", out var settings))
                {
                    LoadSettings(settings);
                }
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

    private async void ImportPlanner_Click(object sender, RoutedEventArgs e)
    {
        var projectId = App.Services.Session.ActiveProjectId;
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ShowStatus("Select an active project first.", InfoBarSeverity.Warning);
            return;
        }

        if (!TryParseObject(AnalysisJsonBox.Text, "Analysis", out var analysis) ||
            !TryParseObject(PlanJsonBox.Text, "Plan", out var plan))
        {
            return;
        }

        var request = new JsonObject
        {
            ["analysis"] = analysis,
            ["plan"] = plan,
            ["settings"] = BuildSettings(),
            ["apply_timeline"] = ApplyTimelineCheckBox.IsChecked == true,
            ["overwrite_timeline"] = OverwriteTimelineCheckBox.IsChecked == true,
        };

        SetBusy(true);
        try
        {
            await App.Services.ApiClient.ImportPlannerLabAsync(projectId, ToJsonElement(request));
            ShowStatus("Planner payload imported. Canonical analysis, plan, Visual DNA, and requested timeline state were updated by the backend.", InfoBarSeverity.Success);
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

    private JsonObject BuildSettings() => new()
    {
        ["analysisFocus"] = SelectedText(AnalysisFocusCombo),
        ["promptStyle"] = SelectedText(PromptStyleCombo),
        ["promptDetail"] = SelectedText(PromptDetailCombo),
        ["aspectRatio"] = SelectedText(AspectRatioCombo),
        ["target"] = SelectedText(TargetCombo),
        ["sceneCount"] = (int)SceneCountBox.Value,
        ["subjectFocus"] = SubjectFocusBox.Text,
        ["creativeBrief"] = CreativeBriefBox.Text,
        ["negativePromptSeed"] = NegativePromptBox.Text,
        ["selectedVariantMode"] = SelectedText(VariantModeCombo),
    };

    private void LoadSettings(JsonElement settings)
    {
        SelectText(AnalysisFocusCombo, settings, "analysisFocus");
        SelectText(PromptStyleCombo, settings, "promptStyle");
        SelectText(PromptDetailCombo, settings, "promptDetail");
        SelectText(AspectRatioCombo, settings, "aspectRatio");
        SelectText(TargetCombo, settings, "target");
        SelectText(VariantModeCombo, settings, "selectedVariantMode");
        if (settings.TryGetProperty("sceneCount", out var sceneCount) && sceneCount.TryGetDouble(out var count))
        {
            SceneCountBox.Value = count;
        }
        SubjectFocusBox.Text = ReadString(settings, "subjectFocus");
        CreativeBriefBox.Text = ReadString(settings, "creativeBrief");
        NegativePromptBox.Text = ReadString(settings, "negativePromptSeed");
    }

    private bool TryParseObject(string json, string label, out JsonNode? node)
    {
        try
        {
            node = JsonNode.Parse(json);
            if (node is JsonObject)
            {
                return true;
            }
            ShowStatus($"{label} JSON must have an object at its root.", InfoBarSeverity.Warning);
        }
        catch (JsonException ex)
        {
            ShowStatus($"{label} JSON is invalid: {ex.Message}", InfoBarSeverity.Warning);
        }
        node = null;
        return false;
    }

    private static string SelectedText(ComboBox combo) =>
        (combo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? string.Empty;

    private static void SelectText(ComboBox combo, JsonElement source, string property)
    {
        var value = ReadString(source, property);
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

    private static string ReadString(JsonElement source, string property) =>
        source.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;

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
        StatusInfoBar.Title = severity == InfoBarSeverity.Success ? "Planner import complete" : "Planner";
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");
}
