using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class AdrCaptureTests
{
  [TestMethod]
  public async Task DeterministicCaptureIsBoundedAndNeverClaimsHardware()
  {
    AdrCaptureCoordinator coordinator = new(new DeterministicAdrCaptureDevice());
    AdrCapturedAudio first = await coordinator.CaptureAsync(new("cue", 48_000, 2, 4));
    AdrCapturedAudio second = await coordinator.CaptureAsync(new("cue", 48_000, 2, 4));
    Assert.IsFalse(coordinator.IsProductionHardwareAvailable);
    Assert.AreEqual(4, first.Frames);
    CollectionAssert.AreEqual(first.InterleavedSamples.ToArray(), second.InterleavedSamples.ToArray());
    StringAssert.Contains(first.Diagnostic, "no production audio hardware");
  }

  [TestMethod]
  public async Task UnavailableDeviceExplicitlyRejectsCapture()
  {
    AdrCaptureCoordinator coordinator = new(new UnavailableAdrCaptureDevice());
    Assert.IsFalse(coordinator.IsProductionHardwareAvailable);
    _ = await Assert.ThrowsExactlyAsync<NotSupportedException>(() => coordinator.CaptureAsync(new("cue", 48_000, 1, 10)));
  }

  [TestMethod]
  public async Task CoordinatorRejectsConcurrentAndInvalidDeviceResults()
  {
    PendingDevice pending = new();
    AdrCaptureCoordinator coordinator = new(pending);
    Task<AdrCapturedAudio> first = coordinator.CaptureAsync(new("cue", 48_000, 1, 10));
    _ = await Assert.ThrowsExactlyAsync<InvalidOperationException>(() => coordinator.CaptureAsync(new("cue", 48_000, 1, 10)));
    pending.Complete(new(44_100, 1, [0], "bad"));
    _ = await Assert.ThrowsExactlyAsync<InvalidDataException>(() => first);
  }

  private sealed class PendingDevice : IAdrCaptureDevice
  {
    private readonly TaskCompletionSource<AdrCapturedAudio> _completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public bool IsHardwareAvailable => false;
    public string AvailabilityDiagnostic => "test";
    public Task<AdrCapturedAudio> CaptureAsync(AdrCaptureRequest request, CancellationToken cancellationToken = default)
    {
      return _completion.Task;
    }

    public void Complete(AdrCapturedAudio value)
    {
      _completion.SetResult(value);
    }
  }
}