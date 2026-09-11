using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineViewportTests
{
    [TestMethod]
    [DataRow(60d)]
    [DataRow(600d)]
    [DataRow(86400d)]
    public void RulerWorkIsBoundedByViewportRatherThanProjectDuration(double duration)
    {
        double[] ticks = TimelineViewport.RulerTicks(duration, 360, 0, 1920, 0.25).ToArray();
        Assert.IsTrue(ticks.Length <= 25);
        Assert.AreEqual(0d, ticks[0]);
        Assert.IsTrue(ticks[^1] * 360 >= 1920);
    }

    [TestMethod]
    public void ScrolledRulerCoversViewportAndPreservesFractionalProjectEnd()
    {
        double[] ticks = TimelineViewport.RulerTicks(600.125, 360, 598 * 360, 1920, 0.25).ToArray();
        Assert.AreEqual(597.75, ticks[0]);
        Assert.AreEqual(600.125, ticks[^1]);
        Assert.AreEqual(ticks.Length, ticks.Distinct().Count());
        Assert.IsTrue(ticks.All(time => time <= 600.125));
    }

    [TestMethod]
    public void InvalidTransportDoesNotCreateVisuals()
    {
        Assert.IsEmpty(TimelineViewport.RulerTicks(double.NaN, 80, 0, 900, 1));
        Assert.IsEmpty(TimelineViewport.RulerTicks(60, 0, 0, 900, 1));
        Assert.IsEmpty(TimelineViewport.RulerTicks(60, 80, 0, 900, 0));
    }

    [TestMethod]
    public void ZoomOffsetKeepsPointerTimeAnchored()
    {
        double offset = TimelineViewport.OffsetAfterZoom(800, 400, 80, 160, 60, 900);

        Assert.AreEqual(2000, offset);
        Assert.AreEqual((800 + 400) / 80, (offset + 400) / 160);
    }

    [TestMethod]
    public void ZoomOffsetClampsAtProjectEdges()
    {
        Assert.AreEqual(0, TimelineViewport.OffsetAfterZoom(0, 0, 80, 160, 60, 900));
        Assert.AreEqual(300, TimelineViewport.OffsetAfterZoom(3900, 900, 80, 20, 60, 900));
    }

    [TestMethod]
    public void FitPixelsPerSecondHonorsZoomLimits()
    {
        Assert.AreEqual(30, TimelineViewport.FitPixelsPerSecond(30, 900, 12, 360));
        Assert.AreEqual(12, TimelineViewport.FitPixelsPerSecond(300, 900, 12, 360));
        Assert.AreEqual(360, TimelineViewport.FitPixelsPerSecond(1, 900, 12, 360));
    }
}
