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
    public void HardwareProfile_ParsesSharedShapeAndPreservesMetadata()
    {
        JsonObject source = JsonNode.Parse("""{"schema_version":"1.0","id":"workstation-1","backend":"cuda","device":"cuda:0","device_name":"Fixture GPU","available_backends":["cpu","cuda"],"vram_gb":24,"ram_gb":64,"cpu_threads":16,"platform":"windows","machine":"amd64","gpu_vendor":"nvidia","future":{"keep":true}}""")!.AsObject();

        HardwareProfile profile = DirectorProviderContracts.ParseHardwareProfile(source);

        Assert.AreEqual("cuda", profile.Backend);
        Assert.AreEqual(24, profile.VramGb);
        Assert.AreEqual("nvidia", profile.GpuVendor);
        Assert.IsTrue(profile.Metadata["future"]!["keep"]!.GetValue<bool>());
    }

    [TestMethod]
    public void HardwareProfile_RejectsUnavailableBackendAndInvalidResources()
    {
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseHardwareProfile(JsonNode.Parse("""{"id":"x","backend":"cuda","device":"cuda:0","device_name":"GPU","available_backends":["cpu"],"cpu_threads":8,"platform":"windows","machine":"amd64"}""")!.AsObject()));
        Assert.Throws<InvalidDataException>(() => DirectorProviderContracts.ParseHardwareProfile(JsonNode.Parse("""{"id":"x","backend":"cpu","device":"cpu","device_name":"CPU","available_backends":["cpu"],"vram_gb":-1,"cpu_threads":8,"platform":"windows","machine":"amd64"}""")!.AsObject()));
    }
}
