namespace EdmgStudio.Core.Models;

public enum ExecutionReadinessTone { Ready, Warning, Blocked }
public sealed record ExecutionReadinessPresentation(ExecutionReadinessTone Tone, string Title, string Detail);

public static class ExecutionPlanePresentation
{
    public static ExecutionReadinessPresentation Describe(ExecutionInventory inventory)
    {
        ExecutionReadiness state = inventory.Wsl.Readiness;
        if (state.RuntimeQualified) return new(ExecutionReadinessTone.Ready, "Runtime qualified", "A validated generation receipt is available.");
        if (state.WorkerLaunchable) return new(ExecutionReadinessTone.Warning, "Worker launchable", "The worker can start, but this runtime is not yet artifact-qualified.");
        if (state.ModelInstalled) return new(ExecutionReadinessTone.Warning, "Model installed", "The model is present, but the WSL worker cannot launch yet.");
        return new(ExecutionReadinessTone.Blocked, "WSL execution blocked", inventory.Blockers.FirstOrDefault()?.Message ?? "Configure the optional WSL worker to use Linux models.");
    }
}
