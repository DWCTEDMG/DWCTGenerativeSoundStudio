namespace EdmgStudio.Core.Graphics;

public enum RendererLifecycleState
{
    Detached,
    Initializing,
    Ready,
    Recovering,
    Faulted,
    Stopping,
    Stopped
}

public sealed record RendererStatus(RendererLifecycleState State, string Message, string? FailureCode = null);

public sealed class RendererLifecycle
{
    private readonly object _sync = new();
    private RendererStatus _status = new(RendererLifecycleState.Detached, "Preview surface is detached.");

    public event EventHandler<RendererStatus>? StatusChanged;

    public RendererStatus Status
    {
        get
        {
            lock (_sync)
            {
                return _status;
            }
        }
    }

    public void BeginInitialization() =>
        Transition(
            [RendererLifecycleState.Detached, RendererLifecycleState.Stopped, RendererLifecycleState.Faulted],
            new RendererStatus(RendererLifecycleState.Initializing, "Initializing the graphics device."));

    public void MarkReady(string message = "Preview renderer is ready.") =>
        Transition(
            [RendererLifecycleState.Initializing, RendererLifecycleState.Recovering],
            new RendererStatus(RendererLifecycleState.Ready, message));

    public void BeginRecovery(string failureCode, string message) =>
        Transition(
            [RendererLifecycleState.Ready, RendererLifecycleState.Initializing],
            new RendererStatus(RendererLifecycleState.Recovering, message, failureCode));

    public void MarkFaulted(string failureCode, string message) =>
        Transition(
            [
                RendererLifecycleState.Detached,
                RendererLifecycleState.Initializing,
                RendererLifecycleState.Ready,
                RendererLifecycleState.Recovering
            ],
            new RendererStatus(RendererLifecycleState.Faulted, message, failureCode));

    public void BeginStopping() =>
        Transition(
            [
                RendererLifecycleState.Detached,
                RendererLifecycleState.Initializing,
                RendererLifecycleState.Ready,
                RendererLifecycleState.Recovering,
                RendererLifecycleState.Faulted
            ],
            new RendererStatus(RendererLifecycleState.Stopping, "Stopping the preview renderer."));

    public void MarkStopped() =>
        Transition(
            [RendererLifecycleState.Stopping],
            new RendererStatus(RendererLifecycleState.Stopped, "Preview renderer is stopped."));

    private void Transition(RendererLifecycleState[] allowedStates, RendererStatus next)
    {
        EventHandler<RendererStatus>? handler;
        lock (_sync)
        {
            if (!allowedStates.Contains(_status.State))
            {
                throw new InvalidOperationException(
                    $"Renderer cannot transition from {_status.State} to {next.State}.");
            }

            _status = next;
            handler = StatusChanged;
        }

        handler?.Invoke(this, next);
    }
}
