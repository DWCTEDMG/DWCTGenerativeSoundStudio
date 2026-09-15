using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioJobsActivityServiceTests
{
    [TestMethod]
    public async Task ConcurrentRefreshesShareOneApiRequest()
    {
        var client = new BlockingJobsClient();
        await using var service = new StudioJobsActivityService(client);

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
        var client = new ImmediateJobsClient(new StudioJobListResponse([job]));
        await using var service = new StudioJobsActivityService(client);
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
        var client = new SequenceJobsClient(
            new StudioJobListResponse([CreateJob("job-1", "project-1")]),
            new HttpRequestException("offline"),
            new HttpRequestException("still offline"));
        await using var service = new StudioJobsActivityService(
            client,
            TimeSpan.FromMilliseconds(10),
            TimeSpan.FromMilliseconds(100));

        await service.RefreshAsync();
        await service.RefreshAsync();
        StudioJobsActivitySnapshot firstFailure = service.Snapshot;
        await service.RefreshAsync();
        StudioJobsActivitySnapshot secondFailure = service.Snapshot;

        Assert.AreEqual("job-1", secondFailure.Jobs.Single().Id);
        Assert.IsInstanceOfType<HttpRequestException>(firstFailure.Error);
        Assert.AreEqual(TimeSpan.FromMilliseconds(10), firstFailure.NextRefreshDelay);
        Assert.AreEqual(TimeSpan.FromMilliseconds(20), secondFailure.NextRefreshDelay);
    }

    [TestMethod]
    public async Task CallerCanCancelWaitingWithoutCancelingSharedRefresh()
    {
        var client = new BlockingJobsClient();
        await using var service = new StudioJobsActivityService(client);
        Task shared = service.RefreshAsync();
        await client.RequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));
        using var cancellation = new CancellationTokenSource();
        Task canceledWait = service.RefreshAsync(cancellation.Token);

        cancellation.Cancel();
        await Assert.ThrowsExactlyAsync<TaskCanceledException>(async () => await canceledWait);
        client.Complete(new StudioJobListResponse([]));
        await shared;

        Assert.IsTrue(service.Snapshot.IsAvailable);
        Assert.AreEqual(1, client.RequestCount);
    }

    [TestMethod]
    public async Task DisposeCancelsAnInFlightRefresh()
    {
        var client = new CancelableJobsClient();
        var service = new StudioJobsActivityService(client);
        using IDisposable lease = service.Activate();
        await client.RequestStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

        await service.DisposeAsync();

        await client.RequestCanceled.Task.WaitAsync(TimeSpan.FromSeconds(2));
    }

    private static StudioJob CreateJob(string id, string projectId) => new(
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

    private sealed class ImmediateJobsClient(StudioJobListResponse response) : IStudioJobsClient
    {
        public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(response);

        public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default) =>
            Task.FromResult(response);
    }

    private sealed class BlockingJobsClient : IStudioJobsClient
    {
        private readonly TaskCompletionSource<StudioJobListResponse> _completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _requestCount;

        public TaskCompletionSource RequestStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public int RequestCount => Volatile.Read(ref _requestCount);

        public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
        {
            Interlocked.Increment(ref _requestCount);
            RequestStarted.TrySetResult();
            return _completion.Task.WaitAsync(cancellationToken);
        }

        public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default) =>
            GetJobsAsync(cancellationToken);

        public void Complete(StudioJobListResponse response) => _completion.TrySetResult(response);
    }

    private sealed class CancelableJobsClient : IStudioJobsClient
    {
        public TaskCompletionSource RequestStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource RequestCanceled { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public async Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default)
        {
            RequestStarted.TrySetResult();
            try
            {
                await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                throw new InvalidOperationException("The infinite delay completed unexpectedly.");
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                RequestCanceled.TrySetResult();
                throw;
            }
        }

        public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default) =>
            GetJobsAsync(cancellationToken);
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

        public Task<StudioJobListResponse> GetProjectJobsAsync(string projectId, CancellationToken cancellationToken = default) =>
            GetJobsAsync(cancellationToken);
    }
}
