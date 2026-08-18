using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineCameraProjectionTests
{
    [TestMethod]
    public void ProjectAndRebuild_PreserveUnknownMetadataAndExistingAliases()
    {
        var timeline = CreateCameraTimeline();
        var keyframes = TimelineCameraProjection.Project(timeline);
        var late = keyframes.Single(keyframe => keyframe.StableId == "late");

        late.TranslationX = 42;
        late.RotationZ = 135;
        late.Zoom = 1.5;
        late.Fov = 75;
        var rebuilt = TimelineCameraProjection.Rebuild(timeline, keyframes);
        var rebuiltLate = rebuilt["camera"]!["keyframes"]!.AsArray()
            .OfType<JsonObject>()
            .Single(keyframe => keyframe["id"]!.GetValue<string>() == "late");

        Assert.AreEqual("root", rebuilt["custom_root"]!.GetValue<string>());
        Assert.AreEqual("camera", rebuilt["camera"]!["vendor"]!.GetValue<string>());
        Assert.AreEqual("keyframe", rebuiltLate["vendor"]!["keep"]!.GetValue<string>());
        Assert.AreEqual(10, rebuiltLate["t"]!.GetValue<double>());
        Assert.AreEqual(42, rebuiltLate["pan_x"]!.GetValue<double>());
        Assert.AreEqual(135, rebuiltLate["rotation_deg"]!.GetValue<double>());
        Assert.AreEqual(1.5, rebuiltLate["zoom"]!.GetValue<double>());
        Assert.AreEqual(75, rebuiltLate["fov"]!.GetValue<double>());
        Assert.IsNull(rebuiltLate["translation_x"]);
        Assert.IsNull(rebuiltLate["rotation_z"]);
    }

    [TestMethod]
    public void Project_NormalizesTimesSortsDeterministicallyAndPersistsGeneratedIdentity()
    {
        var timeline = CreateCameraTimeline();

        var firstProjection = TimelineCameraProjection.Project(timeline);
        var secondProjection = TimelineCameraProjection.Project(timeline);

        CollectionAssert.AreEqual(
            firstProjection.Select(keyframe => keyframe.StableId).ToArray(),
            secondProjection.Select(keyframe => keyframe.StableId).ToArray());
        CollectionAssert.AreEqual(
            new[] { 0d, 0d, 10d },
            firstProjection.Select(keyframe => keyframe.TimeSeconds).ToArray());

        var generated = firstProjection.Single(keyframe => keyframe.StableId.StartsWith("camera_"));
        var rebuilt = TimelineCameraProjection.Rebuild(timeline, firstProjection);
        var projectedAgain = TimelineCameraProjection.Project(rebuilt);

        Assert.IsTrue(
            rebuilt["camera"]!["keyframes"]!.AsArray()
                .OfType<JsonObject>()
                .Any(keyframe => keyframe["id"]?.GetValue<string>() == generated.StableId));
        CollectionAssert.AreEqual(
            firstProjection.Select(keyframe => keyframe.StableId).ToArray(),
            projectedAgain.Select(keyframe => keyframe.StableId).ToArray());
    }

    [TestMethod]
    public void Rebuild_PreservesOpaqueEntriesAndDoesNotInjectUntouchedKnownFields()
    {
        var timeline = CreateCameraTimeline();
        var keyframes = TimelineCameraProjection.Project(timeline);

        var rebuilt = TimelineCameraProjection.Rebuild(timeline, keyframes);
        var idless = rebuilt["camera"]!["keyframes"]!.AsArray()
            .OfType<JsonObject>()
            .Single(keyframe => keyframe["vendor"]?["idless"]?.GetValue<bool>() == true);

        Assert.IsNull(idless["zoom"]);
        Assert.IsNull(idless["translation_x"]);
        Assert.IsTrue(
            rebuilt["camera"]!["keyframes"]!.AsArray()
                .Any(node => node is JsonValue value && value.GetValue<string>() == "opaque"));
    }

    [TestMethod]
    public void CreateDuplicateMoveAndQuantize_UseSafeTimesAndIndependentIdentities()
    {
        var created = TimelineCameraProjection.CreateAt(double.PositiveInfinity, 8);
        created.MoveTo(20, 8);
        created.Quantize(3, 8);
        var duplicate = TimelineCameraProjection.Duplicate(created, 8);

        Assert.AreEqual(8, created.TimeSeconds);
        Assert.AreEqual(8, duplicate.TimeSeconds);
        Assert.AreNotEqual(created.StableId, duplicate.StableId);
        Assert.AreEqual(0, created.TranslationX);
        Assert.AreEqual(1, created.Zoom);
        Assert.AreEqual(60, created.Fov);
    }

    [TestMethod]
    public void Rebuild_AllowsDeletionWithoutLosingCameraMetadata()
    {
        var timeline = CreateCameraTimeline();

        var rebuilt = TimelineCameraProjection.Rebuild(timeline, []);

        Assert.HasCount(1, rebuilt["camera"]!["keyframes"]!.AsArray());
        Assert.AreEqual(
            "opaque",
            rebuilt["camera"]!["keyframes"]![0]!.GetValue<string>());
        Assert.AreEqual("camera", rebuilt["camera"]!["vendor"]!.GetValue<string>());
        Assert.AreEqual("root", rebuilt["custom_root"]!.GetValue<string>());
    }

    [TestMethod]
    public void Rebuild_PersistsUniqueIdentityForDuplicateExplicitIdsAfterReordering()
    {
        var timeline = JsonNode.Parse(
            """
            {
              "duration_s": 20,
              "camera": {
                "keyframes": [
                  {"id": "duplicate", "t": 2, "marker": "first"},
                  {"id": "duplicate", "t": 8, "marker": "second"}
                ]
              }
            }
            """)!.AsObject();
        var keyframes = TimelineCameraProjection.Project(timeline);
        var second = keyframes.Single(keyframe => keyframe.StableId == "duplicate~2");

        second.MoveTo(1, 20);
        var rebuilt = TimelineCameraProjection.Rebuild(timeline, keyframes);
        var projectedAgain = TimelineCameraProjection.Project(rebuilt);

        Assert.AreEqual(
            "duplicate~2",
            rebuilt["camera"]!["keyframes"]![0]!["id"]!.GetValue<string>());
        Assert.AreEqual(
            "second",
            rebuilt["camera"]!["keyframes"]![0]!["marker"]!.GetValue<string>());
        CollectionAssert.AreEquivalent(
            new[] { "duplicate", "duplicate~2" },
            projectedAgain.Select(keyframe => keyframe.StableId).ToArray());
    }

    private static JsonObject CreateCameraTimeline() =>
        JsonNode.Parse(
            """
            {
              "duration_s": 10,
              "custom_root": "root",
              "camera": {
                "vendor": "camera",
                "keyframes": [
                  {
                    "id": "late",
                    "t": 50,
                    "pan_x": 2,
                    "pan_y": 3,
                    "rotation_deg": 45,
                    "zoom": 1.2,
                    "vendor": {"keep": "keyframe"}
                  },
                  {
                    "time_s": -4,
                    "translation": {"x": 4, "y": 5, "z": 6},
                    "rotation": {"x": 7, "y": 8, "z": 9},
                    "field_of_view": 55,
                    "vendor": {"idless": true}
                  },
                  {
                    "id": "invalid",
                    "time": "not-a-number",
                    "custom": true
                  },
                  "opaque"
                ]
              }
            }
            """)!.AsObject();
}
