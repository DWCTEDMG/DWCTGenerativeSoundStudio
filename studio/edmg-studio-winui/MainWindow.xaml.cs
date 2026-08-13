using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;

namespace EdmgStudio.WinUI;

public sealed partial class MainWindow : Window
{
    private bool _closing;
    private bool _closeCompleted;

    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");
        AppWindow.Title = "EDMG Studio";
        AppWindow.Resize(new SizeInt32(1440, 900));
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
