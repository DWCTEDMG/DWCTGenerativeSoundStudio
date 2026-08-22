using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class RenderQuickSetupTests
{
    [TestMethod]
    public void Resolve_FullVideoQuality_UsesVideoModelSettings()
    {
        RenderQuickSetup setup = RenderQuickSetup.Resolve("full_video", "quality", "1920x1080", 24);

        Assert.AreEqual("internal", setup.Route);
        Assert.AreEqual("video_model", setup.TemporalMode);
        Assert.AreEqual("storyboard_full_motion", setup.MotionStrategy);
        Assert.AreEqual("auto", setup.VideoModelEngine);
        Assert.AreEqual(36, setup.Steps);
        Assert.AreEqual(4, setup.RenderFps);
        Assert.AreEqual(480, setup.MaximumFrames);
        Assert.AreEqual(1920, setup.Width);
        Assert.AreEqual(1080, setup.Height);
    }

    [TestMethod]
    public void Resolve_AnimateDiffFast_UsesDraftMotionSettings()
    {
        RenderQuickSetup setup = RenderQuickSetup.Resolve("motion_ad", "fast", "768x432", 12);

        Assert.AreEqual("motion", setup.Route);
        Assert.AreEqual("draft", setup.RenderTier);
        Assert.AreEqual("animatediff", setup.VideoModelEngine);
        Assert.AreEqual(12, setup.Steps);
        Assert.AreEqual(5.5, setup.Cfg);
        Assert.AreEqual(120, setup.MaximumFrames);
        Assert.AreEqual(12, setup.OutputFps);
    }

    [TestMethod]
    public void Resolve_EditGoal_OpensTimeline()
    {
        RenderQuickSetup setup = RenderQuickSetup.Resolve("edit", "balanced", "1280x720", 24);

        Assert.IsTrue(setup.OpensTimeline);
        Assert.AreEqual("timeline", setup.Route);
    }

    [DataTestMethod]
    [DataRow("auto", "pipeline")]
    [DataRow("stills", "stills")]
    [DataRow("motion_ad", "motion")]
    [DataRow("motion_svd", "motion")]
    [DataRow("full_video", "internal")]
    [DataRow("edit", "timeline")]
    public void Resolve_MapsEveryGoalToItsWorkflow(string goal, string route)
    {
        RenderQuickSetup setup = RenderQuickSetup.Resolve(goal, "balanced", "768x432", 24);

        Assert.AreEqual(route, setup.Route);
    }

    [DataTestMethod]
    [DataRow("fast", 12, 5.5, 2, 8, 120)]
    [DataRow("balanced", 24, 7.0, 3, 12, 240)]
    [DataRow("quality", 36, 7.5, 4, 18, 480)]
    [DataRow("ultra", 50, 8.0, 6, 24, 720)]
    public void Resolve_MapsEveryQuality(
        string quality,
        int steps,
        double cfg,
        int renderFps,
        int motionFps,
        int maximumFrames)
    {
        RenderQuickSetup setup = RenderQuickSetup.Resolve("motion_ad", quality, "768x432", 24);

        Assert.AreEqual(quality, setup.Quality);
        Assert.AreEqual(steps, setup.Steps);
        Assert.AreEqual(cfg, setup.Cfg);
        Assert.AreEqual(renderFps, setup.RenderFps);
        Assert.AreEqual(motionFps, setup.MotionFps);
        Assert.AreEqual(maximumFrames, setup.MaximumFrames);
    }

    [DataTestMethod]
    [DataRow("768x432", 768, 432)]
    [DataRow("1024x576", 1024, 576)]
    [DataRow("1280x720", 1280, 720)]
    [DataRow("1920x1080", 1920, 1080)]
    [DataRow("1024x1024", 1024, 1024)]
    [DataRow("864x1080", 864, 1080)]
    [DataRow("576x1024", 576, 1024)]
    public void Resolve_MapsEveryResolution(string resolution, int width, int height)
    {
        RenderQuickSetup setup = RenderQuickSetup.Resolve("auto", "balanced", resolution, 24);

        Assert.AreEqual(width, setup.Width);
        Assert.AreEqual(height, setup.Height);
    }

    [TestMethod]
    public void Resolve_NormalizesUnknownValuesAndClampsFps()
    {
        RenderQuickSetup low = RenderQuickSetup.Resolve("unknown", "unknown", "unknown", -5);
        RenderQuickSetup high = RenderQuickSetup.Resolve("auto", "balanced", "768x432", 120);

        Assert.AreEqual("auto", low.Goal);
        Assert.AreEqual("pipeline", low.Route);
        Assert.AreEqual("balanced", low.Quality);
        Assert.AreEqual(768, low.Width);
        Assert.AreEqual(432, low.Height);
        Assert.AreEqual(1, low.OutputFps);
        Assert.AreEqual(60, high.OutputFps);
    }
}
