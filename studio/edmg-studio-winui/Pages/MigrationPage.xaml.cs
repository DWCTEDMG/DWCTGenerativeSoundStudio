using EdmgStudio.Core.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class MigrationPage : Page
{
    public MigrationPage()
    {
        InitializeComponent();
        Loaded += MigrationPage_Loaded;
    }

    private void MigrationPage_Loaded(object sender, RoutedEventArgs e)
    {
        BackendConfiguration configuration = App.Services.Configuration;
        PendingMigrationInfoBar.Title = configuration.HasPendingMigration
            ? "Migration action is required"
            : "No pending migration";
        PendingMigrationInfoBar.Message = configuration.HasPendingMigration
            ? configuration.PendingMigrationDetail ?? "Review legacy desktop state before continuing."
            : "The active bootstrap configuration does not report legacy data requiring migration.";
        PendingMigrationInfoBar.Severity = configuration.HasPendingMigration
            ? InfoBarSeverity.Warning
            : InfoBarSeverity.Success;
    }

    private void OpenProjects_Click(object sender, RoutedEventArgs e) => App.Navigate("projects");

    private void OpenDashboard_Click(object sender, RoutedEventArgs e) => App.Navigate("dashboard");
}
