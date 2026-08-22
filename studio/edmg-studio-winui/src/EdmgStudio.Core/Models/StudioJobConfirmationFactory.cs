namespace EdmgStudio.Core.Models;

public enum StudioJobConfirmationAction
{
    Resume,
    Retry,
    ResumeFromCheckpoint,
    RestartClean,
    ClearCachedFrames,
    DropCheckpoint,
}

public sealed record StudioActionConfirmation(
    string Title,
    string Message,
    string PrimaryButtonText);

public static class StudioJobConfirmationFactory
{
    public static StudioActionConfirmation CreateRecoveryConsent(
        StudioJob job,
        StudioJobConfirmationAction action)
    {
        ArgumentNullException.ThrowIfNull(job);

        string jobLabel = DescribeJob(job);
        string checkpointLabel = $"saved checkpoint for {jobLabel}";
        return action switch
        {
            StudioJobConfirmationAction.Resume => new StudioActionConfirmation(
                $"Resume {jobLabel}?",
                $"The exact action \"Resume\" will continue {jobLabel}. Studio will not auto-resume this job; select Resume only if you want to continue it now.",
                "Resume"),
            StudioJobConfirmationAction.Retry => new StudioActionConfirmation(
                $"Retry {jobLabel}?",
                $"The exact action \"Retry\" will queue a new attempt for {jobLabel}. Studio will not auto-retry this job; select Retry only if you want to start a new attempt now.",
                "Retry"),
            StudioJobConfirmationAction.ResumeFromCheckpoint => new StudioActionConfirmation(
                $"Resume {checkpointLabel}?",
                $"The exact action \"Resume from checkpoint\" will queue a checkpoint continuation using the {checkpointLabel}. Studio will not auto-resume this checkpoint; select Resume from checkpoint only if you want to continue from it now.",
                "Resume from checkpoint"),
            StudioJobConfirmationAction.RestartClean => new StudioActionConfirmation(
                $"Restart {jobLabel} clean?",
                $"The exact action \"Restart clean\" will queue a clean replacement for {jobLabel} without using the {checkpointLabel} or cached frames. Select Restart clean only if you want a fresh replacement now.",
                "Restart clean"),
            StudioJobConfirmationAction.ClearCachedFrames => new StudioActionConfirmation(
                $"Clear cached frames for {jobLabel}?",
                $"The exact action \"Clear cached frames\" will delete cached render frames for {jobLabel}. Any frames needed for later recovery must be regenerated before recovery continues.",
                "Clear cached frames"),
            StudioJobConfirmationAction.DropCheckpoint => new StudioActionConfirmation(
                $"Drop {checkpointLabel}?",
                $"The exact action \"Drop checkpoint\" will permanently remove the {checkpointLabel}. It will no longer be available for later recovery or continuation.",
                "Drop checkpoint"),
            _ => throw new ArgumentOutOfRangeException(nameof(action), action, "Unknown job confirmation action."),
        };
    }

    private static string DescribeJob(StudioJob job)
    {
        string type = string.IsNullOrWhiteSpace(job.Type) ? "job" : job.Type.Trim();
        return string.Equals(type, "job", StringComparison.OrdinalIgnoreCase)
            ? $"job \"{job.Id}\""
            : $"{type} job \"{job.Id}\"";
    }
}
