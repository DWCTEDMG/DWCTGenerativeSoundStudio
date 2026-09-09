using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ReactiveDraftCompatibilityTests
{
    [TestMethod]
    [DataRow("{}")]
    [DataRow("{\"settings\":null,\"mappings\":null}")]
    [DataRow("{\"settings\":{\"mappings\":null}}")]
    public void OptionalMetadataProducesUsableEditorState(string json)
    {
        var metadata = JsonSerializer.Deserialize(json, StudioJsonContext.Default.ReactiveLabMetadata)!;
        Assert.IsNotNull(metadata.Settings);
        Assert.IsNotNull(metadata.Mappings);
        Assert.IsNotNull(metadata.Settings.Mappings);
        Assert.AreEqual(1d, metadata.Settings.Sensitivity);
        Assert.AreEqual(30, metadata.Settings.FramesPerSecond);
    }

    [TestMethod]
    public void PartialSettingsPreserveExplicitValuesAndExtensionsAcrossReload()
    {
        const string json = """
            {"metadata":{"source":"workspace","settings":{"sensitivity":0.37,"smoothing":0,
              "fps":60,"mappings":[{"id":"custom","gain":0.6}],"custom":{"keep":true}}},
             "keyframes":[{"id":"key-a","time":1.25,"frame":75,"sample":"60000",
               "strength":0.4,"zoom":1.2,"locked":true,"extension":{"keep":true}}]}
            """;
        var request = JsonSerializer.Deserialize(json, StudioJsonContext.Default.ReactiveLabApplyRequest)!;
        var metadata = request.Metadata!.Value.Deserialize(StudioJsonContext.Default.ReactiveLabMetadata)!;
        Assert.AreEqual(0.37, metadata.Settings.Sensitivity);
        Assert.AreEqual(0d, metadata.Settings.Smoothing);
        Assert.AreEqual(60, metadata.Settings.FramesPerSecond);
        Assert.AreEqual(12, metadata.Settings.MinimumCutFrames);
        Assert.AreEqual(0.6, metadata.Settings.Mappings.Single().Gain);
        Assert.IsTrue(metadata.Settings.ExtensionData!["custom"].GetProperty("keep").GetBoolean());

        request.Metadata = JsonSerializer.SerializeToElement(metadata, StudioJsonContext.Default.ReactiveLabMetadata);
        string saved = JsonSerializer.Serialize(request, StudioJsonContext.Default.ReactiveLabApplyRequest);
        var reloaded = JsonSerializer.Deserialize(saved, StudioJsonContext.Default.ReactiveLabApplyRequest)!;
        Assert.AreEqual(saved, JsonSerializer.Serialize(reloaded, StudioJsonContext.Default.ReactiveLabApplyRequest));
        Assert.IsTrue(JsonElement.DeepEquals(request.Keyframes.Single(), reloaded.Keyframes.Single()));
        var editor = new ReactiveKeyframeEditor(reloaded.Keyframes.Single());
        Assert.IsFalse(editor.IsEditable);
        Assert.AreEqual(0.4, editor.Strength);
        Assert.AreEqual(1.2, editor.Zoom);
    }

    [TestMethod]
    public void LegacyLocalStateWithNullOptionalValuesCanReload()
    {
        var state = JsonSerializer.Deserialize("""{"current":null,"presets":null}""",
            StudioJsonContext.Default.ReactiveLabLocalState)!;
        Assert.IsNotNull(state.Current);
        Assert.IsNotNull(state.Current.Mappings);
        Assert.IsNotNull(state.Presets);
        string saved = JsonSerializer.Serialize(state, StudioJsonContext.Default.ReactiveLabLocalState);
        var reloaded = JsonSerializer.Deserialize(saved, StudioJsonContext.Default.ReactiveLabLocalState)!;
        Assert.AreEqual(saved, JsonSerializer.Serialize(reloaded, StudioJsonContext.Default.ReactiveLabLocalState));
    }
}
