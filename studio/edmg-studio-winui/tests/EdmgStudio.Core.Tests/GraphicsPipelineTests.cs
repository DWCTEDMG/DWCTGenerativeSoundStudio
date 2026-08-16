using System.Buffers;
using System.Collections.Concurrent;
using EdmgStudio.Core.Graphics;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class GraphicsPipelineTests
{
    [TestMethod]
    [DataRow(0, 1, 4, 4)]
    [DataRow(1, 0, 4, 4)]
    [DataRow(FrameLayout.MaximumDimension + 1, 1, 4, 4)]
    [DataRow(1, 1, -1, 4)]
    [DataRow(1, 1, 0, 4)]
    [DataRow(2, 1, 7, 8)]
    [DataRow(2, 2, 12, 19)]
    public void FrameLayout_RejectsInvalidDimensionsStrideAndLength(
        int width,
        int height,
        int stride,
        int sourceLength)
    {
        Assert.Throws<ArgumentException>(
            () => FrameLayout.Validate(width, height, stride, sourceLength));
    }

    [TestMethod]
    public void FrameLayout_UsesTheLastPixelRatherThanRequiringTrailingRowPadding()
    {
        var layout = FrameLayout.Validate(width: 2, height: 2, stride: 12, sourceLength: 20);

        Assert.AreEqual(8, layout.RowBytes);
        Assert.AreEqual(20, layout.MinimumSourceLength);
        Assert.AreEqual(16, layout.TightBufferLength);
    }

    [TestMethod]
    public void FrameLayout_RejectsBuffersAboveTheDecodedMemoryLimit()
    {
        Assert.ThrowsExactly<ArgumentException>(
            () => FrameLayout.Validate(16_384, 16_384, 65_536, int.MaxValue));
    }

    [TestMethod]
    public void FrameLayout_RejectsStrideOverflowAfterValidatingTheStride()
    {
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => FrameLayout.Validate(1, 2, int.MinValue, 4));
        Assert.ThrowsExactly<ArgumentException>(
            () => FrameLayout.Validate(1, 3, int.MaxValue, int.MaxValue));
    }

    [TestMethod]
    public void FrameLayout_RejectsNegativeSourceLength()
    {
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => FrameLayout.Validate(1, 1, 4, -1));
    }

    [TestMethod]
    public void OwnedFrame_DisposesTransferredOwnershipWhenValidationFails()
    {
        var owner = new TestMemoryOwner(4);

        Assert.ThrowsExactly<ArgumentException>(
            () => OwnedCpuFrame.Create(owner, 4, width: 2, height: 1, stride: 8, FramePixelFormat.Bgra8));
        Assert.IsTrue(owner.IsDisposed);
    }

    [TestMethod]
    public void CopyToBgra_PassesThroughBgraAndRemovesPaddedRows()
    {
        using var frame = CreateFrame(
            [
                1, 2, 3, 4, 5, 6, 7, 8, 99, 99, 99, 99,
                9, 10, 11, 12, 13, 14, 15, 16
            ],
            width: 2,
            height: 2,
            stride: 12,
            FramePixelFormat.Bgra8);
        var destination = new byte[16];

        frame.CopyToBgra(destination);

        CollectionAssert.AreEqual(
            new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 },
            destination);
    }

    [TestMethod]
    public void CopyToBgra_ConvertsRgbaAndFlipsBottomUpOrientation()
    {
        using var frame = CreateFrame(
            [
                10, 20, 30, 40,
                50, 60, 70, 80
            ],
            width: 1,
            height: 2,
            stride: 4,
            FramePixelFormat.Rgba8,
            FrameOrientation.BottomUp);
        var destination = new byte[8];

        frame.CopyToBgra(destination);

        CollectionAssert.AreEqual(
            new byte[] { 70, 60, 50, 80, 30, 20, 10, 40 },
            destination);
    }

    [TestMethod]
    public void CopyRowToBgra_ConvertsOnlyTheRequestedLogicalRow()
    {
        using var frame = CreateFrame(
            [
                1, 2, 3, 4, 99, 99, 99, 99,
                10, 20, 30, 40
            ],
            width: 1,
            height: 2,
            stride: 8,
            FramePixelFormat.Rgba8,
            FrameOrientation.BottomUp);
        var destination = new byte[] { 255, 255, 255, 255, 77 };

        frame.CopyRowToBgra(0, destination);

        CollectionAssert.AreEqual(new byte[] { 30, 20, 10, 40, 77 }, destination);
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => frame.CopyRowToBgra(2, destination));
        Assert.ThrowsExactly<ArgumentException>(
            () => frame.CopyRowToBgra(0, new byte[3]));
    }

    [TestMethod]
    public void PreviewGeometry_CentersAspectFitWithLetterboxing()
    {
        var rectangle = PreviewGeometry.CalculateAspectFit(1920, 1080, 1000, 1000);

        Assert.AreEqual(0.0f, rectangle.X, 0.001f);
        Assert.AreEqual(218.75f, rectangle.Y, 0.001f);
        Assert.AreEqual(1000.0f, rectangle.Width, 0.001f);
        Assert.AreEqual(562.5f, rectangle.Height, 0.001f);
    }

    [TestMethod]
    public void PreviewGeometry_ConvertsDipsToPhysicalPixelsAndPreservesZero()
    {
        Assert.AreEqual(
            new PhysicalPixelSize(960, 720),
            PreviewGeometry.ToPhysicalPixels(640, 480, 1.5));
        Assert.AreEqual(
            default,
            PreviewGeometry.ToPhysicalPixels(0, 480, 1.5));
    }

    [TestMethod]
    public void PreviewGeometry_ValidatesFiniteDipAndScaleValues()
    {
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => PreviewGeometry.ToPhysicalPixels(double.NaN, 480, 1));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => PreviewGeometry.ToPhysicalPixels(640, double.PositiveInfinity, 1));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(
            () => PreviewGeometry.ToPhysicalPixels(640, 480, 0));
        Assert.ThrowsExactly<OverflowException>(
            () => PreviewGeometry.ToPhysicalPixels(int.MaxValue, int.MaxValue, 2));
    }

    [TestMethod]
    public async Task LatestFrameMailbox_ReplacesAndDisposesTheStaleFrame()
    {
        using var mailbox = new LatestFrameMailbox<DisposableItem>();
        var stale = new DisposableItem();
        var latest = new DisposableItem();

        Assert.IsTrue(mailbox.TryPublish(stale));
        Assert.IsTrue(mailbox.TryPublish(latest));

        Assert.IsTrue(stale.IsDisposed);
        Assert.AreSame(latest, await mailbox.TakeAsync());
        Assert.IsFalse(latest.IsDisposed);
        latest.Dispose();
    }

    [TestMethod]
    public async Task LatestFrameMailbox_HonorsCancellationAndCompletion()
    {
        using var mailbox = new LatestFrameMailbox<DisposableItem>();
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        try
        {
            await mailbox.TakeAsync(cancellation.Token);
            Assert.Fail("The canceled mailbox read should not complete successfully.");
        }
        catch (OperationCanceledException exception)
        {
            Assert.AreEqual(cancellation.Token, exception.CancellationToken);
        }

        mailbox.Complete();
        Assert.IsNull(await mailbox.TakeAsync());

        var rejected = new DisposableItem();
        Assert.IsFalse(mailbox.TryPublish(rejected));
        Assert.IsTrue(rejected.IsDisposed);
    }

    [TestMethod]
    public async Task LatestFrameMailbox_CompletionDisposesAQueuedFrameAndWakesAReader()
    {
        using var mailbox = new LatestFrameMailbox<DisposableItem>();
        var queued = new DisposableItem();
        Assert.IsTrue(mailbox.TryPublish(queued));

        mailbox.Complete();

        Assert.IsTrue(queued.IsDisposed);
        Assert.IsNull(await mailbox.TakeAsync());
    }

    [TestMethod]
    public async Task LatestFrameMailbox_CompletionWakesAnAlreadyWaitingReader()
    {
        using var mailbox = new LatestFrameMailbox<DisposableItem>();
        Task<DisposableItem?> waiting = mailbox.TakeAsync().AsTask();

        mailbox.Complete();

        Assert.IsNull(await waiting.WaitAsync(TimeSpan.FromSeconds(1)));
    }

    [TestMethod]
    public void LatestFrameMailbox_TryTakeConsumesOnlyTheLatestFrame()
    {
        using var mailbox = new LatestFrameMailbox<DisposableItem>();
        var first = new DisposableItem();
        var latest = new DisposableItem();

        Assert.IsFalse(mailbox.TryTake(out var empty));
        Assert.IsNull(empty);
        Assert.IsTrue(mailbox.TryPublish(first));
        Assert.IsTrue(mailbox.TryPublish(latest));
        Assert.IsTrue(first.IsDisposed);

        Assert.IsTrue(mailbox.TryTake(out var taken));
        Assert.AreSame(latest, taken);
        Assert.IsFalse(mailbox.TryTake(out empty));
        Assert.IsNull(empty);
        taken!.Dispose();
    }

    [TestMethod]
    public async Task LatestFrameMailbox_ConcurrentPublishAndTake_DisposesEveryFrameExactlyOnce()
    {
        const int frameCount = 4_096;
        using var mailbox = new LatestFrameMailbox<ConcurrentDisposableItem>();
        var frames = Enumerable.Range(0, frameCount)
            .Select(_ => new ConcurrentDisposableItem())
            .ToArray();

        var consumer = Task.Run(async () =>
        {
            while (await mailbox.TakeAsync() is { } frame)
            {
                frame.Dispose();
            }
        });

        var producer = Task.Run(() =>
        {
            foreach (var frame in frames)
            {
                Assert.IsTrue(mailbox.TryPublish(frame));
            }

            mailbox.Complete();
        });

        await Task.WhenAll(producer, consumer);

        Assert.IsTrue(frames.All(frame => frame.DisposeCount == 1));
    }

    [TestMethod]
    public void LatestFrameMailbox_ConcurrentPublishAndComplete_DoesNotOverflowOrDoubleDispose()
    {
        const int iterationCount = 10_000;
        using var start = new Barrier(3);
        using var finish = new Barrier(3);
        var errors = new ConcurrentQueue<Exception>();
        LatestFrameMailbox<ConcurrentDisposableItem>? mailbox = null;
        ConcurrentDisposableItem? frame = null;

        var publisher = new Thread(() =>
        {
            for (var index = 0; index < iterationCount; index++)
            {
                start.SignalAndWait();
                try
                {
                    mailbox!.TryPublish(frame!);
                }
                catch (Exception ex)
                {
                    errors.Enqueue(ex);
                }
                finally
                {
                    finish.SignalAndWait();
                }
            }
        });

        var completer = new Thread(() =>
        {
            for (var index = 0; index < iterationCount; index++)
            {
                start.SignalAndWait();
                try
                {
                    mailbox!.Complete();
                }
                catch (Exception ex)
                {
                    errors.Enqueue(ex);
                }
                finally
                {
                    finish.SignalAndWait();
                }
            }
        });

        publisher.Start();
        completer.Start();

        var invalidDisposalCount = 0;
        for (var index = 0; index < iterationCount; index++)
        {
            mailbox = new LatestFrameMailbox<ConcurrentDisposableItem>();
            frame = new ConcurrentDisposableItem();

            start.SignalAndWait();
            finish.SignalAndWait();

            mailbox.Dispose();
            if (frame.DisposeCount != 1)
            {
                invalidDisposalCount++;
            }
        }

        publisher.Join();
        completer.Join();

        Assert.IsEmpty(errors);
        Assert.AreEqual(0, invalidDisposalCount);
    }

    [TestMethod]
    public void RendererLifecycle_TracksRecoveryAndOrderlyShutdown()
    {
        var lifecycle = new RendererLifecycle();
        var states = new List<RendererLifecycleState>();
        lifecycle.StatusChanged += (_, status) => states.Add(status.State);

        lifecycle.BeginInitialization();
        lifecycle.MarkReady();
        lifecycle.BeginRecovery("DXGI_ERROR_DEVICE_REMOVED", "Recovering the graphics device.");
        lifecycle.MarkReady("Preview restored.");
        lifecycle.BeginStopping();
        lifecycle.MarkStopped();

        CollectionAssert.AreEqual(
            new[]
            {
                RendererLifecycleState.Initializing,
                RendererLifecycleState.Ready,
                RendererLifecycleState.Recovering,
                RendererLifecycleState.Ready,
                RendererLifecycleState.Stopping,
                RendererLifecycleState.Stopped
            },
            states);
        Assert.AreEqual(RendererLifecycleState.Stopped, lifecycle.Status.State);
    }

    [TestMethod]
    public void RendererLifecycle_RejectsInvalidTransitions()
    {
        var lifecycle = new RendererLifecycle();

        Assert.ThrowsExactly<InvalidOperationException>(() => lifecycle.MarkReady());
    }

    private static OwnedCpuFrame CreateFrame(
        byte[] bytes,
        int width,
        int height,
        int stride,
        FramePixelFormat pixelFormat,
        FrameOrientation orientation = FrameOrientation.TopDown)
    {
        var owner = new TestMemoryOwner(bytes.Length);
        bytes.CopyTo(owner.Memory);
        return OwnedCpuFrame.Create(owner, bytes.Length, width, height, stride, pixelFormat, orientation);
    }

    private sealed class TestMemoryOwner(int length) : IMemoryOwner<byte>
    {
        private byte[]? _buffer = new byte[length];

        public bool IsDisposed => _buffer is null;

        public Memory<byte> Memory => _buffer ?? throw new ObjectDisposedException(nameof(TestMemoryOwner));

        public void Dispose()
        {
            _buffer = null;
        }
    }

    private sealed class DisposableItem : IDisposable
    {
        public bool IsDisposed { get; private set; }

        public void Dispose()
        {
            IsDisposed = true;
        }
    }

    private sealed class ConcurrentDisposableItem : IDisposable
    {
        private int _disposeCount;

        public int DisposeCount => Volatile.Read(ref _disposeCount);

        public void Dispose()
        {
            Interlocked.Increment(ref _disposeCount);
        }
    }
}
