using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ModelRenderGuidanceTests
{
    [TestMethod]
    public void Evaluate_AutoSelection_PrefersInstalledCompatiblePrimary()
    {
        ModelCatalogueResponse catalogue = Catalogue(
            Entry("sdxl", "SDXL", "diffusers", installed: false, family: "sdxl",
                hardware: ["discrete_gpu"], render: Render("internal", ["internal_video"])),
            Entry("sd15", "SD 1.5", "diffusers", installed: true, family: "sd15",
                hardware: ["cpu"], render: Render("internal", ["internal_video"])));

        ModelRenderGuidance result = ModelRenderGuidanceEvaluator.Evaluate(
            catalogue,
            Config(device: "cpu"));

        Assert.AreEqual("sd15", result.Primary?.ModelId);
        Assert.IsTrue(result.IsReady);
    }

    [TestMethod]
    public void Evaluate_InstalledMapExplicitFalse_DoesNotCountAsInstalled()
    {
        ModelCatalogueEntry entry = Entry(
            "sd15",
            "SD 1.5",
            "diffusers",
            installed: false,
            family: "sd15",
            hardware: ["cpu"],
            render: Render("internal", ["internal_video"]));
        ModelCatalogueResponse catalogue = Catalogue(entry);
        catalogue.Installed =
        new Dictionary<string, JsonElement>
        {
            ["sd15"] = Json("false"),
        };

        ModelRenderGuidance result = ModelRenderGuidanceEvaluator.Evaluate(catalogue, Config(device: "cpu"));

        Assert.IsFalse(result.Primary?.IsInstalled);
        StringAssert.Contains(string.Join(" ", result.Blockers), "Not installed");
    }

    [TestMethod]
    public void Evaluate_AnimateDiffWithSdxl_ReportsBaseFamilyBlocker()
    {
        ModelCatalogueResponse catalogue = Catalogue(
            Entry("sdxl", "SDXL", "diffusers", true, "sdxl", ["discrete_gpu"],
                Render("internal", ["internal_video"])),
            Entry("ad", "AnimateDiff", "motion_adapter", true, "animatediff", ["discrete_gpu"],
                Render("internal_video_model", ["internal_video_model"], "animatediff")));

        ModelRenderGuidance result = ModelRenderGuidanceEvaluator.Evaluate(
            catalogue,
            Config(
                modelId: "sdxl",
                videoModelId: "ad",
                device: "cuda",
                temporalMode: "video_model",
                videoEngine: "animatediff"));

        Assert.IsFalse(result.IsReady);
        StringAssert.Contains(string.Join(" ", result.Blockers), "SD 1.5");
    }

    [TestMethod]
    public void Evaluate_CudaSelection_RejectsCpuOnlyModel()
    {
        ModelCatalogueResponse catalogue = Catalogue(
            Entry("cpu", "CPU model", "diffusers", true, "sd15", ["cpu"],
                Render("internal", ["internal_video"])));

        ModelRenderGuidance result = ModelRenderGuidanceEvaluator.Evaluate(
            catalogue,
            Config(modelId: "cpu", device: "cuda"));

        Assert.IsFalse(result.IsReady);
        StringAssert.Contains(string.Join(" ", result.Blockers), "not compatible");
    }

    [TestMethod]
    public void Evaluate_TensorRt_RequiresInstalledCanonicalBundle()
    {
        ModelCatalogueResponse catalogue = Catalogue(
            Entry(
                ModelRenderGuidanceEvaluator.CanonicalTensorRtModelId,
                "Local TensorRT",
                "runtime_bundle",
                installed: true,
                family: "sd15",
                hardware: ["nvidia"],
                render: Render("tensorrt_standalone", ["stills", "internal_video_keyframes"]),
                installable: false));

        ModelRenderGuidance result = ModelRenderGuidanceEvaluator.Evaluate(
            catalogue,
            Config(
                device: "cuda",
                renderMode: "tensorrt",
                keyframeRenderer: "tensorrt_sd15"));

        Assert.IsTrue(result.IsReady);
        Assert.AreEqual(ModelRenderGuidanceEvaluator.CanonicalTensorRtModelId, result.Keyframe?.ModelId);
    }

    [TestMethod]
    public void Evaluate_AutoVideoEngine_RanksInstalledAlternativeFirst()
    {
        ModelCatalogueResponse catalogue = Catalogue(
            Entry("sd15", "SD 1.5", "diffusers", true, "sd15", ["discrete_gpu"],
                Render("internal", ["internal_video"])),
            Entry("svd", "SVD", "video_diffusers", false, "svd", ["discrete_gpu"],
                Render("internal_video_model", ["internal_video_model"], "svd")),
            Entry("ad", "AnimateDiff", "motion_adapter", true, "animatediff", ["discrete_gpu"],
                Render("internal_video_model", ["internal_video_model"], "animatediff")));

        ModelRenderGuidance result = ModelRenderGuidanceEvaluator.Evaluate(
            catalogue,
            Config(device: "cuda", temporalMode: "video_model"));

        Assert.AreEqual("ad", result.Video?.ModelId);
        Assert.AreEqual("ad", result.VideoAlternatives[0].ModelId);
    }

    private static ModelRenderConfiguration Config(
        string modelId = "auto",
        string videoModelId = "",
        string renderMode = "auto",
        string device = "auto",
        string temporalMode = "keyframes",
        string videoEngine = "auto",
        string keyframeRenderer = "internal") =>
        new(
            modelId,
            videoModelId,
            renderMode,
            device,
            temporalMode,
            videoEngine,
            keyframeRenderer,
            string.Empty);

    private static ModelCatalogueResponse Catalogue(params ModelCatalogueEntry[] entries) =>
        new()
        {
            Catalog = entries,
            User = [],
            Packs = [],
            Accepted = new Dictionary<string, JsonElement>(),
            Installed = new Dictionary<string, JsonElement>(),
        };

    private static ModelCatalogueEntry Entry(
        string id,
        string name,
        string kind,
        bool installed,
        string family,
        string[] hardware,
        JsonElement render,
        bool installable = true)
    {
        var extensionData = new Dictionary<string, JsonElement>
        {
            ["family"] = Json($"\"{family}\""),
            ["hardware_targets"] = Json(JsonSerializer.Serialize(hardware)),
            ["render"] = render,
            ["recommended"] = Json("\"default\""),
            ["installable"] = Json(installable ? "true" : "false"),
        };
        return new ModelCatalogueEntry
        {
            Id = id,
            Name = name,
            Kind = kind,
            Source = "hf",
            Installed = installed,
            LicenseId = "Apache-2.0",
            ExtensionData = extensionData,
        };
    }

    private static JsonElement Render(string engine, string[] modes, string? videoEngine = null)
    {
        var value = new Dictionary<string, object?>
        {
            ["engine"] = engine,
            ["render_modes"] = modes,
            ["video_model_engine"] = videoEngine,
        };
        return Json(JsonSerializer.Serialize(value));
    }

    private static JsonElement Json(string value) =>
        JsonDocument.Parse(value).RootElement.Clone();
}
