using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioWorkflowContextTests
{
    [TestMethod]
    public void Normalize_TrimsValuesAndRejectsInvalidNumbers()
    {
        var context = new StudioWorkflowContext(
            ActiveProjectId: "  project-a  ",
            SelectedVariant: -4,
            SelectedArtifactPath: "  output/video.mp4 ",
            SelectedJobId: " job-7 ",
            SelectedJobProjectId: " project-a ",
            SourceAssetPath: "   ",
            TimelineFocusSeconds: double.PositiveInfinity,
            RenderContext: "  preview ",
            LastWorkflowDestination: " outputs ");

        StudioWorkflowContext normalized = context.Normalize();

        Assert.AreEqual("project-a", normalized.ActiveProjectId);
        Assert.AreEqual(0, normalized.SelectedVariant);
        Assert.AreEqual("output/video.mp4", normalized.SelectedArtifactPath);
        Assert.AreEqual("job-7", normalized.SelectedJobId);
        Assert.AreEqual("project-a", normalized.SelectedJobProjectId);
        Assert.IsNull(normalized.SourceAssetPath);
        Assert.IsNull(normalized.TimelineFocusSeconds);
        Assert.AreEqual("preview", normalized.RenderContext);
        Assert.AreEqual("outputs", normalized.LastWorkflowDestination);
    }

    [TestMethod]
    public void WithActiveProject_ClearsProjectScopedStateAndKeepsDestination()
    {
        var context = new StudioWorkflowContext(
            ActiveProjectId: "project-a",
            SelectedVariant: 3,
            SelectedArtifactPath: "render.mp4",
            SelectedJobId: "job-1",
            SelectedJobProjectId: "project-a",
            SourceAssetPath: "source.wav",
            TimelineFocusSeconds: 12.5,
            RenderContext: "final",
            LastWorkflowDestination: "review");

        StudioWorkflowContext updated = context.WithActiveProject("project-b");

        Assert.AreEqual("project-b", updated.ActiveProjectId);
        Assert.AreEqual(0, updated.SelectedVariant);
        Assert.IsNull(updated.SelectedArtifactPath);
        Assert.IsNull(updated.SelectedJobId);
        Assert.IsNull(updated.SelectedJobProjectId);
        Assert.IsNull(updated.SourceAssetPath);
        Assert.IsNull(updated.TimelineFocusSeconds);
        Assert.IsNull(updated.RenderContext);
        Assert.AreEqual("review", updated.LastWorkflowDestination);
    }

    [TestMethod]
    public void WithActiveProject_DoesNotClearStateForEquivalentProject()
    {
        var context = new StudioWorkflowContext(
            ActiveProjectId: "project-a",
            SelectedVariant: 2,
            SelectedArtifactPath: "render.mp4");

        StudioWorkflowContext updated = context.WithActiveProject(" project-a ");

        Assert.AreEqual(2, updated.SelectedVariant);
        Assert.AreEqual("render.mp4", updated.SelectedArtifactPath);
    }

    [TestMethod]
    public void WithSelectedJob_ClearsProjectWhenJobIsCleared()
    {
        StudioWorkflowContext updated = new StudioWorkflowContext()
            .WithSelectedJob("project-a", "job-1")
            .WithSelectedJob("project-a", " ");

        Assert.IsNull(updated.SelectedJobId);
        Assert.IsNull(updated.SelectedJobProjectId);
    }

    [TestMethod]
    [DataRow(-0.01)]
    [DataRow(double.NaN)]
    [DataRow(double.NegativeInfinity)]
    public void Normalize_RejectsInvalidTimelineFocus(double value)
    {
        StudioWorkflowContext normalized = new StudioWorkflowContext(TimelineFocusSeconds: value).Normalize();

        Assert.IsNull(normalized.TimelineFocusSeconds);
    }

    [TestMethod]
    public void Normalize_PreservesExactTimelineRangeAndRevision()
    {
        StudioWorkflowContext normalized = new StudioWorkflowContext(
            TimelineSelectionStartSample: 9_007_199_254_740_993,
            TimelineSelectionEndSample: 9_007_199_254_741_993,
            ContextRevision: 17).Normalize();

        Assert.AreEqual(9_007_199_254_740_993, normalized.TimelineSelectionStartSample);
        Assert.AreEqual(9_007_199_254_741_993, normalized.TimelineSelectionEndSample);
        Assert.AreEqual(17, normalized.ContextRevision);

        string json = JsonSerializer.Serialize(normalized, StudioJsonContext.Default.StudioWorkflowContext);
        StudioWorkflowContext restored = JsonSerializer.Deserialize(json, StudioJsonContext.Default.StudioWorkflowContext)!;
        Assert.AreEqual(normalized, restored);
    }

    [TestMethod]
    [DataRow(-1L, 5L)]
    [DataRow(5L, 5L)]
    [DataRow(6L, 5L)]
    public void Normalize_ClearsIncompleteOrInvalidTimelineRange(long start, long end)
    {
        StudioWorkflowContext normalized = new StudioWorkflowContext(
            TimelineSelectionStartSample: start,
            TimelineSelectionEndSample: end,
            ContextRevision: -2).Normalize();

        Assert.IsNull(normalized.TimelineSelectionStartSample);
        Assert.IsNull(normalized.TimelineSelectionEndSample);
        Assert.AreEqual(0, normalized.ContextRevision);
    }
}
