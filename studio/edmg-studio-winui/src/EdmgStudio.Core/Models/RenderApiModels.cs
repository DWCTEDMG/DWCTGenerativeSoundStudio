using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

internal static class RenderContractValidation
{
    internal static int Range(int value, int minimum, int maximum, string parameterName)
    {
        if (value < minimum || value > maximum)
        {
            throw new ArgumentOutOfRangeException(
                parameterName,
                value,
                $"{parameterName} must be between {minimum} and {maximum}.");
        }

        return value;
    }

    internal static int Minimum(int value, int minimum, string parameterName)
    {
        if (value < minimum)
        {
            throw new ArgumentOutOfRangeException(parameterName, value, $"{parameterName} must be at least {minimum}.");
        }

        return value;
    }

    internal static double Range(double value, double minimum, double maximum, string parameterName)
    {
        if (!double.IsFinite(value) || value < minimum || value > maximum)
        {
            throw new ArgumentOutOfRangeException(
                parameterName,
                value,
                $"{parameterName} must be between {minimum} and {maximum}.");
        }

        return value;
    }

    internal static double Minimum(double value, double minimum, string parameterName)
    {
        if (!double.IsFinite(value) || value < minimum)
        {
            throw new ArgumentOutOfRangeException(parameterName, value, $"{parameterName} must be at least {minimum}.");
        }

        return value;
    }

    internal static string RequiredText(string value, int maximumLength, string parameterName)
    {
        ArgumentNullException.ThrowIfNull(value, parameterName);
        if (value.Length == 0)
        {
            throw new ArgumentException("A value is required.", parameterName);
        }

        if (value.Length > maximumLength)
        {
            throw new ArgumentOutOfRangeException(
                parameterName,
                value.Length,
                $"{parameterName} cannot exceed {maximumLength} characters.");
        }

        return value;
    }

    internal static string? OptionalText(string? value, int maximumLength, string parameterName)
    {
        if (value is not null && value.Length > maximumLength)
        {
            throw new ArgumentOutOfRangeException(
                parameterName,
                value.Length,
                $"{parameterName} cannot exceed {maximumLength} characters.");
        }

        return value;
    }

    internal static string Choice(string value, string parameterName, params string[] allowed)
    {
        if (!allowed.Contains(value, StringComparer.Ordinal))
        {
            throw new ArgumentException(
                $"{parameterName} must be one of: {string.Join(", ", allowed)}.",
                parameterName);
        }

        return value;
    }
}

public sealed record LoraSelection
{
    public LoraSelection(string name, double weight = 1.0, double? clipWeight = null)
    {
        Name = RenderContractValidation.RequiredText(name, 260, nameof(name));
        Weight = RenderContractValidation.Range(weight, -4.0, 4.0, nameof(weight));
        ClipWeight = clipWeight is null
            ? null
            : RenderContractValidation.Range(clipWeight.Value, -4.0, 4.0, nameof(clipWeight));
    }

    [JsonPropertyName("name")]
    public string Name { get; }

    [JsonPropertyName("weight")]
    public double Weight { get; }

    [JsonPropertyName("clip_weight")]
    public double? ClipWeight { get; }
}

public sealed record ControlNetUnit
{
    public ControlNetUnit(
        string model,
        string referenceAsset,
        string conditioningMode = "raw",
        double strength = 0.8,
        double startPercent = 0.0,
        double endPercent = 1.0)
    {
        Model = RenderContractValidation.RequiredText(model, 260, nameof(model));
        ReferenceAsset = RenderContractValidation.RequiredText(referenceAsset, 1024, nameof(referenceAsset));
        ConditioningMode = RenderContractValidation.Choice(
            conditioningMode,
            nameof(conditioningMode),
            "raw",
            "blur",
            "edge",
            "external");
        Strength = RenderContractValidation.Range(strength, 0.0, 2.0, nameof(strength));
        StartPercent = RenderContractValidation.Range(startPercent, 0.0, 1.0, nameof(startPercent));
        EndPercent = RenderContractValidation.Range(endPercent, 0.0, 1.0, nameof(endPercent));
    }

    [JsonPropertyName("model")]
    public string Model { get; }

    [JsonPropertyName("reference_asset")]
    public string ReferenceAsset { get; }

    [JsonPropertyName("conditioning_mode")]
    public string ConditioningMode { get; }

    [JsonPropertyName("strength")]
    public double Strength { get; }

    [JsonPropertyName("start_percent")]
    public double StartPercent { get; }

