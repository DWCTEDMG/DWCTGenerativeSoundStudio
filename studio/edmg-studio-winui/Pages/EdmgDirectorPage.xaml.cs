using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class EdmgDirectorPage : Page
{
    public EdmgDirectorPage()
    {
        InitializeComponent();
        Loaded += EdmgDirectorPage_Loaded;
    }

    private async void EdmgDirectorPage_Loaded(object sender, RoutedEventArgs e)
    {
        Loaded -= EdmgDirectorPage_Loaded;
        await RefreshProjectAsync();
    }

    private async void RefreshProject_Click(object sender, RoutedEventArgs e) => await RefreshProjectAsync();

    private async Task RefreshProjectAsync()
    {
        var projectId = App.Services.Session.ActiveProjectId;
        ProjectIdText.Text = string.IsNullOrWhiteSpace(projectId) ? "—" : projectId;
        VariantText.Text = $"Variant {App.Services.Session.SelectedVariantIndex + 1}";
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ProjectNameText.Text = "No active project";
            AnalysisText.Text = "Unavailable";
            PlanText.Text = "Unavailable";
            ShowStatus("Select a project in Projects before directing a production.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            var response = await App.Services.ApiClient.GetProjectAsync(projectId);
            var project = response.Project;
            ProjectNameText.Text = project.Name;
            AnalysisText.Text = project.HasAnalysis ? "Ready" : "Not available";
            PlanText.Text = project.HasPlan ? "Ready" : "Not available";
            StatusInfoBar.IsOpen = false;
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void SetBusy(bool isBusy)
    {
        BusyIndicator.Visibility = isBusy ? Visibility.Visible : Visibility.Collapsed;
        StudioPageHelpers.SetControlsEnabled(this, !isBusy);
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Title = severity == InfoBarSeverity.Error ? "Director unavailable" : "Director";
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private void OpenPlanner_Click(object sender, RoutedEventArgs e) => App.Navigate("plannerLab");
    private void OpenReactive_Click(object sender, RoutedEventArgs e) => App.Navigate("reactiveLab");
    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");
    private void OpenRender_Click(object sender, RoutedEventArgs e) => App.Navigate("render");
    private void OpenForge_Click(object sender, RoutedEventArgs e) => App.Navigate("studioForge");
}
