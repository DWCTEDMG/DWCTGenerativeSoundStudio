using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class BackendStartupMonitorTests
{
  [TestMethod]
  public async Task WaitAsync_ReturnsReadyAfterDelayedHealth()
  {
    int probes = 0;

    BackendStartupMonitorResult result = await BackendStartupMonitor.WaitAsync(
        _ => Task.FromResult(Interlocked.Increment(ref probes) >= 3),
        () => false,
        TimeSpan.FromSeconds(1),
        TimeSpan.FromMilliseconds(1),
        CancellationToken.None);

    Assert.AreEqual(BackendStartupMonitorResult.Ready, result);
    Assert.IsGreaterThanOrEqualTo(3, probes);
  }

  [TestMethod]
  public async Task WaitAsync_ReturnsWhenProcessExits()
  {
    bool exited = false;
    BackendStartupMonitorResult result = await BackendStartupMonitor.WaitAsync(
        _ =>
        {
          exited = true;
          return Task.FromResult(false);
        },
        () => exited,
        TimeSpan.FromSeconds(1),
        TimeSpan.FromMilliseconds(1),
        CancellationToken.None);

    Assert.AreEqual(BackendStartupMonitorResult.ProcessExited, result);
  }

  [TestMethod]
  public async Task WaitAsync_ReturnsTimedOutWhenHealthNeverSucceeds()
  {
    BackendStartupMonitorResult result = await BackendStartupMonitor.WaitAsync(
        _ => Task.FromResult(false),
        () => false,
        TimeSpan.FromMilliseconds(20),
        TimeSpan.FromMilliseconds(1),
        CancellationToken.None);

    Assert.AreEqual(BackendStartupMonitorResult.TimedOut, result);
  }

  [TestMethod]
  public async Task WaitAsync_ObservesCancellation()
  {
    using CancellationTokenSource cancellation = new();
    cancellation.Cancel();

    _ = await Assert.ThrowsExactlyAsync<OperationCanceledException>(
        () => BackendStartupMonitor.WaitAsync(
            _ => Task.FromResult(false),
            () => false,
            TimeSpan.FromSeconds(1),
            TimeSpan.FromMilliseconds(1),
            cancellation.Token));
  }
}
