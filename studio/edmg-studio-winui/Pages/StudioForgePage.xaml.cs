using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using System.Text;
using System.Text.Json;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class StudioForgePage : Page
{
  public StudioForgePage()
  {
    InitializeComponent();
  }

  protected override async void OnNavigatedTo(NavigationEventArgs e)
  {
    base.OnNavigatedTo(e);
    await RefreshReadinessAsync();
  }

  private async void Refresh_Click(object sender, RoutedEventArgs e)
  {
    await RefreshReadinessAsync();
  }

  private void Navigate_Click(object sender, RoutedEventArgs e)
  {
    if (sender is Button { Tag: string destination })
    {
      App.Navigate(destination);
    }
  }

  private async Task RefreshReadinessAsync()
  {
    try
    {
      SetBusy(true);
      Task<bool> runtimeTask = LoadRuntimeReadinessAsync();
      Task<bool> projectTask = LoadProjectReadinessAsync();
      _ = await Task.WhenAll(runtimeTask, projectTask);
      bool allReady = await runtimeTask && await projectTask;
      ShowStatus(
          allReady
              ? "Forge readiness probes completed."
              : "Forge readiness completed with unavailable optional services. Review the details below.",
          allReady ? InfoBarSeverity.Success : InfoBarSeverity.Warning);
    }
    catch (Exception ex)
    {
      SetNextAction("Forge could not read the current backend or project state. Check the connection in Setup, then refresh.", "Open Setup", "setup");
      ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
    }
    finally
    {
      SetBusy(false);
    }
  }

  private async Task<bool> LoadRuntimeReadinessAsync()
  {
    Task<string>[] probes = new Task<string>[]
    {
            ProbeTypedAsync("Health", async () =>
            {
                HealthResponse health = await App.Services.ApiClient.GetHealthAsync();
                return health.Ok ? $"ready · version {health.Version}" : "backend reported not ready";
            }),
            ProbeJsonAsync("System readiness", App.Services.ApiClient.GetSystemReadinessAsync),
            ProbeTypedAsync("Setup status", async () =>
            {
                SetupStatusResponse status = await App.Services.ApiClient.GetSetupStatusAsync();
                return status.Ok
                    ? $"{status.Tasks.Count} tracked task(s)"
                    : "setup status reported not ready";
            }),
            ProbeJsonAsync("Configuration", App.Services.ApiClient.GetConfigAsync),
            ProbeJsonAsync("AI runtime", App.Services.ApiClient.GetAiStatusAsync),
            ProbeJsonAsync("Render providers", App.Services.ApiClient.GetRenderProvidersAsync),
            ProbeJsonAsync("ComfyUI", App.Services.ApiClient.GetComfyUiCapabilitiesAsync),
            ProbeJsonAsync("Model catalogue", App.Services.ApiClient.GetModelCatalogAsync),
            ProbeTypedAsync("Model tasks", async () =>
            {
                ModelTaskListResponse tasks = await App.Services.ApiClient.GetModelTasksAsync();
                return $"{tasks.Tasks?.Count ?? 0} tracked task(s)";
            }),
    };

    string[] results = await Task.WhenAll(probes);
    RuntimeSummaryTextBlock.Text = string.Join(Environment.NewLine, results);
    return results.All(result => !result.StartsWith("!", StringComparison.Ordinal));
  }

  private async Task<bool> LoadProjectReadinessAsync()
  {
    string projectId = App.Services.Session.ActiveProjectId;
    if (string.IsNullOrWhiteSpace(projectId))
    {
      SetNextAction("Start in Workspace: create or select a project and import an audio track.", "Open Workspace", "workspace");
      ProjectIdentityTextBlock.Text = "No active project selected.";
      ProjectSummaryTextBlock.Text =
          "Select or create a project in Workspace to inspect its Forge readiness.";
      BridgePreviewTextBox.Text =
          "Unreal and live-cue probes require an active project and were not requested.";
      return true;
    }

    Task<ProjectResponse> projectTask = App.Services.ApiClient.GetProjectAsync(projectId);
    Task<JsonElement> outputsTask = App.Services.ApiClient.GetOutputsAsync(projectId);
    Task jobsTask = App.Services.JobsActivity.RefreshAsync();
    Task<(JsonElement Value, string? Error)> unrealTask = ProbeJsonValueAsync(
            () => App.Services.ApiClient.GetUnrealPreviewAsync(
                projectId,
                App.Services.Session.SelectedVariantIndex));
    Task<(JsonElement Value, string? Error)> liveCueTask = ProbeJsonValueAsync(
            () => App.Services.ApiClient.GetLiveCuePublishStatusAsync(projectId));

    await Task.WhenAll(projectTask, outputsTask, jobsTask, unrealTask, liveCueTask);

    ProjectDto project = (await projectTask).Project;
    JsonElement outputs = await outputsTask;
    await jobsTask;
    StudioJobsActivitySnapshot jobs = App.Services.JobsActivity.Snapshot;
    if (jobs.Error is not null)
    {
      throw new InvalidOperationException("Studio job activity is unavailable.", jobs.Error);
    }

    (JsonElement Value, string? Error) unreal = await unrealTask;
    (JsonElement Value, string? Error) liveCue = await liveCueTask;

    ProjectIdentityTextBlock.Text = $"{project.Name} · {project.Id}";
    int artifactCount = StudioOutputCatalog.CountArtifacts(outputs);
    if (!project.HasAudio)
    {
      SetNextAction("Import audio into this project. Forge needs a source track before analysis and planning.", "Import audio in Workspace", "workspace");
    }
    else if (!project.HasAnalysis)
    {
      SetNextAction("Analyze the audio to create reusable timing and structure for the plan.", "Analyze in Workspace", "workspace");
    }
    else if (!project.HasPlan)
    {
      SetNextAction("Create and review a plan; choose a provider and keep the draft editable before render.", "Open AI Planner", "plannerLab");
    }
    else if (artifactCount == 0)
    {
      SetNextAction("Your plan is ready for a render profile and generation job. Check Models if a provider is unavailable.", "Configure Render", "render");
    }
    else
    {
      SetNextAction("Generated media is available. Review the cut and continuity, then inspect or export the final output.", "Open Review", "review");
    }
    StringBuilder summary = new StringBuilder()
            .AppendLine($"Audio:    {ReadyLabel(project.HasAudio)}")
            .AppendLine($"Analysis: {ReadyLabel(project.HasAnalysis)}")
            .AppendLine($"Plan:     {ReadyLabel(project.HasPlan)}")
            .AppendLine($"Outputs:  {artifactCount} artifact(s)")
            .Append($"Jobs:     {jobs.Jobs.Count(job => string.Equals(job.ProjectId, projectId, StringComparison.OrdinalIgnoreCase))} tracked");
    ProjectSummaryTextBlock.Text = summary.ToString();

    BridgePreviewTextBox.Text =
        $"Unreal variant {App.Services.Session.SelectedVariantIndex + 1}: {SummarizeProbe(unreal)}{Environment.NewLine}" +
        $"Live-cue publisher: {SummarizeProbe(liveCue)}";
    return unreal.Error is null && liveCue.Error is null;
  }

  private async Task<string> ProbeJsonAsync(
      string label,
      Func<CancellationToken, Task<JsonElement>> probe)
  {
    try
    {
      JsonElement result = await probe(CancellationToken.None);
      return $"✓ {label}: {SummarizeJson(result)}";
    }
    catch (Exception ex)
    {
      return $"! {label}: {StudioPageHelpers.GetErrorMessage(ex)}";
    }
  }

  private static async Task<string> ProbeTypedAsync(string label, Func<Task<string>> probe)
  {
    try
    {
      return $"✓ {label}: {await probe()}";
    }
    catch (Exception ex)
    {
      return $"! {label}: {StudioPageHelpers.GetErrorMessage(ex)}";
    }
  }

  private static async Task<(JsonElement Value, string? Error)> ProbeJsonValueAsync(
      Func<Task<JsonElement>> probe)
  {
    try
    {
      return (await probe(), null);
    }
    catch (Exception ex)
    {
      return (default, StudioPageHelpers.GetErrorMessage(ex));
    }
  }

  private void SetBusy(bool isBusy)
  {
    RuntimeProgressRing.IsActive = isBusy;
    StudioPageHelpers.SetControlsEnabled(this, !isBusy);
  }

  private void SetNextAction(string message, string buttonLabel, string destination)
  {
    NextActionTextBlock.Text = message;
    NextActionButton.Content = buttonLabel;
    NextActionButton.Tag = destination;
  }

  private void ShowStatus(string message, InfoBarSeverity severity)
  {
    StatusInfoBar.Message = message;
    StatusInfoBar.Severity = severity;
    StatusInfoBar.IsOpen = true;
  }

  private static string ReadyLabel(bool isReady)
  {
    return isReady ? "ready" : "missing";
  }

  private static string SummarizeProbe((JsonElement Value, string? Error) probe)
  {
    return probe.Error is null ? SummarizeJson(probe.Value) : $"unavailable · {probe.Error}";
  }

  private static string SummarizeJson(JsonElement value)
  {
    return value.ValueKind == JsonValueKind.Object
      ? value.TryGetProperty("ok", out JsonElement ok)
        ? $"ok: {ok}"
        : value.TryGetProperty("status", out JsonElement status) ? $"status: {status}" : $"{value.EnumerateObject().Count()} field(s)"
      : value.ValueKind switch
      {
        JsonValueKind.Array => $"{value.GetArrayLength()} item(s)",
        JsonValueKind.Null or JsonValueKind.Undefined => "no payload",
        _ => value.ToString(),
      };
  }

}