    [JsonPropertyName("end_percent")]
    public double EndPercent { get; }
}

public sealed record HiresFixSettings
{
    public HiresFixSettings(
        bool enabled = true,
        double scale = 1.5,
        int? steps = null,
        double denoise = 0.35,
        string? upscaler = null)
    {
        Enabled = enabled;
        Scale = RenderContractValidation.Range(scale, 1.0, 4.0, nameof(scale));
        Steps = steps is null ? null : RenderContractValidation.Range(steps.Value, 1, 80, nameof(steps));
        Denoise = RenderContractValidation.Range(denoise, 0.0, 1.0, nameof(denoise));
        Upscaler = upscaler;
    }

    [JsonPropertyName("enabled")]
    public bool Enabled { get; }

    [JsonPropertyName("scale")]
    public double Scale { get; }

    [JsonPropertyName("steps")]
    public int? Steps { get; }

    [JsonPropertyName("denoise")]
    public double Denoise { get; }

    [JsonPropertyName("upscaler")]
    public string? Upscaler { get; }
}

public sealed record RefinerSettings
{
    public RefinerSettings(string? model = null, double switchAt = 0.8, int? steps = null)
    {
        Model = model;
        SwitchAt = RenderContractValidation.Range(switchAt, 0.0, 1.0, nameof(switchAt));
        Steps = steps is null ? null : RenderContractValidation.Range(steps.Value, 1, 80, nameof(steps));
    }

    [JsonPropertyName("model")]
    public string? Model { get; }

    [JsonPropertyName("switch_at")]
    public double SwitchAt { get; }

    [JsonPropertyName("steps")]
    public int? Steps { get; }
}

public sealed record OutpaintSettings
{
    public OutpaintSettings(int topPx = 0, int rightPx = 0, int bottomPx = 0, int leftPx = 0)
    {
        TopPx = RenderContractValidation.Range(topPx, 0, 4096, nameof(topPx));
        RightPx = RenderContractValidation.Range(rightPx, 0, 4096, nameof(rightPx));
        BottomPx = RenderContractValidation.Range(bottomPx, 0, 4096, nameof(bottomPx));
        LeftPx = RenderContractValidation.Range(leftPx, 0, 4096, nameof(leftPx));
    }

    [JsonPropertyName("top_px")]
    public int TopPx { get; }

    [JsonPropertyName("right_px")]
    public int RightPx { get; }

    [JsonPropertyName("bottom_px")]
    public int BottomPx { get; }

    [JsonPropertyName("left_px")]
    public int LeftPx { get; }
}

