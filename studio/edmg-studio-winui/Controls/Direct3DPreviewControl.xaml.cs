using EdmgStudio.Core.Graphics;
using EdmgStudio.WinUI.Graphics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using System.Diagnostics;

namespace EdmgStudio.WinUI.Controls;

public sealed partial class Direct3DPreviewControl : UserControl
{
    private readonly ImageFrameDecoder _decoder = new();
    private CancellationTokenSource? _loadCancellation;
    private PreviewRendererSession? _renderer;
    private XamlRoot? _subscribedXamlRoot;
    private string _emptyMessage = "No preview selected.";
    private bool _hasFrame;
    private bool _isLoading;

    public Direct3DPreviewControl()
    {
        InitializeComponent();
    }

    public string? AdapterDiagnostics { get; private set; }

    public async Task LoadStreamAsync(
        Stream source,
        string? contentType,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        CancellationTokenSource linkedCancellation = ReplaceLoadCancellation(cancellationToken);
        CancellationToken token = linkedCancellation.Token;

        _isLoading = true;
        _hasFrame = false;
        await SetStateAsync("Loading preview…", isProgressActive: true, isVisible: true);

        OwnedCpuFrame? frame = null;
        try
        {
            frame = await _decoder.DecodeAsync(source, contentType, token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();

            PreviewRendererSession? renderer = Volatile.Read(ref _renderer);
            if (renderer is null)
            {
                throw new InvalidOperationException("The preview surface is not available.");
            }

            if (!renderer.TrySubmitFrame(frame))
            {
                frame = null;
                throw new InvalidOperationException("The preview renderer is stopping.");
            }

            frame = null;
            _isLoading = false;
            _hasFrame = true;
            await SetStateAsync(string.Empty, isProgressActive: false, isVisible: false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (PreviewUnsupportedException exception)
        {
            _isLoading = false;
            _hasFrame = false;
            await SetStateAsync(exception.Message, isProgressActive: false, isVisible: true);
        }
        catch (Exception exception)
        {
            _isLoading = false;
            _hasFrame = false;
            await SetStateAsync(
                $"Preview could not be displayed. {exception.Message}",
                isProgressActive: false,
                isVisible: true);
        }
        finally
        {
            frame?.Dispose();
            if (ReferenceEquals(
                Interlocked.CompareExchange(ref _loadCancellation, null, linkedCancellation),
                linkedCancellation))
            {
                linkedCancellation.Dispose();
            }
        }
    }

    public void ShowEmpty(string message = "No preview selected.")
    {
        CancelPendingLoad();
        _emptyMessage = message;
        _isLoading = false;
        _hasFrame = false;
        SetState(message, isProgressActive: false, isVisible: true);
    }

    public void ShowUnsupported(string message)
    {
        CancelPendingLoad();
        _isLoading = false;
        _hasFrame = false;
        SetState(message, isProgressActive: false, isVisible: true);
    }

    public void ShowError(string message)
    {
        CancelPendingLoad();
        _isLoading = false;
        _hasFrame = false;
        SetState(message, isProgressActive: false, isVisible: true);
    }

    private void Direct3DPreviewControl_Loaded(object sender, RoutedEventArgs e)
    {
        SubscribeToXamlRoot();
        if (_renderer is null)
        {
            var renderer = new PreviewRendererSession(
                PreviewPanel,
                DispatcherQueue,
                Renderer_StatusChanged,
                Renderer_DiagnosticsChanged);
            if (App.Services.TryTrackPreviewSession(renderer))
            {
                _renderer = renderer;
            }
            else
            {
                _ = renderer.DisposeAsync();
                ShowError("Preview is unavailable while Studio is shutting down.");
                return;
            }
        }

        RequestResize();
    }

    private async void Direct3DPreviewControl_Unloaded(object sender, RoutedEventArgs e)
    {
        CancelPendingLoad();
        UnsubscribeFromXamlRoot();

        PreviewRendererSession? renderer = Interlocked.Exchange(ref _renderer, null);
        if (renderer is null)
        {
            return;
        }

        App.Services.UntrackPreviewSession(renderer);
        try
        {
            await renderer.DisposeAsync();
        }
        catch (Exception exception)
        {
            Debug.WriteLine($"Preview renderer shutdown failed: {exception}");
        }
    }

    private void PreviewPanel_SizeChanged(object sender, SizeChangedEventArgs e) => RequestResize();

    private void XamlRoot_Changed(XamlRoot sender, XamlRootChangedEventArgs args) => RequestResize();

    private void SubscribeToXamlRoot()
    {
        XamlRoot? current = XamlRoot;
        if (ReferenceEquals(current, _subscribedXamlRoot))
        {
            return;
        }

        UnsubscribeFromXamlRoot();
        _subscribedXamlRoot = current;
        if (_subscribedXamlRoot is not null)
        {
            _subscribedXamlRoot.Changed += XamlRoot_Changed;
        }
    }

    private void UnsubscribeFromXamlRoot()
    {
        if (_subscribedXamlRoot is not null)
        {
            _subscribedXamlRoot.Changed -= XamlRoot_Changed;
            _subscribedXamlRoot = null;
        }
    }

    private void RequestResize()
    {
        SubscribeToXamlRoot();
        double scale = XamlRoot?.RasterizationScale ?? 1.0;
        _renderer?.RequestResize(PreviewPanel.ActualWidth, PreviewPanel.ActualHeight, scale);
    }

    private void Renderer_StatusChanged(RendererStatus status)
    {
        switch (status.State)
        {
            case RendererLifecycleState.Initializing:
                SetState(status.Message, isProgressActive: true, isVisible: true);
                break;
            case RendererLifecycleState.Ready:
                if (_hasFrame)
                {
                    SetState(string.Empty, isProgressActive: false, isVisible: false);
                }
                else if (_isLoading)
                {
                    SetState("Loading preview…", isProgressActive: true, isVisible: true);
                }
                else
                {
                    SetState(_emptyMessage, isProgressActive: false, isVisible: true);
                }

                break;
            case RendererLifecycleState.Recovering:
                SetState(status.Message, isProgressActive: true, isVisible: true);
                break;
            case RendererLifecycleState.Faulted:
                SetState(status.Message, isProgressActive: false, isVisible: true);
                break;
        }
    }

    private void Renderer_DiagnosticsChanged(PreviewAdapterDiagnostics diagnostics)
    {
        void Update()
        {
            AdapterDiagnostics =
                $"{diagnostics.Description}; LUID {diagnostics.LuidText}; " +
                (diagnostics.IsWarp ? "WARP" : "hardware");
            ToolTipService.SetToolTip(this, AdapterDiagnostics);
            AutomationProperties.SetHelpText(this, AdapterDiagnostics);
        }

        if (DispatcherQueue.HasThreadAccess)
        {
            Update();
        }
        else
        {
            _ = DispatcherQueue.TryEnqueue(Update);
        }
    }

    private CancellationTokenSource ReplaceLoadCancellation(CancellationToken cancellationToken)
    {
        var replacement = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        CancellationTokenSource? previous = Interlocked.Exchange(ref _loadCancellation, replacement);
        previous?.Cancel();
        previous?.Dispose();
        return replacement;
    }

    private void CancelPendingLoad()
    {
        CancellationTokenSource? cancellation = Interlocked.Exchange(ref _loadCancellation, null);
        cancellation?.Cancel();
        cancellation?.Dispose();
    }

    private Task SetStateAsync(string message, bool isProgressActive, bool isVisible)
    {
        if (DispatcherQueue.HasThreadAccess)
        {
            SetState(message, isProgressActive, isVisible);
            return Task.CompletedTask;
        }

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!DispatcherQueue.TryEnqueue(() =>
            {
                SetState(message, isProgressActive, isVisible);
                completion.SetResult();
            }))
        {
            completion.SetResult();
        }

        return completion.Task;
    }

    private void SetState(string message, bool isProgressActive, bool isVisible)
    {
        StateText.Text = message;
        StateProgressRing.IsActive = isProgressActive;
        StateProgressRing.Visibility = isProgressActive ? Visibility.Visible : Visibility.Collapsed;
        StateOverlay.Visibility = isVisible ? Visibility.Visible : Visibility.Collapsed;
    }
}
