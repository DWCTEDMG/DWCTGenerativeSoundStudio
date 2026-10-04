using EdmgStudio.Core.Graphics;
using System.Buffers;
using System.Collections.Concurrent;

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
    _ = Assert.Throws<ArgumentException>(
        () => FrameLayout.Validate(width, height, stride, sourceLength));
  }

  [TestMethod]
  public void FrameLayout_UsesTheLastPixelRatherThanRequiringTrailingRowPadding()
  {
    FrameLayout layout = FrameLayout.Validate(width: 2, height: 2, stride: 12, sourceLength: 20);

    Assert.AreEqual(8, layout.RowBytes);
    Assert.AreEqual(20, layout.MinimumSourceLength);
    Assert.AreEqual(16, layout.TightBufferLength);
  }

  [TestMethod]
  public void FrameLayout_RejectsBuffersAboveTheDecodedMemoryLimit()
  {
    _ = Assert.ThrowsExactly<ArgumentException>(
        () => FrameLayout.Validate(16_384, 16_384, 65_536, int.MaxValue));
  }

  [TestMethod]
  public void FrameLayout_RejectsStrideOverflowAfterValidatingTheStride()
  {
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => FrameLayout.Validate(1, 2, int.MinValue, 4));
    _ = Assert.ThrowsExactly<ArgumentException>(
        () => FrameLayout.Validate(1, 3, int.MaxValue, int.MaxValue));
  }

  [TestMethod]
  public void FrameLayout_RejectsNegativeSourceLength()
  {
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => FrameLayout.Validate(1, 1, 4, -1));
  }

  [TestMethod]
  public void OwnedFrame_DisposesTransferredOwnershipWhenValidationFails()
  {
    TestMemoryOwner owner = new(4);

    _ = Assert.ThrowsExactly<ArgumentException>(
        () => OwnedCpuFrame.Create(owner, 4, width: 2, height: 1, stride: 8, FramePixelFormat.Bgra8));
    Assert.IsTrue(owner.IsDisposed);
  }

  [TestMethod]
  public void CopyToBgra_PassesThroughBgraAndRemovesPaddedRows()
  {
    using OwnedCpuFrame frame = CreateFrame(
        [
            1, 2, 3, 4, 5, 6, 7, 8, 99, 99, 99, 99,
                9, 10, 11, 12, 13, 14, 15, 16
        ],
        width: 2,
        height: 2,
        stride: 12,
        FramePixelFormat.Bgra8);
    byte[] destination = new byte[16];

    frame.CopyToBgra(destination);

    CollectionAssert.AreEqual(
        new byte[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 },
        destination);
  }

  [TestMethod]
  public void CopyToBgra_ConvertsRgbaAndFlipsBottomUpOrientation()
  {
    using OwnedCpuFrame frame = CreateFrame(
        [
            10, 20, 30, 40,
                50, 60, 70, 80
        ],
        width: 1,
        height: 2,
        stride: 4,
        FramePixelFormat.Rgba8,
        FrameOrientation.BottomUp);
    byte[] destination = new byte[8];

    frame.CopyToBgra(destination);

    CollectionAssert.AreEqual(
        new byte[] { 70, 60, 50, 80, 30, 20, 10, 40 },
        destination);
  }

  [TestMethod]
  public void CopyRowToBgra_ConvertsOnlyTheRequestedLogicalRow()
  {
    using OwnedCpuFrame frame = CreateFrame(
        [
            1, 2, 3, 4, 99, 99, 99, 99,
                10, 20, 30, 40
        ],
        width: 1,
        height: 2,
        stride: 8,
        FramePixelFormat.Rgba8,
        FrameOrientation.BottomUp);
    byte[] destination = new byte[] { 255, 255, 255, 255, 77 };

    frame.CopyRowToBgra(0, destination);

    CollectionAssert.AreEqual(new byte[] { 30, 20, 10, 40, 77 }, destination);
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => frame.CopyRowToBgra(2, destination));
    _ = Assert.ThrowsExactly<ArgumentException>(
        () => frame.CopyRowToBgra(0, new byte[3]));
  }

  [TestMethod]
  public void PreviewGeometry_CentersAspectFitWithLetterboxing()
  {
    PreviewRectangle rectangle = PreviewGeometry.CalculateAspectFit(1920, 1080, 1000, 1000);

    Assert.AreEqual(0.0f, rectangle.X, 0.001f);
    Assert.AreEqual(218.75f, rectangle.Y, 0.001f);
    Assert.AreEqual(1000.0f, rectangle.Width, 0.001f);
    Assert.AreEqual(562.5f, rectangle.Height, 0.001f);
  }

  [TestMethod]
  public void PreviewGeometry_CalculatesFillAndActualSizePresentations()
  {
    PreviewRectangle fill = PreviewGeometry.CalculatePresentation(
        1920, 1080, 1000, 1000, PreviewDisplayMode.Fill);
    PreviewRectangle actual = PreviewGeometry.CalculatePresentation(
        1920, 1080, 1000, 1000, PreviewDisplayMode.ActualSize);

    Assert.AreEqual(-388.889f, fill.X, 0.001f);
    Assert.AreEqual(0.0f, fill.Y, 0.001f);
    Assert.AreEqual(1777.778f, fill.Width, 0.001f);
    Assert.AreEqual(1000.0f, fill.Height, 0.001f);
    Assert.AreEqual(-460.0f, actual.X, 0.001f);
    Assert.AreEqual(-40.0f, actual.Y, 0.001f);
    Assert.AreEqual(1920.0f, actual.Width, 0.001f);
    Assert.AreEqual(1080.0f, actual.Height, 0.001f);
  }

  [TestMethod]
  public void PreviewGeometry_CalculatesSafeAreaWithinPresentedFrame()
  {
    PreviewRectangle frame = new(100, 50, 800, 450);

    PreviewRectangle safeArea = PreviewGeometry.CalculateSafeArea(frame, 0.1);

    Assert.AreEqual(new PreviewRectangle(180, 95, 640, 360), safeArea);
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => PreviewGeometry.CalculateSafeArea(frame, 0.5));
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
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => PreviewGeometry.ToPhysicalPixels(double.NaN, 480, 1));
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => PreviewGeometry.ToPhysicalPixels(640, double.PositiveInfinity, 1));
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(
        () => PreviewGeometry.ToPhysicalPixels(640, 480, 0));
    _ = Assert.ThrowsExactly<OverflowException>(
        () => PreviewGeometry.ToPhysicalPixels(int.MaxValue, int.MaxValue, 2));
  }

  [TestMethod]
  public async Task LatestFrameMailbox_ReplacesAndDisposesTheStaleFrame()
  {
    using LatestFrameMailbox<DisposableItem> mailbox = new();
    DisposableItem stale = new();
    DisposableItem latest = new();

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
    using LatestFrameMailbox<DisposableItem> mailbox = new();
    using CancellationTokenSource cancellation = new();
    cancellation.Cancel();

    try
    {
      _ = await mailbox.TakeAsync(cancellation.Token);
      Assert.Fail("The canceled mailbox read should not complete successfully.");
    }
    catch (OperationCanceledException exception)
    {
      Assert.AreEqual(cancellation.Token, exception.CancellationToken);
    }

    mailbox.Complete();
    Assert.IsNull(await mailbox.TakeAsync());

    DisposableItem rejected = new();
    Assert.IsFalse(mailbox.TryPublish(rejected));
    Assert.IsTrue(rejected.IsDisposed);
  }

  [TestMethod]
  public async Task LatestFrameMailbox_CompletionDisposesAQueuedFrameAndWakesAReader()
  {
    using LatestFrameMailbox<DisposableItem> mailbox = new();
    DisposableItem queued = new();
    Assert.IsTrue(mailbox.TryPublish(queued));

    mailbox.Complete();

    Assert.IsTrue(queued.IsDisposed);
    Assert.IsNull(await mailbox.TakeAsync());
  }

  [TestMethod]
  public async Task LatestFrameMailbox_CompletionWakesAnAlreadyWaitingReader()
  {
    using LatestFrameMailbox<DisposableItem> mailbox = new();
    Task<DisposableItem?> waiting = mailbox.TakeAsync().AsTask();

    mailbox.Complete();

    Assert.IsNull(await waiting.WaitAsync(TimeSpan.FromSeconds(1)));
  }

  [TestMethod]
  public void LatestFrameMailbox_TryTakeConsumesOnlyTheLatestFrame()
  {
    using LatestFrameMailbox<DisposableItem> mailbox = new();
    DisposableItem first = new();
    DisposableItem latest = new();

    Assert.IsFalse(mailbox.TryTake(out DisposableItem? empty));
    Assert.IsNull(empty);
    Assert.IsTrue(mailbox.TryPublish(first));
    Assert.IsTrue(mailbox.TryPublish(latest));
    Assert.IsTrue(first.IsDisposed);

    Assert.IsTrue(mailbox.TryTake(out DisposableItem? taken));
    Assert.AreSame(latest, taken);
    Assert.IsFalse(mailbox.TryTake(out empty));
    Assert.IsNull(empty);
    taken!.Dispose();
  }

  [TestMethod]
  public async Task LatestFrameMailbox_ConcurrentPublishAndTake_DisposesEveryFrameExactlyOnce()
  {
    const int frameCount = 4_096;
    using LatestFrameMailbox<ConcurrentDisposableItem> mailbox = new();
    ConcurrentDisposableItem[] frames = Enumerable.Range(0, frameCount)
        .Select(_ => new ConcurrentDisposableItem())
        .ToArray();

    Task consumer = Task.Run(async () =>
        {
          while (await mailbox.TakeAsync() is { } frame)
          {
            frame.Dispose();
          }
        });

    Task producer = Task.Run(() =>
        {
          foreach (ConcurrentDisposableItem? frame in frames)
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
    using Barrier start = new(3);
    using Barrier finish = new(3);
    ConcurrentQueue<Exception> errors = new();
    LatestFrameMailbox<ConcurrentDisposableItem>? mailbox = null;
    ConcurrentDisposableItem? frame = null;

    Thread publisher = new(() =>
        {
          for (int index = 0; index < iterationCount; index++)
          {
            start.SignalAndWait();
            try
            {
              _ = mailbox!.TryPublish(frame!);
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

    Thread completer = new(() =>
        {
          for (int index = 0; index < iterationCount; index++)
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

    int invalidDisposalCount = 0;
    for (int index = 0; index < iterationCount; index++)
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
    RendererLifecycle lifecycle = new();
    List<RendererLifecycleState> states = [];
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
    RendererLifecycle lifecycle = new();

    _ = Assert.ThrowsExactly<InvalidOperationException>(() => lifecycle.MarkReady());
  }

  private static OwnedCpuFrame CreateFrame(
      byte[] bytes,
      int width,
      int height,
      int stride,
      FramePixelFormat pixelFormat,
      FrameOrientation orientation = FrameOrientation.TopDown)
  {
    TestMemoryOwner owner = new(bytes.Length);
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
      _ = Interlocked.Increment(ref _disposeCount);
    }
  }
}