public sealed record RenderScenesRequest
{
    public RenderScenesRequest(
        int variantIndex = 0,
        string? modelId = null,
        string? checkpoint = null,
        string workflowFamily = "auto",
        long? seed = null,
        string? referenceAsset = null,
        string? sourceAsset = null,
        string? inpaintMask = null,
        OutpaintSettings? outpaint = null,
        string conditioningMode = "raw",
        string? controlnetModel = null,
        double controlnetStrength = 0.8,
        IReadOnlyList<LoraSelection>? loras = null,
        IReadOnlyList<ControlNetUnit>? controlnetUnits = null,
        string? vae = null,
        double denoiseStrength = 0.75,
        HiresFixSettings? hiresFix = null,
        RefinerSettings? refiner = null,
        string? upscaler = null,
        int width = 1024,
        int height = 576,
        int steps = 28,
        double cfg = 7.0,
        string sampler = "euler",
        string negativePrompt = "blurry, low quality, watermark, text, logo")
    {
        VariantIndex = variantIndex;
        ModelId = modelId;
        Checkpoint = checkpoint;
        WorkflowFamily = RenderContractValidation.Choice(
            workflowFamily,
            nameof(workflowFamily),
            "auto",
            "txt2img",
            "img2img",
            "inpaint",
            "outpaint",
            "controlnet");
        Seed = seed;
        ReferenceAsset = referenceAsset;
        SourceAsset = sourceAsset;
        InpaintMask = inpaintMask;
        Outpaint = outpaint;
        ConditioningMode = RenderContractValidation.Choice(
            conditioningMode,
            nameof(conditioningMode),
            "raw",
            "blur",
            "edge",
            "external");
        ControlnetModel = controlnetModel;
        ControlnetStrength = RenderContractValidation.Range(controlnetStrength, 0.0, 2.0, nameof(controlnetStrength));
        Loras = loras ?? [];
        ControlnetUnits = controlnetUnits ?? [];
        Vae = vae;
        DenoiseStrength = RenderContractValidation.Range(denoiseStrength, 0.0, 1.0, nameof(denoiseStrength));
        HiresFix = hiresFix;
        Refiner = refiner;
        Upscaler = upscaler;
        Width = width;
        Height = height;
        Steps = steps;
        Cfg = cfg;
        ArgumentNullException.ThrowIfNull(sampler);
        Sampler = sampler;
        NegativePrompt = negativePrompt;
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("model_id")]
    public string? ModelId { get; }
    [JsonPropertyName("checkpoint")]
    public string? Checkpoint { get; }
    [JsonPropertyName("workflow_family")]
    public string WorkflowFamily { get; }
    [JsonPropertyName("seed")]
    public long? Seed { get; }
    [JsonPropertyName("reference_asset")]
    public string? ReferenceAsset { get; }
    [JsonPropertyName("source_asset")]
    public string? SourceAsset { get; }
    [JsonPropertyName("inpaint_mask")]
    public string? InpaintMask { get; }
    [JsonPropertyName("outpaint")]
    public OutpaintSettings? Outpaint { get; }
    [JsonPropertyName("conditioning_mode")]
    public string ConditioningMode { get; }
    [JsonPropertyName("controlnet_model")]
    public string? ControlnetModel { get; }
    [JsonPropertyName("controlnet_strength")]
    public double ControlnetStrength { get; }
    [JsonPropertyName("loras")]
    public IReadOnlyList<LoraSelection> Loras { get; }
    [JsonPropertyName("controlnet_units")]
    public IReadOnlyList<ControlNetUnit> ControlnetUnits { get; }
    [JsonPropertyName("vae")]
    public string? Vae { get; }
    [JsonPropertyName("denoise_strength")]
    public double DenoiseStrength { get; }
    [JsonPropertyName("hires_fix")]
    public HiresFixSettings? HiresFix { get; }
    [JsonPropertyName("refiner")]
    public RefinerSettings? Refiner { get; }
    [JsonPropertyName("upscaler")]
    public string? Upscaler { get; }
    [JsonPropertyName("width")]
    public int Width { get; }
    [JsonPropertyName("height")]
    public int Height { get; }
    [JsonPropertyName("steps")]
    public int Steps { get; }
    [JsonPropertyName("cfg")]
    public double Cfg { get; }
    [JsonPropertyName("sampler")]
    public string Sampler { get; }
    [JsonPropertyName("negative_prompt")]
    public string NegativePrompt { get; }
}

