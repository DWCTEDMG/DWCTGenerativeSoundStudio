using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.Json;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Controls;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class ReviewPage : Page, INotifyPropertyChanged
{
    private readonly StudioApiClient _apiClient = App.Services.ApiClient;
    private readonly StudioProjectMediaClient _projectMediaClient = App.Services.ProjectMediaClient;
    private readonly List<string> _selectedPaths = [];
    private readonly Dictionary<string, Direct3DPreviewControl> _comparisonPreviews = new(StringComparer.OrdinalIgnoreCase);
    private readonly SemaphoreSlim _synchronizedSeekGate = new(1, 1);
    private CancellationTokenSource? _pageCancellation;
    private CancellationTokenSource? _previewCancellation;
    private CancellationTokenSource? _synchronizedSeekCancellation;
    private DispatcherQueueTimer? _pollTimer;
    private ProjectDto? _selectedProject;
    private ReviewArtifact? _primaryArtifact;
    private ReviewJobItem? _selectedJob;
    private ReviewReport? _selectedDirectorReport;
    private string? _referencePath;
    private bool _isBusy;
    private bool _isPolling;
    private bool _isRestoringSelection;
    private bool _isSynchronizingTransport;
    private int _previewGeneration;

    public ReviewPage()
    {
        InitializeComponent();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public ObservableCollection<ReviewArtifact> Artifacts { get; } = [];

    public ObservableCollection<ReviewArtifact> SelectedArtifacts { get; } = [];

    public ObservableCollection<ReviewComparisonSlot> ComparisonSlots { get; } = [];

    public ObservableCollection<ReviewMetadataRow> MetadataDifferences { get; } = [];

    public ObservableCollection<ReviewAnnotationItem> ActiveAnnotations { get; } = [];

    public ObservableCollection<ReviewContinuityWarning> ContinuityWarnings { get; } = [];

    public ObservableCollection<ReviewJobItem> Jobs { get; } = [];

    public ObservableCollection<DirectorReviewReportItem> DirectorReports { get; } = [];

    public ReviewJobItem? SelectedJob
    {
        get => _selectedJob;
        private set => SetField(ref _selectedJob, value);
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        _pageCancellation?.Cancel();
        _pageCancellation?.Dispose();
        _pageCancellation = new CancellationTokenSource();

        _pollTimer = DispatcherQueue.CreateTimer();
        _pollTimer.Interval = TimeSpan.FromSeconds(2.5);
        _pollTimer.Tick += PollTimer_Tick;
        _pollTimer.Start();

        await LoadProjectsAsync(_pageCancellation.Token);
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (_pollTimer is not null)
        {
            _pollTimer.Stop();
            _pollTimer.Tick -= PollTimer_Tick;
            _pollTimer = null;
        }

        CancelPreview();
        _synchronizedSeekCancellation?.Cancel();
        _synchronizedSeekCancellation?.Dispose();
        _synchronizedSeekCancellation = null;
        foreach (Direct3DPreviewControl preview in _comparisonPreviews.Values)
        {
            preview.PositionChanged -= ComparisonPreview_PositionChanged;
        }
        _comparisonPreviews.Clear();
        _pageCancellation?.Cancel();
        _pageCancellation?.Dispose();
        _pageCancellation = null;
    }

    private async Task LoadProjectsAsync(CancellationToken cancellationToken)
    {
        SetBusy(true);
        try
        {
            ProjectListResponse response = await _apiClient.GetProjectsAsync(cancellationToken);
            ProjectComboBox.ItemsSource = response.Projects;

            string activeProjectId = App.Services.Session.ActiveProjectId;
            ProjectDto? project = response.Projects.FirstOrDefault(item =>
                string.Equals(item.Id, activeProjectId, StringComparison.OrdinalIgnoreCase))
                ?? response.Projects.FirstOrDefault();

            if (project is null)
            {
                ResetSurface();
                ShowStatus("No projects", "Create or open a project before reviewing artifacts.", InfoBarSeverity.Warning);
                return;
            }

            _isRestoringSelection = true;
            ProjectComboBox.SelectedItem = project;
            _isRestoringSelection = false;
            await SelectProjectAsync(project, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Projects could not be loaded", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task SelectProjectAsync(ProjectDto project, CancellationToken cancellationToken)
    {
        bool isRestoringProject = string.Equals(
            project.Id,
            App.Services.Session.ActiveProjectId,
            StringComparison.OrdinalIgnoreCase);
        int desiredVariant = isRestoringProject ? App.Services.Session.SelectedVariantIndex : 0;

        _selectedProject = project;
        App.Services.Session.ActiveProjectId = project.Id;
        App.Services.Session.SelectedVariantIndex = Math.Max(0, desiredVariant);
        await RefreshSurfaceAsync(cancellationToken, showSuccess: false);
    }

    private async Task RefreshSurfaceAsync(CancellationToken cancellationToken, bool showSuccess)
    {
        if (_selectedProject is null)
        {
            return;
        }

        string projectId = _selectedProject.Id;
        var failures = new List<string>();
        SetBusy(true);
        try
        {
            try
            {
                await LoadReviewAsync(projectId, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                failures.Add($"Review: {StudioPageHelpers.GetErrorMessage(ex)}");
            }

            try
            {
                await LoadContinuityAsync(projectId, App.Services.Session.SelectedVariantIndex, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                failures.Add($"Continuity: {StudioPageHelpers.GetErrorMessage(ex)}");
            }

            try
            {
                await LoadDirectorReviewsAsync(projectId, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                failures.Add($"Director review: {StudioPageHelpers.GetErrorMessage(ex)}");
            }

            try
            {
                await LoadJobsAsync(projectId, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                failures.Add($"Jobs: {StudioPageHelpers.GetErrorMessage(ex)}");
            }

            try
            {
                await LoadPublishingAsync(projectId, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                failures.Add($"Publishing: {StudioPageHelpers.GetErrorMessage(ex)}");
            }

            cancellationToken.ThrowIfCancellationRequested();
            if (!string.Equals(_selectedProject?.Id, projectId, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (failures.Count > 0)
            {
                ShowStatus(
                    "Review refreshed with warnings",
                    string.Join(Environment.NewLine, failures),
                    InfoBarSeverity.Warning);
            }
            else if (showSuccess)
            {
                ShowStatus("Review refreshed", "Artifacts, continuity, jobs, and publishing status are current.", InfoBarSeverity.Success);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task LoadReviewAsync(string projectId, CancellationToken cancellationToken)
    {
        JsonElement response = await _apiClient.GetVariantReviewAsync(projectId, cancellationToken);
        JsonElement review = TryGetObject(response, "variant_review", out JsonElement wrapper)
            ? wrapper
            : response;

        var loaded = new List<ReviewArtifact>();
        if (review.ValueKind == JsonValueKind.Object &&
            review.TryGetProperty("groups", out JsonElement groups) &&
            groups.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement group in groups.EnumerateArray())
            {
                int groupVariant = ReadInt(group, "variant_index");
                string groupLabel = ReadString(group, "label", $"Variant {groupVariant + 1}");
                string groupMood = ReadString(group, "mood");
                if (!group.TryGetProperty("artifacts", out JsonElement artifactArray) ||
                    artifactArray.ValueKind != JsonValueKind.Array)
                {
                    continue;
                }

                foreach (JsonElement artifact in artifactArray.EnumerateArray())
                {
                    ReviewArtifact item = ReviewArtifact.FromJson(artifact, groupVariant, groupLabel, groupMood);
                    if (!string.IsNullOrWhiteSpace(item.Path))
                    {
                        loaded.Add(item);
                    }
                }
            }
        }

        int variantCount = Math.Max(
            1,
            ReadInt(
                review,
                "plan_variant_count",
                loaded.Count == 0 ? 1 : loaded.Max(item => item.VariantIndex) + 1));
        int desiredVariant = Math.Clamp(App.Services.Session.SelectedVariantIndex, 0, variantCount - 1);

        _isRestoringSelection = true;
        VariantComboBox.ItemsSource = Enumerable.Range(0, variantCount)
            .Select(index => new VariantOption(index, $"Variant {index + 1}"))
            .ToArray();
        VariantComboBox.SelectedIndex = desiredVariant;
        _isRestoringSelection = false;
        App.Services.Session.SelectedVariantIndex = desiredVariant;

        Artifacts.Clear();
        foreach (ReviewArtifact artifact in loaded)
        {
            Artifacts.Add(artifact);
        }

        IReadOnlyList<string> requestedSelection = _selectedPaths.Count == 0
            ? App.Services.Session.ReviewComparisonPaths
            : _selectedPaths;
        IReadOnlyList<string> availableSelection = StudioReviewSelection.KeepAvailable(
            requestedSelection,
            Artifacts.Select(item => item.Path));
        ReplaceSelectedPaths(availableSelection);
        _referencePath = StudioReviewComparison.KeepReference(
            _referencePath ?? App.Services.Session.ReviewComparisonReference,
            _selectedPaths);

        string? sessionArtifact = App.Services.Session.SelectedArtifactPath;
        if (_selectedPaths.Count == 0 &&
            !string.IsNullOrWhiteSpace(sessionArtifact) &&
            Artifacts.Any(item => string.Equals(item.Path, sessionArtifact, StringComparison.OrdinalIgnoreCase)))
        {
            ReplaceSelectedPaths(StudioReviewSelection.AddRecent(_selectedPaths, sessionArtifact));
        }

        RestoreArtifactSelection();
        await UpdateSelectionPresentationAsync(cancellationToken);

        int artifactCount = ReadInt(review, "artifact_count", Artifacts.Count);
        bool compareReady = ReadBoolean(review, "compare_ready", artifactCount > 1);
        ReviewSummaryText.Text =
            $"{artifactCount} artifact{(artifactCount == 1 ? string.Empty : "s")} · Compare ready: {(compareReady ? "yes" : "no")}";
    }

    private async Task LoadContinuityAsync(
        string projectId,
        int variantIndex,
        CancellationToken cancellationToken)
    {
        JsonElement response = await _apiClient.GetRenderConductorContinuityAsync(
            projectId,
            variantIndex,
            cancellationToken);
        JsonElement continuity = TryGetObject(response, "continuity", out JsonElement wrapper)
            ? wrapper
            : response;

        var warnings = new List<ReviewContinuityWarning>();
        if (continuity.ValueKind == JsonValueKind.Object &&
            continuity.TryGetProperty("warnings", out JsonElement warningArray) &&
            warningArray.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement warning in warningArray.EnumerateArray())
            {
                string code = ReadString(warning, "code", "continuity_warning");
                string severity = ReadString(warning, "severity", "warning");
                string sceneId = ReadString(warning, "scene_id");
                string message = ReadString(warning, "message", "Continuity attention is required.");
                warnings.Add(new ReviewContinuityWarning(
                    $"{TitleCase(severity)} · {TitleCase(code)}",
                    $"{(string.IsNullOrWhiteSpace(sceneId) ? "Project-wide" : $"Scene {sceneId}")}: {message}"));
            }
        }

        ContinuityWarnings.Clear();
        foreach (ReviewContinuityWarning warning in warnings)
        {
            ContinuityWarnings.Add(warning);
        }

        int warningCount = ReadInt(continuity, "warning_count", warnings.Count);
        int blockingCount = ReadInt(continuity, "blocking_count");
        bool isReady = ReadBoolean(continuity, "ok_to_render", warningCount == 0);
        ContinuitySummaryText.Text =
            $"{warningCount} warning{(warningCount == 1 ? string.Empty : "s")} · " +
            $"Blocking: {blockingCount} · Ready to render: {(isReady ? "yes" : "no")}";
    }

    private async Task LoadJobsAsync(string projectId, CancellationToken cancellationToken)
    {
        string? desiredJobId = SelectedJob?.Job.Id;
        if (string.IsNullOrWhiteSpace(desiredJobId) &&
            string.Equals(App.Services.Session.SelectedJobProjectId, projectId, StringComparison.OrdinalIgnoreCase))
        {
            desiredJobId = App.Services.Session.SelectedJobId;
        }

        StudioJobListResponse response = await _apiClient.GetProjectJobsAsync(projectId, cancellationToken);
        Jobs.Clear();
        foreach (StudioJob job in response.Jobs.OrderByDescending(item => item.UpdatedAt ?? item.CreatedAt))
        {
            Jobs.Add(new ReviewJobItem(job));
        }

        ReviewJobItem? selected = Jobs.FirstOrDefault(item =>
            string.Equals(item.Job.Id, desiredJobId, StringComparison.OrdinalIgnoreCase));
        JobsList.SelectedItem = selected;
        SelectedJob = selected;
        JobsSummaryText.Text = Jobs.Count == 0
            ? "No project render jobs."
            : $"{Jobs.Count} job{(Jobs.Count == 1 ? string.Empty : "s")} · {Jobs.Count(item => item.Job.IsActive)} active";
        UpdateJobCommands();
    }

    private async Task LoadPublishingAsync(string projectId, CancellationToken cancellationToken)
    {
        LiveCuePublishResponse response =
            await _apiClient.GetTypedLiveCuePublishStatusAsync(projectId, cancellationToken);
        UpdatePublishingStatus(response.Publish);
    }

    private async Task UpdateSelectionPresentationAsync(CancellationToken cancellationToken)
    {
        SelectedArtifacts.Clear();
        foreach (string path in _selectedPaths)
        {
            ReviewArtifact? artifact = Artifacts.FirstOrDefault(item =>
                string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase));
            if (artifact is not null)
            {
                SelectedArtifacts.Add(artifact);
            }
        }

        _primaryArtifact = SelectedArtifacts.FirstOrDefault(item =>
            string.Equals(item.Path, _primaryArtifact?.Path, StringComparison.OrdinalIgnoreCase))
            ?? SelectedArtifacts.LastOrDefault();
        _referencePath = StudioReviewComparison.KeepReference(_referencePath, _selectedPaths);
        App.Services.Session.SetReviewComparison(_selectedPaths, _referencePath);
        int selectedCount = SelectedArtifacts.Count;
        SelectionSummaryText.Text = selectedCount == 0
            ? "Select up to four artifacts."
            : $"{selectedCount} of {StudioReviewSelection.MaximumComparisonArtifacts} selected.";

        bool hasSelection = selectedCount > 0;
        ApproveButton.IsEnabled = hasSelection && !_isBusy;
        CherryPickButton.IsEnabled = hasSelection && !_isBusy;
        RejectButton.IsEnabled = hasSelection && !_isBusy;

        RebuildComparisonState();
        if (_primaryArtifact is null || _selectedProject is null)
        {
            App.Services.Session.SetSelectedArtifact(null);
            App.Services.Session.SetSourceAsset(null);
            CancelPreview();
            PreviewTitleText.Text = "Select artifacts to compare.";
            UpdateDirectorReviewCommands();
            return;
        }

        App.Services.Session.SetSelectedArtifact(_primaryArtifact.Path);
        App.Services.Session.SetSourceAsset(_primaryArtifact.Path);
        App.Services.Session.SelectedVariantIndex = _primaryArtifact.VariantIndex;
        PreviewTitleText.Text = $"Active: {_primaryArtifact.Name}";
        NotesTextBox.Text = _primaryArtifact.ReviewNotes;
        RebuildActiveAnnotations();
        await LoadComparisonPreviewsAsync(_selectedProject.Id, cancellationToken);
        UpdateDirectorReviewCommands();
    }

    private async Task LoadDirectorReviewsAsync(string projectId, CancellationToken cancellationToken)
    {
        string? selectedId = _selectedDirectorReport?.ReportId;
        DirectorReviewListResponse response = await _apiClient.GetDirectorReviewsAsync(projectId, cancellationToken);
        DirectorReports.Clear();
        foreach (ReviewReport report in response.Reports)
        {
            DirectorReports.Add(new DirectorReviewReportItem(report));
        }

        DirectorReviewReportItem? selected = DirectorReports.FirstOrDefault(item => item.Report.ReportId == selectedId)
            ?? DirectorReports.FirstOrDefault();
        DirectorReportsList.SelectedItem = selected;
        ShowDirectorReport(selected?.Report);
    }

    private void ShowDirectorReport(ReviewReport? report)
    {
        _selectedDirectorReport = report;
        if (report is null)
        {
            DirectorReportSummaryText.Text = "No reports yet.";
            DirectorDimensionsText.Text = string.Empty;
            DirectorEvidenceText.Text = string.Empty;
            DirectorFindingsText.Text = string.Empty;
            DirectorRetryText.Text = string.Empty;
            UpdateDirectorReviewCommands();
            return;
        }

        int assessed = report.Dimensions.Count(item => string.Equals(item.State, "assessed", StringComparison.OrdinalIgnoreCase));
        int unassessed = report.Dimensions.Count - assessed;
        DirectorReportSummaryText.Text =
            $"{TitleCase(report.Disposition)} · Aggregate {DirectorReviewPresentation.FormatScore(report.AggregateScore)} · " +
            $"Continuity {DirectorReviewPresentation.FormatScore(report.ContinuityScore)} · Assessed {assessed}, unassessed {unassessed}\n" +
            $"Clip understanding: {TitleCase(report.ClipUnderstanding.State)} — {report.ClipUnderstanding.Detail}\n" +
            $"Correction: {TitleCase(report.CorrectionPlan.State)}" +
            (string.IsNullOrWhiteSpace(report.CorrectionPlan.TargetSceneId) ? string.Empty : $" · target {report.CorrectionPlan.TargetSceneId}");
        DirectorDimensionsText.Text = report.Dimensions.Count == 0
            ? "No dimensions returned."
            : string.Join(Environment.NewLine, report.Dimensions.Select(item =>
                $"{TitleCase(item.Dimension)}: {DirectorReviewPresentation.FormatScore(item.Score, item.State)} ({TitleCase(item.State)})"));
        DirectorEvidenceText.Text = report.Samples.Count == 0
            ? "No sampled frames returned."
            : string.Join(Environment.NewLine, report.Samples.Select(item => $"{item.TimestampSeconds:0.###}s — {item.Path}"));
        var findingLines = report.Findings.Select(item =>
            $"{TitleCase(item.Severity)} · {TitleCase(item.Dimension)}: {item.Message}");
        var guidanceLines = report.CorrectionPlan.Guidance.Select(item => $"Guidance: {item}");
        string[] detailLines = [.. findingLines, .. guidanceLines];
        DirectorFindingsText.Text = detailLines.Length == 0 ? "No findings or correction guidance." : string.Join(Environment.NewLine, detailLines);
        DirectorRetryText.Text =
            $"Attempt {report.Retry.Attempt} of {report.Retry.MaxAttempts} · Result: {TitleCase(report.Retry.Result)}" +
            (report.Retry.History.Count == 0
                ? " · No prior attempts."
                : Environment.NewLine + string.Join(Environment.NewLine, report.Retry.History.Select(item =>
                    $"Attempt {item.Attempt}: {TitleCase(item.Disposition)}, {DirectorReviewPresentation.FormatScore(item.AggregateScore)}")));
        UpdateDirectorReviewCommands();
    }

    private void UpdateDirectorReviewCommands()
    {
        bool videoSelected = _primaryArtifact?.IsVideo == true;
        RunDirectorReviewButton.IsEnabled = !_isBusy && _selectedProject is not null && videoSelected;
        RunNextDirectorAttemptButton.Visibility = DirectorReviewPresentation.CanRunNextAttempt(_selectedDirectorReport)
            ? Visibility.Visible : Visibility.Collapsed;
        RunNextDirectorAttemptButton.IsEnabled = !_isBusy && videoSelected &&
            string.Equals(_selectedDirectorReport?.ArtifactPath, _primaryArtifact?.Path, StringComparison.OrdinalIgnoreCase);
        ApplyDirectorGuidanceButton.Visibility = DirectorReviewPresentation.CanApplyCorrection(_selectedDirectorReport)
            ? Visibility.Visible : Visibility.Collapsed;
        ApplyDirectorGuidanceButton.IsEnabled = !_isBusy && _selectedProject is not null;
        DirectorReviewStatusText.Text = _primaryArtifact is null
            ? "Select one video artifact to run a Director review."
            : !_primaryArtifact.IsVideo
                ? "The active artifact is not a video. Director review accepts video artifacts only."
                : $"Ready to review {_primaryArtifact.Name}. This action collects evidence; it does not regenerate video.";
    }

    private async Task RunDirectorReviewAsync(string? retryOfReportId)
    {
        if (_selectedProject is null || _primaryArtifact?.IsVideo != true || _isBusy)
        {
            ShowStatus("Director review unavailable", "Select a video artifact before running Director review.", InfoBarSeverity.Warning);
            return;
        }

        int sampleCount = (int)DirectorSampleCountBox.Value;
        double threshold = DirectorThresholdBox.Value / 100d;
        int maxAttempts = (int)DirectorMaxAttemptsBox.Value;
        string? targetSceneId = string.IsNullOrWhiteSpace(DirectorTargetSceneTextBox.Text)
            ? null : DirectorTargetSceneTextBox.Text.Trim();
        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        SetBusy(true);
        DirectorReviewStatusText.Text = retryOfReportId is null
            ? "Collecting deterministic frame evidence and assessing available dimensions…"
            : "Running the requested next Director review attempt…";
        try
        {
            DirectorReviewResponse response = await _apiClient.CreateDirectorReviewAsync(
                _selectedProject.Id,
                new ReviewRequest(_selectedProject.Revision, _primaryArtifact.Path, sampleCount, threshold,
                    maxAttempts, DirectorClipUnderstandingCheckBox.IsChecked == true, targetSceneId, retryOfReportId),
                cancellationToken);
            await LoadDirectorReviewsAsync(_selectedProject.Id, cancellationToken);
            DirectorReportsList.SelectedItem = DirectorReports.FirstOrDefault(item => item.Report.ReportId == response.Report.ReportId);
            ShowDirectorReport(response.Report);
            ShowStatus("Director review complete",
                $"{TitleCase(response.Report.Disposition)} at {DirectorReviewPresentation.FormatScore(response.Report.AggregateScore)}. No regeneration was performed.",
                InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (Exception ex)
        {
            DirectorReviewStatusText.Text = "Director review failed. Existing reports and the selected artifact were not changed.";
            ShowStatus("Director review failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task ApplyDirectorGuidanceAsync()
    {
        if (_selectedProject is null || !DirectorReviewPresentation.CanApplyCorrection(_selectedDirectorReport) || _isBusy)
        {
            return;
        }
        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        SetBusy(true);
        try
        {
            DirectorReviewApplyResponse response = await _apiClient.ApplyDirectorReviewCorrectionAsync(
                _selectedProject.Id, _selectedDirectorReport!.ReportId,
                new ApplyCorrectionRequest(_selectedProject.Revision), cancellationToken);
            ProjectResponse refreshed = await _apiClient.GetProjectAsync(_selectedProject.Id, cancellationToken);
            _selectedProject = refreshed.Project;
            await LoadDirectorReviewsAsync(_selectedProject.Id, cancellationToken);
            ShowStatus("Next-scene guidance applied",
                $"The Director draft guidance was applied at project revision {response.Revision}. Video was not regenerated.",
                InfoBarSeverity.Success);
        }
        catch (ProjectRevisionConflictException ex)
        {
            ShowStatus("Project revision changed", ex.UserFacingMessage, InfoBarSeverity.Warning);
            ProjectResponse refreshed = await _apiClient.GetProjectAsync(_selectedProject.Id, cancellationToken);
            _selectedProject = refreshed.Project;
            await LoadDirectorReviewsAsync(_selectedProject.Id, cancellationToken);
        }
        catch (Exception ex)
        {
            ShowStatus("Guidance could not be applied", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void RebuildComparisonState()
    {
        foreach (Direct3DPreviewControl preview in _comparisonPreviews.Values)
        {
            preview.PositionChanged -= ComparisonPreview_PositionChanged;
        }
        _comparisonPreviews.Clear();
        ComparisonSlots.Clear();
        foreach (ReviewArtifact artifact in SelectedArtifacts)
        {
            ComparisonSlots.Add(new ReviewComparisonSlot(
                artifact,
                string.Equals(artifact.Path, _primaryArtifact?.Path, StringComparison.OrdinalIgnoreCase),
                string.Equals(artifact.Path, _referencePath, StringComparison.OrdinalIgnoreCase)));
        }

        MetadataDifferences.Clear();
        IReadOnlyList<ReviewMetadataDifference> differences = StudioReviewComparison.CompareMetadata(
            SelectedArtifacts.Select(item => new ReviewComparisonArtifact(
                item.Path,
                item.Name,
                item.Kind,
                item.VariantLabel,
                item.ReviewState,
                item.Engine,
                item.ModelId,
                item.Seed,
                item.SizeBytes)));
        foreach (ReviewMetadataDifference difference in differences)
        {
            MetadataDifferences.Add(new ReviewMetadataRow(
                difference.Label,
                string.Join("  |  ", difference.Values),
                difference.IsDifferent));
        }
    }

    private async Task LoadComparisonPreviewsAsync(string projectId, CancellationToken pageToken)
    {
        CancelPreview();
        int generation = ++_previewGeneration;
        _previewCancellation = CancellationTokenSource.CreateLinkedTokenSource(pageToken);
        CancellationToken cancellationToken = _previewCancellation.Token;
        await Task.WhenAll(SelectedArtifacts.Select(async artifact =>
        {
            if (!_comparisonPreviews.TryGetValue(artifact.Path, out Direct3DPreviewControl? preview))
            {
                return;
            }

            if (!artifact.IsImage && !artifact.IsVideo)
            {
                preview.ShowUnsupported("This artifact does not have an inline preview.");
                return;
            }

            try
            {
                await _projectMediaClient.StreamProjectMediaAsync(
                    projectId,
                    artifact.Path,
                    async (file, callbackToken) =>
                    {
                        callbackToken.ThrowIfCancellationRequested();
                        if (generation != Volatile.Read(ref _previewGeneration))
                        {
                            return false;
                        }

                        if (artifact.IsVideo)
                        {
                            await preview.LoadVideoStreamAsync(file.Stream, file.ContentHeaders.ContentLength, callbackToken);
                        }
                        else
                        {
                            await preview.LoadStreamAsync(file.Stream, file.ContentHeaders.ContentType?.MediaType, callbackToken);
                        }
                        return true;
                    },
                    cancellationToken);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
            }
            catch (Exception ex)
            {
                if (generation == _previewGeneration)
                {
                    preview.ShowError("Preview failed to load.");
                    ShowStatus("Preview failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
                }
            }
        }));
    }

    private void CancelPreview()
    {
        _previewCancellation?.Cancel();
        _previewCancellation?.Dispose();
        _previewCancellation = null;
    }

    private async Task ApplyDecisionAsync(string decision)
    {
        if (_selectedProject is null || _selectedPaths.Count == 0 || _isBusy)
        {
            ShowStatus("Nothing selected", "Select at least one artifact to review.", InfoBarSeverity.Warning);
            return;
        }

        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        string[] selectedPaths = [.. _selectedPaths];
        string[] traits = TraitsTextBox.Text
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        SetBusy(true);
        try
        {
            foreach (string path in selectedPaths)
            {
                await _apiClient.SaveVariantDecisionAsync(
                    _selectedProject.Id,
                    new VariantReviewDecisionRequest
                    {
                        ArtifactPath = path,
                        Decision = decision,
                        Notes = string.Equals(path, _primaryArtifact?.Path, StringComparison.OrdinalIgnoreCase)
                            ? (string.IsNullOrWhiteSpace(NotesTextBox.Text) ? null : NotesTextBox.Text.Trim())
                            : Artifacts.FirstOrDefault(item => string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase))?.ReviewNotes,
                        CherryPickTraits = decision == "cherry_picked" ? traits : [],
                        LockFields = decision == "approved" ? ["timing", "reference"] : [],
                        Annotations = GetAnnotationRequests(path)
                    },
                    cancellationToken);
            }

            ReplaceSelectedPaths([]);
            App.Services.Session.SetReviewComparison([], null);
            RestoreArtifactSelection();
            await LoadReviewAsync(_selectedProject.Id, cancellationToken);
            ShowStatus(
                "Editorial decision saved",
                $"{TitleCase(decision)} applied to {selectedPaths.Length} artifact{(selectedPaths.Length == 1 ? string.Empty : "s")}.",
                InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Decision could not be saved", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task RunJobActionAsync(
        string action,
        Func<string, string, CancellationToken, Task<StudioJobActionResponse>> operation,
        StudioJobConfirmationAction? confirmationAction = null)
    {
        if (_selectedProject is null || SelectedJob is null || _isBusy)
        {
            return;
        }

        if (confirmationAction is StudioJobConfirmationAction requiredConsent &&
            !await StudioPageHelpers.ConfirmAsync(
                XamlRoot,
                StudioJobConfirmationFactory.CreateRecoveryConsent(SelectedJob.Job, requiredConsent)))
        {
            return;
        }

        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        SetBusy(true);
        try
        {
            StudioJobActionResponse response = await operation(
                _selectedProject.Id,
                SelectedJob.Job.Id,
                cancellationToken);
            await LoadJobsAsync(_selectedProject.Id, cancellationToken);
            ShowStatus($"{action} requested", $"Job {response.Job.Id} is {response.Job.Status}.", InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus($"{action} failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task LoadSelectedJobLogAsync()
    {
        if (_selectedProject is null || SelectedJob is null)
        {
            return;
        }

        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        try
        {
            JsonElement detail = await _apiClient.GetProjectJobAsync(
                _selectedProject.Id,
                SelectedJob.Job.Id,
                80,
                cancellationToken);
            string log = ReadString(detail, "log_tail");
            if (string.IsNullOrWhiteSpace(log) &&
                detail.TryGetProperty("tail", out JsonElement tail))
            {
                log = tail.ValueKind == JsonValueKind.String
                    ? tail.GetString() ?? string.Empty
                    : tail.GetRawText();
            }

            JobLogTextBox.Text = string.IsNullOrWhiteSpace(log)
                ? StudioPageHelpers.FormatJson(detail)
                : log;
            JobLogTextBox.Visibility = Visibility.Visible;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            JobLogTextBox.Text = StudioPageHelpers.GetErrorMessage(ex);
            JobLogTextBox.Visibility = Visibility.Visible;
        }
    }

    private async Task StartPublishingAsync()
    {
        if (_selectedProject is null || _isBusy)
        {
            return;
        }

        string host = OscHostTextBox.Text.Trim();
        int port = (int)OscPortNumberBox.Value;
        if (string.IsNullOrWhiteSpace(host) || port is < 1 or > 65535)
        {
            ShowStatus("Invalid publisher target", "Enter an OSC host and a port from 1 through 65535.", InfoBarSeverity.Warning);
            return;
        }

        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        SetBusy(true);
        try
        {
            LiveCuePublishResponse response = await _apiClient.StartLiveCuePublishAsync(
                _selectedProject.Id,
                new LiveCuePublishRequest
                {
                    OscHost = host,
                    OscPort = port,
                    MidiEnabled = true,
                    WebsocketEnabled = true,
                    PlaybackSpeed = 1.0
                },
                cancellationToken);
            UpdatePublishingStatus(response.Publish);
            ShowStatus("Publishing started", "Live cues are being published to the configured transports.", InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Publishing failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task StopPublishingAsync()
    {
        if (_selectedProject is null || _isBusy)
        {
            return;
        }

        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        SetBusy(true);
        try
        {
            LiveCuePublishResponse response =
                await _apiClient.StopLiveCuePublishAsync(_selectedProject.Id, cancellationToken);
            UpdatePublishingStatus(response.Publish);
            ShowStatus("Publishing stopped", "Live cue transport output is stopped.", InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Publishing could not be stopped", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task ExportAdapterAsync(string adapter)
    {
        if (_selectedProject is null || _isBusy)
        {
            return;
        }

        CancellationToken cancellationToken = _pageCancellation?.Token ?? CancellationToken.None;
        SetBusy(true);
        try
        {
            WorldAdapterExportResponse response = await _apiClient.ExportWorldAdapterAsync(
                _selectedProject.Id,
                new WorldAdapterExportRequest
                {
                    Adapter = adapter,
                    VariantIndex = App.Services.Session.SelectedVariantIndex,
                    SequenceName = "EDMG_LiveSet"
                },
                cancellationToken);
            int simulatedEvents = ReadInt(response.Simulation, "simulated_events");
            ShowStatus(
                "Adapter exported",
                $"{adapter} adapter export is ready ({simulatedEvents} simulated event{(simulatedEvents == 1 ? string.Empty : "s")}).",
                InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Export failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void UpdatePublishingStatus(JsonElement publish)
    {
        bool isRunning = ReadBoolean(publish, "running", ReadBoolean(publish, "active", false));
        int sentCount = ReadInt(publish, "sent_count", ReadInt(publish, "events_sent"));
        string target = ReadString(publish, "osc_target");
        if (string.IsNullOrWhiteSpace(target))
        {
            string host = ReadString(publish, "host");
            int port = ReadInt(publish, "port");
            target = string.IsNullOrWhiteSpace(host) ? "not configured" : $"{host}:{port}";
        }

        PublishStatusText.Text =
            $"{(isRunning ? "Publishing" : "Stopped")} · Sent {sentCount} · OSC {target}";
    }

    private void ReplaceSelectedPaths(IEnumerable<string> paths)
    {
        _selectedPaths.Clear();
        _selectedPaths.AddRange(paths);
    }

    private void RestoreArtifactSelection()
    {
        _isRestoringSelection = true;
        ArtifactList.SelectedItems.Clear();
        foreach (ReviewArtifact artifact in Artifacts)
        {
            if (_selectedPaths.Any(path =>
                string.Equals(path, artifact.Path, StringComparison.OrdinalIgnoreCase)))
            {
                ArtifactList.SelectedItems.Add(artifact);
            }
        }
        _isRestoringSelection = false;
    }

    private void UpdateJobCommands()
    {
        PauseJobButton.IsEnabled = !_isBusy && SelectedJob is { Job.CanPause: true } or { Job.CanResume: true };
        CancelJobButton.IsEnabled = !_isBusy && SelectedJob?.Job.CanCancel == true;
        RetryJobButton.IsEnabled = !_isBusy && SelectedJob?.Job.CanRetry == true;
        ViewJobLogButton.IsEnabled = !_isBusy && SelectedJob is not null;
    }

    private void SetBusy(bool value)
    {
        _isBusy = value;
        BusyProgressBar.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
        ProjectComboBox.IsEnabled = !value;
        VariantComboBox.IsEnabled = !value;
        StartPublishButton.IsEnabled = !value;
        StopPublishButton.IsEnabled = !value;
        ExportTouchDesignerButton.IsEnabled = !value;
        ExportUnrealButton.IsEnabled = !value;
        bool hasSelection = _selectedPaths.Count > 0;
        ApproveButton.IsEnabled = !value && hasSelection;
        CherryPickButton.IsEnabled = !value && hasSelection;
        RejectButton.IsEnabled = !value && hasSelection;
        UpdateJobCommands();
        UpdateDirectorReviewCommands();
    }

    private void ResetSurface()
    {
        _selectedProject = null;
        Artifacts.Clear();
        SelectedArtifacts.Clear();
        ContinuityWarnings.Clear();
        Jobs.Clear();
        DirectorReports.Clear();
        ReplaceSelectedPaths([]);
        SelectedJob = null;
        ComparisonSlots.Clear();
        MetadataDifferences.Clear();
        ActiveAnnotations.Clear();
        ReviewSummaryText.Text = "Select a project to review.";
        SelectionSummaryText.Text = "Select up to four artifacts.";
        PreviewTitleText.Text = "Select artifacts to compare.";
        ContinuitySummaryText.Text = "Run analysis and generate a plan to populate continuity checks.";
        JobsSummaryText.Text = "No jobs loaded.";
        PublishStatusText.Text = "Publishing status unavailable.";
        JobLogTextBox.Visibility = Visibility.Collapsed;
        ShowDirectorReport(null);
    }

    private async void OnProjectSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isRestoringSelection || ProjectComboBox.SelectedItem is not ProjectDto project)
        {
            return;
        }

        await SelectProjectAsync(project, _pageCancellation?.Token ?? CancellationToken.None);
    }

    private async void OnVariantSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isRestoringSelection ||
            _selectedProject is null ||
            VariantComboBox.SelectedItem is not VariantOption option)
        {
            return;
        }

        App.Services.Session.SelectedVariantIndex = option.Index;
        try
        {
            await LoadContinuityAsync(
                _selectedProject.Id,
                option.Index,
                _pageCancellation?.Token ?? CancellationToken.None);
        }
        catch (Exception ex)
        {
            ShowStatus("Continuity could not be refreshed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
    }

    private async void OnArtifactSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isRestoringSelection)
        {
            return;
        }

        IEnumerable<string> remaining = _selectedPaths.Where(path =>
            !e.RemovedItems.OfType<ReviewArtifact>().Any(item =>
                string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase)));
        IReadOnlyList<string> updated = remaining.ToArray();
        foreach (ReviewArtifact added in e.AddedItems.OfType<ReviewArtifact>())
        {
            updated = StudioReviewSelection.AddRecent(updated, added.Path);
        }

        ReplaceSelectedPaths(updated);
        RestoreArtifactSelection();
        await UpdateSelectionPresentationAsync(_pageCancellation?.Token ?? CancellationToken.None);
    }

    private async void OnRefreshClick(object sender, RoutedEventArgs e) =>
        await RefreshSurfaceAsync(_pageCancellation?.Token ?? CancellationToken.None, showSuccess: true);

    private async void OnComparisonPreviewLoaded(object sender, RoutedEventArgs e)
    {
        if (sender is not Direct3DPreviewControl preview || preview.Tag is not string path)
        {
            return;
        }

        if (_comparisonPreviews.TryGetValue(path, out Direct3DPreviewControl? existing))
        {
            existing.PositionChanged -= ComparisonPreview_PositionChanged;
        }
        _comparisonPreviews[path] = preview;
        preview.PositionChanged += ComparisonPreview_PositionChanged;

        ReviewArtifact? artifact = SelectedArtifacts.FirstOrDefault(item =>
            string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase));
        if (artifact is not null && _selectedProject is not null)
        {
            try
            {
                await LoadSingleComparisonPreviewAsync(
                    _selectedProject.Id,
                    artifact,
                    preview,
                    _pageCancellation?.Token ?? CancellationToken.None);
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception ex)
            {
                preview.ShowError("Preview failed to load.");
                ShowStatus("Preview failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
            }
        }
    }

    private async Task LoadSingleComparisonPreviewAsync(
        string projectId,
        ReviewArtifact artifact,
        Direct3DPreviewControl preview,
        CancellationToken cancellationToken)
    {
        if (!artifact.IsImage && !artifact.IsVideo)
        {
            preview.ShowUnsupported("This artifact does not have an inline preview.");
            return;
        }

        await _projectMediaClient.StreamProjectMediaAsync(
            projectId,
            artifact.Path,
            async (file, callbackToken) =>
            {
                if (artifact.IsVideo)
                {
                    await preview.LoadVideoStreamAsync(file.Stream, file.ContentHeaders.ContentLength, callbackToken);
                }
                else
                {
                    await preview.LoadStreamAsync(file.Stream, file.ContentHeaders.ContentType?.MediaType, callbackToken);
                }
                return true;
            },
            cancellationToken);
    }

    private async void ComparisonPreview_PositionChanged(object? sender, PreviewPositionChangedEventArgs e)
    {
        if (_isSynchronizingTransport || sender is not Direct3DPreviewControl source ||
            !string.Equals(source.Tag as string, _primaryArtifact?.Path, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        _isSynchronizingTransport = true;
        try
        {
            ComparisonPositionSlider.Value = e.NormalizedPosition;
        }
        finally
        {
            _isSynchronizingTransport = false;
        }
        await Task.CompletedTask;
    }

    private async void OnComparisonPositionChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (_isSynchronizingTransport)
        {
            return;
        }

        _synchronizedSeekCancellation?.Cancel();
        _synchronizedSeekCancellation?.Dispose();
        _synchronizedSeekCancellation = CancellationTokenSource.CreateLinkedTokenSource(
            _pageCancellation?.Token ?? CancellationToken.None);
        CancellationToken cancellationToken = _synchronizedSeekCancellation.Token;
        try
        {
            await Task.Delay(TimeSpan.FromMilliseconds(180), cancellationToken);
            await SeekAllAsync(e.NewValue, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Comparison seek failed", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
    }

    private async Task SeekAllAsync(double position, CancellationToken cancellationToken = default)
    {
        await _synchronizedSeekGate.WaitAsync(cancellationToken);
        _isSynchronizingTransport = true;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            await Task.WhenAll(_comparisonPreviews.Values.Where(item => item.HasVideo)
                .Select(item => item.SeekNormalizedAsync(position)));
        }
        finally
        {
            _isSynchronizingTransport = false;
            _synchronizedSeekGate.Release();
        }
    }

    private async void OnSyncPlayPauseClick(object sender, RoutedEventArgs e) => await ToggleSynchronizedPlaybackAsync();

    private async void OnSyncPositionClick(object sender, RoutedEventArgs e) =>
        await SeekAllAsync(_primaryArtifact is not null && _comparisonPreviews.TryGetValue(_primaryArtifact.Path, out Direct3DPreviewControl? preview)
            ? preview.NormalizedPosition
            : ComparisonPositionSlider.Value);

    private async Task ToggleSynchronizedPlaybackAsync()
    {
        Direct3DPreviewControl[] videos = _comparisonPreviews.Values.Where(item => item.HasVideo).ToArray();
        bool play = videos.Any() && !videos.Any(item => item.IsVideoPlaying);
        if (play)
        {
            await SeekAllAsync(ComparisonPositionSlider.Value);
        }
        await Task.WhenAll(videos.Select(item => item.SetPlayingAsync(play)));
        SyncPlayPauseButton.Content = play ? "Pause all" : "Play all";
    }

    private async void OnActivateComparisonClick(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string path })
        {
            await SetActiveArtifactAsync(path);
        }
    }

    private void OnSetReferenceClick(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string path })
        {
            _referencePath = path;
            App.Services.Session.SetReviewComparison(_selectedPaths, _referencePath);
            RebuildComparisonState();
        }
    }

    private async Task SetActiveArtifactAsync(string? path)
    {
        ReviewArtifact? artifact = SelectedArtifacts.FirstOrDefault(item =>
            string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase));
        if (artifact is null)
        {
            return;
        }

        _primaryArtifact = artifact;
        App.Services.Session.SetSelectedArtifact(artifact.Path);
        App.Services.Session.SetSourceAsset(artifact.Path);
        PreviewTitleText.Text = $"Active: {artifact.Name}";
        NotesTextBox.Text = artifact.ReviewNotes;
        RebuildComparisonState();
        RebuildActiveAnnotations();
        await Task.CompletedTask;
    }

    private void RebuildActiveAnnotations()
    {
        ActiveAnnotations.Clear();
        if (_primaryArtifact is null)
        {
            return;
        }

        foreach (ReviewAnnotation annotation in _primaryArtifact.Annotations)
        {
            ActiveAnnotations.Add(new ReviewAnnotationItem(Guid.NewGuid().ToString("N"), annotation.Position, annotation.Note));
        }
    }

    private void OnAddMarkerClick(object sender, RoutedEventArgs e)
    {
        string note = MarkerTextBox.Text.Trim();
        if (_primaryArtifact is null || string.IsNullOrWhiteSpace(note))
        {
            ShowStatus("Marker not added", "Select an active artifact and enter a marker note.", InfoBarSeverity.Warning);
            return;
        }

        ActiveAnnotations.Add(new ReviewAnnotationItem(Guid.NewGuid().ToString("N"), ComparisonPositionSlider.Value, note));
        MarkerTextBox.Text = string.Empty;
    }

    private void OnRemoveMarkerClick(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string id } && ActiveAnnotations.FirstOrDefault(item => item.Id == id) is { } marker)
        {
            ActiveAnnotations.Remove(marker);
        }
    }

    private async void OnSaveAnnotationsClick(object sender, RoutedEventArgs e)
    {
        if (_selectedProject is null || _primaryArtifact is null)
        {
            return;
        }

        try
        {
            await _apiClient.SaveVariantDecisionAsync(
                _selectedProject.Id,
                new VariantReviewDecisionRequest
                {
                    ArtifactPath = _primaryArtifact.Path,
                    Decision = NormalizeDecision(_primaryArtifact.ReviewState),
                    Notes = string.IsNullOrWhiteSpace(NotesTextBox.Text) ? null : NotesTextBox.Text.Trim(),
                    CherryPickTraits = _primaryArtifact.Traits,
                    LockFields = _primaryArtifact.Locks,
                    Annotations = GetAnnotationRequests(_primaryArtifact.Path)
                },
                _pageCancellation?.Token ?? CancellationToken.None);
            await LoadReviewAsync(_selectedProject.Id, _pageCancellation?.Token ?? CancellationToken.None);
            ShowStatus("Review notes saved", "The active artifact notes and markers were saved.", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus("Review notes could not be saved", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
    }

    private IReadOnlyList<ReviewAnnotationRequest> GetAnnotationRequests(string path)
    {
        if (string.Equals(path, _primaryArtifact?.Path, StringComparison.OrdinalIgnoreCase))
        {
            return ActiveAnnotations.Select(item => new ReviewAnnotationRequest(item.Position, item.Note)).ToArray();
        }

        return Artifacts.FirstOrDefault(item => string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase))?.Annotations
            .Select(item => new ReviewAnnotationRequest(item.Position, item.Note)).ToArray() ?? [];
    }

    private async void PreviousArtifactAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        await SetActiveArtifactAsync(StudioReviewComparison.MoveActive(_selectedPaths, _primaryArtifact?.Path, -1));
    }

    private async void NextArtifactAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        await SetActiveArtifactAsync(StudioReviewComparison.MoveActive(_selectedPaths, _primaryArtifact?.Path, 1));
    }

    private async void PlayPauseAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        if (FocusManager.GetFocusedElement(XamlRoot) is TextBox)
        {
            return;
        }
        args.Handled = true;
        await ToggleSynchronizedPlaybackAsync();
    }

    private async void ApproveAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        if (FocusManager.GetFocusedElement(XamlRoot) is TextBox)
        {
            return;
        }
        args.Handled = true;
        await ApplyDecisionAsync("approved");
    }

    private async void RejectAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        if (FocusManager.GetFocusedElement(XamlRoot) is TextBox)
        {
            return;
        }
        args.Handled = true;
        await ApplyDecisionAsync("rejected");
    }

    private async void OnApproveClick(object sender, RoutedEventArgs e) =>
        await ApplyDecisionAsync("approved");

    private async void OnCherryPickClick(object sender, RoutedEventArgs e) =>
        await ApplyDecisionAsync("cherry_picked");

    private async void OnRejectClick(object sender, RoutedEventArgs e) =>
        await ApplyDecisionAsync("rejected");

    private void OnJobSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        SelectedJob = JobsList.SelectedItem as ReviewJobItem;
        App.Services.Session.SetSelectedJob(_selectedProject?.Id, SelectedJob?.Job.Id);
        JobLogTextBox.Visibility = Visibility.Collapsed;
        UpdateJobCommands();
    }

    private async void OnPauseResumeJobClick(object sender, RoutedEventArgs e)
    {
        if (SelectedJob?.Job.CanResume == true)
        {
            await RunJobActionAsync("Resume", _apiClient.ResumeJobAsync, StudioJobConfirmationAction.Resume);
        }
        else if (SelectedJob?.Job.CanPause == true)
        {
            await RunJobActionAsync("Pause", _apiClient.PauseJobAsync);
        }
    }

    private async void OnCancelJobClick(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync("Cancel", _apiClient.CancelJobAsync);

    private async void OnRetryJobClick(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync("Retry", _apiClient.RetryJobAsync, StudioJobConfirmationAction.Retry);

    private async void OnRunDirectorReviewClick(object sender, RoutedEventArgs e) =>
        await RunDirectorReviewAsync(null);

    private async void OnRunNextDirectorAttemptClick(object sender, RoutedEventArgs e)
    {
        if (!DirectorReviewPresentation.CanRunNextAttempt(_selectedDirectorReport))
        {
            return;
        }
        DirectorThresholdBox.Value = _selectedDirectorReport!.Retry.Threshold * 100;
        DirectorMaxAttemptsBox.Value = _selectedDirectorReport.Retry.MaxAttempts;
        await RunDirectorReviewAsync(_selectedDirectorReport.ReportId);
    }

    private async void OnApplyDirectorGuidanceClick(object sender, RoutedEventArgs e) =>
        await ApplyDirectorGuidanceAsync();

    private void OnDirectorReportSelectionChanged(object sender, SelectionChangedEventArgs e) =>
        ShowDirectorReport((DirectorReportsList.SelectedItem as DirectorReviewReportItem)?.Report);

    private async void OnViewJobLogClick(object sender, RoutedEventArgs e) =>
        await LoadSelectedJobLogAsync();

    private async void OnStartPublishClick(object sender, RoutedEventArgs e) =>
        await StartPublishingAsync();

    private async void OnStopPublishClick(object sender, RoutedEventArgs e) =>
        await StopPublishingAsync();

    private async void OnExportTouchDesignerClick(object sender, RoutedEventArgs e) =>
        await ExportAdapterAsync("touchdesigner");

    private async void OnExportUnrealClick(object sender, RoutedEventArgs e) =>
        await ExportAdapterAsync("unreal");

    private void OnOpenOutputsClick(object sender, RoutedEventArgs e) => NavigateTo("outputs");

    private void OnOpenQueueClick(object sender, RoutedEventArgs e) => NavigateTo("queue");

    private void OnOpenTimelineClick(object sender, RoutedEventArgs e) => NavigateTo("timeline");

    private void OnOpenRenderClick(object sender, RoutedEventArgs e)
    {
        if (_primaryArtifact is not null)
        {
            App.Services.Session.SetRenderContext(_primaryArtifact.Path);
        }

        NavigateTo("render");
    }

    private void NavigateTo(string destination)
    {
        if (_primaryArtifact is not null)
        {
            App.Services.Session.SetSelectedArtifact(_primaryArtifact.Path);
            App.Services.Session.SetSourceAsset(_primaryArtifact.Path);
            App.Services.Session.SelectedVariantIndex = _primaryArtifact.VariantIndex;
        }

        App.Services.Session.SetLastWorkflowDestination(destination);
        App.Navigate(destination);
    }

    private async void PollTimer_Tick(DispatcherQueueTimer sender, object args)
    {
        CancellationToken cancellationToken = _pageCancellation?.Token ?? new CancellationToken(canceled: true);
        if (_isPolling || _isBusy || _selectedProject is null || cancellationToken.IsCancellationRequested)
        {
            return;
        }

        string projectId = _selectedProject.Id;
        _isPolling = true;
        try
        {
            await LoadJobsAsync(projectId, cancellationToken);
            await LoadPublishingAsync(projectId, cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus("Background refresh paused", StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Warning);
        }
        finally
        {
            _isPolling = false;
        }
    }

    private void ShowStatus(string title, string message, InfoBarSeverity severity)
    {
        StatusBar.Title = title;
        StatusBar.Message = message;
        StatusBar.Severity = severity;
        StatusBar.IsOpen = true;
    }

    internal static bool TryGetObject(JsonElement element, string propertyName, out JsonElement value)
    {
        if (element.ValueKind == JsonValueKind.Object &&
            element.TryGetProperty(propertyName, out value) &&
            value.ValueKind == JsonValueKind.Object)
        {
            return true;
        }

        value = default;
        return false;
    }

    internal static string ReadString(JsonElement element, string propertyName, string fallback = "")
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out JsonElement value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString() ?? fallback,
            JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False => value.ToString(),
            _ => fallback
        };
    }

    internal static int ReadInt(JsonElement element, string propertyName, int fallback = 0)
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out JsonElement value))
        {
            return fallback;
        }

        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int number))
        {
            return number;
        }

        return int.TryParse(value.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : fallback;
    }

    internal static long? ReadLong(JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out long number)
            ? number
            : null;
    }

    internal static double? ReadDouble(JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double number)
            ? number
            : null;
    }

    private static bool ReadBoolean(JsonElement element, string propertyName, bool fallback)
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.TryGetProperty(propertyName, out JsonElement value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => fallback
        };
    }

    internal static string TitleCase(string value) =>
        CultureInfo.CurrentCulture.TextInfo.ToTitleCase(value.Replace('_', ' '));

    private static string NormalizeDecision(string? decision) => decision?.Trim().ToLowerInvariant() switch
    {
        "approved" => "approved",
        "rejected" => "rejected",
        "cherry_picked" => "cherry_picked",
        _ => "unreviewed"
    };

    private bool SetField<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return false;
        }

        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        return true;
    }
}

public sealed record VariantOption(int Index, string Label);

public sealed class DirectorReviewReportItem(ReviewReport report)
{
    public ReviewReport Report { get; } = report;

    public string Heading => $"{ReviewPage.TitleCase(Report.Disposition)} · attempt {Report.Retry.Attempt}";

    public string Summary =>
        $"{DirectorReviewPresentation.FormatScore(Report.AggregateScore)} · {Report.ArtifactPath} · {Report.CreatedAt}";
}

public sealed class ReviewComparisonSlot(
    ReviewArtifact artifact,
    bool isActive,
    bool isReference)
{
    public ReviewArtifact Artifact { get; } = artifact;

    public Thickness ActiveBorderThickness { get; } = isActive ? new Thickness(2) : new Thickness(0);

    public string RoleText { get; } = (isActive, isReference) switch
    {
        (true, true) => "Active · Reference",
        (true, false) => "Active",
        (false, true) => "Reference",
        _ => "Comparison"
    };
}

public sealed class ReviewMetadataRow(string label, string values, bool isDifferent)
{
    public string Label { get; } = label;

    public string Values { get; } = values;

    public Brush ValueBrush { get; } = new SolidColorBrush(
        isDifferent ? Colors.Orange : Colors.Gray);
}

public sealed class ReviewAnnotationItem(string id, double position, string note)
{
    public string Id { get; set; } = id;

    public double Position { get; set; } = position;

    public string Note { get; set; } = note;

    public string PositionText => $"{Position:P1}";
}

public sealed class ReviewArtifact
{
    public ReviewArtifact()
    {
    }

        public string Path { get; set; } = string.Empty;

        public string Name { get; set; } = string.Empty;

        public string Kind { get; set; } = string.Empty;

        public int VariantIndex { get; set; }

        public string VariantLabel { get; set; } = string.Empty;

        public string Mood { get; set; } = string.Empty;

        public string ReviewState { get; set; } = string.Empty;

        public string ReviewNotes { get; set; } = string.Empty;

        public string Engine { get; set; } = string.Empty;

        public string ModelId { get; set; } = string.Empty;

        public string Seed { get; set; } = string.Empty;

        public IReadOnlyList<string> Traits { get; set; } = [];

        public IReadOnlyList<string> Locks { get; set; } = [];

        public IReadOnlyList<ReviewAnnotation> Annotations { get; set; } = [];

        public string Provenance { get; set; } = string.Empty;

        public long? SizeBytes { get; set; }

        public double? ModifiedAt { get; set; }

        public bool IsVideo =>
            string.Equals(Kind, "video", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".webm", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".mov", StringComparison.OrdinalIgnoreCase);

        public bool IsImage =>
            string.Equals(Kind, "image", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".webp", StringComparison.OrdinalIgnoreCase) ||
            Path.EndsWith(".bmp", StringComparison.OrdinalIgnoreCase);

        public string ComparisonSummary =>
            $"{VariantLabel} · {ReviewPage.TitleCase(ReviewState)} · " +
            $"{(string.IsNullOrWhiteSpace(Engine) ? "engine unavailable" : Engine)}";

        public string Metadata
        {
            get
            {
                var parts = new List<string>
                {
                    Path,
                    $"{Kind} · {FormatFileSize(SizeBytes)}",
                    $"{VariantLabel}{(string.IsNullOrWhiteSpace(Mood) ? string.Empty : $" · {Mood}")}",
                    $"State: {ReviewPage.TitleCase(ReviewState)}"
                };
                if (!string.IsNullOrWhiteSpace(ReviewNotes))
                {
                    parts.Add($"Notes: {ReviewNotes}");
                }
                if (Traits.Count > 0)
                {
                    parts.Add($"Traits: {string.Join(", ", Traits)}");
                }
                if (Locks.Count > 0)
                {
                    parts.Add($"Locks: {string.Join(", ", Locks)}");
                }
                parts.Add(Provenance);
                return string.Join(Environment.NewLine, parts);
            }
        }

        public static ReviewArtifact FromJson(
            JsonElement artifact,
            int groupVariantIndex,
            string groupLabel,
            string groupMood)
        {
            int variantIndex = ReviewPage.ReadInt(artifact, "variant_index", groupVariantIndex);
            return new ReviewArtifact
            {
                Path = ReviewPage.ReadString(artifact, "path"),
                Name = ReviewPage.ReadString(artifact, "name", ReviewPage.ReadString(artifact, "path")),
                Kind = ReviewPage.ReadString(artifact, "kind", "artifact"),
                VariantIndex = variantIndex,
                VariantLabel = string.IsNullOrWhiteSpace(groupLabel)
                    ? $"Variant {variantIndex + 1}"
                    : groupLabel,
                Mood = groupMood,
                ReviewState = ReviewPage.ReadString(artifact, "review_state", "unreviewed"),
                ReviewNotes = ReviewPage.ReadString(artifact, "review_notes"),
                Engine = ReviewPage.ReadString(artifact, "engine"),
                ModelId = ReviewPage.ReadString(artifact, "model_id"),
                Seed = ReviewPage.ReadString(artifact, "seed"),
                Traits = ReadStringArray(artifact, "cherry_pick_traits"),
                Locks = ReadStringArray(artifact, "locks"),
                Annotations = ReadAnnotations(artifact),
                Provenance = FormatProvenance(artifact),
                SizeBytes = ReviewPage.ReadLong(artifact, "size_bytes"),
                ModifiedAt = ReviewPage.ReadDouble(artifact, "modified_at")
            };
        }

        private static IReadOnlyList<string> ReadStringArray(JsonElement element, string propertyName)
        {
            if (!element.TryGetProperty(propertyName, out JsonElement values) ||
                values.ValueKind != JsonValueKind.Array)
            {
                return [];
            }

            return values.EnumerateArray()
                .Where(item => item.ValueKind == JsonValueKind.String)
                .Select(item => item.GetString())
                .Where(item => !string.IsNullOrWhiteSpace(item))
                .Cast<string>()
                .ToArray();
        }

        private static IReadOnlyList<ReviewAnnotation> ReadAnnotations(JsonElement element)
        {
            if (!element.TryGetProperty("annotations", out JsonElement values) || values.ValueKind != JsonValueKind.Array)
            {
                return [];
            }

            return values.EnumerateArray()
                .Select(item => new ReviewAnnotation(
                    ReviewPage.ReadDouble(item, "position") ?? 0,
                    ReviewPage.ReadString(item, "note")))
                .Where(item => !string.IsNullOrWhiteSpace(item.Note))
                .Select(item => item.Normalize())
                .Take(200)
                .ToArray();
        }

        private static string FormatProvenance(JsonElement artifact)
        {
            var parts = new List<string>();
            string hash = ReviewPage.ReadString(artifact, "content_hash");
            if (!string.IsNullOrWhiteSpace(hash))
            {
                parts.Add($"Hash {hash[..Math.Min(hash.Length, 12)]}");
            }

            if (ReviewPage.TryGetObject(artifact, "provenance", out JsonElement provenance))
            {
                int parentCount = ArrayCount(provenance, "parents");
                int sourceCount = ArrayCount(provenance, "source_assets");
                if (parentCount > 0)
                {
                    parts.Add($"{parentCount} parent{(parentCount == 1 ? string.Empty : "s")}");
                }
                if (sourceCount > 0)
                {
                    parts.Add($"{sourceCount} source asset{(sourceCount == 1 ? string.Empty : "s")}");
                }
            }

            return parts.Count == 0 ? "No provenance metadata." : string.Join(" · ", parts);
        }

        private static int ArrayCount(JsonElement element, string propertyName) =>
            element.TryGetProperty(propertyName, out JsonElement values) &&
            values.ValueKind == JsonValueKind.Array
                ? values.GetArrayLength()
                : 0;

        private static string FormatFileSize(long? size)
        {
            if (size is null || size < 0)
            {
                return "Unknown size";
            }

            string[] units = ["B", "KB", "MB", "GB"];
            double value = size.Value;
            int unit = 0;
            while (value >= 1024 && unit < units.Length - 1)
            {
                value /= 1024;
                unit++;
            }

            return $"{value:0.#} {units[unit]}";
        }
}

public sealed class ReviewContinuityWarning
{
    public ReviewContinuityWarning(string heading, string detail)
    {
        Heading = heading;
        Detail = detail;
    }

    public string Heading { get; set; }

    public string Detail { get; set; }
}

public sealed class ReviewJobItem
{
    public ReviewJobItem(StudioJob job)
    {
        Job = job;
    }

    public StudioJob Job { get; }

    public string Title => $"{(string.IsNullOrWhiteSpace(Job.Type) ? "Job" : ReviewPage.TitleCase(Job.Type))} · {Job.Id}";

    public string Status => ReviewPage.TitleCase(Job.Status);

    public string Error => Job.Error ?? string.Empty;

    public string ProgressSummary
    {
        get
        {
            string percent = Job.Progress?.Percent is double value
                ? $"{Math.Clamp(value, 0, 100):0.#}%"
                : "Progress unavailable";
            string detail = Job.Progress?.Message ?? Job.Progress?.Stage ?? $"Attempt {Job.Attempt}";
            return $"{percent} · {detail}";
        }
    }
}
