using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class SerializedAsyncOperationTests
{
  [TestMethod]
  public async Task ReloadWaitsForCanceledRefreshThenRuns()
  {
    SerializedAsyncOperation operations = new();
    TaskCompletionSource response = new(TaskCreationOptions.RunContinuationsAsynchronously);
    using CancellationTokenSource oldPage = new();
    bool reloaded = false;
    Task old = operations.RunAsync(async () =>
    {
      await response.Task; // Deliberately ignores transport cancellation.
      oldPage.Token.ThrowIfCancellationRequested();
    }, oldPage.Token);
    oldPage.Cancel();
    Task reload = operations.RunAsync(() => { reloaded = true; return Task.CompletedTask; });
    Assert.IsFalse(reloaded);
    response.SetResult();
    await Assert.ThrowsAsync<OperationCanceledException>(() => old);
    await reload.WaitAsync(TimeSpan.FromSeconds(2));
    Assert.IsTrue(reloaded);
  }

  [TestMethod]
  public async Task UnloadCleanupCompletesBeforeNewPreviewConfiguration()
  {
    SerializedAsyncOperation operations = new();
    TaskCompletionSource closeDevice = new(TaskCreationOptions.RunContinuationsAsynchronously);
    List<string> events = [];
    Task cleanup = operations.RunAsync(async () =>
    {
      await closeDevice.Task;
      events.Add("stop");
    });
    Task reload = operations.RunAsync(() => { events.Add("configure"); return Task.CompletedTask; });
    Assert.IsEmpty(events);
    closeDevice.SetResult();
    await Task.WhenAll(cleanup, reload).WaitAsync(TimeSpan.FromSeconds(2));
    CollectionAssert.AreEqual(new[] { "stop", "configure" }, events);
  }

  [TestMethod]
  public async Task CanceledQueuedLoadDoesNotBlockLaterLoad()
  {
    SerializedAsyncOperation operations = new();
    TaskCompletionSource completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    Task running = operations.RunAsync(() => completion.Task);
    using CancellationTokenSource cancellation = new();
    Task canceled = operations.RunAsync(() => throw new AssertFailedException("Canceled load ran"), cancellation.Token);
    cancellation.Cancel();
    await Assert.ThrowsAsync<OperationCanceledException>(() => canceled);
    completion.SetResult();
    await running;
    await operations.RunAsync(() => Task.CompletedTask).WaitAsync(TimeSpan.FromSeconds(2));
  }
}
