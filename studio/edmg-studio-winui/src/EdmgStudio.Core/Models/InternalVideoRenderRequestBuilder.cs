using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public sealed record InternalVideoRenderSettings
{
    public int VariantIndex { get; init; }
    public int OutputFps { get; init; } = 24;
    public int RenderFps { get; init; } = 2;
    public int Width { get; init; } = 768;
    public int Height { get; init; } = 432;
    public int Steps { get; init; } = 15;
    public double Cfg { get; init; } = 7.0;
    public string Sampler { get; init; } = "euler";
    public long? Seed { get; init; }
    public double KeyframeIntervalSeconds { get; init; } = 5.0;
    public string KeyframeContinuityMode { get; init; } = "scene";
    public string InterpolationEngine { get; init; } = "auto";
    public string ModelId { get; init; } = "auto";
    public string RenderMode { get; init; } = "auto";
    public string RenderTier { get; init; } = "auto";
    public string DevicePreference { get; init; } = "auto";
    public bool AllowHostedFallback { get; init; } = true;
    public string HostedService { get; init; } = "default";
    public string? HostedModel { get; init; }
    public string? HostedStylePreset { get; init; }
    public string NegativePrompt { get; init; } = "blurry, low quality, watermark, text, logo";
    public string Loras { get; init; } = string.Empty;
    public string? Vae { get; init; }
    public bool RefinerEnabled { get; init; }
    public string? RefinerModelId { get; init; }
    public double RefinerSwitchAt { get; init; } = 0.8;
    public int? RefinerSteps { get; init; }
    public string TemporalMode { get; init; } = "keyframes";
    public double TemporalStrength { get; init; } = 0.35;
    public int? TemporalSteps { get; init; }
    public int RefineEveryNFrames { get; init; } = 1;
    public double AnchorStrength { get; init; } = 0.2;
    public bool PromptBlend { get; init; } = true;
    public bool ResumeExistingFrames { get; init; } = true;
    public string MotionStrategy { get; init; } = "manual";
    public double StoryboardShotMaxSeconds { get; init; } = 4.0;
    public string VideoModelEngine { get; init; } = "auto";
    public string? VideoModelId { get; init; }
    public int VideoModelMaxFramesPerScene { get; init; } = 8;
    public int VideoModelMotionBucketId { get; init; } = 127;
    public double VideoModelNoiseAugStrength { get; init; } = 0.02;
    public int VideoModelDecodeChunkSize { get; init; } = 8;
    public string VideoModelDtype { get; init; } = "auto";
    public bool VideoModelCpuOffload { get; init; }
    public string VideoModelMotionScoreMode { get; init; } = "auto";
    public int VideoModelManualMotionScore { get; init; } = 4;
    public string VideoModelAnchorMode { get; init; } = "start";
    public bool VideoModelPromptRefine { get; init; } = true;
    public string VideoModelSceneMotion { get; init; } = "subject";
    public bool VideoModelApplyTimelineCamera { get; init; } = true;
    public string VideoModelKeyframeRenderer { get; init; } = "internal";
    public string? VideoModelKeyframeModelId { get; init; }
    public string MotionScoreSchedule { get; init; } = string.Empty;
    public string NoiseAugSchedule { get; init; } = string.Empty;
    public string AnchorStrengthSchedule { get; init; } = string.Empty;
    public bool ParseqEnabled { get; init; } = true;
    public string ParseqManifest { get; init; } = string.Empty;
    public string? SourceAsset { get; init; }
    public double SourceStrength { get; init; } = 0.55;
    public string DeforumPrompts { get; init; } = string.Empty;
    public string DeforumNegativePrompts { get; init; } = string.Empty;
    public string DeforumZoom { get; init; } = string.Empty;
    public string DeforumAngle { get; init; } = string.Empty;
    public string DeforumTranslationX { get; init; } = string.Empty;
    public string DeforumTranslationY { get; init; } = string.Empty;
    public string DeforumTranslationZ { get; init; } = string.Empty;
    public string DeforumRotationX { get; init; } = string.Empty;
    public string DeforumRotationY { get; init; } = string.Empty;
    public string DeforumRotationZ { get; init; } = string.Empty;
    public string DeforumFov { get; init; } = string.Empty;
    public string DeforumStrength { get; init; } = string.Empty;
    public string DeforumCfg { get; init; } = string.Empty;
    public string DeforumSteps { get; init; } = string.Empty;
    public string DeforumDenoise { get; init; } = string.Empty;
}

