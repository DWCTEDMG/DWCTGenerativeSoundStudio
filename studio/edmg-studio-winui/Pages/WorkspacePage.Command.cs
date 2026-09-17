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
        CommandDirectorModel.SelectedIndex = 0;
        CommandProposalItems.Clear();
        CommandProposalSection.Visibility = Visibility.Collapsed;
        CommandProgress.Value = 0;
        if (project.Meta.ValueKind != JsonValueKind.Object || !project.Meta.TryGetProperty("workspace_command", out JsonElement saved)) return;
        if (saved.TryGetProperty("brief", out var brief)) CommandBrief.Text = brief.GetString() ?? "";
        if (saved.TryGetProperty("style", out var style)) CommandStyle.Text = style.GetString() ?? "";
        if (saved.TryGetProperty("model", out var model)) CommandModel.Text = model.GetString() ?? "";
        if (saved.TryGetProperty("native_audio", out var audio)) CommandNativeAudio.IsChecked = audio.ValueKind == JsonValueKind.True;
        if (saved.TryGetProperty("provider", out var provider))
            foreach (ComboBoxItem item in CommandProvider.Items)
                if ((string?)item.Tag == provider.GetString()) CommandProvider.SelectedItem = item;
        if (GetComboTag(CommandProvider, "internal_qwen") == "internal_qwen")
        {
            foreach (ComboBoxItem item in CommandDirectorModel.Items)
                if ((string?)item.Tag == CommandModel.Text) CommandDirectorModel.SelectedItem = item;
            CommandModel.Text = "";
        }
        CommandProvider_SelectionChanged(CommandProvider, null!);
    }

    private async void CancelCommand_Click(object sender, RoutedEventArgs e)
    {
        CancelCurrentOperation();
        CommandStatus.Text = "Canceled. Completed stages remain in the project.";
        if (_directorDraftJobStatus is "queued" or "running" or "paused" &&
            _directorProjectId is string projectId && _directorDraftJobId is string jobId)
        {
            await RunBusyAsync("Canceling Director", async token =>
            {
                var response = await App.Services.ApiClient.CancelJobAsync(projectId, jobId, token);
                _directorDraftJobStatus = response.Job.Status;
            });
        }
    }

    private async void MakeCommand_Click(object sender, RoutedEventArgs e)
    {
        if (_commandRunning || !TryGetActiveProjectId(out string projectId) || ProtectUnsavedWorkflowEdits()) return;
        string provider = GetComboTag(CommandProvider, "internal_qwen");
        bool internalModel = provider == "internal_qwen";
        string? directorModel = NullIfWhiteSpace(GetComboTag(CommandDirectorModel, ""));
        string? model = NullIfWhiteSpace(CommandModel.Text);
        string? brief = NullIfWhiteSpace(CommandBrief.Text);
        string? style = NullIfWhiteSpace(CommandStyle.Text);
        bool nativeAudio = CommandNativeAudio.IsChecked == true;
        SetCommandBusy(true);
        try
        {
            await RunBusyAsync("Creating direction", async token =>
            {
                try
                {
                    if (_projectResponse?.Project.HasAudio != true && string.IsNullOrWhiteSpace(_pendingAudioPath))
                        throw new InvalidOperationException("Choose source audio before creating direction.");
                    CommandProgress.Value = 5;
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
                    CommandProgress.Value = 30;
                    CommandStatus.Text = "Creating story, scenes, and visual direction";
                    // Reuse reviewed camera/motion data when Qwen already has a current draft.
                    await LoadWorkflowAsync(projectId, token);
                    if (!internalModel || WorkflowSceneItems.Count == 0)
                    {
                        _generatedPlan = await App.Services.ApiClient.GeneratePlanAsync(projectId,
                        new PlanRequest(_projectResponse?.Project.Name, brief, style,
                            NumberOfVariants: 1, MaximumScenes: 24,
                            ExpectedRevision: StudioPageHelpers.ExpectedRevision(_projectResponse?.Project),
                            Provider: internalModel ? "local" : provider, Model: internalModel ? null : model, NativeAudio: nativeAudio),
                        internalModel || provider == "local" ? "local" : "ai", token);
                    }
                    await RefreshProjectSnapshotAsync(projectId, token);
                    _session.SelectedVariantIndex = 0;
                    CommandStatus.Text = "Preparing editable direction and motion";
                    // Plan generation already publishes the shared planner draft.
                    // Preparing again would replace it with the previously saved direction.
                    await LoadSelectedProjectAsync(projectId, token);
                    if (internalModel)
                    {
                        CommandStatus.Text = "Baseline ready. Checking Qwen readiness";
                        JsonElement readiness = await App.Services.ApiClient.GetDirectorReadinessAsync(
                            projectId, "automatic", "automatic", token, directorModel);
                        JsonElement director = readiness.GetProperty("director");
                        if (!director.GetProperty("ready").GetBoolean())
                        {
                            string reason = director.TryGetProperty("reason", out JsonElement reasonValue)
                                ? reasonValue.GetString() ?? "The selected Qwen runtime is unavailable."
                                : "The selected Qwen runtime is unavailable.";
                            CommandStatus.Text = $"Baseline draft ready. Qwen was not run: {reason}";
                            CommandProgress.Value = 100;
                            ShowStatus("Baseline draft retained", reason, InfoBarSeverity.Warning);
                            return;
                        }

                        try
                        {
                            CommandStatus.Text = "Queuing Qwen direction";
                            string instruction = string.Join("\n", new[] { brief, style is null ? null : "Visual style: " + style }
                                .Where(value => !string.IsNullOrWhiteSpace(value)));
                            if (instruction.Length == 0)
                                instruction = "Direct this music video using the analyzed rhythm, sections, and transcript. Preserve scene timing and locked appearances; develop coherent visual storytelling, camera movement, and subject actions.";
                            var request = new DirectorGenerationRequest(_directorRevision, Guid.NewGuid().ToString(),
                                instruction, ModelId: directorModel);
                            JsonElement queued = await App.Services.ApiClient.GenerateDirectorAsync(projectId, request, token);
                            _directorDraftJobId = queued.GetProperty("job_id").GetString()!;
                            _directorDraftJobStatus = queued.GetProperty("status").GetString();
                            _directorRevision = queued.GetProperty("revision").GetInt64();
                            _session.SetSelectedJob(projectId, _directorDraftJobId);
                            await WaitForCommandDirectorAsync(projectId, _directorDraftJobId, token);
                        }
                        catch (OperationCanceledException)
                        {
                            throw;
                        }
                        catch (Exception error) when (error is HttpRequestException or InvalidOperationException)
                        {
                            CommandStatus.Text = $"Baseline draft ready. Qwen stopped: {error.Message}";
                            CommandProgress.Value = 100;
                            ShowStatus("Baseline draft retained", error.Message, InfoBarSeverity.Warning);
                        }
                        return;
                    }
                    string actualProvider = _generatedPlan?.AdditionalData?.GetValueOrDefault("provider").ToString() ?? provider;
                    CommandStatus.Text = $"Draft ready ({actualProvider}). Edit below or continue to Render.";
                    CommandProgress.Value = 100;
                }
                catch (OperationCanceledException) { CommandStatus.Text = "Canceled. Completed stages remain in the project."; throw; }
                catch (Exception error) { CommandStatus.Text = $"Creation stopped: {error.Message}"; throw; }
            });
        }
        finally { SetCommandBusy(false); }
    }

    private async void CommandRender_Click(object sender, RoutedEventArgs e)
    {
        if (_commandRunning || !TryGetActiveProjectId(out string projectId)) return;
        if (WorkspacePlannerFrame.Content is AiPlannerLabPage { HasUnsavedEdits: true } ||
            WorkspaceReactiveFrame.Content is ReactiveLabPage { HasUnsavedEdits: true })
        {
            ShowStatus("Save editor changes", "Save your Planner and Reactive edits before applying the combined draft.", InfoBarSeverity.Warning);
            return;
        }
        if (_directorReviewedJobId is not null && ProtectUnsavedWorkflowEdits()) return;
        await RunBusyAsync("Preparing render handoff", async token =>
        {
            await UseCommandProposalAsync(projectId, token);
            if (!HasUnsavedWorkflowEdits()) await LoadWorkflowAsync(projectId, token);
            if (_workflowStatus == "draft" && _workflowDraftId is string draftId)
            {
                using JsonDocument document = JsonDocument.Parse(BuildWorkflowDocument().ToJsonString());
                JsonElement response = await App.Services.ApiClient.ApplyDirectorWorkflowAsync(projectId,
                    new DirectorWorkflowReviewRequest(_workflowRevision, draftId, document.RootElement.Clone()), token);
                ApplyWorkflowResponse(projectId, response);
                await RefreshProjectSnapshotAsync(projectId, token);
            }
            else if (_workflowStatus != "applied")
                throw new InvalidOperationException("Create or recover a shared draft before opening Render.");
            token.ThrowIfCancellationRequested();
            _session.SetRenderContext("workspace-engine:" + GetComboTag(CommandRenderer, "auto"));
            NavigateTo("render");
        });
    }
}
