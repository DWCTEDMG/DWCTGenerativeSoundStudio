using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;

namespace EdmgStudio.WinUI;

public partial class App : Application
{
    private MainWindow? _window;

    public App()
    {
        UnhandledException += OnUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnDomainUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;

        try
        {
            InitializeComponent();
            Services = AppServices.Create();
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Fatal failure while constructing the WinUI application.", exception);
            throw;
        }
    }

    public static AppServices Services { get; private set; } = null!;
    public static MainWindow? MainWindowInstance { get; private set; }
    public static MainPage? Shell { get; internal set; }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            _window = new MainWindow();
            MainWindowInstance = _window;
            _window.Activate();
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Fatal failure while launching the main WinUI window.", exception);
            throw;
        }
    }

    public static void Navigate(string destination) => Shell?.NavigateTo(destination);

    private static void OnUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        CrashLogger.Write("Unhandled WinUI exception.", e.Exception);
        System.Diagnostics.Debug.WriteLine($"Unhandled WinUI exception: {e.Exception}");
    }

    private static void OnDomainUnhandledException(object? sender, System.UnhandledExceptionEventArgs e)
    {
        CrashLogger.Write($"Unhandled AppDomain exception. IsTerminating={e.IsTerminating}.", e.ExceptionObject as Exception);
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        CrashLogger.Write("Unobserved task exception.", e.Exception);
    }
}
