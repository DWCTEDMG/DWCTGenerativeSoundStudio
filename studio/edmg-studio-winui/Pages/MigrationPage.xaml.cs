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
        PageDescription.Text =
            "Projects, workspace, timeline, render, queue, review, outputs, models, and settings " +
            "are native. Use the Electron compatibility frontend only for specialist interactions " +
            "that are not available through the shared backend API.";
    }

    private void OpenWorkspace_Click(object sender, RoutedEventArgs e) => App.Navigate("workspace");
    private void OpenDashboard_Click(object sender, RoutedEventArgs e) => App.Navigate("dashboard");

    private static string DestinationLabel(string destination) => destination switch
    {
        "directorLab" => "EDMG Director compatibility surface",
        "plannerLab" => "AI Planner Lab compatibility surface",
        "reactiveLab" => "Reactive Lab compatibility surface",
        "cloud" => "Cloud compatibility surface",
        _ => "Compatibility surface"
    };
}
