using System.Numerics;
using EdmgStudio.Core.Graphics;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using SharpGen.Runtime;
using Vortice.Direct2D1;
using Vortice.Direct3D11;
using Vortice.DXGI;
using Vortice.Mathematics;
using WinUISwapChainPanelNative = Vortice.WinUI.ISwapChainPanelNative;
using static Vortice.Direct2D1.D2D1;
using D2DAlphaMode = Vortice.DCommon.AlphaMode;
using D2DPixelFormat = Vortice.DCommon.PixelFormat;
using DxgiAlphaMode = Vortice.DXGI.AlphaMode;
using D2DFactoryType = Vortice.Direct2D1.FactoryType;
using DxgiFormat = Vortice.DXGI.Format;
using DxgiUsage = Vortice.DXGI.Usage;

namespace EdmgStudio.WinUI.Graphics;

internal sealed class PreviewRendererSession : IAsyncDisposable
{
    private const int MaxRecoveryAttempts = 3;
    private const int DxgiErrorDeviceRemoved = unchecked((int)0x887A0005);
    private const int DxgiErrorDeviceHung = unchecked((int)0x887A0006);
    private const int DxgiErrorDeviceReset = unchecked((int)0x887A0007);
    private const int DxgiErrorDriverInternalError = unchecked((int)0x887A0020);
    private const int D2DErrorRecreateTarget = unchecked((int)0x8899000C);

    private readonly SwapChainPanel _panel;
    private readonly DispatcherQueue _dispatcherQueue;
    private readonly LatestFrameMailbox<OwnedCpuFrame> _mailbox = new();
    private readonly AutoResetEvent _workAvailable = new(false);
    private readonly CancellationTokenSource _shutdown = new();
    private readonly RendererLifecycle _lifecycle = new();
    private readonly object _resizeSync = new();
    private readonly object _disposeSync = new();
    private readonly Action<RendererStatus> _statusChanged;
    private readonly Action<PreviewAdapterDiagnostics> _diagnosticsChanged;
    private readonly Task _worker;

    private PhysicalPixelSize _requestedSize;
    private double _requestedScale = 1.0;
    private long _requestedResizeVersion;
    private bool _isAcceptingFrames = true;
    private bool _isDisposed;
    private Task? _disposeTask;

    private D3D11DeviceResources? _deviceBundle;
    private ID2D1Factory1? _d2dFactory;
    private ID2D1Device? _d2dDevice;
    private ID2D1DeviceContext? _d2dContext;
    private IDXGISwapChain1? _swapChain;
    private ID2D1Bitmap1? _backBufferTarget;
    private ID2D1Bitmap1? _sourceBitmap;
    private IFrameUploader? _uploader;
    private OwnedCpuFrame? _retainedFrame;
    private PhysicalPixelSize _surfaceSize;
    private double _surfaceScale = 1.0;
    private long _appliedResizeVersion = -1;
    private int _sourceWidth;
    private int _sourceHeight;
    private bool _isPanelAttached;

    public PreviewRendererSession(
        SwapChainPanel panel,
        DispatcherQueue dispatcherQueue,
        Action<RendererStatus> statusChanged,
        Action<PreviewAdapterDiagnostics> diagnosticsChanged)
    {
        _panel = panel ?? throw new ArgumentNullException(nameof(panel));
        _dispatcherQueue = dispatcherQueue ?? throw new ArgumentNullException(nameof(dispatcherQueue));
        _statusChanged = statusChanged ?? throw new ArgumentNullException(nameof(statusChanged));
        _diagnosticsChanged = diagnosticsChanged ?? throw new ArgumentNullException(nameof(diagnosticsChanged));
        _lifecycle.StatusChanged += Lifecycle_StatusChanged;
        _worker = Task.Factory.StartNew(
            WorkerMain,
            CancellationToken.None,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default);
    }

    public bool TrySubmitFrame(OwnedCpuFrame frame)
    {
        ArgumentNullException.ThrowIfNull(frame);
        if (!_isAcceptingFrames || _isDisposed)
        {
            frame.Dispose();
            return false;
        }

        bool published = _mailbox.TryPublish(frame);
        if (published)
        {
            _workAvailable.Set();
        }

        return published;
    }

