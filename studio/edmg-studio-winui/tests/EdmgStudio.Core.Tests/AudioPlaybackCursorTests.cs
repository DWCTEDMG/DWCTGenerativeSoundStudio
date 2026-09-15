using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class AudioPlaybackCursorTests
{
    private static TransportState Playing(long position = 0) => new(
        "project", 48_000, 480_000, position, TransportMode.Playing, new(false, 0, 480_000));

    [TestMethod]
    public void SmallExplicitSeekIsNotHiddenByDriftTolerance()
    {
        var cursor = new AudioPlaybackCursor();
        cursor.Advance(Playing(), 0, 100);
        AudioPlaybackPosition result = cursor.Advance(Playing(7_200), 100, 100, transportChanged: true);
        Assert.AreEqual(7_200L, result.Samples);
        Assert.IsTrue(result.RequiresSeek);
        Assert.IsFalse(cursor.Advance(Playing(7_200), 100, 110).RequiresSeek);
    }

    [TestMethod]
    public void ShortLoopAlwaysSeeksAtWrap()
    {
        var cursor = new AudioPlaybackCursor();
        TransportState state = Playing() with { Loop = new(true, 0, 2_400) };
        cursor.Advance(state, 0, 40);
        AudioPlaybackPosition result = cursor.Advance(state, 0, 60);
        Assert.AreEqual(480L, result.Samples);
        Assert.IsTrue(result.RequiresSeek);
    }

    [TestMethod]
    public void MultipleLoopsBetweenUpdatesAreDetectedEvenAtSamePosition()
    {
        var cursor = new AudioPlaybackCursor();
        TransportState state = Playing() with { Loop = new(true, 0, 240) };
        cursor.Advance(state, 0, 1);
        AudioPlaybackPosition result = cursor.Advance(state, 0, 11);
        Assert.AreEqual(48L, result.Samples);
        Assert.IsTrue(result.RequiresSeek);
    }

    [TestMethod]
    public void OrdinaryPlaybackDoesNotSeekOnEveryUpdate()
    {
        var cursor = new AudioPlaybackCursor();
        Assert.IsTrue(cursor.Advance(Playing(), 0, 0).RequiresSeek);
        AudioPlaybackPosition result = cursor.Advance(Playing(), 0, 10);
        Assert.AreEqual(480L, result.Samples);
        Assert.IsFalse(result.RequiresSeek);
    }

    [TestMethod]
    public void PauseKeepsPositionAndEndClampsWithoutOverflow()
    {
        var cursor = new AudioPlaybackCursor();
        Assert.AreEqual(123L, cursor.Advance(Playing(123) with { Mode = TransportMode.Stopped }, 0, 999).Samples);
        Assert.AreEqual(480_000L, cursor.Advance(Playing(), 0, long.MaxValue).Samples);
    }

    [TestMethod]
    public void PausedSeekOutsideLoopIsNotWrapped()
    {
        var cursor = new AudioPlaybackCursor();
        TransportState paused = Playing(9_600) with { Mode = TransportMode.Stopped, Loop = new(true, 0, 2_400) };
        Assert.AreEqual(9_600L, cursor.Advance(paused, 0, 10_000, transportChanged: true).Samples);
    }
}
