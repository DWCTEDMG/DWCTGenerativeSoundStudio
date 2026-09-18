namespace EdmgStudio.Core.Models;

public static class WorkspaceReadinessSummary
{
    public static string Analysis(ProjectDto project)
    {
        if (!project.HasAudio)
        {
            return "Analysis: none - choose source audio to begin.";
        }

        if (!project.HasAnalysis)
        {
            return "Analysis: none - project audio has not been analyzed.";
        }

        return project.TranscriptStatus.StartsWith("Transcription failed", StringComparison.OrdinalIgnoreCase)
            ? $"Analysis: cached audio features; Whisper failed. {project.TranscriptStatus}"
            : $"Analysis: cached and reusable. {project.TranscriptStatus}.";
    }

    public static string Model(string label, ModelRuntimeStatus status, bool configured = true)
    {
        string availability = status.Installed ? "available" : "unavailable";
        string summary =
            $"{label}: {availability} | configured: {YesNo(configured)} | installed: {YesNo(status.Installed)} | " +
            $"runtime adapter: {(status.AdapterReady ? "reachable" : "unavailable")} | validation-ready: {YesNo(status.ValidationLevel >= 3)} | " +
            $"execution-ready: {YesNo(status.ExecutionReady || status.RuntimeReady)} | Level-5 qualified: {YesNo(status.RuntimeReady)}";
        string blockers = string.Join(" | ", status.Blockers ?? []);
        if (!string.IsNullOrWhiteSpace(status.Error))
        {
            blockers = string.IsNullOrWhiteSpace(blockers) ? status.Error : $"{blockers} | {status.Error}";
        }

        string warnings = string.Join(" | ", status.Warnings ?? []);
        string result = string.IsNullOrWhiteSpace(blockers) ? summary : $"{summary}\nBlockers: {blockers}";
        return string.IsNullOrWhiteSpace(warnings) ? result : $"{result}\nAdvisories: {warnings}";
    }

    public static string Provider(string provider, string? model)
    {
        string selectedModel = string.IsNullOrWhiteSpace(model) ? "provider default" : model;
        return provider == "internal_qwen"
            ? "Provider: managed internal Qwen; local runtime evidence is shown below."
            : $"BYOM provider selected: {provider}; model: {selectedModel}. Endpoint/model qualification is owned by that provider and is not implied by this selection.";
    }

    private static string YesNo(bool value) => value ? "yes" : "no";
}
