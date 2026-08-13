using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class MigrationPage : Page
{
    public MigrationPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        var destination = e.Parameter as string ?? "destination";
        PageTitle.Text = DestinationLabel(destination);
        PageDescription.Text = $"The native {PageTitle.Text} surface is queued after the working Dashboard, Projects, and create → audio → analyze → plan Workspace milestone.";
    }

    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");
    private void OpenDashboard_Click(object sender, RoutedEventArgs e) => App.Navigate("dashboard");

    private static string DestinationLabel(string destination) => destination switch
    {
        "timeline" => "Timeline migration in progress",
        "render" => "Render migration in progress",
        "queue" => "Render Queue migration in progress",
        "review" => "Review migration in progress",
        "outputs" => "Outputs migration in progress",
        "directorLab" => "EDMG Director migration in progress",
        "plannerLab" => "AI Planner Lab migration in progress",
        "reactiveLab" => "Reactive Lab migration in progress",
        "cloud" => "Cloud migration in progress",
        "models" => "Models migration in progress",
        "settings" => "Settings migration in progress",
        _ => "Native surface in progress"
    };
}
