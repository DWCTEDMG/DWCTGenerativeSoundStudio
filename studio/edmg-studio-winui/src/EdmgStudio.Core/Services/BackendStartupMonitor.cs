using System.Diagnostics;

namespace EdmgStudio.Core.Services;

internal enum BackendStartupMonitorResult
{
    Ready,
    ProcessExited,
    TimedOut
}

internal static class BackendStartupMonitor
{
    public static async Task<BackendStartupMonitorResult> WaitAsync(
        Func<CancellationToken, Task<bool>> healthProbe,
        Func<bool> hasProcessExited,
        TimeSpan timeout,
        TimeSpan pollInterval,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(healthProbe);
        ArgumentNullException.ThrowIfNull(hasProcessExited);

        if (timeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(timeout));
        }

        if (pollInterval <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(pollInterval));
        }

        var stopwatch = Stopwatch.StartNew();
        while (stopwatch.Elapsed < timeout)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (hasProcessExited())
            {
                return BackendStartupMonitorResult.ProcessExited;
            }

            if (await healthProbe(cancellationToken).ConfigureAwait(false))
            {
                return BackendStartupMonitorResult.Ready;
            }

            var remaining = timeout - stopwatch.Elapsed;
            if (remaining <= TimeSpan.Zero)
            {
                break;
            }

            await Task.Delay(
                    remaining < pollInterval ? remaining : pollInterval,
                    cancellationToken)
                .ConfigureAwait(false);
        }

        return BackendStartupMonitorResult.TimedOut;
    }
}
