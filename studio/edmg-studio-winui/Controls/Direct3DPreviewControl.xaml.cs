using EdmgStudio.Core.Graphics;
using EdmgStudio.Core.Media;
using EdmgStudio.WinUI.Graphics;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using System.Diagnostics;
using System.Globalization;

namespace EdmgStudio.WinUI.Controls;

public sealed class PreviewPositionChangedEventArgs(double normalizedPosition) : EventArgs
{
    public double NormalizedPosition { get; } = normalizedPosition;
}

public sealed partial class Direct3DPreviewControl : UserControl
{
    private readonly ImageFrameDecoder _decoder = new();
    private readonly SemaphoreSlim _videoLifecycleGate = new(1, 1);
    private CancellationTokenSource? _loadCancellation;
    private CancellationTokenSource? _playbackCancellation;
    private CancellationTokenSource? _seekDebounceCancellation;
    private PreviewRendererSession? _renderer;
    private VideoPlaybackSession? _videoSession;
    private Popup? _fullScreenPopup;
    private Task _videoCleanupTask = Task.CompletedTask;
    private XamlRoot? _subscribedXamlRoot;
    private string _emptyMessage = "No preview selected.";
    private string _previewContext = "Preview";
    private bool _hasFrame;
    private bool _isLoading;
    private bool _isVideoPlaying;
    private bool _isUpdatingPosition;
    private bool _resumePlaybackAfterSeek;
    private bool _isFullScreen;
    private bool _restoreMaximizedAfterFullScreen;
    private PreviewDisplayMode _displayMode = PreviewDisplayMode.Fit;
    private int _videoGeneration;
    private TimeSpan _videoPosition;

    public Direct3DPreviewControl()
    {
        InitializeComponent();
    }

    public string? AdapterDiagnostics { get; private set; }

    public bool AutoPlay { get; set; } = true;

    public bool HasVideo => Volatile.Read(ref _videoSession) is not null;

    public bool IsVideoPlaying => _isVideoPlaying;

    public double NormalizedPosition => Volatile.Read(ref _videoSession) is { Metadata.Duration: var duration }
        && duration > TimeSpan.Zero
            ? Math.Clamp(_videoPosition.TotalSeconds / duration.TotalSeconds, 0, 1)
            : 0;

    public event EventHandler<PreviewPositionChangedEventArgs>? PositionChanged;

    public string PreviewContext
    {
        get => _previewContext;
        set
        {
            _previewContext = string.IsNullOrWhiteSpace(value) ? "Preview" : value.Trim();
            PreviewContextText.Text = _previewContext;
        }
    }

    public async Task SetPlayingAsync(bool isPlaying)
    {
        VideoPlaybackSession? session = Volatile.Read(ref _videoSession);
        if (session is null || isPlaying == _isVideoPlaying)
        {
            return;
        }

        if (!isPlaying)
        {
            CancelPlayback();
            await session.StopAsync();
            await UpdatePlaybackStateAsync(false);
            return;
        }

        _ = StartPlaybackAsync(session, PlaybackStartPosition(session), Volatile.Read(ref _videoGeneration));
    }

    public async Task SeekNormalizedAsync(double normalizedPosition)
    {
        VideoPlaybackSession? session = Volatile.Read(ref _videoSession);
        if (session is null || session.Metadata.Duration <= TimeSpan.Zero)
        {
            return;
        }

        TimeSpan target = TimeSpan.FromTicks((long)(session.Metadata.Duration.Ticks * Math.Clamp(normalizedPosition, 0, 1)));
        bool resume = _isVideoPlaying;
        CancelPlayback();
        await session.StopAsync();
        _videoPosition = target;
        await UpdatePlaybackStateAsync(false);
        await session.DecodeAsync(
            target,
            frame => SubmitVideoFrame(session, Volatile.Read(ref _videoGeneration), frame),
            paceFrames: false,
            maximumFrames: 1,
            CancellationToken.None);
        if (resume)
        {
            _ = StartPlaybackAsync(session, target, Volatile.Read(ref _videoGeneration));
        }
    }