    public void RequestResize(double widthInDips, double heightInDips, double rasterizationScale)
    {
        PhysicalPixelSize size;
        try
        {
            size = PreviewGeometry.ToPhysicalPixels(widthInDips, heightInDips, rasterizationScale);
        }
        catch (ArgumentOutOfRangeException)
        {
            size = default;
            rasterizationScale = 1.0;
        }
        catch (OverflowException)
        {
            size = default;
            rasterizationScale = 1.0;
        }

        lock (_resizeSync)
        {
            _requestedSize = size;
            _requestedScale = rasterizationScale;
            _requestedResizeVersion++;
        }

        _workAvailable.Set();
    }

    public ValueTask DisposeAsync()
    {
        lock (_disposeSync)
        {
            _disposeTask ??= DisposeCoreAsync();
            return new ValueTask(_disposeTask);
        }
    }

    private async Task DisposeCoreAsync()
    {
        _isDisposed = true;
        _isAcceptingFrames = false;
        _mailbox.Complete();
        _shutdown.Cancel();
        _workAvailable.Set();
        List<Exception>? failures = null;

        try
        {
            await DetachPanelOnUiThreadAsync().ConfigureAwait(true);
        }
        catch (Exception exception)
        {
            _isPanelAttached = false;
            (failures ??= []).Add(exception);
        }

        try
        {
            await _worker.ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        _lifecycle.StatusChanged -= Lifecycle_StatusChanged;
        try
        {
            _mailbox.Dispose();
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        try
        {
            _workAvailable.Dispose();
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        try
        {
            _shutdown.Dispose();
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        if (failures is not null)
        {
            throw new AggregateException("One or more preview renderer shutdown steps failed.", failures);
        }
    }

    private void WorkerMain()
    {
        try
        {
            while (!_shutdown.IsCancellationRequested)
            {
                _workAvailable.WaitOne();
                if (_shutdown.IsCancellationRequested)
                {
                    break;
                }

                ProcessPendingWork();
            }
        }
        catch (Exception exception)
        {
            TryMarkFaulted(exception);
        }
        finally
        {
            TryBeginStopping();
            if (!_shutdown.IsCancellationRequested)
            {
                DetachPanelOnUiThread();
            }

            List<Exception>? cleanupFailures = null;
            try
            {
                DisposeGraphicsResources();
            }
            catch (Exception exception)
            {
                (cleanupFailures ??= []).Add(exception);
            }
            finally
            {
                try
                {
                    _retainedFrame?.Dispose();
                }
                catch (Exception exception)
                {
                    (cleanupFailures ??= []).Add(exception);
                }
                finally
                {
                    _retainedFrame = null;
                }

                TryMarkStopped();
            }

            if (cleanupFailures is { Count: > 0 })
            {
                throw new AggregateException("The Direct3D preview worker could not release every resource.", cleanupFailures);
            }
        }
    }

    private void ProcessPendingWork()
    {
        SnapshotRequestedSize(out PhysicalPixelSize requestedSize, out double requestedScale, out long resizeVersion);

        bool hasNewFrame = false;
        while (_mailbox.TryTake(out OwnedCpuFrame? nextFrame))
        {
            _retainedFrame?.Dispose();
            _retainedFrame = nextFrame;
            hasNewFrame = true;
        }

        if (!requestedSize.IsRenderable)
        {
            return;
        }

        try
        {
            EnsureGraphicsResources(requestedSize, requestedScale);
            if (resizeVersion != _appliedResizeVersion)
            {
                ResizeSurface(requestedSize, requestedScale);
                _appliedResizeVersion = resizeVersion;
            }

            if (_retainedFrame is null)
            {
                DrawEmptySurface();
                return;
            }

            if (hasNewFrame || _sourceBitmap is null)
            {
                UploadRetainedFrame();
            }

            DrawRetainedFrame();
        }
        catch (Exception exception) when (IsRecoverableGraphicsFailure(exception))
        {
            RecoverGraphics(exception, requestedSize, requestedScale, resizeVersion);
        }
    }

    private void EnsureGraphicsResources(PhysicalPixelSize size, double scale)
    {
        if (_swapChain is not null)
        {
            return;
        }

        if (_lifecycle.Status.State is RendererLifecycleState.Detached or
            RendererLifecycleState.Stopped or
            RendererLifecycleState.Faulted)
        {
            _lifecycle.BeginInitialization();
        }

        _deviceBundle = D3D11DeviceFactory.Create();
        _diagnosticsChanged(_deviceBundle.Diagnostics);
        _uploader = new CpuFrameUploader(_deviceBundle.Device, _deviceBundle.Context);

        _d2dFactory = D2D1CreateFactory<ID2D1Factory1>(D2DFactoryType.MultiThreaded);
        using IDXGIDevice dxgiDevice = _deviceBundle.Device.QueryInterface<IDXGIDevice>();
        _d2dDevice = _d2dFactory.CreateDevice(dxgiDevice);
        _d2dContext = _d2dDevice.CreateDeviceContext(DeviceContextOptions.None);

        using IDXGIAdapter adapter = dxgiDevice.GetAdapter();
        using IDXGIFactory2 factory = adapter.GetParent<IDXGIFactory2>();
        var description = new SwapChainDescription1
        {
            Width = (uint)size.Width,
            Height = (uint)size.Height,
            Format = DxgiFormat.B8G8R8A8_UNorm,
            Stereo = false,
            SampleDescription = new SampleDescription(1, 0),
            BufferUsage = DxgiUsage.RenderTargetOutput,
            BufferCount = 2,
            Scaling = Scaling.Stretch,
            SwapEffect = SwapEffect.FlipSequential,
            AlphaMode = DxgiAlphaMode.Premultiplied,
            Flags = SwapChainFlags.None,
        };

        _swapChain = factory.CreateSwapChainForComposition(_deviceBundle.Device, description, null);
        using (IDXGISwapChain2 swapChain2 = _swapChain.QueryInterface<IDXGISwapChain2>())
        {
            Matrix3x2 transform = Matrix3x2.CreateScale((float)(1.0 / scale));
            swapChain2.MatrixTransform = transform;
        }

        _surfaceSize = size;
        _surfaceScale = scale;
        CreateBackBufferTarget();
        AttachPanelOnUiThread();
        _lifecycle.MarkReady(
            $"Preview renderer is ready on {_deviceBundle.Diagnostics.Description} " +
            $"(LUID {_deviceBundle.Diagnostics.LuidText}).");
    }

    private void ResizeSurface(PhysicalPixelSize size, double scale)
    {
        if (_swapChain is null || _d2dContext is null)
        {
            return;
        }

        bool sizeChanged = size != _surfaceSize;
        _surfaceScale = scale;
        using (IDXGISwapChain2 swapChain2 = _swapChain.QueryInterface<IDXGISwapChain2>())
        {
            Matrix3x2 transform = Matrix3x2.CreateScale((float)(1.0 / scale));
            swapChain2.MatrixTransform = transform;
        }

        if (!sizeChanged)
        {
            return;
        }

        _d2dContext.Target = null;
        _backBufferTarget?.Dispose();
        _backBufferTarget = null;
        _swapChain.ResizeBuffers(
            2,
            (uint)size.Width,
            (uint)size.Height,
            DxgiFormat.B8G8R8A8_UNorm,
            SwapChainFlags.None).CheckError();
        _surfaceSize = size;
        CreateBackBufferTarget();
    }

    private void CreateBackBufferTarget()
    {
        if (_swapChain is null || _d2dContext is null)
        {
            throw new InvalidOperationException("The preview swap chain is not initialized.");
        }

        using IDXGISurface surface = _swapChain.GetBuffer<IDXGISurface>(0);
        var properties = new BitmapProperties1(
            new D2DPixelFormat(DxgiFormat.B8G8R8A8_UNorm, D2DAlphaMode.Premultiplied),
            96.0f,
            96.0f,
            BitmapOptions.Target | BitmapOptions.CannotDraw);
        _backBufferTarget = _d2dContext.CreateBitmapFromDxgiSurface(surface, properties);
        _d2dContext.Target = _backBufferTarget;
    }

    private void UploadRetainedFrame()
    {
        if (_retainedFrame is null || _uploader is null || _d2dContext is null)
        {
            return;
        }

        ID3D11Texture2D uploadedTexture = _uploader.Upload(_retainedFrame);
        if (_sourceBitmap is not null &&
            _sourceWidth == _retainedFrame.Layout.Width &&
            _sourceHeight == _retainedFrame.Layout.Height)
        {
            return;
        }

        _sourceBitmap?.Dispose();
        _sourceBitmap = null;
        using IDXGISurface sourceSurface = uploadedTexture.QueryInterface<IDXGISurface>();
        var properties = new BitmapProperties1(
            new D2DPixelFormat(DxgiFormat.B8G8R8A8_UNorm, D2DAlphaMode.Premultiplied));
        _sourceBitmap = _d2dContext.CreateBitmapFromDxgiSurface(sourceSurface, properties);
        _sourceWidth = _retainedFrame.Layout.Width;
        _sourceHeight = _retainedFrame.Layout.Height;
    }

    private void DrawEmptySurface()
    {
        if (_d2dContext is null || _swapChain is null)
        {
            return;
        }

        _d2dContext.BeginDraw();
        _d2dContext.Clear(new Color4(0.035f, 0.035f, 0.045f, 1.0f));
        _d2dContext.EndDraw().CheckError();
        _swapChain.Present(1, PresentFlags.None).CheckError();
    }

    private void DrawRetainedFrame()
    {
        if (_retainedFrame is null ||
            _sourceBitmap is null ||
            _d2dContext is null ||
            _swapChain is null)
        {
            return;
        }

        AspectFitRectangle fit = PreviewGeometry.CalculateAspectFit(
            _retainedFrame.Layout.Width,
            _retainedFrame.Layout.Height,
            _surfaceSize.Width,
            _surfaceSize.Height);
        var destination = new Vortice.RawRectF(
            fit.X,
            fit.Y,
            fit.X + fit.Width,
            fit.Y + fit.Height);

        _d2dContext.BeginDraw();
        _d2dContext.Clear(new Color4(0.035f, 0.035f, 0.045f, 1.0f));
        _d2dContext.DrawBitmap(
            _sourceBitmap,
            destination,
            1.0f,
            InterpolationMode.Linear,
            null,
            null);
        _d2dContext.EndDraw().CheckError();
        _swapChain.Present(1, PresentFlags.None).CheckError();
    }

    private void RecoverGraphics(
        Exception failure,
        PhysicalPixelSize requestedSize,
        double requestedScale,
        long resizeVersion)
    {
        string failureCode = $"0x{failure.HResult:X8}";
        _lifecycle.BeginRecovery(
            failureCode,
            "The graphics device was interrupted. Recreating the preview renderer.");

        DetachPanelOnUiThread();
        DisposeGraphicsResources();

        Exception lastFailure = failure;
        for (int attempt = 1; attempt <= MaxRecoveryAttempts && !_shutdown.IsCancellationRequested; attempt++)
        {
            try
            {
                if (attempt > 1)
                {
                    _shutdown.Token.WaitHandle.WaitOne(TimeSpan.FromMilliseconds(150 * attempt));
                }

                EnsureGraphicsResources(requestedSize, requestedScale);
                _appliedResizeVersion = resizeVersion;
                if (_retainedFrame is not null)
                {
                    UploadRetainedFrame();
                    DrawRetainedFrame();
                }
                else
                {
                    DrawEmptySurface();
                }

                return;
            }
            catch (Exception exception) when (IsRecoverableGraphicsFailure(exception))
            {
                lastFailure = exception;
                DetachPanelOnUiThread();
                DisposeGraphicsResources();
            }
        }

        _lifecycle.MarkFaulted(
            $"0x{lastFailure.HResult:X8}",
            "The preview renderer could not recover. Select the artifact again to retry.");
    }

    private void AttachPanelOnUiThread()
    {
        if (_swapChain is null || _isPanelAttached)
        {
            return;
        }

        RunOnUiThread(
            () =>
            {
                if (_shutdown.IsCancellationRequested)
                {
                    return;
                }

                SetPanelSwapChain(_swapChain);
                _isPanelAttached = true;
            });
    }

    private void DetachPanelOnUiThread()
    {
        if (!_isPanelAttached)
        {
            return;
        }

        try
        {
            RunOnUiThread(
                () =>
                {
                    SetPanelSwapChain(null);
                    _isPanelAttached = false;
                });
        }
        catch
        {
            _isPanelAttached = false;
        }
    }

    private void RunOnUiThread(Action action)
    {
        if (_dispatcherQueue.HasThreadAccess)
        {
            action();
            return;
        }

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!_dispatcherQueue.TryEnqueue(
                () =>
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
            throw new InvalidOperationException("The preview UI dispatcher is no longer available.");
        }

        completion.Task.GetAwaiter().GetResult();
    }

    private Task DetachPanelOnUiThreadAsync()
    {
        if (!_isPanelAttached)
        {
            return Task.CompletedTask;
        }

        if (_dispatcherQueue.HasThreadAccess)
        {
            SetPanelSwapChain(null);
            _isPanelAttached = false;
            return Task.CompletedTask;
        }

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!_dispatcherQueue.TryEnqueue(
                () =>
                {
                    try
                    {
                        SetPanelSwapChain(null);
                        _isPanelAttached = false;
                        completion.SetResult();
                    }
                    catch (Exception exception)
                    {
                        completion.SetException(exception);
                    }
                }))
        {
            completion.SetException(
                new InvalidOperationException("The preview UI dispatcher is no longer available."));
        }

        return completion.Task;
    }

    private void SetPanelSwapChain(IDXGISwapChain? swapChain)
    {
        using var nativePanel = new WinUISwapChainPanelNative(_panel);
        nativePanel.SetSwapChain(swapChain).CheckError();
    }

    private void DisposeGraphicsResources()
    {
        List<Exception>? failures = null;
        try
        {
            if (_d2dContext is not null)
            {
                _d2dContext.Target = null;
            }
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        ID2D1Bitmap1? sourceBitmap = _sourceBitmap;
        _sourceBitmap = null;
        DisposeResource(sourceBitmap, ref failures);

        ID2D1Bitmap1? backBufferTarget = _backBufferTarget;
        _backBufferTarget = null;
        DisposeResource(backBufferTarget, ref failures);

        IDXGISwapChain1? swapChain = _swapChain;
        _swapChain = null;
        DisposeResource(swapChain, ref failures);

        ID2D1DeviceContext? d2dContext = _d2dContext;
        _d2dContext = null;
        DisposeResource(d2dContext, ref failures);

        ID2D1Device? d2dDevice = _d2dDevice;
        _d2dDevice = null;
        DisposeResource(d2dDevice, ref failures);

        ID2D1Factory1? d2dFactory = _d2dFactory;
        _d2dFactory = null;
        DisposeResource(d2dFactory, ref failures);

        IFrameUploader? uploader = _uploader;
        _uploader = null;
        DisposeResource(uploader, ref failures);

        D3D11DeviceResources? deviceBundle = _deviceBundle;
        _deviceBundle = null;
        DisposeResource(deviceBundle, ref failures);

        _surfaceSize = default;
        _sourceWidth = 0;
        _sourceHeight = 0;

        if (failures is { Count: > 0 })
        {
            throw new AggregateException("One or more Direct3D preview resources could not be released.", failures);
        }
    }

    private static void DisposeResource(IDisposable? resource, ref List<Exception>? failures)
    {
        if (resource is null)
        {
            return;
        }

        try
        {
            resource.Dispose();
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }
    }

    private void SnapshotRequestedSize(
        out PhysicalPixelSize size,
        out double scale,
        out long resizeVersion)
    {
        lock (_resizeSync)
        {
            size = _requestedSize;
            scale = _requestedScale;
            resizeVersion = _requestedResizeVersion;
        }
    }

    private void Lifecycle_StatusChanged(object? sender, RendererStatus status)
    {
        if (_dispatcherQueue.HasThreadAccess)
        {
            _statusChanged(status);
            return;
        }

        _ = _dispatcherQueue.TryEnqueue(() => _statusChanged(status));
    }

    private static bool IsRecoverableGraphicsFailure(Exception exception)
    {
        int result = exception.HResult;
        return result is
            DxgiErrorDeviceRemoved or
            DxgiErrorDeviceHung or
            DxgiErrorDeviceReset or
            DxgiErrorDriverInternalError or
            D2DErrorRecreateTarget;
    }

    private void TryMarkFaulted(Exception exception)
    {
        try
        {
            _lifecycle.MarkFaulted(
                $"0x{exception.HResult:X8}",
                $"Preview renderer failed: {exception.Message}");
        }
        catch (InvalidOperationException)
        {
        }
    }

    private void TryBeginStopping()
    {
        try
        {
            _lifecycle.BeginStopping();
        }
        catch (InvalidOperationException)
        {
        }
    }

    private void TryMarkStopped()
    {
        try
        {
            _lifecycle.MarkStopped();
        }
        catch (InvalidOperationException)
        {
        }
    }
}
