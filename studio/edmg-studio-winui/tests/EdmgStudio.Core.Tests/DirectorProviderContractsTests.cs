using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class DirectorProviderContractsTests
{
    [TestMethod]
    public void DirectorDocument_RoundTripsExactSamplesAndUnknownMetadata()
    {
        using JsonDocument json = JsonDocument.Parse("""
            {"version":1,"future":{"keep":true},"analysis_revision":7,
             "story_bible":{"revision":3,"project_theme":"Arrival","visual_style":"Noir","future_bible":"keep"},
             "scenes":[{"scene_id":"scene-1","start_sample":"9007199254740993","end_sample":"9007199254788993",
               "intent":"A traveler arrives","continuity_mode":"cut","future_scene":{"keep":true},
               "subjects":[{"id":"traveler","appearance_lock":true,"future_subject":4}],
               "camera":{"movement":"dolly","reviewed_keyframes":[1,2]},"environment":{},"lighting":{},
               "renderer_hints":{"provider_id":"external"}}]}
            """);

        SharedDirectorDocument document = DirectorProviderContracts.ParseDirectorDocument(json.RootElement);
        JsonObject rebuilt = DirectorProviderContracts.RebuildDirectorDocument(document);

        Assert.AreEqual(9_007_199_254_740_993L, document.Scenes.Single().Start.Samples);
        Assert.AreEqual("external", document.Scenes.Single().RendererHints["provider_id"]!.GetValue<string>());
        Assert.IsTrue(rebuilt["future"]!["keep"]!.GetValue<bool>());
        Assert.AreEqual("keep", rebuilt["story_bible"]!["future_bible"]!.GetValue<string>());
        Assert.AreEqual(4, rebuilt["scenes"]![0]!["subjects"]![0]!["future_subject"]!.GetValue<int>());
        Assert.AreEqual(2, rebuilt["scenes"]![0]!["camera"]!["reviewed_keyframes"]![1]!.GetValue<int>());
    }

    [TestMethod]
    public void DirectorDocument_RejectsUnsupportedVersionsDuplicateIdsAndMalformedSamples()
    {
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseDirectorDocument(JsonNode.Parse("""{"version":2}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseDirectorDocument(JsonNode.Parse("""{"version":"one"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseDirectorDocument(JsonNode.Parse("""{"version":1,"scenes":[{"scene_id":"same","start_sample":"0","end_sample":"1","intent":"a"},{"scene_id":"same","start_sample":"1","end_sample":"2","intent":"b"}]}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseDirectorDocument(JsonNode.Parse("""{"version":1,"scenes":[{"scene_id":"scene","start_sample":"00","end_sample":"1","intent":"a"}]}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseDirectorDocument(JsonNode.Parse("""{"version":1,"scenes":[null]}""")!.AsObject()));
    }

    [TestMethod]
    public void ProviderCapability_ParsesSharedVersionedShapeAndPreservesMetadata()
    {
        JsonObject source = JsonNode.Parse("""{"schema_version":"1.0","id":"external-video","provider_id":"external","media":"video","operation":"generate","controls":["text","image"],"max_duration_seconds":12,"resolutions":["1920x1080"],"deterministic":false,"supports_cancel":true,"locality":"remote","metadata":{"cost":true}}""")!.AsObject();

        ProviderCapability capability = DirectorProviderContracts.ParseCapability(source);

        Assert.AreEqual("external", capability.ProviderId);
        Assert.AreEqual("remote", capability.Locality);
        Assert.AreEqual("image", capability.Controls[1]);
        Assert.IsTrue(capability.Metadata["metadata"]!["cost"]!.GetValue<bool>());
    }

    [TestMethod]
    public void ProviderCapability_RejectsUnknownSchemaAndVocabulary()
    {
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseCapability(JsonNode.Parse("""{"schema_version":"2.0"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseCapability(JsonNode.Parse("""{"schema_version":"1.0","id":"x","provider_id":"p","media":"video","operation":"unknown","deterministic":true,"supports_cancel":true,"locality":"remote"}""")!.AsObject()));
    }

    [TestMethod]
    public void Renderer_RequiresInferenceEvidenceBeforeReportingValidated()
    {
        JsonObject source = JsonNode.Parse("""{"schema_version":"1.0","id":"hunyuan","provider_id":"internal","engine":"internal_video_model","model_id":"hunyuan-video-1.5","family":"hunyuan_video15","media":"video","operations":["generate"],"controls":["text","image"],"render_modes":["t2v","i2v"],"hardware_backends":["cuda"],"minimum_vram_gb":8,"readiness":{"state":"validated","installed":true,"adapter_ready":true,"hardware_compatible":true,"validation_level":3,"validation_receipt_id":"receipt-1","validated_at":"2026-09-12T00:00:00Z"},"future":{"keep":true}}""")!.AsObject();

        RendererDescriptor renderer = DirectorProviderContracts.ParseRenderer(source);

        Assert.AreEqual("validated", renderer.Readiness.State);
        Assert.AreEqual("receipt-1", renderer.Readiness.ValidationReceiptId);
        Assert.AreEqual("i2v", renderer.RenderModes[1]);
        Assert.IsTrue(renderer.Metadata["future"]!["keep"]!.GetValue<bool>());

        source["readiness"]!["validation_receipt_id"] = null;
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseRenderer(source));
    }

    [TestMethod]
    public void HardwareProfile_ParsesSharedShapeAndPreservesMetadata()
    {
        JsonObject source = JsonNode.Parse("""{"schema_version":"1.0","id":"workstation-1","backend":"cuda","device":"cuda:0","device_name":"Fixture GPU","available_backends":["cpu","cuda"],"vram_gb":24,"ram_gb":64,"cpu_threads":16,"physical_core_count":8,"logical_core_count":16,"platform":"windows","machine":"amd64","gpu_vendor":"nvidia","gpus":[{"id":"cuda:0","vendor":"nvidia","name":"Fixture GPU","dedicated_vram_gb":24,"cuda_available":true}],"disks":[{"id":"studio","path":"D:\\\\EDMG","free_gb":500,"total_gb":1000}],"audio_devices":[{"id":"wasapi-default","name":"Speakers","backend":"wasapi","output_channels":2,"is_default":true}],"recommended_tier":"quality","recommended_director":"qwen3-vl-30b","recommended_renderer":"ltx-2.5","warnings":["fixture"],"future":{"keep":true}}""")!.AsObject();

        HardwareProfile profile = DirectorProviderContracts.ParseHardwareProfile(source);

        Assert.AreEqual("cuda", profile.Backend);
        Assert.AreEqual(24, profile.VramGb);
        Assert.AreEqual("nvidia", profile.GpuVendor);
        Assert.AreEqual(8, profile.PhysicalCoreCount);
        Assert.AreEqual("Fixture GPU", profile.Gpus.Single().Name);
        Assert.AreEqual(500, profile.Disks.Single().FreeGb);
        Assert.AreEqual(2, profile.AudioDevices.Single().OutputChannels);
        Assert.AreEqual("ltx-2.5", profile.RecommendedRenderer);
        Assert.IsTrue(profile.Metadata["future"]!["keep"]!.GetValue<bool>());
    }

    [TestMethod]
    public void HardwareProfile_RejectsUnavailableBackendAndInvalidResources()
    {
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseHardwareProfile(JsonNode.Parse("""{"id":"x","backend":"cuda","device":"cuda:0","device_name":"GPU","available_backends":["cpu"],"cpu_threads":8,"platform":"windows","machine":"amd64"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseHardwareProfile(JsonNode.Parse("""{"id":"x","backend":"cpu","device":"cpu","device_name":"CPU","available_backends":["cpu"],"vram_gb":-1,"cpu_threads":8,"platform":"windows","machine":"amd64"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseHardwareProfile(JsonNode.Parse("""{"id":"x","backend":"cpu","device":"cpu","device_name":"CPU","available_backends":["cpu"],"cpu_threads":8,"physical_core_count":9,"logical_core_count":8,"platform":"windows","machine":"amd64"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseHardwareProfile(JsonNode.Parse("""{"id":"x","backend":"cpu","device":"cpu","device_name":"CPU","available_backends":["cpu"],"cpu_threads":8,"platform":"windows","machine":"amd64","gpus":[{"id":"same","name":"A"},{"id":"same","name":"B"}]}""")!.AsObject()));
    }
}
