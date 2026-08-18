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
    private readonly ApplicationDataContainer _settings = ApplicationData.Current.LocalSettings;

    private const string WindowXKey = "MainWindow.X";
    private const string WindowYKey = "MainWindow.Y";
    private const string WindowWidthKey = "MainWindow.Width";
    private const string WindowHeightKey = "MainWindow.Height";
    private const string WindowMaximizedKey = "MainWindow.IsMaximized";

    public MainWindow()
    {
        InitializeComponent();
        StudioAppearanceService.ApplySavedTheme(RootFrame);
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");
        AppWindow.Title = "EDMG Studio";
        var hwnd = Win32Interop.GetWindowFromWindowId(AppWindow.Id);
        var scale = GetDpiForWindow(hwnd) / 96.0;
        RestoreWindowPlacement(scale);
        RootFrame.Navigate(typeof(MainPage));
        AppWindow.Changed += OnAppWindowChanged;
        AppWindow.Closing += OnClosing;
    }

    public nint WindowHandle => WinRT.Interop.WindowNative.GetWindowHandle(this);

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
        if (_settings.Values[WindowMaximizedKey] is true &&
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

        _settings.Values[WindowMaximizedKey] = presenter.State == OverlappedPresenterState.Maximized;
        if (presenter.State != OverlappedPresenterState.Restored ||
            (!args.DidPositionChange && !args.DidSizeChange))
        {
            return;
        }

        SaveNormalWindowPlacement(sender);
    }

    private void SaveNormalWindowPlacement(AppWindow window)
    {
        _settings.Values[WindowXKey] = window.Position.X;
        _settings.Values[WindowYKey] = window.Position.Y;
        _settings.Values[WindowWidthKey] = window.Size.Width;
        _settings.Values[WindowHeightKey] = window.Size.Height;
    }

    private int? ReadInt(string key) => _settings.Values[key] switch
    {
        int value => value,
        long value when value is >= int.MinValue and <= int.MaxValue => (int)value,
        _ => null,
    };

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
            _settings.Values[WindowMaximizedKey] = presenter.State == OverlappedPresenterState.Maximized;
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
            System.Diagnostics.Debug.WriteLine($"Application shutdown completed with errors: {exception}");
        }
        finally
        {
            _closeCompleted = true;
            Close();
        }
    }
}
