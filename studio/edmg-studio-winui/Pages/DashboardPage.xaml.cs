using System.Text.Json;
using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class DashboardPage : Page, IStudioRefreshable
{
    private bool _refreshing;

    public DashboardPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_refreshing)
        {
            return;
        }

        _refreshing = true;
        DashboardProgress.IsActive = true;
        DashboardInfoBar.IsOpen = false;
        try
        {
            var supervisor = App.Services.BackendSupervisor;
            var status = await supervisor.RefreshHealthAsync(cancellationToken);
            if (!status.IsReady && status.State is not (
                    BackendLifecycleState.Resolving or
                    BackendLifecycleState.Starting or
                    BackendLifecycleState.WaitingForHealth))
            {
                status = await supervisor.StartAsync(cancellationToken);
            }
            BackendStateValue.Text = status.IsReady ? "Ready" : status.Message;
            BackendAddressValue.Text = status.CurrentBackendUri.ToString().TrimEnd('/');
            BackendModeValue.Text = $"Mode: {status.Mode}";
            StorageHomeValue.Text = $"Storage: {App.Services.Configuration.Paths.StudioHome}";

            if (!status.IsReady)
            {
                ShowError("Backend is not ready", status.Detail ?? status.Message);
                BackendVersionValue.Text = "Version: unavailable";
                ProjectCountValue.Text = "—";
                return;
            }

            try
            {
                var health = await App.Services.ApiClient.GetHealthAsync(cancellationToken);
                BackendVersionValue.Text = $"Version: {health.Version}";
            }
            catch (Exception exception)
            {
                BackendVersionValue.Text = "Version: unavailable";
                ShowError("Health check failed", exception.Message);
            }

            try
            {
                var projects = await App.Services.ApiClient.GetProjectsAsync(cancellationToken);
                ProjectCountValue.Text = projects.Projects.Count.ToString();
                var active = projects.Projects.FirstOrDefault(project => project.Id == App.Services.Session.ActiveProjectId);
                ActiveProjectValue.Text = active is null ? "Active project: none" : $"Active project: {active.Name}";
            }
            catch (Exception exception)
            {
                ProjectCountValue.Text = "—";
                ActiveProjectValue.Text = "Project library unavailable";
                ShowError("Projects could not be loaded", exception.Message);
            }

            try
            {
                var config = await App.Services.ApiClient.GetConfigAsync(cancellationToken);
                ConfigValue.Text = DescribeConfig(config);
            }
            catch (Exception exception)
            {
                ConfigValue.Text = $"Configuration unavailable: {exception.Message}";
            }
        }
        finally
        {
            DashboardProgress.IsActive = false;
            _refreshing = false;
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();
    private void OpenProjects_Click(object sender, RoutedEventArgs e) => App.Navigate("projects");
    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");

    private void ShowError(string title, string message)
    {
        DashboardInfoBar.Title = title;
        DashboardInfoBar.Message = message;
        DashboardInfoBar.Severity = InfoBarSeverity.Warning;
        DashboardInfoBar.IsOpen = true;
    }

    private static string DescribeConfig(JsonElement config)
    {
        if (config.ValueKind != JsonValueKind.Object)
        {
            return "Configuration loaded.";
        }

        var parts = new List<string>();
        if (config.TryGetProperty("ai", out var ai) && ai.ValueKind == JsonValueKind.Object)
        {
            if (ai.TryGetProperty("provider", out var provider) && provider.ValueKind == JsonValueKind.String)
            {
                parts.Add($"AI provider: {provider.GetString()}");
            }
        }

        if (config.TryGetProperty("version", out var version) && version.ValueKind == JsonValueKind.String)
        {
            parts.Add($"Config version: {version.GetString()}");
        }

        return parts.Count == 0 ? "Configuration loaded from the active backend." : string.Join(" · ", parts);
    }
}