public static class InternalVideoRenderRequestBuilder
{
    private const string TensorRtBundle = "local_sd15_tensorrt_bundle";

    public static JsonElement Build(InternalVideoRenderSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        Validate(settings);

        bool tensorRt = settings.RenderMode == "tensorrt";
        var request = new JsonObject
        {
            ["variant_index"] = Math.Max(0, settings.VariantIndex),
            ["fps_output"] = settings.OutputFps,
            ["fps_render"] = settings.RenderFps,
            ["width"] = settings.Width,
            ["height"] = settings.Height,
            ["steps"] = settings.Steps,
            ["cfg"] = settings.Cfg,
            ["sampler"] = Required(settings.Sampler, "Sampler"),
            ["seed"] = settings.Seed,
            ["keyframe_interval_s"] = settings.KeyframeIntervalSeconds,
            ["keyframe_continuity_mode"] = settings.KeyframeContinuityMode,
            ["interpolation_engine"] = settings.InterpolationEngine,
            ["model_id"] = tensorRt ? TensorRtBundle : Required(settings.ModelId, "Model"),
            ["render_mode"] = settings.RenderMode,
            ["render_tier"] = settings.RenderTier,
            ["device_preference"] = tensorRt ? "cuda" : settings.DevicePreference,
            ["allow_hosted_fallback"] = tensorRt ? false : settings.AllowHostedFallback,
            ["hosted_service"] = settings.HostedService,
            ["hosted_model"] = Optional(settings.HostedModel),
            ["hosted_style_preset"] = Optional(settings.HostedStylePreset),
            ["negative_prompt"] = settings.NegativePrompt.Trim(),
            ["loras"] = ParseLoras(settings.Loras),
            ["vae"] = Optional(settings.Vae),
            ["refiner"] = BuildRefiner(settings),
            ["temporal_mode"] = tensorRt ? "keyframes" : settings.TemporalMode,
            ["temporal_strength"] = settings.TemporalStrength,
            ["temporal_steps"] = settings.TemporalSteps,
            ["refine_every_n_frames"] = settings.RefineEveryNFrames,
            ["anchor_strength"] = settings.AnchorStrength,
            ["prompt_blend"] = settings.PromptBlend,
            ["resume_existing_frames"] = tensorRt ? false : settings.ResumeExistingFrames,
            ["motion_strategy"] = tensorRt ? "manual" : settings.MotionStrategy,
            ["storyboard_shot_max_s"] = settings.StoryboardShotMaxSeconds,
            ["video_model_engine"] = settings.VideoModelEngine,
            ["video_model_id"] = Optional(settings.VideoModelId),
            ["video_model_max_frames_per_scene"] = settings.VideoModelMaxFramesPerScene,
            ["video_model_motion_bucket_id"] = settings.VideoModelMotionBucketId,
            ["video_model_noise_aug_strength"] = settings.VideoModelNoiseAugStrength,
            ["video_model_decode_chunk_size"] = settings.VideoModelDecodeChunkSize,
            ["video_model_dtype"] = settings.VideoModelDtype,
            ["video_model_cpu_offload"] = settings.VideoModelCpuOffload,
            ["video_model_motion_score_mode"] = settings.VideoModelMotionScoreMode,
            ["video_model_manual_motion_score"] = settings.VideoModelManualMotionScore,
            ["video_model_anchor_mode"] = settings.VideoModelAnchorMode,
            ["video_model_prompt_refine"] = settings.VideoModelPromptRefine,
            ["video_model_scene_motion"] = settings.VideoModelSceneMotion,
            ["video_model_apply_timeline_camera"] = settings.VideoModelApplyTimelineCamera,
            ["video_model_keyframe_renderer"] = tensorRt ? "tensorrt_sd15" : settings.VideoModelKeyframeRenderer,
            ["video_model_keyframe_model_id"] = tensorRt
                ? Optional(settings.VideoModelKeyframeModelId) ?? TensorRtBundle
                : Optional(settings.VideoModelKeyframeModelId),
            ["video_model_motion_score_schedule"] = ParseSchedule(settings.MotionScoreSchedule, "Motion score schedule"),
            ["video_model_noise_aug_schedule"] = ParseSchedule(settings.NoiseAugSchedule, "Noise augmentation schedule"),
            ["anchor_strength_schedule"] = ParseSchedule(settings.AnchorStrengthSchedule, "Anchor strength schedule"),
            ["parseq_enabled"] = settings.ParseqEnabled,
            ["parseq_manifest"] = ParseOptionalObject(settings.ParseqManifest, "Parseq manifest"),
            ["source_asset"] = Optional(settings.SourceAsset),
            ["source_strength"] = settings.SourceStrength,
            ["deforum_prompts"] = ParseOptionalObject(settings.DeforumPrompts, "Deforum prompts"),
            ["deforum_negative_prompts"] = ParseOptionalObject(settings.DeforumNegativePrompts, "Deforum negative prompts"),
            ["deforum_zoom"] = ParseSchedule(settings.DeforumZoom, "Deforum zoom schedule"),
            ["deforum_angle"] = ParseSchedule(settings.DeforumAngle, "Deforum angle schedule"),
            ["deforum_translation_x"] = ParseSchedule(settings.DeforumTranslationX, "Deforum translation X schedule"),
            ["deforum_translation_y"] = ParseSchedule(settings.DeforumTranslationY, "Deforum translation Y schedule"),
            ["deforum_translation_z"] = ParseSchedule(settings.DeforumTranslationZ, "Deforum translation Z schedule"),
            ["deforum_rotation_3d_x"] = ParseSchedule(settings.DeforumRotationX, "Deforum rotation X schedule"),
            ["deforum_rotation_3d_y"] = ParseSchedule(settings.DeforumRotationY, "Deforum rotation Y schedule"),
            ["deforum_rotation_3d_z"] = ParseSchedule(settings.DeforumRotationZ, "Deforum rotation Z schedule"),
            ["deforum_fov"] = ParseSchedule(settings.DeforumFov, "Deforum FOV schedule"),
            ["deforum_strength_schedule"] = ParseSchedule(settings.DeforumStrength, "Deforum strength schedule"),
            ["deforum_cfg_scale_schedule"] = ParseSchedule(settings.DeforumCfg, "Deforum CFG schedule"),
            ["deforum_steps_schedule"] = ParseSchedule(settings.DeforumSteps, "Deforum steps schedule"),
            ["deforum_denoise_schedule"] = ParseSchedule(settings.DeforumDenoise, "Deforum denoise schedule"),
        };

        using JsonDocument document = JsonDocument.Parse(request.ToJsonString());
        return document.RootElement.Clone();
    }

