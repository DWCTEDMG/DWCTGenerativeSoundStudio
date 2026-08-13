using EdmgStudio.Core.Models;
using EdmgStudio.WinUI.Pages;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI;

public sealed partial class MainPage : Page
{
    private bool _started;

    public MainPage()
    {
        InitializeComponent();
        App.Shell = this;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        App.Services.BackendSupervisor.StatusChanged += BackendSupervisor_StatusChanged;
    }

    public void NavigateTo(string destination)
    {
        var item = FindNavigationItem(destination);
        if (item is not null)
        {
            StudioNavigation.SelectedItem = item;
        }

        var pageType = ResolvePageType(destination);
        if (ContentFrame.CurrentSourcePageType != pageType || pageType == typeof(MigrationPage))
        {
            ContentFrame.Navigate(pageType, destination);
        }
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (!_started)
        {
            _started = true;
            NavigateTo("dashboard");
            var status = await App.Services.BackendSupervisor.StartAsync();
            UpdateBackendStatus(status);
            if (!status.IsReady)
            {
                NavigateTo("setup");
                return;
            }

            try
            {
                var setup = await App.Services.ApiClient.GetSetupStatusAsync();
                if (setup.ValueKind == System.Text.Json.JsonValueKind.Object &&
                    setup.TryGetProperty("system_readiness", out var readiness) &&
                    readiness.ValueKind == System.Text.Json.JsonValueKind.Object &&
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

            if (ContentFrame.Content is IStudioRefreshable refreshable)
            {
                await refreshable.RefreshAsync();
            }
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (App.Shell == this)
        {
            App.Shell = null;
        }
    }

    private void BackendSupervisor_StatusChanged(object? sender, BackendStatus status)
    {
        DispatcherQueue.TryEnqueue(DispatcherQueuePriority.Normal, () => UpdateBackendStatus(status));
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
            if (ContentFrame.CurrentSourcePageType != pageType || pageType == typeof(MigrationPage))
            {
                ContentFrame.Navigate(pageType, destination);
            }
        }
    }

    private void ContentFrame_Navigated(object sender, NavigationEventArgs e)
    {
        if (e.Parameter is not string destination)
        {
            return;
        }

        var item = FindNavigationItem(destination);
        if (item is not null && !ReferenceEquals(StudioNavigation.SelectedItem, item))
        {
            StudioNavigation.SelectedItem = item;
        }
    }

    private NavigationViewItem? FindNavigationItem(string destination) =>
        StudioNavigation.MenuItems
            .OfType<NavigationViewItem>()
            .FirstOrDefault(item => string.Equals(item.Tag as string, destination, StringComparison.OrdinalIgnoreCase));

    private static Type ResolvePageType(string destination) => destination switch
    {
        "dashboard" => typeof(DashboardPage),
        "projects" => typeof(ProjectsPage),
        "workspace" => typeof(WorkspacePage),
        "setup" => typeof(SetupPage),
        _ => typeof(MigrationPage)
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
