using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class WorkspacePage
{
    private const string DefaultQwenModelId = "hf_qwen3_vl_8b_gguf_director";
    private const string ManagedWhisperModelId = "hf_whisper_large_v3_turbo_internal";

    public ObservableCollection<WorkspaceDirectionSceneItem> CommandProposalItems { get; } = [];

    private void CommandProvider_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CommandDirectorModel is null || CommandModel is null || CommandNativeAudio is null) return;
        bool internalModel = GetComboTag(CommandProvider, "internal_qwen") == "internal_qwen";
        CommandDirectorModel.Visibility = internalModel ? Visibility.Visible : Visibility.Collapsed;
        CommandModel.Visibility = internalModel ? Visibility.Collapsed : Visibility.Visible;
        CommandNativeAudio.IsEnabled = !internalModel;
        if (internalModel) CommandNativeAudio.IsChecked = false;
        UpdateCommandProviderStatus();
        if (!_restoringCommand) _ = RefreshCommandQwenReadinessAsync();
    }

    private void CommandDirectorModel_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_restoringCommand) _ = RefreshCommandQwenReadinessAsync();
    }

    private void CommandModel_TextChanged(object sender, TextChangedEventArgs e) => UpdateCommandProviderStatus();

    private void CommandModels_Click(object sender, RoutedEventArgs e) => NavigateTo("models");
    private void CommandSettings_Click(object sender, RoutedEventArgs e) => NavigateTo("settings");

    private void SetCommandBusy(bool busy)
    {
        _commandRunning = busy;
        MakeCommandButton.IsEnabled = !busy;
        CancelCommandButton.IsEnabled = busy;
        CommandRenderButton.IsEnabled = !busy;
        CommandReviewButton.IsEnabled = !busy;
        UseCommandProposalButton.IsEnabled = !busy;
        ProjectComboBox.IsEnabled = !busy;
        CommandProvider.IsEnabled = !busy;
        CommandDirectorModel.IsEnabled = !busy;
        WorkspaceModeSelector.IsEnabled = !busy;
        PlannerSection.IsEnabled = !busy;
        ReactiveSection.IsEnabled = !busy;
        RefreshWorkspaceButton.IsEnabled = !busy;
        AudioAnalysisExpander.IsEnabled = !busy;
        MediaPoolExpander.IsEnabled = !busy;
        ReferenceAssetsExpander.IsEnabled = !busy;
        PlanExpander.IsEnabled = !busy;
        DirectorExpander.IsEnabled = !busy;
        WorkflowScenesList.IsEnabled = !busy;
        WorkflowThemeTextBox.IsEnabled = !busy && _workflowStatus == "draft";
        WorkflowStyleTextBox.IsEnabled = !busy && _workflowStatus == "draft";
    }

    private async Task WaitForCommandDirectorAsync(string projectId, string jobId, CancellationToken token)
    {
        JsonElement reviewed = await new WorkspaceDirectorRunner(App.Services.ApiClient).WaitForReviewAsync(
            projectId, jobId, _directorRevision, job =>
            {
                _directorDraftJobStatus = job.Status;
                CommandStatus.Text = job.Progress?.Message ?? $"Qwen Director: {job.Status}";
                CommandProgress.Value = 35 + Math.Clamp(job.Progress?.Percent ?? 0, 0, 100) * .6;
            }, token);
        _directorRevision = reviewed.GetProperty("revision").GetInt64();
        _directorReviewedJobId = jobId;
        _directorDraftJobStatus = "reviewed";
        WorkspaceDirectorDraftTextBox.Text = reviewed.GetProperty("document").ToString();
        JsonObject document = JsonNode.Parse(reviewed.GetProperty("document").GetRawText())!.AsObject();
        CommandProposalItems.Clear();
        int rate = 48000;
        if (_projectResponse?.Project.Meta is JsonElement { ValueKind: JsonValueKind.Object } meta &&
            meta.TryGetProperty("timeline", out var timeline) && timeline.TryGetProperty("sample_rate", out var sampleRate) &&
            sampleRate.TryGetInt32(out int hz) && hz > 0) rate = hz;
        foreach (JsonObject scene in (document["scenes"] as JsonArray ?? []).OfType<JsonObject>())
            CommandProposalItems.Add(new WorkspaceDirectionSceneItem(scene, rate, false, () => { }));
        CommandProposalSummary.Text = $"{CommandProposalItems.Count} scenes | {document["story_bible"]?["project_theme"]}";
        CommandProposalSection.Visibility = Visibility.Visible;
        CommandProposalSection.IsExpanded = true;
        CommandProgress.Value = 100;
        CommandStatus.Text = "Qwen draft ready for review. Use draft to refine it, or apply and open Render.";
        UpdateDirectorWorkspaceAvailability();
    }

    private async void CommandReview_Click(object sender, RoutedEventArgs e)
    {
        if (_commandRunning || !TryGetActiveProjectId(out string projectId)) return;
        SetCommandBusy(true);
        try
        {
            await RunBusyAsync("Recovering Director draft", async token =>
            {
                if (!await CheckpointWorkspaceEditsAsync(projectId, token)) return;
                await LoadSelectedProjectAsync(projectId, token);
                if (_directorDraftJobId is not string jobId)
                    throw new InvalidOperationException("This project has no Director job to recover.");
                await WaitForCommandDirectorAsync(projectId, jobId, token);
            });
        }
        finally { SetCommandBusy(false); }
    }

    private async Task UseCommandProposalAsync(string projectId, CancellationToken token)
    {
        if (_directorReviewedJobId is not string jobId) return;
        JsonElement response = await App.Services.ApiClient.ApplyDirectorDraftAsync(projectId,
            jobId, new DirectorApplyRequest(_directorRevision), token);
        ApplyDirectorWorkspaceDocument(response);
        await LoadSelectedProjectAsync(projectId, token);
        CommandProposalItems.Clear();
        CommandProposalSection.Visibility = Visibility.Collapsed;
        CommandStatus.Text = "Shared direction and reactive draft ready to refine.";
    }

    private async void UseCommandProposal_Click(object sender, RoutedEventArgs e)
    {
        if (_commandRunning || !TryGetActiveProjectId(out string projectId)) return;
        SetCommandBusy(true);
        try
        {
            await RunBusyAsync("Preparing shared direction", async token =>
            {
                if (!await CheckpointWorkspaceEditsAsync(projectId, token)) return;
                await UseCommandProposalAsync(projectId, token);
            });
        }
        finally { SetCommandBusy(false); }
    }

    private async Task LoadCommandTranscriptionAsync(CancellationToken token)
    {
        try
        {
            JsonElement response = await App.Services.ApiClient.GetTranscriptionSettingsAsync(token);
            JsonElement settings = response.TryGetProperty("settings", out var nested) ? nested : response;
            string provider = settings.TryGetProperty("provider", out var value) ? value.GetString() ?? "unknown" : "unknown";
            string model = settings.TryGetProperty("model", out var selected) ? selected.GetString() ?? "" : "";
            string device = settings.TryGetProperty("device", out var configuredDevice) ? configuredDevice.GetString() ?? "auto" : "auto";
            string label = provider.Replace("faster_whisper", "Whisper").Replace("transformers_whisper", "Whisper (Transformers)");
            if (provider is "faster_whisper" or "transformers_whisper")
            {
                ModelRuntimeStatus status = await App.Services.ApiClient.GetModelRuntimeReadinessAsync(ManagedWhisperModelId, token);
                CommandTranscriptionStatus.Text = $"Whisper configured: {label} {model} on {device}\n" +
                    WorkspaceReadinessSummary.Model("Managed Whisper package", status);
            }
            else
            {
                CommandTranscriptionStatus.Text = $"Transcription configured: {label} {model} on {device}. Runtime qualification is not reported by the managed Whisper package.";
            }
        }
        catch (OperationCanceledException) { throw; }
        catch (HttpRequestException error) { CommandTranscriptionStatus.Text = $"Whisper readiness unavailable: {error.Message}"; }
        catch (StudioApiException error) { CommandTranscriptionStatus.Text = $"Whisper readiness unavailable: {error.UserFacingMessage}"; }
        catch (InvalidOperationException error) { CommandTranscriptionStatus.Text = $"Whisper readiness unavailable: {error.Message}"; }
        catch (JsonException error) { CommandTranscriptionStatus.Text = $"Whisper readiness unavailable: {error.Message}"; }
    }

    private void UpdateCommandProviderStatus()
    {
        if (CommandProviderStatus is null || CommandProvider is null || CommandModel is null) return;
        CommandProviderStatus.Text = WorkspaceReadinessSummary.Provider(
            GetComboTag(CommandProvider, "internal_qwen"), NullIfWhiteSpace(CommandModel.Text));
    }

    private async Task RefreshCommandQwenReadinessAsync(CancellationToken token = default)
    {
        if (CommandQwenStatus is null || CommandProvider is null || CommandDirectorModel is null) return;
        if (GetComboTag(CommandProvider, "internal_qwen") != "internal_qwen")
        {
            CommandQwenStatus.Text = "Internal Qwen readiness is not applicable while BYOM is selected.";
            return;
        }

        string modelId = GetComboTag(CommandDirectorModel, DefaultQwenModelId);
        if (string.IsNullOrWhiteSpace(modelId)) modelId = DefaultQwenModelId;
        CommandQwenStatus.Text = "Qwen: checking configuration and runtime evidence";
        try
        {
            ModelRuntimeStatus status = await App.Services.ApiClient.GetModelRuntimeReadinessAsync(modelId, token);
            CommandQwenStatus.Text = WorkspaceReadinessSummary.Model("Qwen", status);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
        catch (HttpRequestException error) { CommandQwenStatus.Text = $"Qwen: unavailable - readiness could not be read: {error.Message}"; }
        catch (StudioApiException error) { CommandQwenStatus.Text = $"Qwen: unavailable - readiness could not be read: {error.UserFacingMessage}"; }
        catch (InvalidOperationException error) { CommandQwenStatus.Text = $"Qwen: unavailable - readiness could not be read: {error.Message}"; }
        catch (JsonException error) { CommandQwenStatus.Text = $"Qwen: unavailable - readiness could not be read: {error.Message}"; }
    }
}