public sealed record RenderMotionRequest
{
    public RenderMotionRequest(
        int variantIndex = 0,
        string? modelId = null,
        string? checkpoint = null,
        string? svdModelId = null,
        string engine = "animatediff",
        long? seed = null,
        int fps = 12,
        int maxFramesPerScene = 240,
        int width = 768,
        int height = 432,
        int steps = 24,
        double cfg = 6.5,
        string sampler = "euler",
        string negativePrompt = "blurry, low quality, watermark, text, logo",
        IReadOnlyList<LoraSelection>? loras = null,
        string? vae = null,
        string motionModelName = "mm_sd_v15_v2.ckpt",
        int contextLength = 16,
        int contextOverlap = 4,
        string betaSchedule = "autoselect",
        string svdCheckpoint = "svd_xt.safetensors",
        int svdNumSteps = 25,
        int svdMotionBucketId = 127,
        int svdFpsId = 6,
        double svdCondAug = 0.02,
        int svdDecodingT = 14,
        string device = "cuda")
    {
        VariantIndex = variantIndex;
        ModelId = modelId;
        Checkpoint = checkpoint;
        SvdModelId = svdModelId;
        Engine = RenderContractValidation.Choice(engine, nameof(engine), "animatediff", "svd");
        Seed = seed;
        Fps = RenderContractValidation.Range(fps, 1, 60, nameof(fps));
        MaxFramesPerScene = RenderContractValidation.Range(maxFramesPerScene, 1, 4000, nameof(maxFramesPerScene));
        Width = width;
        Height = height;
        Steps = steps;
        Cfg = cfg;
        ArgumentNullException.ThrowIfNull(sampler);
        Sampler = sampler;
        NegativePrompt = negativePrompt;
        Loras = loras ?? [];
        Vae = vae;
        MotionModelName = motionModelName;
        ContextLength = contextLength;
        ContextOverlap = contextOverlap;
        BetaSchedule = betaSchedule;
        SvdCheckpoint = svdCheckpoint;
        SvdNumSteps = svdNumSteps;
        SvdMotionBucketId = svdMotionBucketId;
        SvdFpsId = svdFpsId;
        SvdCondAug = svdCondAug;
        SvdDecodingT = svdDecodingT;
        Device = RenderContractValidation.Choice(device, nameof(device), "cuda", "cpu");
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("model_id")]
    public string? ModelId { get; }
    [JsonPropertyName("checkpoint")]
    public string? Checkpoint { get; }
    [JsonPropertyName("svd_model_id")]
    public string? SvdModelId { get; }
    [JsonPropertyName("engine")]
    public string Engine { get; }
    [JsonPropertyName("seed")]
    public long? Seed { get; }
    [JsonPropertyName("fps")]
    public int Fps { get; }
    [JsonPropertyName("max_frames_per_scene")]
    public int MaxFramesPerScene { get; }
    [JsonPropertyName("width")]
    public int Width { get; }
    [JsonPropertyName("height")]
    public int Height { get; }
    [JsonPropertyName("steps")]
    public int Steps { get; }
    [JsonPropertyName("cfg")]
    public double Cfg { get; }
    [JsonPropertyName("sampler")]
    public string Sampler { get; }
    [JsonPropertyName("negative_prompt")]
    public string NegativePrompt { get; }
    [JsonPropertyName("loras")]
    public IReadOnlyList<LoraSelection> Loras { get; }
    [JsonPropertyName("vae")]
    public string? Vae { get; }
    [JsonPropertyName("motion_model_name")]
    public string MotionModelName { get; }
    [JsonPropertyName("context_length")]
    public int ContextLength { get; }
    [JsonPropertyName("context_overlap")]
    public int ContextOverlap { get; }
    [JsonPropertyName("beta_schedule")]
    public string BetaSchedule { get; }
    [JsonPropertyName("svd_checkpoint")]
    public string SvdCheckpoint { get; }
    [JsonPropertyName("svd_num_steps")]
    public int SvdNumSteps { get; }
    [JsonPropertyName("svd_motion_bucket_id")]
    public int SvdMotionBucketId { get; }
    [JsonPropertyName("svd_fps_id")]
    public int SvdFpsId { get; }
    [JsonPropertyName("svd_cond_aug")]
    public double SvdCondAug { get; }
    [JsonPropertyName("svd_decoding_t")]
    public int SvdDecodingT { get; }
    [JsonPropertyName("device")]
    public string Device { get; }
}

public sealed record TensorRtStandaloneRenderRequest
{
    public TensorRtStandaloneRenderRequest(
        int variantIndex = 0,
        string? modelId = null,
        string? prompt = null,
        long? seed = null,
        int width = 1024,
        int height = 1024,
        int steps = 28,
        double cfg = 7.0,
        string sampler = "pndm",
        string negativePrompt = "blurry, low quality, watermark, text, logo",
        int batchSize = 1)
    {
        VariantIndex = RenderContractValidation.Range(variantIndex, 0, 9999, nameof(variantIndex));
        ModelId = RenderContractValidation.OptionalText(modelId, 260, nameof(modelId));
        Prompt = RenderContractValidation.OptionalText(prompt, 10_000, nameof(prompt));
        if (seed is < 0 or > 4_294_967_295)
        {
            throw new ArgumentOutOfRangeException(nameof(seed), seed, "seed must fit in an unsigned 32-bit integer.");
        }

        Seed = seed;
        Width = RenderContractValidation.Range(width, 256, 1920, nameof(width));
        Height = RenderContractValidation.Range(height, 256, 1080, nameof(height));
        Steps = RenderContractValidation.Range(steps, 1, 80, nameof(steps));
        Cfg = RenderContractValidation.Range(cfg, 1.0, 20.0, nameof(cfg));
        Sampler = RenderContractValidation.RequiredText(sampler, 64, nameof(sampler));
        NegativePrompt = RenderContractValidation.OptionalText(negativePrompt, 10_000, nameof(negativePrompt))!;
        BatchSize = RenderContractValidation.Range(batchSize, 1, 8, nameof(batchSize));
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("model_id")]
    public string? ModelId { get; }
    [JsonPropertyName("prompt")]
    public string? Prompt { get; }
    [JsonPropertyName("seed")]
    public long? Seed { get; }
    [JsonPropertyName("width")]
    public int Width { get; }
    [JsonPropertyName("height")]
    public int Height { get; }
    [JsonPropertyName("steps")]
    public int Steps { get; }
    [JsonPropertyName("cfg")]
    public double Cfg { get; }
    [JsonPropertyName("sampler")]
    public string Sampler { get; }
    [JsonPropertyName("negative_prompt")]
    public string NegativePrompt { get; }
    [JsonPropertyName("batch_size")]
    public int BatchSize { get; }
}

