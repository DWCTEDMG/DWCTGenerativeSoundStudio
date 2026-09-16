using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Pages;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI;

public sealed partial class MainPage : Page
{
    private readonly HashSet<string> _reviewedJobIds = new(StringComparer.OrdinalIgnoreCase);
    private bool _started;
    private bool _isBackendStatusSubscribed;
    private IDisposable? _jobsActivityLease;
    private ModelCatalogueResponse? _modelCatalogue;
    private DateTimeOffset _modelCatalogueUpdatedAt;

    public MainPage()
    {
        InitializeComponent();
        if (StudioNavigation.SettingsItem is NavigationViewItem settingsItem)
        {
            AutomationProperties.SetAutomationId(settingsItem, "SettingsNavigationItem");
        }

        App.Shell = this;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    public void NavigateTo(string destination)
    {
        destination = StudioNavigationDestination.NormalizeOrDefault(destination);
        var item = FindNavigationItem(destination);
        if (item is not null)
        {
            StudioNavigation.SelectedItem = item;
        }

        var pageType = ResolvePageType(destination);
        if (ContentFrame.CurrentSourcePageType != pageType)
        {
            ContentFrame.Navigate(pageType, destination);
        }
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (!_isBackendStatusSubscribed)
        {
            App.Services.BackendSupervisor.StatusChanged += BackendSupervisor_StatusChanged;
            App.Services.JobsActivity.SnapshotChanged += JobsActivity_SnapshotChanged;
            _jobsActivityLease = App.Services.JobsActivity.Activate();
            _isBackendStatusSubscribed = true;
        }

        if (!_started)
        {
            _started = true;
            var status = await App.Services.BackendSupervisor.StartAsync();
            UpdateBackendStatus(status);
            if (status.State == BackendLifecycleState.WaitingForHealth)
            {
                NavigateTo("setup");
                return;
            }

            if (!status.IsReady)
            {
                NavigateTo("setup");
                return;
            }

            try
            {
                var setup = await App.Services.ApiClient.GetSetupStatusAsync();
                var readiness = setup.SystemReadiness;
                if (readiness.ValueKind == System.Text.Json.JsonValueKind.Object &&
                    readiness.TryGetProperty("ready", out var ready) &&
                    ready.ValueKind == System.Text.Json.JsonValueKind.False)
                {
                    NavigateTo("setup");
                    return;
                }
            }
            catch (Exception ex)
            {
                CrashLogger.Write("Startup setup status could not be loaded.", ex);
                NavigateTo("setup");
                return;
            }

            StudioLaunchRequest? launchRequest = App.TakePendingLaunchRequest();
            if (launchRequest?.ProjectId is { Length: > 0 } projectId)
            {
                App.Services.Session.ActiveProjectId = projectId;
            }

            NavigateTo(App.Services.Configuration.HasPendingMigration
                ? "migration"
                : launchRequest?.Destination
                    ?? StudioNavigationDestination.NormalizeRestorableOrDefault(
                        App.Services.Session.LastWorkflowDestination));
            await RefreshActivityAsync();
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        _jobsActivityLease?.Dispose();
        _jobsActivityLease = null;
        if (App.Shell == this)
        {
            App.Shell = null;
        }

        if (_isBackendStatusSubscribed)
        {
            App.Services.BackendSupervisor.StatusChanged -= BackendSupervisor_StatusChanged;
            App.Services.JobsActivity.SnapshotChanged -= JobsActivity_SnapshotChanged;
            _isBackendStatusSubscribed = false;
        }
    }

    private void BackendSupervisor_StatusChanged(object? sender, BackendStatus status)
    {
        if (!DispatcherQueue.TryEnqueue(
            DispatcherQueuePriority.Normal,
            () => { _ = ObserveBackendStatusAsync(status); }))
            CrashLogger.Write("Backend status update could not be dispatched because the shell dispatcher is unavailable.");
    }

    private async Task ObserveBackendStatusAsync(BackendStatus status)
    {
        UpdateBackendStatus(status);
        if (!status.IsReady || ContentFrame.Content is not IStudioRefreshable refreshable) return;

        try
        {
            await refreshable.RefreshAsync();
        }
        catch (Exception ex)
        {
            CrashLogger.Write("Backend connected, but the active page refresh failed.", ex);
            BackendInfoBar.Severity = InfoBarSeverity.Warning;
            BackendInfoBar.Title = "Backend connected; page refresh failed";
            BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(ex);
            BackendInfoBar.IsOpen = true;
        }
    }

    private void UpdateBackendStatus(BackendStatus status)
    {
        BackendStatusCard.Title = $"Backend: {StatusLabel(status)}";
        BackendStatusCard.Detail = status.CurrentBackendUri.ToString().TrimEnd('/');
        ToolTipService.SetToolTip(BackendStatusCard, status.CurrentBackendUri.ToString());

        BackendInfoBar.Title = status.Message;
        BackendInfoBar.Message = status.Detail ?? status.CurrentBackendUri.ToString();
        BackendInfoBar.Severity = status.State switch
        {
            BackendLifecycleState.Ready => InfoBarSeverity.Success,
            BackendLifecycleState.Failed => InfoBarSeverity.Error,
            BackendLifecycleState.Unavailable => InfoBarSeverity.Warning,
            _ => InfoBarSeverity.Informational
        };
        BackendInfoBar.IsOpen = status.State != BackendLifecycleState.Ready;
    }

    private async void ReconnectBackend_Click(object sender, RoutedEventArgs e)
    {
        BackendInfoBar.IsOpen = true;
        BackendInfoBar.Severity = InfoBarSeverity.Informational;
        BackendInfoBar.Title = "Connecting to the Studio backend";
        BackendInfoBar.Message = "Checking health and safely starting the managed backend when required.";
        try
        {
            var status = await App.Services.BackendSupervisor.RefreshHealthAsync();
            if (status.State == BackendLifecycleState.WaitingForHealth)
            {
                UpdateBackendStatus(status);
                return;
            }

            if (!status.IsReady)
            {
                status = await App.Services.BackendSupervisor.StartAsync();
                if (status.State == BackendLifecycleState.WaitingForHealth)
                {
                    UpdateBackendStatus(status);
                    return;
                }
            }

            status = await App.Services.BackendSupervisor.RefreshHealthAsync();
            if (status.State == BackendLifecycleState.WaitingForHealth)
            {
                UpdateBackendStatus(status);
                return;
            }

            if (!status.IsReady)
            {
                throw new InvalidOperationException(
                    status.Detail ?? status.Message ?? "The backend did not become ready.");
            }

            BackendInfoBar.Severity = InfoBarSeverity.Success;
            BackendInfoBar.Title = "Studio backend connected";
            BackendInfoBar.Message = status.Detail ?? status.Message;
            if (ContentFrame.Content is IStudioRefreshable refreshable)
            {
                await refreshable.RefreshAsync();
            }
        }
        catch (Exception ex)
        {
            BackendInfoBar.Severity = InfoBarSeverity.Error;
            BackendInfoBar.Title = "Backend connection failed";
            BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(ex);
        }
    }

    private void Navigation_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            NavigateTo("settings");
            return;
        }

        if (args.SelectedItemContainer?.Tag is string destination)
        {
            if (destination.Equals("review", StringComparison.OrdinalIgnoreCase))
            {
                MarkReviewItemsRead();
            }

            var pageType = ResolvePageType(destination);
            if (ContentFrame.CurrentSourcePageType != pageType)
            {
                ContentFrame.Navigate(pageType, destination);
            }
        }

    }