    public static JsonNode? ParseSchedule(string value, string label)
    {
        string schedule = value.Trim();
        if (schedule.Length == 0)
        {
            return null;
        }

        return schedule.StartsWith('{')
            ? ParseObject(schedule, label)
            : JsonValue.Create(schedule);
    }

    private static void Validate(InternalVideoRenderSettings settings)
    {
        Range(settings.OutputFps, 1, 60, "Output FPS");
        Range(settings.RenderFps, 1, 30, "Render FPS");
        Range(settings.Width, 256, 1920, "Width");
        Range(settings.Height, 256, 1080, "Height");
        Range(settings.Steps, 1, 80, "Steps");
        Range(settings.Cfg, 1.0, 20.0, "CFG");
        Range(settings.KeyframeIntervalSeconds, 0.5, 60.0, "Keyframe interval");
        Range(settings.TemporalStrength, 0.01, 0.99, "Temporal strength");
        OptionalRange(settings.TemporalSteps, 1, 80, "Temporal steps");
        Range(settings.RefineEveryNFrames, 1, 30, "Refine every N frames");
        Range(settings.AnchorStrength, 0.0, 1.0, "Anchor strength");
        Range(settings.StoryboardShotMaxSeconds, 1.0, 12.0, "Storyboard shot maximum");
        Range(settings.VideoModelMaxFramesPerScene, 8, 96, "Video model frames per scene");
        Range(settings.VideoModelMotionBucketId, 1, 255, "Video model motion bucket");
        Range(settings.VideoModelNoiseAugStrength, 0.0, 1.0, "Video model noise augmentation");
        Range(settings.VideoModelDecodeChunkSize, 1, 64, "Video model decode chunk size");
        Range(settings.VideoModelManualMotionScore, 1, 7, "Video model manual motion score");
        Range(settings.SourceStrength, 0.05, 0.95, "Source strength");
        if (settings.RefinerEnabled)
        {
            Range(settings.RefinerSwitchAt, 0.0, 1.0, "Refiner switch point");
            OptionalRange(settings.RefinerSteps, 1, 80, "Refiner steps");
        }
        Enum(settings.RenderMode, ["auto", "diffusion", "hosted", "tensorrt"], "Render mode");
        Enum(settings.RenderTier, ["auto", "draft", "balanced", "quality"], "Render tier");
        Enum(settings.TemporalMode, ["off", "keyframes", "frame_img2img", "video_model"], "Temporal mode");
        Enum(settings.KeyframeContinuityMode, ["scene", "project"], "Keyframe continuity mode");
        Enum(settings.InterpolationEngine, ["auto", "minterpolate", "fps", "rife"], "Interpolation engine");
        Enum(settings.HostedService, ["default", "core", "ultra", "sd3"], "Hosted service");
        Enum(settings.DevicePreference, ["auto", "cpu", "cuda", "mps", "directml"], "Device preference");
        Enum(settings.VideoModelEngine, ["auto", "svd", "animatediff"], "Video model engine");
        Enum(settings.MotionStrategy, ["manual", "storyboard_full_motion"], "Motion strategy");
        Enum(settings.VideoModelDtype, ["auto", "float16", "bfloat16", "float32"], "Video model dtype");
        Enum(settings.VideoModelMotionScoreMode, ["auto", "manual", "off"], "Motion score mode");
        Enum(settings.VideoModelAnchorMode, ["start", "end", "both", "loop"], "Anchor mode");
        Enum(settings.VideoModelSceneMotion, ["camera", "subject", "scene"], "Scene motion");
        Enum(settings.VideoModelKeyframeRenderer, ["internal", "tensorrt_sd15"], "Keyframe renderer");
    }

