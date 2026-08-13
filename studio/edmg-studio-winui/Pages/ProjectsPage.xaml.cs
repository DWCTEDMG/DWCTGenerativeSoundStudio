using System.Collections.ObjectModel;
using System.Globalization;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class ProjectsPage : Page, IStudioRefreshable
{
    private bool _refreshing;
    private bool _creating;

    public ProjectsPage()
    {
        InitializeComponent();
        Loaded += async (_, _) => await RefreshAsync();
    }

    public ObservableCollection<ProjectListItem> Projects { get; } = [];

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_refreshing)
        {
            return;
        }

        _refreshing = true;
        ProjectProgress.IsActive = true;
        ProjectEmptyState.Visibility = Visibility.Collapsed;
        ProjectCountText.Text = "Loading…";
        try
        {
            if (!App.Services.BackendSupervisor.Status.IsReady)
            {
                Projects.Clear();
                ShowError("Backend is not ready", App.Services.BackendSupervisor.Status.Detail ?? "Open Setup and review the backend target.");
                ProjectCountText.Text = "Unavailable";
                ShowEmpty("Project library unavailable", "Connect to the Studio backend, then refresh.");
                return;
            }

            var response = await App.Services.ApiClient.GetProjectsAsync(cancellationToken);
            Projects.Clear();
            foreach (var project in response.Projects.OrderByDescending(ProjectSortKey))
            {
                Projects.Add(ProjectListItem.From(project));
            }

            ProjectCountText.Text = Projects.Count == 1 ? "1 project" : $"{Projects.Count} projects";
            if (Projects.Count == 0)
            {
                ShowEmpty("No projects yet", "Create your first Studio session above.");
            }
        }
        catch (Exception exception)
        {
            Projects.Clear();
            ProjectCountText.Text = "Load failed";
            ShowError("Projects could not be loaded", UserMessage(exception));
            ShowEmpty("Project library unavailable", "Resolve the connection issue, then refresh.");
        }
        finally
        {
            ProjectProgress.IsActive = false;
            _refreshing = false;
        }
    }

    private async void CreateProject_Click(object sender, RoutedEventArgs e)
    {
        if (_creating)
        {
            return;
        }

        var name = ProjectNameBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ShowError("Project name is required", "Enter a name between 1 and 200 characters.");
            ProjectNameBox.Focus(FocusState.Programmatic);
            return;
        }

        _creating = true;
        CreateProjectButton.IsEnabled = false;
        ProjectProgress.IsActive = true;
        ProjectsInfoBar.IsOpen = false;
        try
        {
            var response = await App.Services.ApiClient.CreateProjectAsync(name);
            App.Services.Session.ActiveProjectId = response.Project.Id;
            await RefreshAsync();
            App.Navigate("workspace");
        }
        catch (Exception exception)
        {
            ShowError("Project could not be created", UserMessage(exception));
        }
        finally
        {
            _creating = false;
            CreateProjectButton.IsEnabled = true;
            ProjectProgress.IsActive = false;
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private void ProjectList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is ProjectListItem project)
        {
            OpenProject(project.Id);
        }
    }

    private void OpenProject_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string id })
        {
            OpenProject(id);
        }
    }

    private static void OpenProject(string id)
    {
        App.Services.Session.ActiveProjectId = id;
        App.Navigate("workspace");
    }

    private void ShowError(string title, string message)
    {
        ProjectsInfoBar.Title = title;
        ProjectsInfoBar.Message = message;
        ProjectsInfoBar.Severity = InfoBarSeverity.Error;
        ProjectsInfoBar.IsOpen = true;
    }

    private void ShowEmpty(string title, string message)
    {
        ProjectEmptyTitle.Text = title;
        ProjectEmptyMessage.Text = message;
        ProjectEmptyState.Visibility = Visibility.Visible;
    }

    private static string UserMessage(Exception exception) => exception is StudioApiException api
        ? api.UserFacingMessage
        : exception.Message;

    private static DateTime ProjectSortKey(ProjectDto project) =>
        DateTime.TryParseExact(project.CreatedAt, "yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out var created)
            ? created
            : DateTime.MinValue;
}

public sealed class ProjectListItem
{
    public ProjectListItem()
    {
    }

    public ProjectListItem(string id, string name, string metadata, string workflowStatus)
    {
        Id = id;
        Name = name;
        Metadata = metadata;
        WorkflowStatus = workflowStatus;
    }

    public string Id { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Metadata { get; set; } = string.Empty;
    public string WorkflowStatus { get; set; } = string.Empty;
    public string OpenLabel => $"Open {Name} in Workspace";
    public string FullIdLabel => $"Project ID {Id}";

    public static ProjectListItem From(ProjectDto project)
    {
        var created = DateTime.TryParseExact(
            project.CreatedAt,
            "yyyy-MM-dd HH:mm:ss",
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeLocal,
            out var parsed)
            ? parsed.ToString("g")
            : project.CreatedAt;
        var shortId = project.Id.Length > 10 ? project.Id[..10] : project.Id;
        var workflow = string.Join(" · ", new[]
        {
            project.HasAudio ? "Audio ready" : "No audio",
            project.HasAnalysis ? "Analyzed" : "Analysis pending",
            project.HasPlan ? $"{project.PlanVariants.Count} plan variants" : "Plan pending"
        });
        return new ProjectListItem(project.Id, project.Name, $"Created {created} · {shortId}", workflow);
    }
}