public sealed record AutoAnimateRequest
{
    public AutoAnimateRequest(
        string preset = "balanced_motion",
        string engine = "auto",
        int variantIndex = 0,
        string? sourceAsset = null,
        bool run = true,
        int? fps = null)
    {
        Preset = preset;
        Engine = RenderContractValidation.Choice(engine, nameof(engine), "auto", "internal", "comfyui");
        VariantIndex = variantIndex;
        SourceAsset = sourceAsset;
        Run = run;
        Fps = fps is null ? null : RenderContractValidation.Range(fps.Value, 1, 60, nameof(fps));
    }

    [JsonPropertyName("preset")]
    public string Preset { get; }
    [JsonPropertyName("engine")]
    public string Engine { get; }
    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("source_asset")]
    public string? SourceAsset { get; }
    [JsonPropertyName("run")]
    public bool Run { get; }
    [JsonPropertyName("fps")]
    public int? Fps { get; }
}

public sealed record ParseqMotionApplyRequest
{
    public ParseqMotionApplyRequest(
        int variantIndex = 0,
        int fps = 24,
        JsonElement? manifest = null,
        bool activate = true)
    {
        VariantIndex = variantIndex;
        Fps = RenderContractValidation.Range(fps, 1, 60, nameof(fps));
        Manifest = manifest;
        Activate = activate;
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("fps")]
    public int Fps { get; }
    [JsonPropertyName("manifest")]
    public JsonElement? Manifest { get; }
    [JsonPropertyName("activate")]
    public bool Activate { get; }
}

public sealed record LayerMaskSpec
{
    public LayerMaskSpec(
        string maskAsset,
        string? prompt = null,
        double depth = 1.0,
        double motionScale = 1.0,
        double strength = 1.0)
    {
        ArgumentNullException.ThrowIfNull(maskAsset);
        MaskAsset = maskAsset;
        Prompt = prompt;
        Depth = RenderContractValidation.Range(depth, 0.0, 1.0, nameof(depth));
        MotionScale = RenderContractValidation.Range(motionScale, 0.0, 4.0, nameof(motionScale));
        Strength = RenderContractValidation.Range(strength, 0.0, 2.0, nameof(strength));
    }

    [JsonPropertyName("mask_asset")]
    public string MaskAsset { get; }
    [JsonPropertyName("prompt")]
    public string? Prompt { get; }
    [JsonPropertyName("depth")]
    public double Depth { get; }
    [JsonPropertyName("motion_scale")]
    public double MotionScale { get; }
    [JsonPropertyName("strength")]
    public double Strength { get; }
}

public sealed record LayeredAnimateRequest
{
    public LayeredAnimateRequest(
        string sourceAsset,
        string mode = "parallax",
        string? motion = null,
        int bands = 3,
        IReadOnlyList<LayerMaskSpec>? masks = null,
        double subjectMotion = 1.0,
        double backgroundMotion = 0.12,
        int fps = 24,
        double durationS = 5.0,
        int width = 768,
        int height = 432,
        bool includeAudio = false,
        bool diffusionRefine = false,
        string modelId = "auto",
        string devicePreference = "auto",
        string? refinePrompt = null,
        string refineNegative = "blurry, low quality, watermark, text, logo",
        double refineDenoise = 0.3,
        int refineSteps = 20,
        double refineCfg = 7.0,
        long? seed = null)
    {
        ArgumentNullException.ThrowIfNull(sourceAsset);
        SourceAsset = sourceAsset;
        Mode = RenderContractValidation.Choice(mode, nameof(mode), "parallax", "masked", "segment", "background");
        Motion = motion;
        Bands = RenderContractValidation.Range(bands, 1, 8, nameof(bands));
        Masks = masks ?? [];
        SubjectMotion = RenderContractValidation.Range(subjectMotion, 0.0, 4.0, nameof(subjectMotion));
        BackgroundMotion = RenderContractValidation.Range(backgroundMotion, 0.0, 4.0, nameof(backgroundMotion));
        Fps = RenderContractValidation.Range(fps, 1, 60, nameof(fps));
        DurationS = RenderContractValidation.Range(durationS, 0.5, 120.0, nameof(durationS));
        Width = RenderContractValidation.Range(width, 256, 1920, nameof(width));
        Height = RenderContractValidation.Range(height, 256, 1080, nameof(height));
        IncludeAudio = includeAudio;
        DiffusionRefine = diffusionRefine;
        ModelId = modelId;
        DevicePreference = RenderContractValidation.Choice(
            devicePreference,
            nameof(devicePreference),
            "auto",
            "cpu",
            "cuda",
            "mps",
            "directml");
        RefinePrompt = refinePrompt;
        RefineNegative = refineNegative;
        RefineDenoise = RenderContractValidation.Range(refineDenoise, 0.05, 0.95, nameof(refineDenoise));
        RefineSteps = RenderContractValidation.Range(refineSteps, 1, 80, nameof(refineSteps));
        RefineCfg = RenderContractValidation.Range(refineCfg, 1.0, 20.0, nameof(refineCfg));
        Seed = seed;
    }

