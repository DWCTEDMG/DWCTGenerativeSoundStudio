using System.Text;
using System.Text.Json;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

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

    private async void Refresh_Click(object sender, RoutedEventArgs e) =>
        await RefreshReadinessAsync();

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
            await Task.WhenAll(LoadRuntimeReadinessAsync(), LoadProjectReadinessAsync());
            ShowStatus("Forge readiness probes completed.", InfoBarSeverity.Success);
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

    private async Task LoadRuntimeReadinessAsync()
    {
        var probes = new Task<string>[]
        {
            ProbeTypedAsync("Health", async () =>
            {
                var health = await App.Services.ApiClient.GetHealthAsync();
                return health.Ok ? $"ready · version {health.Version}" : "backend reported not ready";
            }),
            ProbeJsonAsync("System readiness", App.Services.ApiClient.GetSystemReadinessAsync),
            ProbeJsonAsync("Setup status", App.Services.ApiClient.GetSetupStatusAsync),
            ProbeJsonAsync("Configuration", App.Services.ApiClient.GetConfigAsync),
            ProbeJsonAsync("AI runtime", App.Services.ApiClient.GetAiStatusAsync),
            ProbeJsonAsync("Render providers", App.Services.ApiClient.GetRenderProvidersAsync),
            ProbeJsonAsync("ComfyUI", App.Services.ApiClient.GetComfyUiCapabilitiesAsync),
            ProbeJsonAsync("Model catalogue", App.Services.ApiClient.GetModelCatalogAsync),
            ProbeTypedAsync("Model tasks", async () =>
            {
                var tasks = await App.Services.ApiClient.GetModelTasksAsync();
                return $"{tasks.Tasks?.Count ?? 0} tracked task(s)";
            }),
        };

        RuntimeSummaryTextBlock.Text = string.Join(Environment.NewLine, await Task.WhenAll(probes));
    }

    private async Task LoadProjectReadinessAsync()
    {
        var projectId = App.Services.Session.ActiveProjectId;
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ProjectIdentityTextBlock.Text = "No active project selected.";
            ProjectSummaryTextBlock.Text =
                "Select or create a project in Workspace to inspect its Forge readiness.";
            BridgePreviewTextBox.Text =
                "Unreal and live-cue probes require an active project and were not requested.";
            return;
        }

        var projectTask = App.Services.ApiClient.GetProjectAsync(projectId);
        var outputsTask = App.Services.ApiClient.GetOutputsAsync(projectId);
        var jobsTask = App.Services.ApiClient.GetProjectJobsAsync(projectId);
        var unrealTask = ProbeJsonValueAsync(
            () => App.Services.ApiClient.GetUnrealPreviewAsync(projectId, 0));
        var liveCueTask = ProbeJsonValueAsync(
            () => App.Services.ApiClient.GetLiveCuePublishStatusAsync(projectId));

        await Task.WhenAll(projectTask, outputsTask, jobsTask, unrealTask, liveCueTask);

        var project = (await projectTask).Project;
        var outputs = await outputsTask;
        var jobs = await jobsTask;
        var unreal = await unrealTask;
        var liveCue = await liveCueTask;

        ProjectIdentityTextBlock.Text = $"{project.Name} · {project.Id}";
        var summary = new StringBuilder()
            .AppendLine($"Audio:    {ReadyLabel(project.HasAudio)}")
            .AppendLine($"Analysis: {ReadyLabel(project.HasAnalysis)}")
            .AppendLine($"Plan:     {ReadyLabel(project.HasPlan)}")
            .AppendLine($"Outputs:  {CountCollection(outputs)} item(s)")
            .Append($"Jobs:     {jobs.Jobs.Count} tracked");
        ProjectSummaryTextBlock.Text = summary.ToString();

        BridgePreviewTextBox.Text =
            $"Unreal variant 0: {SummarizeProbe(unreal)}{Environment.NewLine}" +
            $"Live-cue publisher: {SummarizeProbe(liveCue)}";
    }

    private async Task<string> ProbeJsonAsync(
        string label,
        Func<CancellationToken, Task<JsonElement>> probe)
    {
        try
        {
            var result = await probe(CancellationToken.None);
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

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private static string ReadyLabel(bool isReady) => isReady ? "ready" : "missing";

    private static string SummarizeProbe((JsonElement Value, string? Error) probe) =>
        probe.Error is null ? SummarizeJson(probe.Value) : $"unavailable · {probe.Error}";

    private static string SummarizeJson(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Object)
        {
            if (value.TryGetProperty("ok", out var ok))
            {
                return $"ok: {ok}";
            }

            if (value.TryGetProperty("status", out var status))
            {
                return $"status: {status}";
            }

            return $"{value.EnumerateObject().Count()} field(s)";
        }

        return value.ValueKind switch
        {
            JsonValueKind.Array => $"{value.GetArrayLength()} item(s)",
            JsonValueKind.Null or JsonValueKind.Undefined => "no payload",
            _ => value.ToString(),
        };
    }

    private static int CountCollection(JsonElement value)
    {
        if (value.ValueKind == JsonValueKind.Array)
        {
            return value.GetArrayLength();
        }

        if (value.ValueKind == JsonValueKind.Object)
        {
            foreach (var propertyName in new[] { "outputs", "items", "artifacts" })
            {
                if (value.TryGetProperty(propertyName, out var collection)
                    && collection.ValueKind == JsonValueKind.Array)
                {
                    return collection.GetArrayLength();
                }
            }
        }

        return 0;
    }
}
