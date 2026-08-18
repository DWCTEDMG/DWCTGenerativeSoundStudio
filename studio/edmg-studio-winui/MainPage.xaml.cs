using EdmgStudio.Core.Models;
using EdmgStudio.WinUI.Pages;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI;

public sealed partial class MainPage : Page
{
    private bool _started;
    private bool _isBackendStatusSubscribed;

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
            catch
            {
                NavigateTo("setup");
                return;
            }

            NavigateTo(App.Services.Configuration.HasPendingMigration
                ? "migration"
                : StudioNavigationDestination.NormalizeRestorableOrDefault(
                    App.Services.Session.LastWorkflowDestination));
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (App.Shell == this)
        {
            App.Shell = null;
        }

        if (_isBackendStatusSubscribed)
        {
            App.Services.BackendSupervisor.StatusChanged -= BackendSupervisor_StatusChanged;
            _isBackendStatusSubscribed = false;
        }
    }

    private void BackendSupervisor_StatusChanged(object? sender, BackendStatus status)
    {
        DispatcherQueue.TryEnqueue(
            DispatcherQueuePriority.Normal,
            async () =>
            {
                UpdateBackendStatus(status);
                if (status.IsReady && ContentFrame.Content is IStudioRefreshable refreshable)
                {
                    try
                    {
                        await refreshable.RefreshAsync();
                    }
                    catch (Exception ex)
                    {
                        BackendInfoBar.Severity = InfoBarSeverity.Warning;
                        BackendInfoBar.Title = "Backend connected; page refresh failed";
                        BackendInfoBar.Message = StudioPageHelpers.GetUserFacingError(ex);
                        BackendInfoBar.IsOpen = true;
                    }
                }
            });
    }

    private void UpdateBackendStatus(BackendStatus status)
    {
        BackendStateText.Text = $"Backend: {StatusLabel(status)}";
        BackendUriText.Text = status.CurrentBackendUri.ToString().TrimEnd('/');
        ToolTipService.SetToolTip(BackendUriText, status.CurrentBackendUri.ToString());

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