    [JsonPropertyName("source_asset")]
    public string SourceAsset { get; }
    [JsonPropertyName("mode")]
    public string Mode { get; }
    [JsonPropertyName("motion")]
    public string? Motion { get; }
    [JsonPropertyName("bands")]
    public int Bands { get; }
    [JsonPropertyName("masks")]
    public IReadOnlyList<LayerMaskSpec> Masks { get; }
    [JsonPropertyName("subject_motion")]
    public double SubjectMotion { get; }
    [JsonPropertyName("background_motion")]
    public double BackgroundMotion { get; }
    [JsonPropertyName("fps")]
    public int Fps { get; }
    [JsonPropertyName("duration_s")]
    public double DurationS { get; }
    [JsonPropertyName("width")]
    public int Width { get; }
    [JsonPropertyName("height")]
    public int Height { get; }
    [JsonPropertyName("include_audio")]
    public bool IncludeAudio { get; }
    [JsonPropertyName("diffusion_refine")]
    public bool DiffusionRefine { get; }
    [JsonPropertyName("model_id")]
    public string ModelId { get; }
    [JsonPropertyName("device_preference")]
    public string DevicePreference { get; }
    [JsonPropertyName("refine_prompt")]
    public string? RefinePrompt { get; }
    [JsonPropertyName("refine_negative")]
    public string RefineNegative { get; }
    [JsonPropertyName("refine_denoise")]
    public double RefineDenoise { get; }
    [JsonPropertyName("refine_steps")]
    public int RefineSteps { get; }
    [JsonPropertyName("refine_cfg")]
    public double RefineCfg { get; }
    [JsonPropertyName("seed")]
    public long? Seed { get; }
}

public sealed record AssembleVideoRequest
{
    public AssembleVideoRequest(int variantIndex = 0, int fps = 30)
    {
        VariantIndex = variantIndex;
        Fps = fps;
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("fps")]
    public int Fps { get; }
}

public sealed record ExportDeforumRequest
{
    public ExportDeforumRequest(
        int variantIndex = 0,
        int fps = 30,
        int width = 1024,
        int height = 576,
        string preset = "cinematic",
        double sensitivity = 1.0)
    {
        VariantIndex = variantIndex;
        Fps = fps;
        Width = width;
        Height = height;
        Preset = RenderContractValidation.Choice(
            preset,
            nameof(preset),
            "cinematic",
            "psychedelic",
            "ambient",
            "narrative",
            "performance",
            "abstract",
            "lyric",
            "product");
        Sensitivity = RenderContractValidation.Range(sensitivity, 0.1, 3.0, nameof(sensitivity));
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("fps")]
    public int Fps { get; }
    [JsonPropertyName("width")]
    public int Width { get; }
    [JsonPropertyName("height")]
    public int Height { get; }
    [JsonPropertyName("preset")]
    public string Preset { get; }
    [JsonPropertyName("sensitivity")]
    public double Sensitivity { get; }
}

