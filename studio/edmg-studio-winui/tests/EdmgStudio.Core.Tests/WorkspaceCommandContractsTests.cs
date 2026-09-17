using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WorkspaceCommandContractsTests
{
    [TestMethod]
    public void PlanRequestPreservesSelectedProviderModelAndAudioMode()
    {
        var request = new PlanRequest("Music", "Story", "Sculptural", Provider: "openai_compat",
            Model: "audio-model", NativeAudio: true, ExpectedRevision: 42);
        using var json = JsonDocument.Parse(JsonSerializer.Serialize(request));
        Assert.AreEqual("openai_compat", json.RootElement.GetProperty("provider").GetString());
        Assert.AreEqual("audio-model", json.RootElement.GetProperty("model").GetString());
        Assert.IsTrue(json.RootElement.GetProperty("native_audio").GetBoolean());
        Assert.AreEqual(42, json.RootElement.GetProperty("expected_revision").GetInt32());
    }
}
