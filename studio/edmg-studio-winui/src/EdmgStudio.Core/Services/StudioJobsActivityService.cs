using System.Collections.Immutable;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Services;

public interface IStudioJobsClient
{
    Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default);

    Task<StudioJobListResponse> GetProjectJobsAsync(
        string projectId,
        CancellationToken cancellationToken = default);
}

public sealed record StudioJobsActivitySnapshot(
    ImmutableArray<StudioJob> Jobs,
    DateTimeOffset UpdatedAt,
    Exception? Error,
    TimeSpan NextRefreshDelay)
{
    public static StudioJobsActivitySnapshot Empty { get; } = new(
        [],
        DateTimeOffset.MinValue,
        null,
        TimeSpan.Zero);

    public bool IsAvailable => Error is null && UpdatedAt != DateTimeOffset.MinValue;
}

public sealed class StudioJobsActivityService : IAsyncDisposable
{
    private static readonly TimeSpan DefaultRefreshInterval = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan DefaultMaximumBackoff = TimeSpan.FromSeconds(30);

    private readonly IStudioJobsClient _client;
    private readonly TimeSpan _refreshInterval;
    private readonly TimeSpan _maximumBackoff;
    private readonly object _lifecycleSync = new();
    private readonly object _refreshSync = new();
    private readonly CancellationTokenSource _lifetimeCancellation = new();
    private CancellationTokenSource? _loopCancellation;
    private Task? _loopTask;
    private Task? _refreshTask;
    private StudioJobsActivitySnapshot _snapshot = StudioJobsActivitySnapshot.Empty;
    private int _subscriberCount;
    private int _consecutiveFailures;
    private bool _disposed;

    public StudioJobsActivityService(
        IStudioJobsClient client,
        TimeSpan? refreshInterval = null,
        TimeSpan? maximumBackoff = null)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _refreshInterval = ValidateDelay(refreshInterval ?? DefaultRefreshInterval, nameof(refreshInterval));
        _maximumBackoff = ValidateDelay(maximumBackoff ?? DefaultMaximumBackoff, nameof(maximumBackoff));
        if (_maximumBackoff < _refreshInterval)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumBackoff), "Maximum backoff must not be shorter than the refresh interval.");
        }
    }

    public event EventHandler<StudioJobsActivitySnapshot>? SnapshotChanged;

    public StudioJobsActivitySnapshot Snapshot => Volatile.Read(ref _snapshot);

    public IDisposable Activate()
    {
        lock (_lifecycleSync)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _subscriberCount++;
            if (_subscriberCount == 1)
            {
                CancellationTokenSource? previousCancellation = _loopCancellation;
                Task? previousLoop = _loopTask;
                _loopCancellation = new CancellationTokenSource();
                _loopTask = RunLoopAfterAsync(previousLoop, previousCancellation, _loopCancellation.Token);
            }
        }

        return new ActivityLease(this);
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        Task refreshTask;
        lock (_refreshSync)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_refreshTask is null || _refreshTask.IsCompleted)
            {
                _refreshTask = RefreshCoreAsync();
            }

            refreshTask = _refreshTask;
        }

        await refreshTask.WaitAsync(cancellationToken).ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        Task? loopTask;
        lock (_lifecycleSync)
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            _subscriberCount = 0;
            _lifetimeCancellation.Cancel();
            _loopCancellation?.Cancel();
            loopTask = _loopTask;
        }

        if (loopTask is not null)
        {
            try
            {
                await loopTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }

        lock (_lifecycleSync)
        {
            _loopCancellation?.Dispose();
            _loopCancellation = null;
            _loopTask = null;
        }

        _lifetimeCancellation.Dispose();
    }

    private async Task RunLoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await RefreshAsync(cancellationToken).ConfigureAwait(false);
                await Task.Delay(Snapshot.NextRefreshDelay, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                return;
            }
        }
    }

    private async Task RunLoopAfterAsync(
        Task? previousLoop,
        CancellationTokenSource? previousCancellation,
        CancellationToken cancellationToken)
    {
        if (previousLoop is not null)
        {
            try
            {
                await previousLoop.ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (previousCancellation?.IsCancellationRequested == true)
            {
            }
            finally
            {
                previousCancellation?.Dispose();
            }
        }

        cancellationToken.ThrowIfCancellationRequested();
        await RunLoopAsync(cancellationToken).ConfigureAwait(false);
    }

    private async Task RefreshCoreAsync()
    {
        StudioJobsActivitySnapshot next;
        try
        {
            StudioJobListResponse response = await _client.GetJobsAsync(_lifetimeCancellation.Token).ConfigureAwait(false);
            _consecutiveFailures = 0;
            next = new StudioJobsActivitySnapshot(
                response.Jobs.ToImmutableArray(),
                DateTimeOffset.UtcNow,
                null,
                _refreshInterval);
        }
        catch (Exception exception)
        {
            _consecutiveFailures = Math.Min(_consecutiveFailures + 1, 30);
            double multiplier = Math.Pow(2, Math.Min(_consecutiveFailures - 1, 10));
            TimeSpan delay = TimeSpan.FromTicks(Math.Min(
                (long)(_refreshInterval.Ticks * multiplier),
                _maximumBackoff.Ticks));
            StudioJobsActivitySnapshot previous = Snapshot;
            next = previous with
            {
                Error = exception,
                NextRefreshDelay = delay
            };
        }

        Volatile.Write(ref _snapshot, next);
        SnapshotChanged?.Invoke(this, next);
    }

    private void Deactivate()
    {
        lock (_lifecycleSync)
        {
            if (_subscriberCount == 0)
            {
                return;
            }

            _subscriberCount--;
            if (_subscriberCount == 0)
            {
                _loopCancellation?.Cancel();
            }
        }
    }

    private static TimeSpan ValidateDelay(TimeSpan delay, string parameterName)
    {
        if (delay <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(parameterName, "Refresh delays must be positive.");
        }

        return delay;
    }

    private sealed class ActivityLease(StudioJobsActivityService owner) : IDisposable
    {
        private StudioJobsActivityService? _owner = owner;

        public void Dispose() => Interlocked.Exchange(ref _owner, null)?.Deactivate();
    }
}
