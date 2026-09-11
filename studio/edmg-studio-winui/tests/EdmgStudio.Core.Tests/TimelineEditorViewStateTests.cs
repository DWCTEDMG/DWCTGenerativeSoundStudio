using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineEditorViewStateTests
{
    [TestMethod]
    public void NormalizeClampsViewportAndPreservesAvailableSelection()
    {
        var state = new TimelineEditorViewState(75, 500, 50_000, 500, "clip-b");

        TimelineEditorViewState normalized = state.Normalize(
            60, 12, 360, 900, 500, 200, ["clip-a", "clip-b"]);

        Assert.AreEqual(60, normalized.PositionSeconds);
        Assert.AreEqual(360, normalized.PixelsPerSecond);
        Assert.AreEqual(20_700, normalized.HorizontalOffset);
        Assert.AreEqual(300, normalized.VerticalOffset);
        Assert.AreEqual("clip-b", normalized.SelectedLaneId);
    }

    [TestMethod]
    public void NormalizeRepairsInvalidNumbersAndMissingSelection()
    {
        var state = new TimelineEditorViewState(
            double.NaN,
            double.PositiveInfinity,
            double.NegativeInfinity,
            double.NaN,
            "missing");

        TimelineEditorViewState normalized = state.Normalize(
            60, 12, 360, 900, 500, 200, ["clip-a"]);

        Assert.AreEqual(0, normalized.PositionSeconds);
        Assert.AreEqual(12, normalized.PixelsPerSecond);
        Assert.AreEqual(0, normalized.HorizontalOffset);
        Assert.AreEqual(0, normalized.VerticalOffset);
        Assert.IsNull(normalized.SelectedLaneId);
    }
}
