namespace EdmgStudio.Core.Services;

/// <summary>Orders asynchronous operations that own the same mutable resource.</summary>
public sealed class SerializedAsyncOperation
{
  private readonly SemaphoreSlim _gate = new(1, 1);

  public async Task RunAsync(Func<Task> operation, CancellationToken cancellationToken = default)
  {
    await _gate.WaitAsync(cancellationToken);
    try
    {
      cancellationToken.ThrowIfCancellationRequested();
      await operation();
    }
    finally
    {
      _gate.Release();
    }
  }
}