    public async Task LoadStreamAsync(
        Stream source,
        string? contentType,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        CancellationTokenSource linkedCancellation = ReplaceLoadCancellation(cancellationToken);
        CancellationToken token = linkedCancellation.Token;
        OwnedCpuFrame? frame = null;
        try
        {
            await DisposeVideoSessionAsync();
            token.ThrowIfCancellationRequested();
            _isLoading = true;
            _hasFrame = false;
            await SetFrameMetadataAsync(string.Empty);
            await SetStateAsync("Loading preview…", isProgressActive: true, isVisible: true);
            frame = await _decoder.DecodeAsync(source, contentType, token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();

            PreviewRendererSession? renderer = Volatile.Read(ref _renderer);
            if (renderer is null)
            {
                throw new InvalidOperationException("The preview surface is not available.");
            }

            int width = frame.Layout.Width;
            int height = frame.Layout.Height;
            if (!renderer.TrySubmitFrame(frame))
            {
                frame = null;
                throw new InvalidOperationException("The preview renderer is stopping.");
            }

            frame = null;
            _isLoading = false;
            await SetFrameMetadataAsync($"{width} x {height} · BGRA8");
            _hasFrame = true;
            await SetStateAsync(string.Empty, isProgressActive: false, isVisible: false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (PreviewUnsupportedException exception)
        {
            token.ThrowIfCancellationRequested();
            _isLoading = false;
            _hasFrame = false;
            await SetStateAsync(exception.Message, isProgressActive: false, isVisible: true);
        }
        catch (Exception exception)
        {
            token.ThrowIfCancellationRequested();
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
            Interlocked.CompareExchange(ref _loadCancellation, null, linkedCancellation);
            linkedCancellation.Dispose();
        }
    }

    public Task LoadVideoStreamAsync(Stream source, CancellationToken cancellationToken)
        => LoadVideoStreamAsync(source, knownContentLength: null, cancellationToken);

    public async Task LoadVideoStreamAsync(
        Stream source,
        long? knownContentLength,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        CancellationTokenSource linkedCancellation = ReplaceLoadCancellation(cancellationToken);
        CancellationToken token = linkedCancellation.Token;
        VideoPlaybackSession? session = null;
        try
        {
            await DisposeVideoSessionAsync();
            token.ThrowIfCancellationRequested();
            int generation = Interlocked.Increment(ref _videoGeneration);
            _isLoading = true;
            _hasFrame = false;
            await SetFrameMetadataAsync(string.Empty);
            await SetStateAsync("Preparing video preview…", isProgressActive: true, isVisible: true);
            MediaToolPaths tools = MediaToolLocator.Locate();
            session = await VideoPlaybackSession.CreateAsync(source, tools, knownContentLength, token).ConfigureAwait(false);
            await _videoLifecycleGate.WaitAsync(token).ConfigureAwait(false);
            try
            {
                token.ThrowIfCancellationRequested();
                if (generation != Volatile.Read(ref _videoGeneration))
                {
                    throw new OperationCanceledException(token);
                }

                if (!App.Services.TryTrackVideoPlaybackSession(session))
                {
                    throw new InvalidOperationException("Video playback is unavailable while Studio is shutting down.");
                }

                VideoPlaybackSession playbackSession = session;
                _videoSession = playbackSession;
                session = null;
                _videoPosition = TimeSpan.Zero;
                _isLoading = false;
                await ConfigureVideoTransportAsync(playbackSession.Metadata);
                if (AutoPlay)
                {
                    _ = StartPlaybackAsync(playbackSession, TimeSpan.Zero, generation);
                }
                else
                {
                    await playbackSession.DecodeAsync(
                        TimeSpan.Zero,
                        frame => SubmitVideoFrame(playbackSession, generation, frame),
                        paceFrames: false,
                        maximumFrames: 1,
                        token);
                }
            }
            finally
            {
                _videoLifecycleGate.Release();
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception)
        {
            token.ThrowIfCancellationRequested();
            _isLoading = false;
            _hasFrame = false;
            await SetStateAsync(
                $"Video preview could not be displayed. {exception.Message}",
                isProgressActive: false,
                isVisible: true);
        }
        finally
        {
            if (session is not null)
            {
                await session.DisposeAsync();
            }

            Interlocked.CompareExchange(ref _loadCancellation, null, linkedCancellation);
            linkedCancellation.Dispose();
        }
    }

    public void ShowEmpty(string message = "No preview selected.")
    {
        CancelPendingLoad();
        BeginVideoCleanup();
        _emptyMessage = message;
        _isLoading = false;
        _hasFrame = false;
        SetFrameMetadata(string.Empty);
        SetState(message, isProgressActive: false, isVisible: true);
    }

    public void ShowUnsupported(string message)
    {
        CancelPendingLoad();
        BeginVideoCleanup();
        _isLoading = false;
        _hasFrame = false;
        SetFrameMetadata(string.Empty);
        SetState(message, isProgressActive: false, isVisible: true);
    }

    public void ShowError(string message)
    {
        CancelPendingLoad();
        BeginVideoCleanup();
        _isLoading = false;
        _hasFrame = false;
        SetFrameMetadata(string.Empty);
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
                ApplyPresentation();
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
        ExitFullScreen();
        UnsubscribeFromXamlRoot();
        // Capture this attachment before yielding. A later Loaded event may
        // already have installed a new renderer when cleanup resumes.
        PreviewRendererSession? renderer = Interlocked.Exchange(ref _renderer, null);
        try
        {
            await DisposeVideoSessionAsync();
        }
        catch (Exception exception)
        {
            Debug.WriteLine($"Video playback shutdown failed: {exception}");
        }

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

    private void XamlRoot_Changed(XamlRoot sender, XamlRootChangedEventArgs args)
    {
        if (_isFullScreen)
        {
            SizeFullScreenPreview(sender);
        }
        RequestResize();
    }

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

    private void DisplayModeMenuItem_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not RadioMenuFlyoutItem { Tag: string modeName } ||
            !Enum.TryParse(modeName, out PreviewDisplayMode mode))
        {
            return;
        }

        _displayMode = mode;
        DisplayModeButton.Label = mode switch
        {
            PreviewDisplayMode.Fill => "Fill",
            PreviewDisplayMode.ActualSize => "1:1",
            _ => "Fit",
        };
        ApplyPresentation();
    }

    private void SafeAreasButton_Click(object sender, RoutedEventArgs e) => ApplyPresentation();

    private void ApplyPresentation()
        => _renderer?.SetPresentation(_displayMode, SafeAreasButton.IsChecked == true);

    private void FullScreenButton_Click(object sender, RoutedEventArgs e)
    {
        MainWindow? window = App.MainWindowInstance;
        if (window is null)
        {
            return;
        }

        if (_isFullScreen)
        {
            ExitFullScreen();
        }
        else
        {
            XamlRoot? root = XamlRoot;
            if (root is null)
            {
                return;
            }

            _restoreMaximizedAfterFullScreen =
                window.AppWindow.Presenter is OverlappedPresenter
                {
                    State: OverlappedPresenterState.Maximized,
                };
            Content = null;
            _fullScreenPopup = new Popup
            {
                XamlRoot = root,
                Child = PreviewRoot,
                IsLightDismissEnabled = false,
                IsOpen = true,
            };
            _isFullScreen = true;
            SizeFullScreenPreview(root);
            window.AppWindow.SetPresenter(AppWindowPresenterKind.FullScreen);
            FullScreenButton.Icon = new SymbolIcon(Symbol.BackToWindow);
            FullScreenButton.Label = "Exit full screen";
            AutomationProperties.SetName(FullScreenButton, "Exit full screen preview");
            RequestResize();
        }
    }

    private void ExitFullScreen()
    {
        if (!_isFullScreen || App.MainWindowInstance is not MainWindow window)
        {
            return;
        }

        Popup? popup = _fullScreenPopup;
        _fullScreenPopup = null;
        if (popup is not null)
        {
            popup.IsOpen = false;
            popup.Child = null;
        }
        PreviewRoot.Width = double.NaN;
        PreviewRoot.Height = double.NaN;
        Content = PreviewRoot;

        window.AppWindow.SetPresenter(AppWindowPresenterKind.Overlapped);
        if (_restoreMaximizedAfterFullScreen && window.AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.Maximize();
        }
        _restoreMaximizedAfterFullScreen = false;
        _isFullScreen = false;
        FullScreenButton.Icon = new SymbolIcon(Symbol.FullScreen);
        FullScreenButton.Label = "Full screen";
        AutomationProperties.SetName(FullScreenButton, "Enter full screen preview");
        RequestResize();
    }

    private void SizeFullScreenPreview(XamlRoot root)
    {
        PreviewRoot.Width = root.Size.Width;
        PreviewRoot.Height = root.Size.Height;
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
            PreviewContextText.Text = diagnostics.IsWarp
                ? $"{_previewContext} · software GPU"
                : _previewContext;
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

    private async void PlayPauseButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            await SetPlayingAsync(!_isVideoPlaying);
        }
        catch (Exception exception)
        {
            await SetStateAsync($"Video preview transport failed. {exception.Message}", false, true);
        }
    }

    private TimeSpan PlaybackStartPosition(VideoPlaybackSession session) =>
        session.Metadata.Duration > TimeSpan.Zero
        && _videoPosition >= session.Metadata.Duration - TimeSpan.FromMilliseconds(50)
            ? TimeSpan.Zero
            : _videoPosition;

    private async void PositionSlider_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (_isUpdatingPosition)
        {
            return;
        }

        VideoPlaybackSession? session = Volatile.Read(ref _videoSession);
        if (session is null)
        {
            return;
        }

        TimeSpan target = TimeSpan.FromSeconds(Math.Max(0, e.NewValue));
        _videoPosition = target;
        bool resumePlayback = _isVideoPlaying || _resumePlaybackAfterSeek;
        _resumePlaybackAfterSeek = resumePlayback;
        CancelPlayback();
        await UpdatePlaybackStateAsync(isPlaying: false);
        await UpdatePositionAsync(target, session.Metadata.Duration);

        CancellationTokenSource replacement = new();
        CancellationTokenSource? previous = Interlocked.Exchange(ref _seekDebounceCancellation, replacement);
        CancelSafely(previous);

        try
        {
            await Task.Delay(TimeSpan.FromMilliseconds(180), replacement.Token);
            if (!ReferenceEquals(session, Volatile.Read(ref _videoSession)))
            {
                return;
            }

            await session.StopAsync();
            int generation = Volatile.Read(ref _videoGeneration);
            if (_resumePlaybackAfterSeek)
            {
                _resumePlaybackAfterSeek = false;
                _ = StartPlaybackAsync(session, target, generation);
            }
            else
            {
                await session.DecodeAsync(
                    target,
                    frame => SubmitVideoFrame(session, generation, frame),
                    paceFrames: false,
                    maximumFrames: 1,
                    replacement.Token);
            }
        }
        catch (OperationCanceledException) when (replacement.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            await SetStateAsync(
                $"Video preview could not seek. {exception.Message}",
                isProgressActive: false,
                isVisible: true);
        }
        finally
        {
            Interlocked.CompareExchange(ref _seekDebounceCancellation, null, replacement);
            replacement.Dispose();
        }
    }

    private async Task StartPlaybackAsync(
        VideoPlaybackSession session,
        TimeSpan startPosition,
        int generation)
    {
        if (!ReferenceEquals(session, Volatile.Read(ref _videoSession))
            || generation != Volatile.Read(ref _videoGeneration))
        {
            return;
        }

        CancellationTokenSource replacement = new();
        CancellationTokenSource? previous = Interlocked.Exchange(ref _playbackCancellation, replacement);
        CancelSafely(previous);
        _resumePlaybackAfterSeek = false;

        try
        {
            await UpdatePlaybackStateAsync(isPlaying: true);
            await session.DecodeAsync(
                startPosition,
                frame => SubmitVideoFrame(session, generation, frame),
                paceFrames: true,
                maximumFrames: null,
                replacement.Token);

            if (ReferenceEquals(session, Volatile.Read(ref _videoSession))
                && generation == Volatile.Read(ref _videoGeneration))
            {
                _videoPosition = session.Metadata.Duration;
                await UpdatePositionAsync(_videoPosition, session.Metadata.Duration);
            }
        }
        catch (OperationCanceledException) when (replacement.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            if (ReferenceEquals(session, Volatile.Read(ref _videoSession))
                && generation == Volatile.Read(ref _videoGeneration))
            {
                await SetStateAsync(
                    $"Video playback stopped. {exception.Message}",
                    isProgressActive: false,
                    isVisible: true);
            }
        }
        finally
        {
            if (ReferenceEquals(
                Interlocked.CompareExchange(ref _playbackCancellation, null, replacement),
                replacement))
            {
                await UpdatePlaybackStateAsync(isPlaying: false);
            }
            replacement.Dispose();
        }
    }

    private void SubmitVideoFrame(
        VideoPlaybackSession session,
        int generation,
        OwnedCpuFrame frame)
    {
        if (!ReferenceEquals(session, Volatile.Read(ref _videoSession))
            || generation != Volatile.Read(ref _videoGeneration))
        {
            frame.Dispose();
            return;
        }

        PreviewRendererSession? renderer = Volatile.Read(ref _renderer);
        TimeSpan timestamp = frame.Timestamp;
        if (renderer is null)
        {
            frame.Dispose();
            return;
        }
        if (!renderer.TrySubmitFrame(frame))
        {
            return;
        }

        _hasFrame = true;
        _videoPosition = timestamp;
        _ = UpdateVideoFrameStateAsync(session, generation, timestamp);
    }

    private Task ConfigureVideoTransportAsync(VideoMetadata metadata)
        => RunOnDispatcherAsync(() =>
        {
            VideoTransport.Visibility = Visibility.Visible;
            _isUpdatingPosition = true;
            try
            {
                PositionSlider.Minimum = 0;
                PositionSlider.Maximum = Math.Max(metadata.Duration.TotalSeconds, 0.001);
                PositionSlider.Value = 0;
            }
            finally
            {
                _isUpdatingPosition = false;
            }
            PositionText.Text = $"{FormatTime(TimeSpan.Zero)} / {FormatTime(metadata.Duration)}";
            PositionSlider.StepFrequency = 1.0 / metadata.FramesPerSecond;
            SetFrameMetadata($"{metadata.Width} x {metadata.Height} · {metadata.FramesPerSecond:0.##} fps");
            SetPlaybackButtonState(isPlaying: false);
        });

    private Task UpdateVideoFrameStateAsync(VideoPlaybackSession session, int generation, TimeSpan position)
        => RunOnDispatcherAsync(() =>
        {
            if (!ReferenceEquals(session, Volatile.Read(ref _videoSession))
                || generation != Volatile.Read(ref _videoGeneration)) return;
            SetState(string.Empty, isProgressActive: false, isVisible: false);
            UpdatePosition(position, session.Metadata.Duration);
        });

    private Task UpdatePositionAsync(TimeSpan position, TimeSpan duration)
        => RunOnDispatcherAsync(() => UpdatePosition(position, duration));

    private void UpdatePosition(TimeSpan position, TimeSpan duration)
    {
        _isUpdatingPosition = true;
        try
        {
            PositionSlider.Value = Math.Clamp(
                position.TotalSeconds,
                PositionSlider.Minimum,
                PositionSlider.Maximum);
            PositionText.Text = $"{FormatTime(position)} / {FormatTime(duration)}";
        }
        finally
        {
            _isUpdatingPosition = false;
        }

        if (duration > TimeSpan.Zero)
        {
            PositionChanged?.Invoke(this, new PreviewPositionChangedEventArgs(
                Math.Clamp(position.TotalSeconds / duration.TotalSeconds, 0, 1)));
        }
    }

    private Task UpdatePlaybackStateAsync(bool isPlaying)
    {
        _isVideoPlaying = isPlaying;
        return RunOnDispatcherAsync(() => SetPlaybackButtonState(isPlaying));
    }

    private void SetPlaybackButtonState(bool isPlaying)
    {
        PlayPauseIcon.Glyph = isPlaying ? "\uE769" : "\uE768";
        AutomationProperties.SetName(
            PlayPauseButton,
            isPlaying ? "Pause video preview" : "Play video preview");
    }

    private void CancelPlayback()
    {
        CancellationTokenSource? cancellation = Interlocked.Exchange(ref _playbackCancellation, null);
        CancelSafely(cancellation);
        Volatile.Read(ref _videoSession)?.Cancel();
        _isVideoPlaying = false;
    }

    private void BeginVideoCleanup()
    {
        _videoCleanupTask = ObserveVideoCleanupAsync();
    }

    private async Task ObserveVideoCleanupAsync()
    {
        try { await DisposeVideoSessionAsync(); }
        catch (Exception exception) { Debug.WriteLine($"Video playback shutdown failed: {exception}"); }
    }

    private async Task DisposeVideoSessionAsync()
    {
        await _videoLifecycleGate.WaitAsync();
        try
        {
            Interlocked.Increment(ref _videoGeneration);
            _resumePlaybackAfterSeek = false;
            CancelPlayback();

            CancellationTokenSource? seekCancellation =
                Interlocked.Exchange(ref _seekDebounceCancellation, null);
            CancelSafely(seekCancellation);

            VideoPlaybackSession? session = Interlocked.Exchange(ref _videoSession, null);
            if (session is not null)
            {
                App.Services.UntrackVideoPlaybackSession(session);
                await session.DisposeAsync();
            }

            _videoPosition = TimeSpan.Zero;
            await RunOnDispatcherAsync(() =>
            {
                VideoTransport.Visibility = Visibility.Collapsed;
                SetPlaybackButtonState(isPlaying: false);
            });
        }
        finally
        {
            _videoLifecycleGate.Release();
        }
    }

    private Task RunOnDispatcherAsync(Action action)
    {
        if (DispatcherQueue.HasThreadAccess)
        {
            action();
            return Task.CompletedTask;
        }

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!DispatcherQueue.TryEnqueue(() =>
            {
                try
                {
                    action();
                    completion.SetResult();
                }
                catch (Exception exception)
                {
                    completion.SetException(exception);
                }
            }))
        {
            completion.SetResult();
        }

        return completion.Task;
    }