    private void Navigation_BackRequested(NavigationView sender, NavigationViewBackRequestedEventArgs args)
    {
        if (ContentFrame.CanGoBack)
        {
            ContentFrame.GoBack();
        }
    }

    private void ContentFrame_Navigated(object sender, NavigationEventArgs e)
    {
        if (e.Parameter is not string destination)
        {
            return;
        }

        destination = StudioNavigationDestination.NormalizeOrDefault(destination);
        var item = FindNavigationItem(destination);
        if (item is not null && !ReferenceEquals(StudioNavigation.SelectedItem, item))
        {
            StudioNavigation.SelectedItem = item;
        }

        StudioNavigation.IsBackEnabled = ContentFrame.CanGoBack;
        if (StudioNavigationDestination.IsRestorable(destination))
        {
            App.Services.Session.SetLastWorkflowDestination(destination);
        }
    }

    private void JobsActivity_SnapshotChanged(object? sender, StudioJobsActivitySnapshot snapshot)
    {
        if (!DispatcherQueue.TryEnqueue(
            DispatcherQueuePriority.Normal,
            () => { _ = ObserveActivitySnapshotAsync(snapshot); }))
            CrashLogger.Write("Studio activity update could not be dispatched because the shell dispatcher is unavailable.");
    }

    private async Task ObserveActivitySnapshotAsync(StudioJobsActivitySnapshot snapshot)
    {
        try
        {
            await ApplyActivitySnapshotAsync(snapshot);
        }
        catch (Exception ex)
        {
            CrashLogger.Write("Studio activity update failed.", ex);
        }
    }

