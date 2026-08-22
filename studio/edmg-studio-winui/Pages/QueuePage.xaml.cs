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

    public ObservableCollection<JobListItem> Jobs { get; } = [];

    public QueuePage()
    {
        InitializeComponent();
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

            var selectedId = (JobsList.SelectedItem as JobListItem)?.Job.Id;
            Jobs.Clear();
            foreach (var job in response.Jobs.OrderByDescending(job => job.CreatedAt))
            {
                Jobs.Add(new JobListItem(job));
            }

            var selected = Jobs.FirstOrDefault(item => item.Job.Id == selectedId);
            if (selected is not null)
            {
                JobsList.SelectedItem = selected;
            }
            else if (Jobs.Count > 0)
            {
                JobsList.SelectedIndex = 0;
            }
            else
            {
                ClearSelection();
            }

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
        if (!_isCommandRunning && Jobs.Any(item => item.Job.IsActive))
        {
            await RefreshAsync();
        }
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async void AllProjectsSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (IsLoaded)
        {
            await RefreshAsync();
        }
    }

    private void JobsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (JobsList.SelectedItem is not JobListItem item)
        {
            ClearSelection();
            return;
        }

        UpdateSelection(item);
    }

    private void UpdateSelection(JobListItem item)
    {
        var job = item.Job;
        App.Services.Session.SetSelectedJob(job.ProjectId, job.Id);
        SelectedJobText.Text = $"{job.Type} · {StudioPageHelpers.ShortId(job.Id)}";
        SelectedJobSummaryText.Text = item.Summary;
        SelectedProgressBar.Value = item.Percent;
        SelectedProgressBar.Visibility = item.ProgressVisibility;
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
        OpenTimelineButton.IsEnabled = true;
        DetailsTextBox.Text = FormatJobDetails(job);
    }

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

    private void OpenTimelineButton_Click(object sender, RoutedEventArgs e) => NavigateWithSelectedJob("timeline");

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

    private void ClearSelection()
    {
        App.Services.Session.SetSelectedJob(null, null);
        SelectedJobText.Text = "Select a job";
        SelectedJobSummaryText.Text = "Job actions and diagnostic details appear here.";
        SelectedProgressBar.Visibility = Visibility.Collapsed;
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
                UpdateSelection(item);
            }
            else
            {
                ClearSelection();
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
    public JobListItem(StudioJob job) => Job = job;

    public StudioJob Job { get; }
    public string Title => $"{Job.Type} · {StudioPageHelpers.ShortId(Job.Id)}";
    public string StatusLabel => Job.Status.Replace('_', ' ');
    public double Percent => Math.Clamp(Job.Progress?.Percent ?? 0, 0, 100);
    public Visibility ProgressVisibility => Job.IsActive ? Visibility.Visible : Visibility.Collapsed;
    public string Summary
    {
        get
        {
            var progress = Job.Progress?.Message ?? Job.Progress?.Stage;
            var timestamp = Job.UpdatedAt ?? Job.CreatedAt ?? "unknown time";
            return string.IsNullOrWhiteSpace(progress)
                ? $"{StudioPageHelpers.ShortId(Job.ProjectId)} · {timestamp}"
                : $"{progress} · {StudioPageHelpers.ShortId(Job.ProjectId)} · {timestamp}";
        }
    }
}
