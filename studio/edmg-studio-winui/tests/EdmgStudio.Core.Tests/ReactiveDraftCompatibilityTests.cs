using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ReactiveDraftCompatibilityTests
{
    [TestMethod]
    [DataRow("{}")]
    [DataRow("{\"settings\":null,\"mappings\":null}")]
    [DataRow("{\"settings\":{\"mappings\":null}}")]
    public void OptionalMetadataProducesUsableEditorState(string json)
    {
        var metadata = JsonSerializer.Deserialize(json, StudioJsonContext.Default.ReactiveLabMetadata)!;
        Assert.IsNotNull(metadata.Settings);
        Assert.IsNotNull(metadata.Mappings);
        Assert.IsNotNull(metadata.Settings.Mappings);
        Assert.AreEqual(1d, metadata.Settings.Sensitivity);
        Assert.AreEqual(30, metadata.Settings.FramesPerSecond);
    }

    [TestMethod]
    public void PartialSettingsPreserveExplicitValuesAndExtensionsAcrossReload()
    {
        const string json = """
            {"metadata":{"source":"workspace","settings":{"sensitivity":0.37,"smoothing":0,
              "fps":60,"mappings":[{"id":"custom","gain":0.6}],"custom":{"keep":true}}},
             "keyframes":[{"id":"key-a","time":1.25,"frame":75,"sample":"60000",
               "strength":0.4,"zoom":1.2,"locked":true,"extension":{"keep":true}}]}
            """;
        var request = JsonSerializer.Deserialize(json, StudioJsonContext.Default.ReactiveLabApplyRequest)!;
        var metadata = request.Metadata!.Value.Deserialize(StudioJsonContext.Default.ReactiveLabMetadata)!;
        Assert.AreEqual(0.37, metadata.Settings.Sensitivity);
        Assert.AreEqual(0d, metadata.Settings.Smoothing);
        Assert.AreEqual(60, metadata.Settings.FramesPerSecond);
        Assert.AreEqual(12, metadata.Settings.MinimumCutFrames);
        Assert.AreEqual(0.6, metadata.Settings.Mappings.Single().Gain);
        Assert.IsTrue(metadata.Settings.ExtensionData!["custom"].GetProperty("keep").GetBoolean());

        request.Metadata = JsonSerializer.SerializeToElement(metadata, StudioJsonContext.Default.ReactiveLabMetadata);
        string saved = JsonSerializer.Serialize(request, StudioJsonContext.Default.ReactiveLabApplyRequest);
        var reloaded = JsonSerializer.Deserialize(saved, StudioJsonContext.Default.ReactiveLabApplyRequest)!;
        Assert.AreEqual(saved, JsonSerializer.Serialize(reloaded, StudioJsonContext.Default.ReactiveLabApplyRequest));
        Assert.IsTrue(JsonElement.DeepEquals(request.Keyframes.Single(), reloaded.Keyframes.Single()));
        var editor = new ReactiveKeyframeEditor(reloaded.Keyframes.Single());
        Assert.IsFalse(editor.IsEditable);
        Assert.AreEqual(0.4, editor.Strength);
        Assert.AreEqual(1.2, editor.Zoom);
    }

    [TestMethod]
    public void LegacyLocalStateWithNullOptionalValuesCanReload()
    {
        var state = JsonSerializer.Deserialize("""{"current":null,"presets":null}""",
            StudioJsonContext.Default.ReactiveLabLocalState)!;
        Assert.IsNotNull(state.Current);
        Assert.IsNotNull(state.Current.Mappings);
        Assert.IsNotNull(state.Presets);
        string saved = JsonSerializer.Serialize(state, StudioJsonContext.Default.ReactiveLabLocalState);
        var reloaded = JsonSerializer.Deserialize(saved, StudioJsonContext.Default.ReactiveLabLocalState)!;
        Assert.AreEqual(saved, JsonSerializer.Serialize(reloaded, StudioJsonContext.Default.ReactiveLabLocalState));
    }

    [TestMethod]
    public void PartialDraftWithNullCollectionsProducesUsableReactiveState()
    {
        const string json = """
            {"keyframes":null,"beat_markers":null,"cue_events":null,"sections":null,
             "repair_suggestions":null}
            """;
        var request = JsonSerializer.Deserialize(json, StudioJsonContext.Default.ReactiveLabApplyRequest)!;

        Assert.IsNotNull(request.Keyframes);
        Assert.IsNotNull(request.BeatMarkers);
        Assert.IsNotNull(request.CueEvents);
        Assert.IsNotNull(request.Sections);
        Assert.IsNotNull(request.RepairSuggestions);
        Assert.IsFalse(ReactiveWorkflow.HasMeaningfulPayload(request));
    }

    [TestMethod]
    public void LegacyLocalStateMigratesToCurrentRecoveryVersion()
    {
        var state = JsonSerializer.Deserialize("""{"current":{"name":"legacy"},"presets":[]}""",
            StudioJsonContext.Default.ReactiveLabLocalState)!;

        Assert.IsTrue(state.TryNormalizeForRecovery(out ReactiveLabLocalState normalized));
        Assert.AreEqual(ReactiveLabLocalState.CurrentVersion, normalized.Version);
        Assert.AreEqual("legacy", normalized.Current.Name);
    }

    [TestMethod]
    public void FutureLocalStateIsRejectedWithoutMutation()
    {
        var state = JsonSerializer.Deserialize("""{"version":99,"current":{"name":"future"},"workspace_draft_id":" draft "}""",
            StudioJsonContext.Default.ReactiveLabLocalState)!;

        Assert.IsFalse(state.TryNormalizeForRecovery(out ReactiveLabLocalState rejected));
        Assert.AreSame(state, rejected);
        Assert.AreEqual(" draft ", state.WorkspaceDraftId);
        Assert.AreEqual("future", state.Current.Name);
    }

    [TestMethod]
    public void DirectorWorkflowRecoveryUsesOptionalJobAndExactTimelineContext()
    {
        using JsonDocument document = JsonDocument.Parse("""
            {"director_job":{"version":1,"job_id":"job-8","status":"reviewed","reviewed":true,"reviewed_job_id":"job-8"},
             "context_revision":12,
             "timeline_context":{"version":1,"selected_range":{"start_sample":"9007199254740993",
             "end_sample":"9007199254741993"}}}
            """);

        DirectorWorkflowRecovery recovery = DirectorWorkflowRecovery.FromResponse(document.RootElement, "fallback");

        Assert.AreEqual("job-8", recovery.JobId);
        Assert.AreEqual("reviewed", recovery.JobStatus);
        Assert.AreEqual("job-8", recovery.ReviewedJobId);
        Assert.AreEqual(9_007_199_254_740_993, recovery.SelectionStartSample);
        Assert.AreEqual(9_007_199_254_741_993, recovery.SelectionEndSample);
        Assert.AreEqual(12, recovery.ContextRevision);
    }

    [TestMethod]
    public void DirectorWorkflowRecoveryFallsBackToSelectedSessionJob()
    {
        using JsonDocument document = JsonDocument.Parse("{}" );

        DirectorWorkflowRecovery recovery = DirectorWorkflowRecovery.FromResponse(document.RootElement, " selected-job ");

        Assert.AreEqual("selected-job", recovery.JobId);
    }

    [TestMethod]
    public void FutureServerRecoveryVersionIsRejected()
    {
        using JsonDocument future = JsonDocument.Parse("{\"recovery_version\":2}");
        using JsonDocument legacy = JsonDocument.Parse("{}");

        Assert.IsFalse(ReactiveWorkflow.SupportsRecovery(future.RootElement));
        Assert.IsTrue(ReactiveWorkflow.SupportsRecovery(legacy.RootElement));
    }
}