    private async Task RefreshActivityAsync()
    {
        if (!App.Services.BackendSupervisor.Status.IsReady)
        {
            App.MainWindowInstance?.UpdateTaskbarProgress(StudioTaskbarProgress.None);
            return;
        }

        await App.Services.JobsActivity.RefreshAsync();
        await ApplyActivitySnapshotAsync(App.Services.JobsActivity.Snapshot);
    }

    private async Task ApplyActivitySnapshotAsync(StudioJobsActivitySnapshot snapshot)
    {
        if (snapshot.Error is not null)
        {
            CrashLogger.Write("Studio activity poll failed.", snapshot.Error);
            App.MainWindowInstance?.UpdateTaskbarProgress(StudioTaskbarProgress.None);
            BackendInfoBar.Severity = InfoBarSeverity.Warning;
            BackendInfoBar.Title = "Studio activity could not be refreshed";
            BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(snapshot.Error);
            BackendInfoBar.IsOpen = true;
            return;
        }

        try
        {
            if (_modelCatalogue is null || DateTimeOffset.UtcNow - _modelCatalogueUpdatedAt >= TimeSpan.FromSeconds(30))
            {
                _modelCatalogue = await App.Services.ApiClient.GetTypedModelCatalogueAsync();
                _modelCatalogueUpdatedAt = DateTimeOffset.UtcNow;
            }

            StudioShellActivity activity = StudioShellActivity.Create(snapshot.Jobs, _modelCatalogue, _reviewedJobIds);
            GlobalRenderPlayer.UpdateJob(activity.FeaturedJob);
            App.MainWindowInstance?.UpdateTaskbarProgress(StudioTaskbarProgress.Create(snapshot.Jobs));
            SetBadge(QueueBadge, activity.ActiveJobCount + activity.FailedJobCount);
            SetBadge(ReviewBadge, activity.ReviewItemCount);
            SetBadge(ModelsBadge, activity.ModelAttentionCount);
            ToolTipService.SetToolTip(
                QueueBadge,
                $"{activity.ActiveJobCount} active and {activity.FailedJobCount} failed jobs");
        }
        catch (Exception ex)
        {
            CrashLogger.Write("Studio shell activity could not be applied.", ex);
            BackendInfoBar.Severity = InfoBarSeverity.Warning;
            BackendInfoBar.Title = "Studio activity could not be refreshed";
            BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(ex);
            BackendInfoBar.IsOpen = true;
        }
    }

    private void MarkReviewItemsRead()
    {
        _ = MarkReviewItemsReadAsync();
    }

