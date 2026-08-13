using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;

namespace EdmgStudio.WinUI;

public partial class App : Application
{
    private MainWindow? _window;

    public App()
    {
        InitializeComponent();
        Services = AppServices.Create();
        UnhandledException += OnUnhandledException;
    }

    public static AppServices Services { get; private set; } = null!;
    public static MainWindow? MainWindowInstance { get; private set; }
    public static MainPage? Shell { get; internal set; }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow();
        MainWindowInstance = _window;
        _window.Activate();
    }

    public static void Navigate(string destination) => Shell?.NavigateTo(destination);

    private static void OnUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        System.Diagnostics.Debug.WriteLine($"Unhandled WinUI exception: {e.Exception}");
    }
}
