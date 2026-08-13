using System.Diagnostics;

namespace EdmgStudio.Core.Models;

public enum BackendMode
{
    ManagedSource,
    ManagedPackaged,
    External,
    Attached
}

public enum BackendLifecycleState
{
    Stopped,
    Resolving,
    CheckingExisting,
    Starting,
    WaitingForHealth,
    Ready,
    Unavailable,
    Failed,
    Stopping
}

public sealed record BackendStatus(
    BackendLifecycleState State,
    BackendMode Mode,
    Uri CurrentBackendUri,
    string Message,
    string? Detail = null,
    int? OwnedProcessId = null,
    string? AcceleratorProfile = null,
    DateTimeOffset? StartedAt = null,
    DateTimeOffset? LastHealthCheck = null,
    string? FailureCode = null,
    string? StdoutLogPath = null,
    string? StderrLogPath = null)
{
    public bool IsReady => State == BackendLifecycleState.Ready;
    public bool OwnsProcess => OwnedProcessId is not null;
}

public sealed record BackendLaunchSpec(
    BackendMode Mode,
    string FileName,
    IReadOnlyList<string> Arguments,
    string WorkingDirectory,
    IReadOnlyDictionary<string, string> Environment,
    string StdoutLogPath,
    string StderrLogPath,
    string AcceleratorProfile)
{
    public ProcessStartInfo CreateProcessStartInfo()
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = FileName,
            WorkingDirectory = WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = false
        };

        foreach (var argument in Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        foreach (var pair in Environment)
        {
            startInfo.Environment[pair.Key] = pair.Value;
        }

        return startInfo;
    }
}