public sealed record RenderIntentSection
{
    public RenderIntentSection(
        string sceneId,
        double startS = 0.0,
        double endS = 0.0,
        string? creativeGoal = null,
        double? continuityPriority = null,
        double? speedPriority = null,
        IReadOnlyList<string>? notes = null)
    {
        SceneId = RenderContractValidation.RequiredText(sceneId, 120, nameof(sceneId));
        StartS = RenderContractValidation.Minimum(startS, 0.0, nameof(startS));
        EndS = RenderContractValidation.Minimum(endS, 0.0, nameof(endS));

        CreativeGoal = RenderContractValidation.OptionalText(creativeGoal, 260, nameof(creativeGoal));
        ContinuityPriority = continuityPriority is null
            ? null
            : RenderContractValidation.Range(continuityPriority.Value, 0.0, 1.0, nameof(continuityPriority));
        SpeedPriority = speedPriority is null
            ? null
            : RenderContractValidation.Range(speedPriority.Value, 0.0, 1.0, nameof(speedPriority));
        Notes = notes ?? [];
    }

    [JsonPropertyName("scene_id")]
    public string SceneId { get; }
    [JsonPropertyName("start_s")]
    public double StartS { get; }
    [JsonPropertyName("end_s")]
    public double EndS { get; }
    [JsonPropertyName("creative_goal")]
    public string? CreativeGoal { get; }
    [JsonPropertyName("continuity_priority")]
    public double? ContinuityPriority { get; }
    [JsonPropertyName("speed_priority")]
    public double? SpeedPriority { get; }
    [JsonPropertyName("notes")]
    public IReadOnlyList<string> Notes { get; }
}

public sealed record RenderConductorPlanRequest
{
    private static readonly string[] DefaultEngines =
    [
        "internal",
        "comfyui_still",
        "comfyui_motion",
        "hosted_video",
        "deforum_export",
        "tensorrt_standalone",
    ];

    public RenderConductorPlanRequest(
        int variantIndex = 0,
        string preset = "balanced",
        string aspectRatio = "16:9",
        string outputMode = "full_video",
        string? qualityTier = null,
        double? continuityPriority = null,
        double? speedPriority = null,
        double? styleLockStrength = null,
        IReadOnlyList<string>? allowedEngines = null,
        string fallbackPolicy = "auto",
        IReadOnlyList<RenderIntentSection>? sections = null)
    {
        VariantIndex = RenderContractValidation.Minimum(variantIndex, 0, nameof(variantIndex));
        Preset = RenderContractValidation.Choice(preset, nameof(preset), "fast", "balanced", "quality", "ultra");
        AspectRatio = RenderContractValidation.Choice(aspectRatio, nameof(aspectRatio), "16:9", "9:16", "1:1", "21:9");
        OutputMode = RenderContractValidation.Choice(
            outputMode,
            nameof(outputMode),
            "full_video",
            "scene_batch",
            "preview");
        QualityTier = qualityTier is null
            ? null
            : RenderContractValidation.Choice(
                qualityTier,
                nameof(qualityTier),
                "draft",
                "balanced",
                "quality",
                "ultra");
        ContinuityPriority = OptionalUnitRange(continuityPriority, nameof(continuityPriority));
        SpeedPriority = OptionalUnitRange(speedPriority, nameof(speedPriority));
        StyleLockStrength = OptionalUnitRange(styleLockStrength, nameof(styleLockStrength));
        AllowedEngines = (allowedEngines ?? DefaultEngines)
            .Select(engine => RenderContractValidation.Choice(
                engine,
                nameof(allowedEngines),
                "internal",
                "comfyui_still",
                "comfyui_motion",
                "hosted_video",
                "proxy",
                "deforum_export",
                "tensorrt_standalone"))
            .ToArray();
        FallbackPolicy = RenderContractValidation.Choice(
            fallbackPolicy,
            nameof(fallbackPolicy),
            "auto",
            "strict",
            "manual");
        Sections = sections ?? [];
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("preset")]
    public string Preset { get; }
    [JsonPropertyName("aspect_ratio")]
    public string AspectRatio { get; }
    [JsonPropertyName("output_mode")]
    public string OutputMode { get; }
    [JsonPropertyName("quality_tier")]
    public string? QualityTier { get; }
    [JsonPropertyName("continuity_priority")]
    public double? ContinuityPriority { get; }
    [JsonPropertyName("speed_priority")]
    public double? SpeedPriority { get; }
    [JsonPropertyName("style_lock_strength")]
    public double? StyleLockStrength { get; }
    [JsonPropertyName("allowed_engines")]
    public IReadOnlyList<string> AllowedEngines { get; }
    [JsonPropertyName("fallback_policy")]
    public string FallbackPolicy { get; }
    [JsonPropertyName("sections")]
    public IReadOnlyList<RenderIntentSection> Sections { get; }

