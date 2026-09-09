using System.Text.Json;
using EdmgStudio.Core.Models;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ReactiveKeyframeEditorTests
{
    [TestMethod]
    public void RefinementPreservesSourceTimingExtensionsAndOriginalDocument()
    {
        using var source = JsonDocument.Parse("""{"id":"key-a","source_id":"scene-a","t":1.2,"frame":36,"sample":"57600","strength":0.4,"zoom":1.01,"extension":{"keep":true}}""");
        var editor = new ReactiveKeyframeEditor(source.RootElement);
        Assert.IsTrue(editor.Refine(0.7, 1.3));
        var result = editor.ToJson();
        Assert.AreEqual("57600", result.GetProperty("sample").GetString());
        Assert.AreEqual(36, result.GetProperty("frame").GetInt32());
        Assert.AreEqual(1.2, result.GetProperty("t").GetDouble());
        Assert.AreEqual("scene-a", result.GetProperty("source_id").GetString());
        Assert.IsTrue(result.GetProperty("extension").GetProperty("keep").GetBoolean());
        Assert.AreEqual(0.4, source.RootElement.GetProperty("strength").GetDouble());
        Assert.AreEqual(0.7, result.GetProperty("strength").GetDouble());
    }

    [TestMethod]
    [DataRow(0.01)]
    [DataRow(20.01)]
    [DataRow(100.0)]
    public void RefinementAcceptsSharedZoomRangeAndSerializesExactValue(double zoom)
    {
        using var source = JsonDocument.Parse("""{"id":"key-a","strength":0.4,"zoom":1}""");
        var editor = new ReactiveKeyframeEditor(source.RootElement);

        Assert.IsTrue(editor.Refine(0.7, zoom));
        Assert.AreEqual(zoom, editor.ToJson().GetProperty("zoom").GetDouble());
        Assert.IsFalse(editor.Refine(0.7, zoom));
    }

    [TestMethod]
    public void InvalidZoomRejectsRefinementWithoutChangingAnyField()
    {
        using var source = JsonDocument.Parse("""{"id":"key-a","strength":0.4,"zoom":1}""");
        var editor = new ReactiveKeyframeEditor(source.RootElement);
        var original = editor.ToJson().GetRawText();

        double[] invalidZooms = [Math.BitDecrement(0.01), Math.BitIncrement(100),
            0, double.NaN, double.NegativeInfinity, double.PositiveInfinity];
        foreach (var zoom in invalidZooms)
        {
            var error = Assert.Throws<ArgumentOutOfRangeException>(() => editor.Refine(0.7, zoom));
            Assert.AreEqual("zoom", error.ParamName);
            Assert.AreEqual(original, editor.ToJson().GetRawText());
        }
    }

    [TestMethod]
    public void LockedKeyframeRejectsRefinement()
    {
        using var source = JsonDocument.Parse("""{"id":"locked","locked":true,"strength":0.4,"zoom":1}""");
        var editor = new ReactiveKeyframeEditor(source.RootElement);
        Assert.IsFalse(editor.IsEditable);
        Assert.Throws<InvalidOperationException>(() => editor.Refine(0.5, 1.2));
    }

    [TestMethod]
    public void WorkspaceMetadataWithoutCustomPresetsHasUsableDefaults()
    {
        var metadata = JsonSerializer.Deserialize("""{"source":"workspace","fps":30,"selected_variant_index":0}""", StudioJsonContext.Default.ReactiveLabMetadata)!;
        Assert.IsNotNull(metadata.Settings);
        Assert.IsNotNull(metadata.Mappings);
        Assert.IsNotNull(metadata.Settings.Mappings);
    }
}
