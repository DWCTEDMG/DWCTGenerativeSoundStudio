using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI;
using System.Runtime.InteropServices;
using Windows.Graphics;
using Windows.Storage;
using EdmgStudio.WinUI.Services;

namespace EdmgStudio.WinUI;

public sealed partial class MainWindow : Window
{
    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hWnd);

    private bool _closing;
    private bool _closeCompleted;
    private readonly ApplicationDataContainer? _settings;

    private const string WindowXKey = "MainWindow.X";
    private const string WindowYKey = "MainWindow.Y";
    private const string WindowWidthKey = "MainWindow.Width";
    private const string WindowHeightKey = "MainWindow.Height";
    private const string WindowMaximizedKey = "MainWindow.IsMaximized";

    public MainWindow()
    {
        InitializeComponent();
        _settings = TryGetLocalSettings();
        StudioAppearanceService.ApplySavedTheme(RootFrame);
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        TrySetWindowIcon();
        AppWindow.Title = "EDMG Studio";

        var hwnd = Win32Interop.GetWindowFromWindowId(AppWindow.Id);
        var scale = hwnd != IntPtr.Zero ? GetDpiForWindow(hwnd) / 96.0 : 1.0;
        if (scale <= 0)
        {
            scale = 1.0;
        }

        RestoreWindowPlacement(scale);
        RootFrame.Navigate(typeof(MainPage));
        AppWindow.Changed += OnAppWindowChanged;
        AppWindow.Closing += OnClosing;
    }

    public nint WindowHandle => WinRT.Interop.WindowNative.GetWindowHandle(this);

    private static ApplicationDataContainer? TryGetLocalSettings()
    {
        try
        {
            return ApplicationData.Current.LocalSettings;
        }
        catch (Exception exception)
        {
            CrashLogger.Write("LocalSettings unavailable; continuing without persisted window settings.", exception);
            return null;
        }
    }

    private void TrySetWindowIcon()
    {
        try
        {
            string iconPath = Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico");
            if (File.Exists(iconPath))
            {
                AppWindow.SetIcon(iconPath);
            }
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Unable to set the AppWindow icon.", exception);
        }
    }

    private void RestoreWindowPlacement(double scale)
    {
        int defaultWidth = (int)(1440 * scale);
        int defaultHeight = (int)(900 * scale);
        int x = ReadInt(WindowXKey) ?? AppWindow.Position.X;
        int y = ReadInt(WindowYKey) ?? AppWindow.Position.Y;
        int width = ReadInt(WindowWidthKey) ?? defaultWidth;
        int height = ReadInt(WindowHeightKey) ?? defaultHeight;

        DisplayArea display = DisplayArea.GetFromPoint(
            new PointInt32(x + Math.Max(1, width / 2), y + Math.Max(1, height / 2)),
            DisplayAreaFallback.Nearest);
        RectInt32 workArea = display.WorkArea;
        int minWidth = Math.Min(workArea.Width, (int)(960 * scale));
        int minHeight = Math.Min(workArea.Height, (int)(640 * scale));
        width = Math.Clamp(width, minWidth, workArea.Width);
        height = Math.Clamp(height, minHeight, workArea.Height);
        x = Math.Clamp(x, workArea.X, workArea.X + workArea.Width - width);
        y = Math.Clamp(y, workArea.Y, workArea.Y + workArea.Height - height);

        AppWindow.MoveAndResize(new RectInt32(x, y, width, height));
        if (ReadBool(WindowMaximizedKey) is true &&
            AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.Maximize();
        }
    }

    private void OnAppWindowChanged(AppWindow sender, AppWindowChangedEventArgs args)
    {
        if (sender.Presenter is not OverlappedPresenter presenter)
        {
            return;
        }

        WriteSetting(WindowMaximizedKey, presenter.State == OverlappedPresenterState.Maximized);
        if (presenter.State != OverlappedPresenterState.Restored ||
            (!args.DidPositionChange && !args.DidSizeChange))
        {
            return;
        }

        SaveNormalWindowPlacement(sender);
    }

    private void SaveNormalWindowPlacement(AppWindow window)
    {
        WriteSetting(WindowXKey, window.Position.X);
        WriteSetting(WindowYKey, window.Position.Y);
        WriteSetting(WindowWidthKey, window.Size.Width);
        WriteSetting(WindowHeightKey, window.Size.Height);
    }

    private int? ReadInt(string key)
    {
        if (_settings is null)
        {
            return null;
        }

        try
        {
            return _settings.Values[key] switch
            {
                int value => value,
                long value when value is >= int.MinValue and <= int.MaxValue => (int)value,
                _ => null,
            };
        }
        catch (Exception exception)
        {
            CrashLogger.Write($"Unable to read window setting '{key}'.", exception);
            return null;
        }
    }

    private bool? ReadBool(string key)
    {
        if (_settings is null)
        {
            return null;
        }

        try
        {
            return _settings.Values[key] is bool value ? value : null;
        }
        catch (Exception exception)
        {
            CrashLogger.Write($"Unable to read window setting '{key}'.", exception);
            return null;
        }
    }

    private void WriteSetting(string key, object value)
    {
        if (_settings is null)
        {
            return;
        }

        try
        {
            _settings.Values[key] = value;
        }
        catch (Exception exception)
        {
            CrashLogger.Write($"Unable to write window setting '{key}'.", exception);
        }
    }

    private async void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_closeCompleted)
        {
            return;
        }

        args.Cancel = true;
        if (_closing)
        {
            return;
        }

        _closing = true;
        if (sender.Presenter is OverlappedPresenter presenter)
        {
            WriteSetting(WindowMaximizedKey, presenter.State == OverlappedPresenterState.Maximized);
            if (presenter.State == OverlappedPresenterState.Restored)
            {
                SaveNormalWindowPlacement(sender);
            }
        }

        try
        {
            await App.Services.DisposeAsync();
        }
        catch (Exception exception)
        {
            CrashLogger.Write("Application shutdown completed with errors.", exception);
        }
        finally
        {
            _closeCompleted = true;
            Close();
        }
    }
}
