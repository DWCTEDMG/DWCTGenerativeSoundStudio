using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WorkspaceReadinessSummaryTests
{
    [TestMethod]
    public void ModelSummarySeparatesExecutionFromLevelFiveQualification()
    {
        var status = new ModelRuntimeStatus("qwen", "execution_ready", true, false, 3, true, true, true, true, null, [])
        {
            ExecutionReady = true,
            Warnings = ["Level-5 runtime smoke qualification is recommended."],
        };

        string summary = WorkspaceReadinessSummary.Model("Qwen", status);

        StringAssert.Contains(summary, "configured: yes");
        StringAssert.Contains(summary, "installed: yes");
        StringAssert.Contains(summary, "runtime adapter: reachable");
        StringAssert.Contains(summary, "validation-ready: yes");
        StringAssert.Contains(summary, "execution-ready: yes");
        StringAssert.Contains(summary, "Level-5 qualified: no");
        StringAssert.Contains(summary, "Advisories:");
    }

    [TestMethod]
    public void ProviderSummaryMakesByomQualificationBoundaryExplicit()
    {
        string summary = WorkspaceReadinessSummary.Provider("openai_compat", "custom-model");

        StringAssert.Contains(summary, "BYOM provider selected");
        StringAssert.Contains(summary, "not implied by this selection");
    }

    [TestMethod]
    public void AnalysisSummaryDistinguishesMissingCachedAndWhisperFailure()
    {
        var missing = Project("{\"audio\":{\"filename\":\"song.wav\"}}");
        var cached = Project("{\"audio\":{\"filename\":\"song.wav\"},\"analysis\":{\"transcript\":{\"text\":\"lyrics\"}}}");
        var failed = Project("{\"audio\":{\"filename\":\"song.wav\"},\"analysis\":{\"transcript\":{\"error\":\"offline\"}}}");

        StringAssert.StartsWith(WorkspaceReadinessSummary.Analysis(missing), "Analysis: none");
        StringAssert.StartsWith(WorkspaceReadinessSummary.Analysis(cached), "Analysis: cached and reusable");
        StringAssert.Contains(WorkspaceReadinessSummary.Analysis(failed), "Whisper failed");
    }

    private static ProjectDto Project(string metadata) => new()
    {
        Id = "project",
        Name = "Project",
        Meta = JsonDocument.Parse(metadata).RootElement.Clone(),
    };
}