    private async Task MarkReviewItemsReadAsync()
    {
        try
        {
            await App.Services.JobsActivity.RefreshAsync();
            foreach (StudioJob job in App.Services.JobsActivity.Snapshot.Jobs.Where(job =>
                         job.Status.Equals("succeeded", StringComparison.OrdinalIgnoreCase)
                         && (job.Type.Contains("render", StringComparison.OrdinalIgnoreCase)
                             || job.Type.Contains("video", StringComparison.OrdinalIgnoreCase))))
            {
                _reviewedJobIds.Add(job.Id);
            }

            await RefreshActivityAsync();
        }
        catch (Exception ex)
        {
            CrashLogger.Write("Review badge update failed.", ex);
            BackendInfoBar.Severity = InfoBarSeverity.Warning;
            BackendInfoBar.Title = "Review badge could not be updated";
            BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(ex);
            BackendInfoBar.IsOpen = true;
        }
    }

    private async void GlobalRenderPlayer_PauseRequested(object? sender, StudioJob job)
    {
        await RunGlobalJobActionAsync(() => App.Services.ApiClient.PauseJobAsync(job.ProjectId, job.Id));
    }

    private async void GlobalRenderPlayer_CancelRequested(object? sender, StudioJob job)
    {
        await RunGlobalJobActionAsync(() => App.Services.ApiClient.CancelJobAsync(job.ProjectId, job.Id));
    }

    private void GlobalRenderPlayer_OpenQueueRequested(object? sender, EventArgs e)
    {
        if (GlobalRenderPlayer.DataContext is StudioJob job)
        {
            App.Services.Session.SetSelectedJob(job.ProjectId, job.Id);
        }

        NavigateTo("queue");
    }

    private async Task RunGlobalJobActionAsync(Func<Task<StudioJobActionResponse>> action)
    {
        try
        {
            await action();
            await RefreshActivityAsync();
        }
        catch (Exception ex)
        {
            BackendInfoBar.Severity = InfoBarSeverity.Error;
            BackendInfoBar.Title = "Render command failed";
            BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(ex);
            BackendInfoBar.IsOpen = true;
        }
    }

    private static void SetBadge(InfoBadge badge, int value)
    {
        badge.Value = value;
        badge.Visibility = value > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private NavigationViewItem? FindNavigationItem(string destination)
    {
        if (string.Equals(destination, "settings", StringComparison.OrdinalIgnoreCase))
        {
            return StudioNavigation.SettingsItem as NavigationViewItem;
        }

        return StudioNavigation.MenuItems
            .OfType<NavigationViewItem>()
            .FirstOrDefault(item => string.Equals(item.Tag as string, destination, StringComparison.OrdinalIgnoreCase));
    }

    private static Type ResolvePageType(string destination) => destination switch
    {
        "dashboard" => typeof(DashboardPage),
        "projects" => typeof(ProjectsPage),
        "workspace" => typeof(WorkspacePage),
        "timeline" => typeof(TimelinePage),
        "render" => typeof(RenderPage),
        "queue" => typeof(QueuePage),
        "review" => typeof(ReviewPage),
        "outputs" => typeof(OutputsPage),
        "models" => typeof(ModelsPage),
        "cloud" => typeof(CloudPage),
        "directorLab" => typeof(EdmgDirectorPage),
        "plannerLab" => typeof(AiPlannerLabPage),
        "reactiveLab" => typeof(ReactiveLabPage),
        "studioForge" => typeof(StudioForgePage),
        "migration" => typeof(MigrationPage),
        "settings" => typeof(SettingsPage),
        "setup" => typeof(SetupPage),
        _ => typeof(DashboardPage)
    };

    private static string StatusLabel(BackendStatus status) => status.State switch
    {
        BackendLifecycleState.Ready when status.Mode == BackendMode.External => "external ready",
        BackendLifecycleState.Ready when status.Mode == BackendMode.Attached => "attached",
        BackendLifecycleState.Ready => $"{status.AcceleratorProfile ?? "managed"} ready",
        BackendLifecycleState.WaitingForHealth => "starting",
        BackendLifecycleState.Failed => "failed",
        BackendLifecycleState.Unavailable => "unavailable",
        _ => status.State.ToString().ToLowerInvariant()
    };
}

public interface IStudioRefreshable
{
    Task RefreshAsync(CancellationToken cancellationToken = default);
}
