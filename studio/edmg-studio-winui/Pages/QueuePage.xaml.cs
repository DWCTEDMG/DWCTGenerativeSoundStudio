using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class QueuePage : Page, IStudioRefreshable
{
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
    private readonly DispatcherQueueTimer _refreshTimer;
    private bool _isRefreshing;
    private bool _isCommandRunning;
    private bool _isRebuildingJobs;
    private string? _desiredJobId;
    private string? _desiredJobProjectId;
    private readonly List<StudioJob> _allJobs = [];

    public ObservableCollection<JobListItem> Jobs { get; } = [];

    public QueuePage()
    {
        InitializeComponent();
        _desiredJobId = App.Services.Session.SelectedJobId;
        _desiredJobProjectId = App.Services.Session.SelectedJobProjectId;
        AllProjectsSwitch.IsOn = App.Services.Session.QueueAllProjects;
        StatusFilterComboBox.SelectedIndex = (int)App.Services.Session.QueueFilter;
        _refreshTimer = DispatcherQueue.CreateTimer();
        _refreshTimer.Interval = TimeSpan.FromSeconds(2);
        _refreshTimer.Tick += RefreshTimer_Tick;
        Loaded += QueuePage_Loaded;
        Unloaded += QueuePage_Unloaded;
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_isRefreshing)
        {
            return;
        }

        _isRefreshing = true;
        SetBusy(Jobs.Count == 0);
        try
        {
            var projectId = App.Services.Session.ActiveProjectId;
            StudioJobListResponse response;
            if (AllProjectsSwitch.IsOn)
            {
                response = await _apiClient.GetJobsAsync(cancellationToken);
            }
            else if (!string.IsNullOrWhiteSpace(projectId))
            {
                response = await _apiClient.GetProjectJobsAsync(projectId, cancellationToken);
            }
            else
            {
                Jobs.Clear();
                ShowStatus("Open a project or enable All projects to browse jobs.", InfoBarSeverity.Warning);
                return;
            }

            _allJobs.Clear();
            _allJobs.AddRange(response.Jobs);
            ApplyFilter();

            ShowStatus(
                Jobs.Count == 0 ? "No jobs are queued for this scope." : $"{Jobs.Count} jobs loaded.",
                Jobs.Count == 0 ? InfoBarSeverity.Informational : InfoBarSeverity.Success,
                open: Jobs.Count == 0);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            _isRefreshing = false;
            SetBusy(_isCommandRunning);
        }
    }

    private async void QueuePage_Loaded(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
        _refreshTimer.Start();
    }

    private void QueuePage_Unloaded(object sender, RoutedEventArgs e) => _refreshTimer.Stop();

    private async void RefreshTimer_Tick(DispatcherQueueTimer sender, object args)
    {
        if (!_isCommandRunning && _allJobs.Any(job => job.IsActive))
        {
            await RefreshAsync();
        }
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async void AllProjectsSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        App.Services.Session.QueueAllProjects = AllProjectsSwitch.IsOn;
        if (IsLoaded)
        {
            await RefreshAsync();
        }
    }

    private void StatusFilterComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (StatusFilterComboBox.SelectedItem is ComboBoxItem { Tag: string tag } &&
            Enum.TryParse(tag, out RenderQueueFilter filter))
        {
            App.Services.Session.QueueFilter = filter;
            ApplyFilter();
        }
    }

    private void ApplyFilter()
    {
        RenderQueueFilter filter = App.Services.Session.QueueFilter;
        RenderQueueSnapshot snapshot = RenderQueueSnapshot.Create(_allJobs);
        ActiveMetricText.Text = snapshot.ActiveCount.ToString();
        RunningMetricText.Text = snapshot.RunningCount.ToString();
        CompletedMetricText.Text = snapshot.CompletedCount.ToString();
        AttentionMetricText.Text = snapshot.AttentionCount.ToString();

        IEnumerable<StudioJob> ordered = _allJobs
            .OrderBy(job => job.IsActive ? 0 : 1)
            .ThenByDescending(job => job.IsActive ? job.Priority : int.MinValue)
            .ThenBy(job => job.IsActive ? job.CreatedAt : null, StringComparer.Ordinal)
            .ThenByDescending(job => job.IsActive ? null : job.UpdatedAt ?? job.CreatedAt);
        _isRebuildingJobs = true;
        try
        {
            Jobs.Clear();
            foreach (StudioJob job in ordered)
            {
                RenderQueueJobSummary summary = RenderQueueJobSummary.Create(job);
                if (summary.Matches(filter))
                {
                    Jobs.Add(new JobListItem(summary));
                }
            }

            JobListItem? selected = Jobs.FirstOrDefault(item =>
                item.Job.Id == _desiredJobId && item.Job.ProjectId == _desiredJobProjectId);
            JobsList.SelectedItem = selected ?? Jobs.FirstOrDefault();
            if (JobsList.SelectedItem is JobListItem visible)
            {
                UpdateSelection(visible, persist: false);
            }
            else
            {
                ClearSelection(false);
            }
        }
        finally
        {
            _isRebuildingJobs = false;
        }
    }

    private void JobsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isRebuildingJobs)
        {
            return;
        }

        if (JobsList.SelectedItem is not JobListItem item)
        {
            ClearSelection(false);
            return;
        }

        UpdateSelection(item);
    }

    private void UpdateSelection(JobListItem item, bool persist = true)
    {
        var job = item.Job;
        if (persist)
        {
            _desiredJobProjectId = job.ProjectId;
            _desiredJobId = job.Id;
            App.Services.Session.SetSelectedJob(job.ProjectId, job.Id);
        }
        SelectedJobText.Text = $"{job.Type} · {StudioPageHelpers.ShortId(job.Id)}";
        SelectedJobSummaryText.Text = item.Summary;
        SelectedDestinationText.Text = $"Provider: {item.Operations.ProviderLabel}\nDestination: {item.Operations.DestinationLabel}";
        RecommendationBar.Message = item.Operations.Recommendation;
        RecommendationBar.IsOpen = true;
        SelectedProgressBar.Value = item.Percent;
        SelectedProgressBar.Visibility = item.ProgressVisibility;
        bool canPrioritize = job.Status is "queued" or "paused";
        PriorityHighButton.IsEnabled = canPrioritize;
        PriorityNormalButton.IsEnabled = canPrioritize;
        PriorityLowButton.IsEnabled = canPrioritize;
        PauseButton.IsEnabled = job.CanPause;
        ResumeButton.IsEnabled = job.CanResume;
        CancelButton.IsEnabled = job.CanCancel;
        RetryButton.IsEnabled = job.CanRetry;
        ResumeCheckpointButton.IsEnabled = !job.IsActive;
        RestartCleanButton.IsEnabled = !job.IsActive;
        ClearCachedFramesButton.IsEnabled = !job.IsActive;
        DropCheckpointButton.IsEnabled = !job.IsActive;
        LogButton.IsEnabled = true;
        EventsButton.IsEnabled = true;
        OpenOutputsButton.IsEnabled = true;
        OpenReviewButton.IsEnabled = true;
        OpenTimelineButton.IsEnabled = job.Status == "succeeded" && job.Type == "internal_video";
        DetailsTextBox.Text = FormatJobDetails(job);
    }

    private async void PriorityHighButton_Click(object sender, RoutedEventArgs e) => await SetPriorityAsync(50);

    private async void PriorityNormalButton_Click(object sender, RoutedEventArgs e) => await SetPriorityAsync(0);

    private async void PriorityLowButton_Click(object sender, RoutedEventArgs e) => await SetPriorityAsync(-50);

    private Task SetPriorityAsync(int priority) => RunJobActionAsync(
        priority switch { > 0 => "promoted", < 0 => "deprioritized", _ => "priority reset" },
        (projectId, jobId) => _apiClient.SetJobPriorityAsync(projectId, jobId, priority));

    private async void PauseButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync("pause", (projectId, jobId) => _apiClient.PauseJobAsync(projectId, jobId));

    private async void ResumeButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync(
            "resume",
            (projectId, jobId) => _apiClient.ResumeJobAsync(projectId, jobId),
            StudioJobConfirmationAction.Resume);

    private async void CancelButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync("cancel", (projectId, jobId) => _apiClient.CancelJobAsync(projectId, jobId));

    private async void RetryButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync(
            "retry",
            (projectId, jobId) => _apiClient.RetryJobAsync(projectId, jobId),
            StudioJobConfirmationAction.Retry);

    private async void ResumeCheckpointButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync(
            "checkpoint continuation",
            (projectId, jobId) => _apiClient.ResumeJobFromCheckpointAsync(projectId, jobId),
            StudioJobConfirmationAction.ResumeFromCheckpoint);

    private async void RestartCleanButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync(
            "clean restart",
            (projectId, jobId) => _apiClient.RestartJobCleanAsync(projectId, jobId),
            StudioJobConfirmationAction.RestartClean);

    private async void ClearCachedFramesButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync(
            "cached-frame cleanup",
            (projectId, jobId) => _apiClient.ClearJobCachedFramesAsync(projectId, jobId),
            StudioJobConfirmationAction.ClearCachedFrames);

    private async void DropCheckpointButton_Click(object sender, RoutedEventArgs e) =>
        await RunJobActionAsync(
            "checkpoint removal",
            (projectId, jobId) => _apiClient.DropJobCheckpointAsync(projectId, jobId),
            StudioJobConfirmationAction.DropCheckpoint);

    private async Task RunJobActionAsync<TResponse>(
        string action,
        Func<string, string, Task<TResponse>> command,
        StudioJobConfirmationAction? confirmationAction = null)
    {
        if (JobsList.SelectedItem is not JobListItem item)
        {
            return;
        }

        if (_isCommandRunning)
        {
            return;
        }

        if (confirmationAction is StudioJobConfirmationAction requiredConsent &&
            !await StudioPageHelpers.ConfirmAsync(
                XamlRoot,
                StudioJobConfirmationFactory.CreateRecoveryConsent(item.Job, requiredConsent)))
        {
            return;
        }

        _isCommandRunning = true;
        SetBusy(true);
        try
        {
            await command(item.Job.ProjectId, item.Job.Id);
            ShowStatus($"Job {action} request accepted.", InfoBarSeverity.Success);
            await RefreshAsync();
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            _isCommandRunning = false;
            SetBusy(false);
        }
    }

    private async void LogButton_Click(object sender, RoutedEventArgs e) =>
        await LoadDiagnosticAsync("log", (projectId, jobId) => _apiClient.GetJobLogAsync(projectId, jobId));

    private async void EventsButton_Click(object sender, RoutedEventArgs e) =>
        await LoadDiagnosticAsync("events", (projectId, jobId) => _apiClient.GetJobEventsAsync(projectId, jobId));

    private void OpenOutputsButton_Click(object sender, RoutedEventArgs e) => NavigateWithSelectedJob("outputs");

    private void OpenReviewButton_Click(object sender, RoutedEventArgs e) => NavigateWithSelectedJob("review");

    private async void OpenTimelineButton_Click(object sender, RoutedEventArgs e)
    {
        if (JobsList.SelectedItem is not JobListItem { Job.Status: "succeeded" } item)
        {
            ShowStatus("Only a completed render can be inserted into the timeline.", InfoBarSeverity.Warning);
            return;
        }

        _isCommandRunning = true;
        SetBusy(true);
        try
        {
            StudioJob job = item.Job;
            App.Services.Session.ActiveProjectId = job.ProjectId;
            App.Services.Session.SetSelectedJob(job.ProjectId, job.Id);
            EditorState editor = await _apiClient.GetEditorStateAsync(job.ProjectId);
            double startSeconds = App.Services.Session.TimelineFocusSeconds ?? 0;
            string outputPath = FindOutputPath(job.Result) ?? string.Empty;
            await _apiClient.InsertRenderResultWithFallbackAsync(
                job.ProjectId,
                new InsertRenderResultRequest(job.Id, editor.Revision, StartSeconds: startSeconds),
                RenderResultDescriptor.FromJob(job, outputPath));
            App.Services.Session.SetLastWorkflowDestination("timeline");
            App.Navigate("timeline");
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            _isCommandRunning = false;
            SetBusy(false);
        }
    }

    private static string? FindOutputPath(JsonElement? result)
    {
        if (result is not JsonElement element) return null;
        return FindOutputPath(element);
    }

    private static string? FindOutputPath(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (string name in new[] { "output_path", "path", "video_path", "artifact_path" })
            {
                if (element.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String)
                    return value.GetString();
            }
            foreach (JsonProperty property in element.EnumerateObject())
            {
                string? nested = FindOutputPath(property.Value);
                if (!string.IsNullOrWhiteSpace(nested)) return nested;
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement item in element.EnumerateArray())
            {
                string? nested = FindOutputPath(item);
                if (!string.IsNullOrWhiteSpace(nested)) return nested;
            }
        }
        return null;
    }

    private void NavigateWithSelectedJob(string destination)
    {
        if (JobsList.SelectedItem is not JobListItem item)
        {
            return;
        }

        App.Services.Session.ActiveProjectId = item.Job.ProjectId;
        App.Services.Session.SetSelectedJob(item.Job.ProjectId, item.Job.Id);
        App.Services.Session.SetLastWorkflowDestination(destination);
        App.Navigate(destination);
    }

    private async Task LoadDiagnosticAsync(
        string label,
        Func<string, string, Task<JsonElement>> loader)
    {
        if (JobsList.SelectedItem is not JobListItem item)
        {
            return;
        }

        if (_isCommandRunning)
        {
            return;
        }

        _isCommandRunning = true;
        SetBusy(true);
        try
        {
            DetailsTextBox.Text = StudioPageHelpers.FormatJson(await loader(item.Job.ProjectId, item.Job.Id));
            ShowStatus($"Job {label} loaded.", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            _isCommandRunning = false;
            SetBusy(false);
        }
    }

    private static string FormatJobDetails(StudioJob job)
    {
        var details = new JsonObject
        {
            ["id"] = job.Id,
            ["projectId"] = job.ProjectId,
            ["type"] = job.Type,
            ["status"] = job.Status,
            ["createdAt"] = job.CreatedAt,
            ["startedAt"] = job.StartedAt,
            ["finishedAt"] = job.FinishedAt,
            ["attempt"] = job.Attempt,
            ["priority"] = job.Priority,
            ["error"] = job.Error,
            ["progress"] = job.Progress is null
                ? null
                : new JsonObject
                {
                    ["percent"] = job.Progress.Percent,
                    ["stage"] = job.Progress.Stage,
                    ["message"] = job.Progress.Message,
                    ["current"] = job.Progress.Current,
                    ["total"] = job.Progress.Total
                },
            ["result"] = job.Result is JsonElement result
                ? JsonNode.Parse(result.GetRawText())
                : null
        };

        return StudioPageHelpers.FormatJson(details);
    }

    private void ClearSelection(bool clearPersistedSelection = true)
    {
        if (clearPersistedSelection)
        {
            App.Services.Session.SetSelectedJob(null, null);
        }

        SelectedJobText.Text = "Select a job";
        SelectedJobSummaryText.Text = "Job actions and diagnostic details appear here.";
        SelectedDestinationText.Text = string.Empty;
        RecommendationBar.IsOpen = false;
        SelectedProgressBar.Visibility = Visibility.Collapsed;
        PriorityHighButton.IsEnabled = false;
        PriorityNormalButton.IsEnabled = false;
        PriorityLowButton.IsEnabled = false;
        PauseButton.IsEnabled = false;
        ResumeButton.IsEnabled = false;
        CancelButton.IsEnabled = false;
        RetryButton.IsEnabled = false;
        ResumeCheckpointButton.IsEnabled = false;
        RestartCleanButton.IsEnabled = false;
        ClearCachedFramesButton.IsEnabled = false;
        DropCheckpointButton.IsEnabled = false;
        LogButton.IsEnabled = false;
        EventsButton.IsEnabled = false;
        OpenOutputsButton.IsEnabled = false;
        OpenReviewButton.IsEnabled = false;
        OpenTimelineButton.IsEnabled = false;
        DetailsTextBox.Text = string.Empty;
    }

    private void SetBusy(bool value)
    {
        BusyRing.IsActive = value;
        StudioPageHelpers.SetControlsEnabled(QueueScopeControls, !value);
        StudioPageHelpers.SetControlsEnabled(QueueWorkspace, !value);
        if (!value)
        {
            if (JobsList.SelectedItem is JobListItem item)
            {
                UpdateSelection(item, persist: false);
            }
            else
            {
                ClearSelection(false);
            }
        }
    }

    private void ShowStatus(string message, InfoBarSeverity severity, bool open = true)
    {
        StatusBar.Message = message;
        StatusBar.Severity = severity;
        StatusBar.IsOpen = open;
    }
}

public sealed class JobListItem
{
    public JobListItem(RenderQueueJobSummary operations) => Operations = operations;

    public RenderQueueJobSummary Operations { get; }
    public StudioJob Job => Operations.Job;
    public string Title => Operations.Title;
    public string StatusLabel => Operations.StatusLabel;
    public string PriorityLabel => Operations.PriorityLabel;
    public double Percent => Operations.Percent;
    public Visibility ProgressVisibility => Job.IsActive ? Visibility.Visible : Visibility.Collapsed;
    public string Summary => $"{Operations.StageLabel} · {Operations.ProgressLabel} · {Operations.EtaLabel}";
}