    private static JsonNode? BuildRefiner(InternalVideoRenderSettings settings) =>
        settings.RefinerEnabled
            ? new JsonObject
            {
                ["model"] = Optional(settings.RefinerModelId),
                ["switch_at"] = settings.RefinerSwitchAt,
                ["steps"] = settings.RefinerSteps,
            }
            : null;

    private static JsonArray ParseLoras(string value)
    {
        var result = new JsonArray();
        foreach (string entry in value.Split([',', ';', '\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            string[] parts = entry.Split('@', 2, StringSplitOptions.TrimEntries);
            if (parts[0].Length == 0)
            {
                continue;
            }

            double weight = parts.Length == 2
                && double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed)
                    ? Math.Clamp(parsed, -4.0, 4.0)
                    : 1.0;
            result.Add(new JsonObject { ["name"] = parts[0], ["weight"] = weight });
        }

        return result;
    }

    private static JsonNode? ParseOptionalObject(string value, string label) =>
        string.IsNullOrWhiteSpace(value) ? null : ParseObject(value, label);

    private static JsonNode ParseObject(string value, string label)
    {
        try
        {
            JsonNode? node = JsonNode.Parse(value);
            return node is JsonObject
                ? node
                : throw new InvalidOperationException($"{label} must be a JSON object.");
        }
        catch (JsonException exception)
        {
            throw new InvalidOperationException($"{label} contains invalid JSON: {exception.Message}", exception);
        }
    }

    private static string Required(string? value, string label) =>
        string.IsNullOrWhiteSpace(value)
            ? throw new InvalidOperationException($"{label} is required.")
            : value.Trim();

    private static string? Optional(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static void Enum(string value, string[] allowed, string label)
    {
        if (!allowed.Contains(value))
        {
            throw new InvalidOperationException($"{label} must be one of: {string.Join(", ", allowed)}.");
        }
    }

    private static void Range(double value, double minimum, double maximum, string label)
    {
        if (value < minimum || value > maximum)
        {
            throw new InvalidOperationException($"{label} must be between {minimum} and {maximum}.");
        }
    }

    private static void OptionalRange(int? value, int minimum, int maximum, string label)
    {
        if (value.HasValue)
        {
            Range(value.Value, minimum, maximum, label);
        }
    }
}
