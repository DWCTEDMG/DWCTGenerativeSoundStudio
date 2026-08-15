using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI;
using System.Runtime.InteropServices;
using Windows.Graphics;

namespace EdmgStudio.WinUI;

public sealed partial class MainWindow : Window
{
    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hWnd);

    private bool _closing;
    private bool _closeCompleted;

    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");
        AppWindow.Title = "EDMG Studio";
        var hwnd = Win32Interop.GetWindowFromWindowId(AppWindow.Id);
        var scale = GetDpiForWindow(hwnd) / 96.0;
        AppWindow.Resize(new SizeInt32((int)(1440 * scale), (int)(900 * scale)));
        RootFrame.Navigate(typeof(MainPage));
        AppWindow.Closing += OnClosing;
    }

    public nint WindowHandle => WinRT.Interop.WindowNative.GetWindowHandle(this);

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
        try
        {
            await App.Services.DisposeAsync();
        }
        finally
        {
            _closeCompleted = true;
            Close();
        }
    }
}
