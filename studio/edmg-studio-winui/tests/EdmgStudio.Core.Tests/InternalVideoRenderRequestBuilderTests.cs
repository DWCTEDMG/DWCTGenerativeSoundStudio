using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class InternalVideoRenderRequestBuilderTests
{
    [TestMethod]
    public void Build_SerializesAdvancedSettingsAndBackendRefinerContract()
    {
        JsonElement request = InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings
        {
            VariantIndex = 3,
            OutputFps = 30,
            RenderFps = 6,
            Width = 1920,
            Height = 1080,
            Steps = 40,
            Cfg = 8.5,
            Seed = 42,
            RefinerEnabled = true,
            RefinerModelId = "refiner-xl",
            RefinerSwitchAt = 0.7,
            RefinerSteps = 12,
            TemporalSteps = 20,
            ParseqManifest = """{"rendered_frames":[{"frame":0}]}""",
            DeforumPrompts = """{"0":"opening","24":"finale"}""",
            DeforumNegativePrompts = """{"0":"blur"}""",
        });

        Assert.AreEqual(3, request.GetProperty("variant_index").GetInt32());
        Assert.AreEqual(30, request.GetProperty("fps_output").GetInt32());
        Assert.AreEqual(42, request.GetProperty("seed").GetInt64());
        Assert.AreEqual("opening", request.GetProperty("deforum_prompts").GetProperty("0").GetString());
        Assert.AreEqual(JsonValueKind.Object, request.GetProperty("parseq_manifest").ValueKind);

        JsonElement refiner = request.GetProperty("refiner");
        Assert.AreEqual("refiner-xl", refiner.GetProperty("model").GetString());
        Assert.AreEqual(0.7, refiner.GetProperty("switch_at").GetDouble());
        Assert.AreEqual(12, refiner.GetProperty("steps").GetInt32());
        CollectionAssert.AreEquivalent(
            new[] { "model", "switch_at", "steps" },
            refiner.EnumerateObject().Select(property => property.Name).ToArray());
    }

    [TestMethod]
    public void Build_TensorRtModeAppliesRequiredOverrides()
    {
        JsonElement request = InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings
        {
            RenderMode = "tensorrt",
            ModelId = "ignored",
            DevicePreference = "cpu",
            TemporalMode = "video_model",
            MotionStrategy = "storyboard_full_motion",
            AllowHostedFallback = true,
            ResumeExistingFrames = true,
        });

        Assert.AreEqual("local_sd15_tensorrt_bundle", request.GetProperty("model_id").GetString());
        Assert.AreEqual("cuda", request.GetProperty("device_preference").GetString());
        Assert.AreEqual("keyframes", request.GetProperty("temporal_mode").GetString());
        Assert.AreEqual("manual", request.GetProperty("motion_strategy").GetString());
        Assert.IsFalse(request.GetProperty("allow_hosted_fallback").GetBoolean());
        Assert.IsFalse(request.GetProperty("resume_existing_frames").GetBoolean());
        Assert.AreEqual("tensorrt_sd15", request.GetProperty("video_model_keyframe_renderer").GetString());
        Assert.AreEqual(
            "local_sd15_tensorrt_bundle",
            request.GetProperty("video_model_keyframe_model_id").GetString());
    }

    [TestMethod]
    public void Build_ParsesSchedulesAndLoras()
    {
        JsonElement request = InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings
        {
            Loras = "cinematic@1.5; subtle@-8, default",
            MotionScoreSchedule = """{"0":2,"24":6}""",
            DeforumZoom = "0:(1.0), 24:(1.1)",
        });

        JsonElement loras = request.GetProperty("loras");
        Assert.AreEqual(3, loras.GetArrayLength());
        Assert.AreEqual(1.5, loras[0].GetProperty("weight").GetDouble());
        Assert.AreEqual(-4.0, loras[1].GetProperty("weight").GetDouble());
        Assert.AreEqual(1.0, loras[2].GetProperty("weight").GetDouble());
        Assert.AreEqual(JsonValueKind.Object, request.GetProperty("video_model_motion_score_schedule").ValueKind);
        Assert.AreEqual("0:(1.0), 24:(1.1)", request.GetProperty("deforum_zoom").GetString());
        Assert.AreEqual(JsonValueKind.Null, request.GetProperty("deforum_angle").ValueKind);
    }

    [TestMethod]
    public void Build_AllowsCinematicStartAndEndAnchorMode()
    {
        JsonElement request = InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings
        {
            VideoModelAnchorMode = "both",
        });

        Assert.AreEqual("both", request.GetProperty("video_model_anchor_mode").GetString());
    }

    [TestMethod]
    public void Build_RejectsMalformedJsonWithFieldName()
    {
        InvalidOperationException exception = Assert.ThrowsExactly<InvalidOperationException>(() =>
            InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings
            {
                MotionScoreSchedule = "{not-json",
            }));

        StringAssert.Contains(exception.Message, "Motion score schedule contains invalid JSON");
    }

    [TestMethod]
    public void Build_RejectsNonObjectPromptJson()
    {
        InvalidOperationException exception = Assert.ThrowsExactly<InvalidOperationException>(() =>
            InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings
            {
                DeforumPrompts = """["not","an","object"]""",
            }));

        StringAssert.Contains(exception.Message, "Deforum prompts must be a JSON object");
    }

    [TestMethod]
    public void Build_ValidatesEnumsAndBackendRanges()
    {
        InvalidOperationException enumException = Assert.ThrowsExactly<InvalidOperationException>(() =>
            InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings { RenderMode = "proxy" }));
        InvalidOperationException rangeException = Assert.ThrowsExactly<InvalidOperationException>(() =>
            InternalVideoRenderRequestBuilder.Build(new InternalVideoRenderSettings { OutputFps = 61 }));

        StringAssert.Contains(enumException.Message, "Render mode must be one of");
        StringAssert.Contains(rangeException.Message, "Output FPS must be between 1 and 60");
    }
}
