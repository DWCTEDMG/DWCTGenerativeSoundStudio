using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class DashboardPage : Page, INotifyPropertyChanged
{
    private readonly StudioApiClient _apiClient = App.Services.ApiClient;
    private readonly StudioSessionService _session = App.Services.Session;
    private CancellationTokenSource? _loadCancellation;
    private bool _isBusy;
    private bool _hasActiveProject;

    public DashboardPage()
    {
        InitializeComponent();
        Cards =
        [
            new DashboardCard("\uE80F", "Backend", "Checking…", "Studio service health"),
            new DashboardCard("\uE8F1", "Active project", "None", "Choose a project to begin"),
            new DashboardCard("\uE9F9", "Queue", "—", "No active project"),
            new DashboardCard("\uE91B", "Outputs", "—", "No active project"),
            new DashboardCard("\uE896", "Models", "Checking…", "Installed and available inventory"),
            new DashboardCard("\uE774", "Render providers", "Checking…", "Local and hosted readiness"),
        ];
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public ObservableCollection<DashboardCard> Cards { get; }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (_isBusy == value)
            {
                return;
            }

            _isBusy = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(IsNotBusy));
        }
    }

    public bool IsNotBusy => !IsBusy;

    public bool HasActiveProject
    {
        get => _hasActiveProject;
        private set
        {
            if (_hasActiveProject == value)
            {
                return;
            }

            _hasActiveProject = value;
            OnPropertyChanged();
        }
    }

    public static Visibility BoolToVisibility(bool value) =>
        value ? Visibility.Visible : Visibility.Collapsed;

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        _loadCancellation?.Cancel();
        _loadCancellation?.Dispose();
        _loadCancellation = null;
    }

    private async void OnRefreshClick(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
    }

    private async Task RefreshAsync()
    {
        _loadCancellation?.Cancel();
        _loadCancellation?.Dispose();
        _loadCancellation = new CancellationTokenSource();
        var cancellationToken = _loadCancellation.Token;

        IsBusy = true;
        StatusBar.IsOpen = false;

        try
        {
            var healthTask = CaptureAsync(
                () => _apiClient.GetHealthAsync(cancellationToken),
                "Backend health");
            var projectsTask = CaptureAsync(
                () => _apiClient.GetProjectsAsync(cancellationToken),
                "Projects");
            var configTask = CaptureAsync(
                () => _apiClient.GetConfigAsync(cancellationToken),
                "Configuration");
            var modelsTask = CaptureAsync(
                () => _apiClient.GetTypedModelCatalogueAsync(cancellationToken),
                "Models");
            var providersTask = CaptureAsync(
                () => _apiClient.GetRenderProvidersAsync(cancellationToken),
                "Render providers");

            var projectsResult = await projectsTask;
            var projects = projectsResult.Value?.Projects
                .OrderByDescending(project => project.CreatedAt, StringComparer.Ordinal)
                .ToList() ?? [];
            var activeProject = ResolveActiveProject(projects);

            Task<LoadResult<StudioJobListResponse>>? jobsTask = null;
            Task<LoadResult<JsonElement>>? outputsTask = null;
            if (activeProject is not null)
            {
                jobsTask = CaptureAsync(
                    () => _apiClient.GetProjectJobsAsync(activeProject.Id, cancellationToken),
                    "Queue");
                outputsTask = CaptureAsync(
                    () => _apiClient.GetOutputsAsync(activeProject.Id, cancellationToken),
                    "Outputs");
            }

            var healthResult = await healthTask;
            var configResult = await configTask;
            var modelsResult = await modelsTask;
            var providersResult = await providersTask;
            var jobsResult = jobsTask is null ? null : await jobsTask;
            var outputsResult = outputsTask is null ? null : await outputsTask;

            RenderBackendCard(healthResult, configResult);
            RenderProjectCard(activeProject, projects.Count);
            RenderQueueCard(activeProject, jobsResult);
            RenderOutputsCard(activeProject, outputsResult);
            RenderModelsCard(modelsResult);
            RenderProvidersCard(providersResult);
            RenderRecentActivity(projects, jobsResult?.Value?.Jobs);

            var errors = new[]
            {
                healthResult.Error,
                projectsResult.Error,
                configResult.Error,
                modelsResult.Error,
                providersResult.Error,
                jobsResult?.Error,
                outputsResult?.Error,
            }.Where(error => !string.IsNullOrWhiteSpace(error)).ToArray();

            if (errors.Length > 0)
            {
                StatusBar.Title = "Dashboard refreshed with limited data";
                StatusBar.Message = string.Join("  ", errors);
                StatusBar.Severity = InfoBarSeverity.Warning;
                StatusBar.IsOpen = true;
            }
            else
            {
                StatusBar.Title = "Dashboard refreshed";
                StatusBar.Message = activeProject is null
                    ? "Choose a project to start a Studio workflow."
                    : $"Active project: {activeProject.Name}.";
                StatusBar.Severity = InfoBarSeverity.Success;
                StatusBar.IsOpen = true;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        finally
        {
            if (!cancellationToken.IsCancellationRequested)
            {
                IsBusy = false;
            }
        }
    }

    private ProjectDto? ResolveActiveProject(IReadOnlyList<ProjectDto> projects)
    {
        var activeProject = projects.FirstOrDefault(
            project => string.Equals(project.Id, _session.ActiveProjectId, StringComparison.Ordinal));
        activeProject ??= projects.FirstOrDefault();

        if (activeProject is not null
            && !string.Equals(activeProject.Id, _session.ActiveProjectId, StringComparison.Ordinal))
        {
            _session.ActiveProjectId = activeProject.Id;
        }

        HasActiveProject = activeProject is not null;
        return activeProject;
    }

    private void RenderBackendCard(
        LoadResult<HealthResponse> healthResult,
        LoadResult<JsonElement> configResult)
    {
        var card = Cards[0];
        if (healthResult.Value is not null)
        {
            card.Value = healthResult.Value.Ok ? "Connected" : "Unavailable";
            card.Subtitle = $"FastAPI {healthResult.Value.Version} · "
                + (configResult.Value.ValueKind == JsonValueKind.Object
                    ? "configuration loaded"
                    : "configuration unavailable");
        }
        else
        {
            card.Value = "Unavailable";
            card.Subtitle = healthResult.Error ?? "Backend health could not be read.";
        }
    }

    private void RenderProjectCard(ProjectDto? project, int projectCount)
    {
        var card = Cards[1];
        if (project is null)
        {
            card.Value = "No active project";
            card.Subtitle = projectCount == 0
                ? "Create a project to begin."
                : $"{projectCount} project(s) available.";
            return;
        }

        card.Value = project.Name;
        card.Subtitle =
            $"{projectCount} total · Audio {Ready(project.HasAudio)} · "
            + $"Analysis {Ready(project.HasAnalysis)} · Plan {Ready(project.HasPlan)}";
    }

    private void RenderQueueCard(
        ProjectDto? project,
        LoadResult<StudioJobListResponse>? jobsResult)
    {
        var card = Cards[2];
        if (project is null)
        {
            card.Value = "No project";
            card.Subtitle = "Select a project to inspect its render jobs.";
            return;
        }

        if (jobsResult?.Value is null)
        {
            card.Value = "Unavailable";
            card.Subtitle = jobsResult?.Error ?? "Queue health could not be read.";
            return;
        }

        var jobs = jobsResult.Value.Jobs;
        var active = jobs.Count(job => job.IsActive);
        var failed = jobs.Count(job => job.Status == "failed");
        card.Value = $"{active} active";
        card.Subtitle = $"{jobs.Count} total · {failed} failed · {project.Name}";
    }

    private void RenderOutputsCard(
        ProjectDto? project,
        LoadResult<JsonElement>? outputsResult)
    {
        var card = Cards[3];
        if (project is null)
        {
            card.Value = "No project";
            card.Subtitle = "Select a project to inspect its artifacts.";
            return;
        }

        if (outputsResult?.Value.ValueKind != JsonValueKind.Object)
        {
            card.Value = "Unavailable";
            card.Subtitle = outputsResult?.Error ?? "Output inventory could not be read.";
            return;
        }

        var total = StudioOutputCatalog.CountArtifacts(outputsResult.Value);
        card.Value = $"{total} artifact{(total == 1 ? string.Empty : "s")}";
        card.Subtitle = total == 0
            ? "No generated output yet."
            : "Images, videos, exports, and returned renders.";
    }

    private void RenderModelsCard(LoadResult<ModelCatalogueResponse> modelsResult)
    {
        var card = Cards[4];
        if (modelsResult.Value is null)
        {
            card.Value = "Unavailable";
            card.Subtitle = modelsResult.Error ?? "Model catalogue could not be read.";
            return;
        }

        var catalogue = (modelsResult.Value.Catalog ?? []).Concat(modelsResult.Value.User ?? []).ToList();
        var installed = catalogue.Count(model => model.Installed);
        var available = catalogue.Count(model => model.Available);
        card.Value = $"{installed} installed";
        card.Subtitle =
            $"{available} available · {modelsResult.Value.StorageMode ?? "default"} storage";
    }

    private void RenderProvidersCard(LoadResult<JsonElement> providersResult)
    {
        var card = Cards[5];
        if (providersResult.Value.ValueKind != JsonValueKind.Object)
        {
            card.Value = "Unavailable";
            card.Subtitle = providersResult.Error ?? "Provider readiness could not be read.";
            return;
        }

        var (ready, total) = CountReadyProviders(providersResult.Value);
        card.Value = $"{ready} ready";
        card.Subtitle = $"{total} detected · configure hosted providers in Settings or Cloud.";
    }

    private void RenderRecentActivity(
        IReadOnlyList<ProjectDto> projects,
        IReadOnlyList<StudioJob>? jobs)
    {
        RecentProjectsText.Text = projects.Count == 0
            ? "Recent projects: none."
            : "Recent projects: " + string.Join(
                "  •  ",
                projects.Take(3).Select(project => project.Name));

        RecentJobsText.Text = jobs is null
            ? "Recent jobs: select an active project."
            : jobs.Count == 0
                ? "Recent jobs: none."
                : "Recent jobs: " + string.Join(
                    "  •  ",
                    jobs.OrderByDescending(job => job.UpdatedAt ?? job.CreatedAt, StringComparer.Ordinal)
                        .Take(3)
                        .Select(job => $"{job.Type} — {job.Status}"));
    }

    private static (int Ready, int Total) CountReadyProviders(JsonElement providers)
    {
        var ready = 0;
        var total = 0;
        foreach (var property in providers.EnumerateObject())
        {
            if (property.Value.ValueKind != JsonValueKind.Object
                || !property.Value.TryGetProperty("provider", out _))
            {
                continue;
            }

            total++;
            if (GetBoolean(property.Value, "active")
                || GetBoolean(property.Value, "visible")
                || (GetBoolean(property.Value, "available") && GetBoolean(property.Value, "enabled"))
                || (GetBoolean(property.Value, "configured") && GetBoolean(property.Value, "enabled")))
            {
                ready++;
            }
        }

        return (ready, total);
    }

    private static bool GetBoolean(JsonElement value, string propertyName) =>
        value.TryGetProperty(propertyName, out var property)
        && property.ValueKind is JsonValueKind.True;

    private static string Ready(bool value) => value ? "ready" : "pending";

    private static async Task<LoadResult<T>> CaptureAsync<T>(
        Func<Task<T>> operation,
        string subsystem)
    {
        try
        {
            return new LoadResult<T>(await operation(), null);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (StudioApiException ex)
        {
            return new LoadResult<T>(default, $"{subsystem}: {ex.Message}");
        }
        catch (HttpRequestException ex)
        {
            return new LoadResult<T>(default, $"{subsystem}: {ex.Message}");
        }
        catch (JsonException ex)
        {
            return new LoadResult<T>(default, $"{subsystem}: {ex.Message}");
        }
    }

    private void OnOpenProjectsClick(object sender, RoutedEventArgs e) => App.Navigate("projects");

    private void OnOpenWorkspaceClick(object sender, RoutedEventArgs e) => App.Navigate("workspace");

    private void OnOpenTimelineClick(object sender, RoutedEventArgs e) => App.Navigate("timeline");

    private void OnOpenRenderClick(object sender, RoutedEventArgs e) => App.Navigate("render");

    private void OnOpenQueueClick(object sender, RoutedEventArgs e) => App.Navigate("queue");

    private void OnOpenOutputsClick(object sender, RoutedEventArgs e) => App.Navigate("outputs");

    private void OnOpenModelsClick(object sender, RoutedEventArgs e) => App.Navigate("models");

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    private sealed record LoadResult<T>(T? Value, string? Error);
}

public sealed class DashboardCard : INotifyPropertyChanged
{
    private string _value;
    private string _subtitle;

    public DashboardCard(string glyph, string title, string value, string subtitle)
    {
        Glyph = glyph;
        Title = title;
        _value = value;
        _subtitle = subtitle;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Glyph { get; }

    public string Title { get; }

    public string Value
    {
        get => _value;
        set
        {
            if (_value == value)
            {
                return;
            }

            _value = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Value)));
        }
    }

    public string Subtitle
    {
        get => _subtitle;
        set
        {
            if (_subtitle == value)
            {
                return;
            }

            _subtitle = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Subtitle)));
        }
    }
}
