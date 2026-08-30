using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WorkspaceModelTests
{
    [TestMethod]
    public void ClampVariantIndex_UsesAvailableVariantRange()
    {
        Assert.AreEqual(0, WorkspaceModelHelpers.ClampVariantIndex(-4, 3));
        Assert.AreEqual(1, WorkspaceModelHelpers.ClampVariantIndex(1, 3));
        Assert.AreEqual(2, WorkspaceModelHelpers.ClampVariantIndex(8, 3));
        Assert.AreEqual(0, WorkspaceModelHelpers.ClampVariantIndex(8, 0));
    }

    [TestMethod]
    public void MoveScene_ReordersCompleteSceneObjectsDeterministically()
    {
        using var metadata = JsonDocument.Parse("""{"camera":"orbit"}""");
        var scenes = new[]
        {
            new PlanSceneDto { StartSeconds = 0, EndSeconds = 4, Prompt = "First" },
            new PlanSceneDto
            {
                StartSeconds = 4,
                EndSeconds = 8,
                Prompt = "Second",
                AdditionalData = new Dictionary<string, JsonElement>
                {
                    ["metadata"] = metadata.RootElement.GetProperty("camera").Clone(),
                },
            },
            new PlanSceneDto { StartSeconds = 8, EndSeconds = 12, Prompt = "Third" },
        };

        var reordered = WorkspaceModelHelpers.MoveScene(scenes, 1, -1);

        CollectionAssert.AreEqual(
            new[] { "Second", "First", "Third" },
            reordered.Select(scene => scene.Prompt).ToArray());
        CollectionAssert.AreEqual(
            new[] { 0D, 4D, 8D },
            reordered.Select(scene => scene.StartSeconds).ToArray());
        CollectionAssert.AreEqual(
            new[] { 4D, 8D, 12D },
            reordered.Select(scene => scene.EndSeconds).ToArray());
        Assert.AreEqual("orbit", reordered[0].AdditionalData!["metadata"].GetString());
        Assert.AreEqual("First", scenes[0].Prompt);
    }

    [TestMethod]
    public void CloneScene_PreservesMetadataAfterSourceDocumentIsDisposed()
    {
        PlanSceneDto clone;
        using (var metadata = JsonDocument.Parse("""{"continuity":{"subject":"performer"},"score":0.92}"""))
        {
            var source = new PlanSceneDto
            {
                StartSeconds = 2,
                EndSeconds = 6,
                Prompt = "Tracking shot",
                NegativePrompt = "flicker",
                Subject = "same copper automaton",
                Action = "turns and reaches",
                Camera = "left-to-right track",
                Motion = "head and hand movement",
                EnvironmentMotion = "orchids and rain move",
                ContinuityNote = "preserve blue eye and screen direction",
                Transition = "match action",
                AdditionalData = new Dictionary<string, JsonElement>
                {
                    ["continuity"] = metadata.RootElement.GetProperty("continuity"),
                    ["score"] = metadata.RootElement.GetProperty("score"),
                },
            };

            clone = WorkspaceModelHelpers.CloneScene(source);
        }

        Assert.AreEqual(2D, clone.StartSeconds);
        Assert.AreEqual(6D, clone.EndSeconds);
        Assert.AreEqual("Tracking shot", clone.Prompt);
        Assert.AreEqual("flicker", clone.NegativePrompt);
        Assert.AreEqual("same copper automaton", clone.Subject);
        Assert.AreEqual("turns and reaches", clone.Action);
        Assert.AreEqual("left-to-right track", clone.Camera);
        Assert.AreEqual("head and hand movement", clone.Motion);
        Assert.AreEqual("orchids and rain move", clone.EnvironmentMotion);
        Assert.AreEqual("preserve blue eye and screen direction", clone.ContinuityNote);
        Assert.AreEqual("match action", clone.Transition);
        Assert.AreEqual("performer", clone.AdditionalData!["continuity"].GetProperty("subject").GetString());
        Assert.AreEqual(0.92D, clone.AdditionalData["score"].GetDouble());
    }

    [TestMethod]
    public void CloneScene_ReplacesEditableStoryboardContractTogether()
    {
        var source = new PlanSceneDto
        {
            Prompt = "Original",
            Subject = "old subject",
            Action = "old action",
            Camera = "old camera",
            Motion = "old motion",
            EnvironmentMotion = "old environment",
            ContinuityNote = "old continuity",
            Transition = "old transition",
        };

        PlanSceneDto clone = WorkspaceModelHelpers.CloneScene(
            source,
            subject: "same copper automaton",
            action: "raises its hand",
            camera: "measured tracking move",
            motion: "head and hand movement",
            environmentMotion: "orchids sway",
            continuity: "preserve the blue eye",
            transition: "match action",
            replaceStoryboardFields: true);

        Assert.AreEqual("same copper automaton", clone.Subject);
        Assert.AreEqual("raises its hand", clone.Action);
        Assert.AreEqual("measured tracking move", clone.Camera);
        Assert.AreEqual("head and hand movement", clone.Motion);
        Assert.AreEqual("orchids sway", clone.EnvironmentMotion);
        Assert.AreEqual("preserve the blue eye", clone.ContinuityNote);
        Assert.AreEqual("match action", clone.Transition);
    }

    [TestMethod]
    public void SceneCurationHelpers_ApplyApprovalLockAndRepairSemantics()
    {
        var original = new PlanSceneDto
        {
            Prompt = "Original",
            AdditionalData = new Dictionary<string, JsonElement>
            {
                ["continuity_id"] = JsonDocument.Parse("\"scene-a\"").RootElement.Clone(),
            },
        };

        var approved = WorkspaceModelHelpers.SetSceneApproval(original, approved: true);
        Assert.IsTrue(WorkspaceModelHelpers.IsSceneApproved(approved));
        Assert.AreEqual("approved", WorkspaceModelHelpers.GetSceneStatus(approved));
        Assert.IsFalse(WorkspaceModelHelpers.IsSceneApproved(original));

        var unapproved = WorkspaceModelHelpers.SetSceneApproval(approved, approved: false);
        Assert.IsFalse(WorkspaceModelHelpers.IsSceneApproved(unapproved));
        Assert.AreEqual("draft", WorkspaceModelHelpers.GetSceneStatus(unapproved));

        var locked = WorkspaceModelHelpers.SetSceneLocked(unapproved, locked: true);
        Assert.IsTrue(WorkspaceModelHelpers.IsSceneLocked(locked));
        Assert.AreEqual("scene-a", locked.AdditionalData!["continuity_id"].GetString());

        var needsRepair = WorkspaceModelHelpers.MarkSceneNeedsRepair(locked);
        Assert.IsFalse(WorkspaceModelHelpers.IsSceneApproved(needsRepair));
        Assert.IsTrue(WorkspaceModelHelpers.IsSceneLocked(needsRepair));
        Assert.AreEqual("needs-repair", WorkspaceModelHelpers.GetSceneStatus(needsRepair));
    }

    [TestMethod]
    public void ParseTemplatePackage_AcceptsBackendSchemaAndPreservesPayload()
    {
        var package = WorkspaceModelHelpers.ParseTemplatePackage(
            """{"schema_version":1,"payload":{"visual_dna":{"palette":"amber"},"render_preset":"quality"},"name":"Reusable look"}""");

        Assert.AreEqual(1, package.SchemaVersion);
        Assert.AreEqual("amber", package.Payload.GetProperty("visual_dna").GetProperty("palette").GetString());
        Assert.AreEqual("Reusable look", package.AdditionalData!["name"].GetString());
    }

    [TestMethod]
    public void ParseTemplatePackage_RejectsUnsupportedOrEmptyPackages()
    {
        Assert.ThrowsExactly<JsonException>(() =>
            WorkspaceModelHelpers.ParseTemplatePackage("""{"schema_version":2,"payload":{"visual_dna":{}}}"""));
        Assert.ThrowsExactly<JsonException>(() =>
            WorkspaceModelHelpers.ParseTemplatePackage("""{"schema_version":1,"payload":{"unknown":true}}"""));
        Assert.ThrowsExactly<JsonException>(() =>
            WorkspaceModelHelpers.ParseTemplatePackage("""{"schema_version":1,"payload":[]}"""));
    }

    [TestMethod]
    public void LiveContextContracts_NormalizeExplicitNullCollections()
    {
        var graph = JsonSerializer.Deserialize(
            """{"timebase":null,"tempo":null,"beats":null,"sections":null,"stems":null,"confidenceNotes":null}""",
            StudioJsonContext.Default.MusicGraphResponse);
        var cues = JsonSerializer.Deserialize(
            """{"events":null,"notes":null}""",
            StudioJsonContext.Default.LiveCuesResponse);
        var assets = JsonSerializer.Deserialize(
            """{"packs":null}""",
            StudioJsonContext.Default.LiveAssetsResponse);

        Assert.IsNotNull(graph);
        Assert.IsNotNull(graph.Timebase);
        Assert.IsNotNull(graph.Tempo);
        Assert.HasCount(0, graph.Beats);
        Assert.HasCount(0, graph.Sections);
        Assert.HasCount(0, graph.Stems);
        Assert.HasCount(0, graph.ConfidenceNotes);
        Assert.IsNotNull(cues);
        Assert.HasCount(0, cues.Events);
        Assert.HasCount(0, cues.Notes);
        Assert.IsNotNull(assets);
        Assert.HasCount(0, assets.Packs);
    }
}
