using System.Net.Http;
using System.Net.Sockets;
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

        // A temporarily unavailable local backend must never take down the shell.
        // SetupPage uses async event handlers, so a connection-refused exception can
        // otherwise reach WinUI's top-level handler before the backend finishes starting.
        if (IsExpectedLocalBackendConnectionFailure(e.Exception))
        {
            e.Handled = true;
            CrashLogger.Write("Handled local backend connection failure; keeping WinUI running.", e.Exception);
        }
    }

    private static bool IsExpectedLocalBackendConnectionFailure(Exception exception)
    {
        for (Exception? current = exception; current is not null; current = current.InnerException)
        {
            if (current is SocketException socketException &&
                socketException.SocketErrorCode == SocketError.ConnectionRefused)
            {
                return true;
            }

            if (current is HttpRequestException &&
                current.Message.Contains("127.0.0.1:7863", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
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