    private static string FormatTime(TimeSpan value)
    {
        TimeSpan bounded = value < TimeSpan.Zero ? TimeSpan.Zero : value;
        return bounded.TotalHours >= 1
            ? bounded.ToString(@"h\:mm\:ss", CultureInfo.InvariantCulture)
            : bounded.ToString(@"m\:ss", CultureInfo.InvariantCulture);
    }

    private CancellationTokenSource ReplaceLoadCancellation(CancellationToken cancellationToken)
    {
        var replacement = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        CancellationTokenSource? previous = Interlocked.Exchange(ref _loadCancellation, replacement);
        CancelSafely(previous);
        return replacement;
    }

    private void CancelPendingLoad()
    {
        CancellationTokenSource? cancellation = Interlocked.Exchange(ref _loadCancellation, null);
        CancelSafely(cancellation);
    }

    private static void CancelSafely(CancellationTokenSource? cancellation)
    {
        // Only the operation that created a source disposes it, after its last
        // continuation. Replacement may race that final continuation.
        try { cancellation?.Cancel(); }
        catch (ObjectDisposedException) { }
    }

    private Task SetFrameMetadataAsync(string metadata)
        => RunOnDispatcherAsync(() => SetFrameMetadata(metadata));

    private void SetFrameMetadata(string metadata)
    {
        FrameMetadataText.Text = metadata;
        FrameMetadataBadge.Visibility = string.IsNullOrWhiteSpace(metadata)
            ? Visibility.Collapsed
            : Visibility.Visible;
    }

    private Task SetStateAsync(string message, bool isProgressActive, bool isVisible)
        => RunOnDispatcherAsync(() => SetState(message, isProgressActive, isVisible));

    private void SetState(string message, bool isProgressActive, bool isVisible)
    {
        StateText.Text = message;
        StateProgressRing.IsActive = isProgressActive;
        StateProgressRing.Visibility = isProgressActive ? Visibility.Visible : Visibility.Collapsed;
        StateIcon.Visibility = isProgressActive ? Visibility.Collapsed : Visibility.Visible;
        StateIcon.Glyph = message.Contains("error", StringComparison.OrdinalIgnoreCase) ||
            message.Contains("could not", StringComparison.OrdinalIgnoreCase) ||
            message.Contains("failed", StringComparison.OrdinalIgnoreCase)
                ? "\uEA39"
                : "\uE946";
        StateOverlay.Visibility = isVisible ? Visibility.Visible : Visibility.Collapsed;
    }
}
