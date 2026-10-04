using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioJobsActivityServiceTests
{
  [TestMethod]
  public async Task ConcurrentRefreshesShareOneApiRequest()
  {
    BlockingJobsClient client = new();
    await using StudioJobsActivityService service = new(client);

    Task first = service.RefreshAsync();
    await client.RequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));
    Task second = service.RefreshAsync();

    Assert.AreEqual(1, client.RequestCount);
    client.Complete(new StudioJobListResponse([]));
    await Task.WhenAll(first, second);
    Assert.AreEqual(1, client.RequestCount);
  }

  [TestMethod]
  public async Task SuccessfulRefreshPublishesImmutableSnapshot()
  {
    StudioJob job = CreateJob("job-1", "project-1");
    ImmediateJobsClient client = new(new StudioJobListResponse([job]));
    await using StudioJobsActivityService service = new(client);
    StudioJobsActivitySnapshot? published = null;
    service.SnapshotChanged += (_, snapshot) => published = snapshot;

    await service.RefreshAsync();

    Assert.IsNotNull(published);
    Assert.IsTrue(published.IsAvailable);
    Assert.AreEqual("job-1", published.Jobs.Single().Id);
    Assert.IsNull(published.Error);
    Assert.AreEqual(TimeSpan.FromSeconds(2), published.NextRefreshDelay);
  }

  [TestMethod]
  public async Task FailurePreservesJobsAndBacksOffExponentially()
  {
    SequenceJobsClient client = new(
            new StudioJobListResponse([CreateJob("job-1", "project-1")]),
            new HttpRequestException("offline"),
            new HttpRequestException("still offline"));
    await using StudioJobsActivityService service = new(
        client,
        TimeSpan.FromMilliseconds(10),
        TimeSpan.FromMilliseconds(100));

    await service.RefreshAsync();
    await service.RefreshAsync();
    StudioJobsActivitySnapshot firstFailure = service.Snapshot;
    await service.RefreshAsync();
    StudioJobsActivitySnapshot secondFailure = service.Snapshot;

    Assert.AreEqual("job-1", secondFailure.Jobs.Single().Id);
    _ = Assert.IsInstanceOfType<HttpRequestException>(firstFailure.Error);
    Assert.AreEqual(TimeSpan.FromMilliseconds(10), firstFailure.NextRefreshDelay);
    Assert.AreEqual(TimeSpan.FromMilliseconds(20), secondFailure.NextRefreshDelay);
  }

  [TestMethod]
  public async Task CallerCanCancelWaitingWithoutCancelingSharedRefresh()
  {
    BlockingJobsClient client = new();
    await using StudioJobsActivityService service = new(client);
    Task shared = service.RefreshAsync();
    await client.RequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));
    using CancellationTokenSource cancellation = new();
    Task canceledWait = service.RefreshAsync(cancellation.Token);

    cancellation.Cancel();
    _ = await Assert.ThrowsExactlyAsync<TaskCanceledException>(async () => await canceledWait);
    client.Complete(new StudioJobListResponse([]));
    await shared;

    Assert.IsTrue(service.Snapshot.IsAvailable);
    Assert.AreEqual(1, client.RequestCount);
  }

  [TestMethod]
  public async Task DisposeCancelsAnInFlightRefresh()
  {
    CancelableJobsClient client = new();
    StudioJobsActivityService service = new(client);
    using IDisposable lease = service.Activate();
    await client.RequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

    await service.DisposeAsync();

    await client.RequestCanceled.Task.WaitAsync(TimeSpan.FromSeconds(2));
  }

  [TestMethod]
  public async Task ReleasingFinalLeaseStopsPolling()
  {
    CountingJobsClient client = new();
    await using StudioJobsActivityService service = new(
        client,
        TimeSpan.FromMilliseconds(20),
        TimeSpan.FromMilliseconds(100));
    IDisposable lease = service.Activate();
    await client.WaitForRequestsAsync(2);

    lease.Dispose();
    await Task.Delay(60);
    int settledCount = client.RequestCount;
    await Task.Delay(80);

    Assert.AreEqual(settledCount, client.RequestCount);
  }

  [TestMethod]
  public async Task PollingContinuesUntilLastLeaseIsReleased()
  {
    CountingJobsClient client = new();
    await using StudioJobsActivityService service = new(
        client,
        TimeSpan.FromMilliseconds(20),
        TimeSpan.FromMilliseconds(100));
    IDisposable first = service.Activate();
    IDisposable second = service.Activate();
    await client.WaitForRequestsAsync(1);

    first.Dispose();
    await client.WaitForRequestsAsync(2);
    second.Dispose();
    await Task.Delay(60);
    int settledCount = client.RequestCount;
    await Task.Delay(80);

    Assert.AreEqual(settledCount, client.RequestCount);
  }

  [TestMethod]
  public async Task ReactivationWaitsForPreviousLoopAndDoesNotOverlapRequests()
  {
    ReentryJobsClient client = new();
    await using StudioJobsActivityService service = new(
        client,
        TimeSpan.FromMilliseconds(20),
        TimeSpan.FromMilliseconds(100));
    IDisposable first = service.Activate();
    await client.FirstRequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

    first.Dispose();
    using IDisposable second = service.Activate();
    await Task.Delay(50);
    Assert.AreEqual(1, client.RequestCount);

    client.ReleaseFirstRequest();
    await client.SecondRequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

    Assert.AreEqual(1, client.MaximumConcurrentRequests);
  }

  private static StudioJob CreateJob(string id, string projectId)
  {
    return new(
      id,
      projectId,
      "render",
      "queued",
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null);
  }

  private sealed class ImmediateJobsClient(StudioJobListResponse response) : IStudioJobsClient
  {
    public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
    {
      return Task.FromResult(response);
    }

    public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default)
    {
      return Task.FromResult(response);
    }
  }

  private sealed class BlockingJobsClient : IStudioJobsClient
  {
    private readonly TaskCompletionSource<StudioJobListResponse> _completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int _requestCount;

    public TaskCompletionSource RequestStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public int RequestCount => Volatile.Read(ref _requestCount);

    public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
    {
      _ = Interlocked.Increment(ref _requestCount);
      _ = RequestStarted.TrySetResult();
      return _completion.Task.WaitAsync(cancellationToken);
    }

    public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default)
    {
      return GetJobsAsync(cancellationToken);
    }

    public void Complete(StudioJobListResponse response)
    {
      _ = _completion.TrySetResult(response);
    }
  }

  private sealed class CancelableJobsClient : IStudioJobsClient
  {
    public TaskCompletionSource RequestStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource RequestCanceled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public async Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
    {
      _ = RequestStarted.TrySetResult();
      try
      {
        await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
        throw new InvalidOperationException("The infinite delay completed unexpectedly.");
      }
      catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
      {
        _ = RequestCanceled.TrySetResult();
        throw;
      }
    }

    public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default)
    {
      return GetJobsAsync(cancellationToken);
    }
  }

  private sealed class CountingJobsClient : IStudioJobsClient
  {
    private int _requestCount;

    public int RequestCount => Volatile.Read(ref _requestCount);

    public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
    {
      cancellationToken.ThrowIfCancellationRequested();
      _ = Interlocked.Increment(ref _requestCount);
      return Task.FromResult(new StudioJobListResponse([]));
    }

    public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default)
    {
      return GetJobsAsync(cancellationToken);
    }

    public async Task WaitForRequestsAsync(int count)
    {
      using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(2));
      while (RequestCount < count)
      {
        await Task.Delay(5, timeout.Token);
      }
    }
  }

  private sealed class ReentryJobsClient : IStudioJobsClient
  {
    private readonly TaskCompletionSource _releaseFirst = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int _activeRequests;
    private int _maximumConcurrentRequests;
    private int _requestCount;

    public TaskCompletionSource FirstRequestStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource SecondRequestStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public int RequestCount => Volatile.Read(ref _requestCount);
    public int MaximumConcurrentRequests => Volatile.Read(ref _maximumConcurrentRequests);

    public async Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
    {
      int active = Interlocked.Increment(ref _activeRequests);
      UpdateMaximum(active);
      int request = Interlocked.Increment(ref _requestCount);
      try
      {
        if (request == 1)
        {
          _ = FirstRequestStarted.TrySetResult();
          await _releaseFirst.Task.WaitAsync(cancellationToken);
        }
        else if (request == 2)
        {
          _ = SecondRequestStarted.TrySetResult();
        }

        return new StudioJobListResponse([]);
      }
      finally
      {
        _ = Interlocked.Decrement(ref _activeRequests);
      }
    }

    public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default)
    {
      return GetJobsAsync(cancellationToken);
    }

    public void ReleaseFirstRequest()
    {
      _ = _releaseFirst.TrySetResult();
    }

    private void UpdateMaximum(int candidate)
    {
      int current;
      while (candidate > (current = Volatile.Read(ref _maximumConcurrentRequests)) &&
             Interlocked.CompareExchange(ref _maximumConcurrentRequests, candidate, current) != current)
      {
      }
    }
  }

  private sealed class SequenceJobsClient(params object[] results) : IStudioJobsClient
  {
    private readonly Queue<object> _results = new(results);

    public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
    {
      cancellationToken.ThrowIfCancellationRequested();
      object result = _results.Dequeue();
      return result is Exception exception
          ? Task.FromException<StudioJobListResponse>(exception)
          : Task.FromResult((StudioJobListResponse)result);
    }

    public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default)
    {
      return GetJobsAsync(cancellationToken);
    }
  }
}