    private static double? OptionalUnitRange(double? value, string parameterName) =>
        value is null ? null : RenderContractValidation.Range(value.Value, 0.0, 1.0, parameterName);
}

public sealed record RenderConductorPromoteRequest
{
    public RenderConductorPromoteRequest(
        string? planId = null,
        IReadOnlyList<string>? sceneIds = null,
        string targetEngine = "internal",
        string qualityTier = "quality",
        string? reason = null)
    {
        PlanId = planId;
        SceneIds = sceneIds ?? [];
        TargetEngine = RenderContractValidation.Choice(
            targetEngine,
            nameof(targetEngine),
            "internal",
            "comfyui_still",
            "comfyui_motion",
            "hosted_video",
            "proxy",
            "deforum_export",
            "tensorrt_standalone");
        QualityTier = RenderContractValidation.Choice(
            qualityTier,
            nameof(qualityTier),
            "draft",
            "balanced",
            "quality",
            "ultra");
        Reason = RenderContractValidation.OptionalText(reason, 400, nameof(reason));
    }

    [JsonPropertyName("plan_id")]
    public string? PlanId { get; }
    [JsonPropertyName("scene_ids")]
    public IReadOnlyList<string> SceneIds { get; }
    [JsonPropertyName("target_engine")]
    public string TargetEngine { get; }
    [JsonPropertyName("quality_tier")]
    public string QualityTier { get; }
    [JsonPropertyName("reason")]
    public string? Reason { get; }
}

public sealed record PerformerWorkflowPlanRequest
{
    public PerformerWorkflowPlanRequest(
        int variantIndex = 0,
        IReadOnlyList<string>? sceneIds = null,
        string modelId = "wan_s2v_14b")
    {
        VariantIndex = RenderContractValidation.Minimum(variantIndex, 0, nameof(variantIndex));
        SceneIds = sceneIds ?? [];
        ArgumentNullException.ThrowIfNull(modelId);
        ModelId = RenderContractValidation.OptionalText(modelId, 120, nameof(modelId))!;
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("scene_ids")]
    public IReadOnlyList<string> SceneIds { get; }
    [JsonPropertyName("model_id")]
    public string ModelId { get; }
}

public sealed record PerformerWorkflowRunRequest
{
    public PerformerWorkflowRunRequest(
        int variantIndex = 0,
        string? planId = null,
        string provider = "auto",
        bool allowMockFallback = false,
        IReadOnlyDictionary<string, JsonElement>? renderSettings = null)
    {
        VariantIndex = RenderContractValidation.Minimum(variantIndex, 0, nameof(variantIndex));
        PlanId = RenderContractValidation.OptionalText(planId, 160, nameof(planId));
        Provider = RenderContractValidation.Choice(provider, nameof(provider), "auto", "high_end", "mock");
        AllowMockFallback = allowMockFallback;
        RenderSettings = renderSettings ?? new Dictionary<string, JsonElement>();
    }

    [JsonPropertyName("variant_index")]
    public int VariantIndex { get; }
    [JsonPropertyName("plan_id")]
    public string? PlanId { get; }
    [JsonPropertyName("provider")]
    public string Provider { get; }
    [JsonPropertyName("allow_mock_fallback")]
    public bool AllowMockFallback { get; }
    [JsonPropertyName("render_settings")]
    public IReadOnlyDictionary<string, JsonElement> RenderSettings { get; }
}

public sealed record PipelineRunOptions(
    int VariantIndex = 0,
    string Preset = "balanced",
    string Mode = "auto",
    string Engine = "auto");

public sealed record MotionSequencerOptions(int VariantIndex = 0, int Fps = 24);

public sealed record ComfyUiWorkflowExportOptions(
    int VariantIndex = 0,
    string? ModelId = null,
    string WorkflowFamily = "auto",
    string? SourceAsset = null,
    string? ReferenceAsset = null,
    string? InpaintMask = null,
    string? ControlnetModel = null,
    string ConditioningMode = "raw",
    int Width = 1024,
    int Height = 576,
    int Steps = 28,
    double Cfg = 7.0,
    string Sampler = "euler",
    string NegativePrompt = "blurry, low quality, watermark, text, logo",
    long? Seed = null,
    double DenoiseStrength = 0.75,
    string? LorasJson = null,
    string? OutpaintJson = null,
    string? ControlnetUnitsJson = null,
    string? HiresFixJson = null,
    string? RefinerJson = null,
    string? Upscaler = null);
