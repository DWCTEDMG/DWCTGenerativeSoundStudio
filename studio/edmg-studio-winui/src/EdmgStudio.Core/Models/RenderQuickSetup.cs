namespace EdmgStudio.Core.Models;

public sealed record RenderQuickSetup(
    string Goal,
    string Route,
    string Quality,
    string RenderTier,
    string TemporalMode,
    string VideoModelEngine,
    string MotionStrategy,
    int Steps,
    double Cfg,
    int RenderFps,
    int MotionFps,
    int OutputFps,
    int MaximumFrames,
    int Width,
    int Height)
{
    public bool OpensTimeline => Goal == "edit";

    public static RenderQuickSetup Resolve(
        string goal,
        string quality,
        string resolution,
        int outputFps)
    {
        goal = NormalizeGoal(goal);
        quality = NormalizeQuality(quality);

        (string tier, int steps, double cfg, int renderFps, int motionFps, int maximumFrames) = quality switch
        {
            "fast" => ("draft", 12, 5.5, 2, 8, 120),
            "quality" => ("quality", 36, 7.5, 4, 18, 480),
            "ultra" => ("quality", 50, 8.0, 6, 24, 720),
            _ => ("balanced", 24, 7.0, 3, 12, 240),
        };

        (int width, int height) = resolution switch
        {
            "1024x576" => (1024, 576),
            "1280x720" => (1280, 720),
            "1920x1080" => (1920, 1080),
            "1024x1024" => (1024, 1024),
            "864x1080" => (864, 1080),
            "576x1024" => (576, 1024),
            _ => (768, 432),
        };

        (string route, string temporalMode, string engine, string strategy) = goal switch
        {
            "stills" => ("stills", "off", "auto", "manual"),
            "motion_ad" => ("motion", "video_model", "animatediff", "storyboard_full_motion"),
            "motion_svd" => ("motion", "video_model", "svd", "storyboard_full_motion"),
            "full_video" => ("internal", "video_model", "auto", "storyboard_full_motion"),
            "edit" => ("timeline", "off", "auto", "manual"),
            _ => ("pipeline", "keyframes", "auto", "automatic"),
        };

        return new RenderQuickSetup(
            goal,
            route,
            quality,
            tier,
            temporalMode,
            engine,
            strategy,
            steps,
            cfg,
            renderFps,
            motionFps,
            Math.Clamp(outputFps, 1, 60),
            maximumFrames,
            width,
            height);
    }

    private static string NormalizeGoal(string goal)
    {
        string normalized = string.IsNullOrWhiteSpace(goal) ? "auto" : goal.Trim().ToLowerInvariant();
        return normalized is "auto" or "stills" or "motion_ad" or "motion_svd" or "full_video" or "edit"
            ? normalized
            : "auto";
    }

    private static string NormalizeQuality(string quality)
    {
        string normalized = string.IsNullOrWhiteSpace(quality) ? "balanced" : quality.Trim().ToLowerInvariant();
        return normalized is "fast" or "balanced" or "quality" or "ultra"
            ? normalized
            : "balanced";
    }
}
