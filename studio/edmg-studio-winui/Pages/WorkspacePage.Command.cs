using System.Text.Json;
using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class WorkspacePage
{
    private bool _commandRunning;
    private string? _commandProjectId;

    private void RestoreCommand(ProjectDto project)
    {
        if (_commandProjectId == project.Id) return;
        _commandProjectId = project.Id;
        _pendingAudioPath = null;
        PendingAudioText.Text = project.HasAudio ? $"Project audio: {project.AudioFileName}" : "No audio selected";
        CommandRenderer.SelectedIndex = 0;
        CommandBrief.Text = "";
        CommandStyle.Text = "";
        CommandModel.Text = "";
        CommandProvider.SelectedIndex = 0;
        CommandNativeAudio.IsChecked = false;
        if (project.Meta.ValueKind != JsonValueKind.Object || !project.Meta.TryGetProperty("workspace_command", out JsonElement saved)) return;
        if (saved.TryGetProperty("brief", out var brief)) CommandBrief.Text = brief.GetString() ?? "";
        if (saved.TryGetProperty("style", out var style)) CommandStyle.Text = style.GetString() ?? "";
        if (saved.TryGetProperty("model", out var model)) CommandModel.Text = model.GetString() ?? "";
        if (saved.TryGetProperty("native_audio", out var audio)) CommandNativeAudio.IsChecked = audio.ValueKind == JsonValueKind.True;
        if (saved.TryGetProperty("provider", out var provider))
            foreach (ComboBoxItem item in CommandProvider.Items)
                if ((string?)item.Tag == provider.GetString()) CommandProvider.SelectedItem = item;
    }

    private void CancelCommand_Click(object sender, RoutedEventArgs e)
    {
        CancelCurrentOperation();
        CommandStatus.Text = "Canceled. Completed stages remain in the project.";
    }

    private async void MakeCommand_Click(object sender, RoutedEventArgs e)
    {
        if (_commandRunning || !TryGetActiveProjectId(out string projectId) || ProtectUnsavedWorkflowEdits()) return;
        string provider = GetComboTag(CommandProvider, "configured");
        string? model = NullIfWhiteSpace(CommandModel.Text);
        string? brief = NullIfWhiteSpace(CommandBrief.Text);
        string? style = NullIfWhiteSpace(CommandStyle.Text);
        bool nativeAudio = CommandNativeAudio.IsChecked == true;
        _commandRunning = true;
        MakeCommandButton.IsEnabled = false;
        ProjectComboBox.IsEnabled = false;
        try
        {
            await RunBusyAsync("Creating direction", async token =>
            {
                try
                {
                    if (!string.IsNullOrWhiteSpace(_pendingAudioPath))
                    {
                        CommandStatus.Text = "Importing audio";
                        await using var stream = System.IO.File.OpenRead(_pendingAudioPath);
                        await App.Services.ApiClient.UploadAudioAsync(projectId, stream,
                            System.IO.Path.GetFileName(_pendingAudioPath), GetAudioContentType(_pendingAudioPath), token);
                        _pendingAudioPath = null;
                        PendingAudioText.Text = "Project audio selected";
                        await RefreshProjectSnapshotAsync(projectId, token);
                        CommandStatus.Text = "Analyzing imported audio";
                        AnalysisResponse importedAnalysis = await App.Services.ApiClient.AnalyzeAudioAsync(projectId, token);
                        if (!importedAnalysis.Ok) throw new InvalidOperationException("Audio analysis did not complete.");
                        await RefreshProjectSnapshotAsync(projectId, token);
                    }
                    if (_projectResponse?.Project.HasAnalysis != true)
                    {
                        CommandStatus.Text = "Analyzing audio";
                        AnalysisResponse analysis = await App.Services.ApiClient.AnalyzeAudioAsync(projectId, token);
                        if (!analysis.Ok) throw new InvalidOperationException("Audio analysis did not complete.");
                        await RefreshProjectSnapshotAsync(projectId, token);
                    }
                    token.ThrowIfCancellationRequested();
                    CommandStatus.Text = "Creating story, scenes, and visual direction";
                    _generatedPlan = await App.Services.ApiClient.GeneratePlanAsync(projectId,
                        new PlanRequest(_projectResponse?.Project.Name, brief, style,
                            NumberOfVariants: 1, MaximumScenes: 24,
                            ExpectedRevision: StudioPageHelpers.ExpectedRevision(_projectResponse?.Project),
                            Provider: provider, Model: model, NativeAudio: nativeAudio),
                        provider == "local" ? "local" : "ai", token);
                    await RefreshProjectSnapshotAsync(projectId, token);
                    _session.SelectedVariantIndex = 0;
                    CommandStatus.Text = "Preparing editable direction and motion";
                    // Plan generation already publishes the shared planner draft.
                    // Preparing again would replace it with the previously saved direction.
                    await LoadSelectedProjectAsync(projectId, token);
                    string actualProvider = _generatedPlan?.AdditionalData?.GetValueOrDefault("provider").ToString() ?? provider;
                    CommandStatus.Text = $"Draft ready ({actualProvider}). Edit below or continue to Render.";
                }
                catch (OperationCanceledException) { CommandStatus.Text = "Canceled. Completed stages remain in the project."; throw; }
                catch { CommandStatus.Text = "Creation failed. Your saved project and completed stages are retained."; throw; }
            });
        }
        finally { _commandRunning = false; MakeCommandButton.IsEnabled = true; ProjectComboBox.IsEnabled = true; }
    }

    private async void CommandRender_Click(object sender, RoutedEventArgs e)
    {
        if (_commandRunning || !TryGetActiveProjectId(out string projectId)) return;
        await RunBusyAsync("Preparing render handoff", async token =>
        {
            if (_workflowStatus == "draft" && _workflowDraftId is string draftId)
            {
                using JsonDocument document = JsonDocument.Parse(BuildWorkflowDocument().ToJsonString());
                JsonElement response = await App.Services.ApiClient.ApplyDirectorWorkflowAsync(projectId,
                    new DirectorWorkflowReviewRequest(_workflowRevision, draftId, document.RootElement.Clone()), token);
                ApplyWorkflowResponse(projectId, response);
                await RefreshProjectSnapshotAsync(projectId, token);
            }
            token.ThrowIfCancellationRequested();
            _session.SetRenderContext("workspace-engine:" + GetComboTag(CommandRenderer, "auto"));
            NavigateTo("render");
        });
    }
}
