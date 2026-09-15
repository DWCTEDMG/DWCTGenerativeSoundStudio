using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineEditorViewStateTests
{
    [TestMethod]
    public void NormalizeClampsViewportAndPreservesAvailableSelection()
    {
        var state = new TimelineEditorViewState(75, 500, 50_000, 500, "clip-b", "audio");

        TimelineEditorViewState normalized = state.Normalize(
            60, 12, 360, 900, 500, 200, ["clip-a", "clip-b"], ["video", "audio"]);

        Assert.AreEqual(60, normalized.PositionSeconds);
        Assert.AreEqual(360, normalized.PixelsPerSecond);
        Assert.AreEqual(20_700, normalized.HorizontalOffset);
        Assert.AreEqual(300, normalized.VerticalOffset);
        Assert.AreEqual("clip-b", normalized.SelectedLaneId);
        Assert.AreEqual("audio", normalized.SelectedTrackId);
    }

    [TestMethod]
    public void NormalizeRepairsInvalidNumbersAndMissingSelection()
    {
        var state = new TimelineEditorViewState(
            double.NaN,
            double.PositiveInfinity,
            double.NegativeInfinity,
            double.NaN,
            "missing",
            "missing-track");

        TimelineEditorViewState normalized = state.Normalize(
            60, 12, 360, 900, 500, 200, ["clip-a"], ["audio"]);

        Assert.AreEqual(0, normalized.PositionSeconds);
        Assert.AreEqual(12, normalized.PixelsPerSecond);
        Assert.AreEqual(0, normalized.HorizontalOffset);
        Assert.AreEqual(0, normalized.VerticalOffset);
        Assert.IsNull(normalized.SelectedLaneId);
        Assert.IsNull(normalized.SelectedTrackId);
    }
}
