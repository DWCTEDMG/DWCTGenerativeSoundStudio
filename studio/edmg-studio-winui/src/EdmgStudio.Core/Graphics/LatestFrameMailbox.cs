namespace EdmgStudio.Core.Graphics;

public sealed class LatestFrameMailbox<T> : IDisposable
    where T : class, IDisposable
{
    private readonly object _sync = new();
    private readonly SemaphoreSlim _available = new(0, 1);
    private T? _item;
    private bool _completed;

    public bool TryPublish(T item)
    {
        ArgumentNullException.ThrowIfNull(item);

        T? replaced = null;
        var published = false;
        lock (_sync)
        {
            if (_completed)
            {
                replaced = item;
            }
            else
            {
                replaced = _item;
                var shouldSignal = _item is null && _available.CurrentCount == 0;
                _item = item;
                published = true;

                // Publish the permit while holding the state lock. Otherwise a
                // concurrent completion can publish its own permit first and
                // overflow this capacity-one semaphore.
                if (shouldSignal)
                {
                    _available.Release();
                }
            }
        }

        replaced?.Dispose();
        return published;
    }

    public async ValueTask<T?> TakeAsync(CancellationToken cancellationToken = default)
    {
        await _available.WaitAsync(cancellationToken).ConfigureAwait(false);

        lock (_sync)
        {
            if (_item is not null)
            {
                var item = _item;
                _item = null;
                return item;
            }

            return null;
        }
    }

    public bool TryTake(out T? item)
    {
        lock (_sync)
        {
            item = _item;
            if (item is null)
            {
                return false;
            }

            _item = null;
            _ = _available.Wait(0);
            return true;
        }
    }

    public void Complete()
    {
        T? remaining;
        lock (_sync)
        {
            if (_completed)
            {
                return;
            }

            _completed = true;
            remaining = _item;
            _item = null;

            // Keep completion and its wake-up permit in the same critical
            // section as the item transition. An outstanding item permit can
            // also wake a consumer to observe completion.
            if (_available.CurrentCount == 0)
            {
                _available.Release();
            }
        }

        remaining?.Dispose();
    }

    public void Dispose()
    {
        Complete();
        _available.Dispose();
    }
}
