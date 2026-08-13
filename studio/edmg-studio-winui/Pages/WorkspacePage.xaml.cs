using System.Collections.ObjectModel;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class WorkspacePage : Page, IStudioRefreshable
{
    private ProjectDto? _activeProject;
    private StorageFile? _pendingAudio;
    private CancellationTokenSource? _operationCancellation;
    private CancellationTokenSource? _projectLoadCancellation;
    private long _projectLoadGeneration;
    private bool _refreshing;
    private bool _busy;
    private bool _suppressProjectSelection;

    public WorkspacePage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
    }

    public ObservableCollection<ProjectChoice> Projects { get; } = [];
    public ObservableCollection<VariantListItem> Variants { get; } = [];

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_refreshing || _busy)
        {
            return;
        }

        _refreshing = true;
        OperationStatusText.Text = "Loading Studio session…";
        try
        {
            if (!App.Services.BackendSupervisor.Status.IsReady)
            {
                ClearProjectState();
                ShowError("Backend is not ready", App.Services.BackendSupervisor.Status.Detail ?? "Open Setup and review the active backend.");
                return;
            }

            var response = await App.Services.ApiClient.GetProjectsAsync(cancellationToken);
            _suppressProjectSelection = true;
            Projects.Clear();
            foreach (var project in response.Projects)
            {
                Projects.Add(new ProjectChoice(project.Id, project.Name));
            }

            var requestedId = App.Services.Session.ActiveProjectId;
            var selected = Projects.FirstOrDefault(project => project.Id == requestedId) ?? Projects.FirstOrDefault();
            ProjectPicker.SelectedItem = selected;
            _suppressProjectSelection = false;

            if (selected is null)
            {
                App.Services.Session.ActiveProjectId = string.Empty;
                ClearProjectState();
                NoProjectsText.Visibility = Visibility.Visible;
                OperationStatusText.Text = "No projects available.";
                return;
            }

            NoProjectsText.Visibility = Visibility.Collapsed;
            if (App.Services.Session.ActiveProjectId != selected.Id)
            {
                App.Services.Session.ActiveProjectId = selected.Id;
            }

            await SelectProjectAsync(selected.Id, cancellationToken);
        }
        catch (Exception exception)
        {
            ShowError("Workspace could not be loaded", UserMessage(exception));
            OperationStatusText.Text = "Workspace load failed.";
        }
        finally
        {
            _suppressProjectSelection = false;
            _refreshing = false;
            UpdateCommandState();
        }
    }

    private async Task<bool> SelectProjectAsync(string projectId, CancellationToken cancellationToken)
    {
        _projectLoadCancellation?.Cancel();
        _projectLoadCancellation?.Dispose();
        _projectLoadCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var generation = Interlocked.Increment(ref _projectLoadGeneration);
        var token = _projectLoadCancellation.Token;

        _activeProject = null;
        _pendingAudio = null;
        PendingAudioText.Text = "No local file selected";
        AnalyzeButton.Label = "Analyze + Transcribe";
        OperationStatusText.Text = "Loading project…";
        ClearProjectState();
        UpdateCommandState();

        try
        {
            var response = await App.Services.ApiClient.GetProjectAsync(projectId, token);
            if (generation != Volatile.Read(ref _projectLoadGeneration) ||
                ProjectPicker.SelectedItem is not ProjectChoice selected ||
                !string.Equals(selected.Id, projectId, StringComparison.Ordinal))
            {
                return false;
            }

            _activeProject = response.Project;
            App.Services.Session.ActiveProjectId = projectId;
            PopulateProjectState();
            OperationStatusText.Text = "Ready";
            return true;
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            return false;
        }
    }

    private async void ProjectPicker_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressProjectSelection || ProjectPicker.SelectedItem is not ProjectChoice project || _busy)
        {
            return;
        }

        try
        {
            await SelectProjectAsync(project.Id, CancellationToken.None);
        }
        catch (Exception exception)
        {
            _activeProject = null;
            ClearProjectState();
            OperationStatusText.Text = "Project load failed.";
            ShowError("Project could not be opened", UserMessage(exception));
        }
    }

    private async void ChooseAudio_Click(object sender, RoutedEventArgs e)
    {
        if (App.MainWindowInstance is null)
        {
            ShowError("Audio picker unavailable", "The main Studio window is not ready.");
            return;
        }

        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
            ViewMode = PickerViewMode.List
        };
        foreach (var extension in new[] { ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wma" })
        {
            picker.FileTypeFilter.Add(extension);
        }

        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance.WindowHandle);
        _pendingAudio = await picker.PickSingleFileAsync();
        PendingAudioText.Text = _pendingAudio?.Name ?? "No local file selected";
        ToolTipService.SetToolTip(PendingAudioText, _pendingAudio?.Path ?? PendingAudioText.Text);
        AnalyzeButton.Label = _pendingAudio is null ? "Analyze + Transcribe" : "Upload + Analyze";
        UpdateCommandState();
    }

    private async void Upload_Click(object sender, RoutedEventArgs e)
    {
        await RunOperationAsync("Uploading audio", async cancellationToken =>
        {
            await UploadPendingAudioAsync(cancellationToken);
            ShowSuccess("Audio uploaded", "The saved track is ready. Run analysis before generating a new plan.");
        });
    }

    private async void Analyze_Click(object sender, RoutedEventArgs e)
    {
        await RunOperationAsync(
            _pendingAudio is null ? "Analyzing audio and transcription" : "Uploading and analyzing audio",
            async cancellationToken =>
            {
                if (_pendingAudio is not null)
                {
                    await UploadPendingAudioAsync(cancellationToken);
                }

                if (_activeProject is null || !_activeProject.HasAudio)
                {
                    throw new InvalidOperationException("Choose or upload an audio track before analysis.");
                }

                var analysis = await App.Services.ApiClient.AnalyzeAudioAsync(_activeProject.Id, cancellationToken);
                if (!analysis.Ok)
                {
                    throw new InvalidOperationException("The backend did not confirm the audio analysis result.");
                }

                var projectId = _activeProject.Id;
                await ReloadActiveProjectAsync(projectId, cancellationToken);
                ShowSuccess("Analysis complete", _activeProject!.TranscriptStatus);
            });
    }

    private async void GeneratePlan_Click(object sender, RoutedEventArgs e)
    {
        if (_activeProject is null)
        {
            return;
        }

        var mode = (PlanModePicker.SelectedItem as ComboBoxItem)?.Tag as string ?? "auto";
        await RunOperationAsync($"Generating plan variants ({mode})", async cancellationToken =>
        {
            var request = new PlanRequest(
                _activeProject.Name,
                UserNotes: null,
                StylePreferences: "cinematic, coherent subject, high detail, consistent style",
                NumberOfVariants: 3,
                MaximumScenes: 12);
            var plan = await App.Services.ApiClient.GeneratePlanAsync(_activeProject.Id, request, mode, cancellationToken);
            App.Services.Session.SelectedVariantIndex = 0;
            await ReloadActiveProjectAsync(_activeProject.Id, cancellationToken);
            ShowSuccess("Plan variants generated", $"{plan.Variants.Count} variants are ready for review and handoff.");
        });
    }

    private async Task UploadPendingAudioAsync(CancellationToken cancellationToken)
    {
        if (_activeProject is null || _pendingAudio is null)
        {
            throw new InvalidOperationException("Choose a project and a local audio file first.");
        }

        var file = _pendingAudio;
        await using var stream = await file.OpenStreamForReadAsync();
        await App.Services.ApiClient.UploadAudioAsync(
            _activeProject.Id,
            stream,
            file.Name,
            ContentTypeFor(file.FileType),
            cancellationToken);

        _pendingAudio = null;
        PendingAudioText.Text = "No local file selected";
        AnalyzeButton.Label = "Analyze + Transcribe";
        await ReloadActiveProjectAsync(_activeProject.Id, cancellationToken);
    }

    private async Task ReloadActiveProjectAsync(string projectId, CancellationToken cancellationToken)
    {
        var response = await App.Services.ApiClient.GetProjectAsync(projectId, cancellationToken);
        if (_activeProject is null || !string.Equals(_activeProject.Id, projectId, StringComparison.Ordinal))
        {
            throw new InvalidOperationException("The active project changed while the operation was completing.");
        }

        _activeProject = response.Project;
        PopulateProjectState();
    }

    private async Task RunOperationAsync(string label, Func<CancellationToken, Task> operation)
    {
        if (_busy)
        {
            return;
        }

        _busy = true;
        _operationCancellation = new CancellationTokenSource();
        WorkspaceInfoBar.IsOpen = false;
        OperationStatusText.Text = label;
        OperationProgress.Visibility = Visibility.Visible;
        // Analyze and plan are synchronous mutating backend calls. Canceling only the
        // HTTP wait could let an older operation overwrite a later project mutation.
        CancelOperationButton.Visibility = Visibility.Collapsed;
        UpdateCommandState();
        try
        {
            await operation(_operationCancellation.Token);
            OperationStatusText.Text = "Ready";
        }
        catch (OperationCanceledException)
        {
            WorkspaceInfoBar.Title = "Stopped waiting for the operation";
            WorkspaceInfoBar.Message = "The backend may still be finishing the request. Refresh the project before starting another operation.";
            WorkspaceInfoBar.Severity = InfoBarSeverity.Warning;
            WorkspaceInfoBar.IsOpen = true;
            OperationStatusText.Text = "Client wait canceled";
        }
        catch (Exception exception)
        {
            ShowError($"{label} failed", UserMessage(exception));
            OperationStatusText.Text = "Operation failed";
        }
        finally
        {
            _operationCancellation.Dispose();
            _operationCancellation = null;
            _busy = false;
            OperationProgress.Visibility = Visibility.Collapsed;
            CancelOperationButton.Visibility = Visibility.Collapsed;
            UpdateCommandState();
        }
    }

    private void CancelOperation_Click(object sender, RoutedEventArgs e) => _operationCancellation?.Cancel();
    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();
    private void OpenProjects_Click(object sender, RoutedEventArgs e) => App.Navigate("projects");
    private void Timeline_Click(object sender, RoutedEventArgs e) => App.Navigate("timeline");
    private void Render_Click(object sender, RoutedEventArgs e) => App.Navigate("render");

    private void Variant_Checked(object sender, RoutedEventArgs e)
    {
        if (sender is not RadioButton { Tag: int index })
        {
            return;
        }

        App.Services.Session.SelectedVariantIndex = index;
        foreach (var variant in Variants)
        {
            variant.IsSelected = variant.Index == index;
        }

        PopulateSessionSummary();
    }

    private void PopulateProjectState()
    {
        if (_activeProject is null)
        {
            ClearProjectState();
            return;
        }

        SavedAudioText.Text = _activeProject.HasAudio
            ? $"{_activeProject.AudioFileName} ({FormatBytes(_activeProject.AudioSizeBytes)})"
            : "None";
        AnalysisStateText.Text = _activeProject.TranscriptStatus;
        TempoText.Text = _activeProject.Bpm is double bpm ? $"{bpm:0.#} BPM" : "—";
        DurationSectionsText.Text = _activeProject.DurationSeconds is double duration
            ? $"{TimeSpan.FromSeconds(duration):mm\\:ss} · {_activeProject.SectionCount} sections"
            : "—";

        Variants.Clear();
        if (_activeProject.HasPlan)
        {
            var variants = _activeProject.PlanVariants;
            var selected = Math.Min(App.Services.Session.SelectedVariantIndex, Math.Max(0, variants.Count - 1));
            App.Services.Session.SelectedVariantIndex = selected;
            for (var index = 0; index < variants.Count; index++)
            {
                Variants.Add(VariantListItem.From(variants[index], index, index == selected));
            }
        }

        PlanEmptyText.Text = Variants.Count == 0
            ? "No plan generated yet."
            : $"{Variants.Count} plan variants ready.";
        HandoffText.Text = Variants.Count == 0
            ? "Generate a plan to unlock Timeline and Render handoff."
            : $"Variant {App.Services.Session.SelectedVariantIndex + 1} is selected for the next production stage.";
        PopulateSessionSummary();
        UpdateCommandState();
    }

    private void PopulateSessionSummary()
    {
        SessionProjectText.Text = _activeProject is null ? "Project: none" : $"Project: {_activeProject.Name}";
        SessionAudioText.Text = _activeProject?.HasAudio == true ? "Audio: ready" : "Audio: missing";
        SessionAnalysisText.Text = _activeProject?.HasAnalysis == true ? "Analysis: ready" : "Analysis: pending";
        SessionPlanText.Text = Variants.Count > 0 ? $"Plan: {Variants.Count} variants" : "Plan: pending";
        SessionVariantText.Text = Variants.Count > App.Services.Session.SelectedVariantIndex
            ? $"Variant: {Variants[App.Services.Session.SelectedVariantIndex].DisplayName}"
            : "Variant: none";
        var backend = App.Services.BackendSupervisor.Status;
        SessionBackendText.Text = $"{backend.Mode} · {backend.CurrentBackendUri.ToString().TrimEnd('/')}";
    }

    private void ClearProjectState()
    {
        _activeProject = null;
        Variants.Clear();
        SavedAudioText.Text = "None";
        AnalysisStateText.Text = "Pending";
        TempoText.Text = "—";
        DurationSectionsText.Text = "—";
        PlanEmptyText.Text = "Choose a project and analyze its audio first.";
        HandoffText.Text = "Generate a plan to unlock Timeline and Render handoff.";
        PopulateSessionSummary();
        UpdateCommandState();
    }

    private void UpdateCommandState()
    {
        var hasProject = _activeProject is not null;
        ChooseAudioButton.IsEnabled = hasProject && !_busy;
        UploadButton.IsEnabled = hasProject && _pendingAudio is not null && !_busy;
        AnalyzeButton.IsEnabled = hasProject && (_pendingAudio is not null || _activeProject?.HasAudio == true) && !_busy;
        GeneratePlanButton.IsEnabled = hasProject && _activeProject?.HasAnalysis == true && !_busy;
        TimelineButton.IsEnabled = Variants.Count > 0 && !_busy;
        RenderButton.IsEnabled = Variants.Count > 0 && !_busy;
        ProjectPicker.IsEnabled = !_busy && !_refreshing;
    }

    private void ShowError(string title, string message)
    {
        WorkspaceInfoBar.Title = title;
        WorkspaceInfoBar.Message = message;
        WorkspaceInfoBar.Severity = InfoBarSeverity.Error;
        WorkspaceInfoBar.IsOpen = true;
    }

    private void ShowSuccess(string title, string message)
    {
        WorkspaceInfoBar.Title = title;
        WorkspaceInfoBar.Message = message;
        WorkspaceInfoBar.Severity = InfoBarSeverity.Success;
        WorkspaceInfoBar.IsOpen = true;
    }

    private static string UserMessage(Exception exception) => exception is StudioApiException api
        ? api.UserFacingMessage
        : exception.Message;

    private static string ContentTypeFor(string extension) => extension.ToLowerInvariant() switch
    {
        ".wav" => "audio/wav",
        ".mp3" => "audio/mpeg",
        ".flac" => "audio/flac",
        ".m4a" => "audio/mp4",
        ".aac" => "audio/aac",
        ".ogg" => "audio/ogg",
        ".wma" => "audio/x-ms-wma",
        _ => "application/octet-stream"
    };

    private static string FormatBytes(long? bytes)
    {
        if (bytes is null)
        {
            return "size unknown";
        }

        var value = (double)bytes.Value;
        string[] units = ["B", "KB", "MB", "GB"];
        var unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }

        return $"{value:0.#} {units[unit]}";
    }
}

public sealed class ProjectChoice
{
    public ProjectChoice()
    {
    }

    public ProjectChoice(string id, string name)
    {
        Id = id;
        Name = name;
    }

    public string Id { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
}

public sealed class VariantListItem
{
    public int Index { get; set; }
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public bool IsSelected { get; set; }
    public string SelectLabel => $"Select {DisplayName}";

    public static VariantListItem From(PlanVariantDto variant, int index, bool selected) => new()
    {
        Index = index,
        DisplayName = string.IsNullOrWhiteSpace(variant.Name) ? $"Variant {index + 1}" : variant.Name,
        Description = $"{variant.SceneCount} scenes" +
                      (string.IsNullOrWhiteSpace(variant.Logline) ? string.Empty : $" · {variant.Logline}"),
        IsSelected = selected
    };
}
