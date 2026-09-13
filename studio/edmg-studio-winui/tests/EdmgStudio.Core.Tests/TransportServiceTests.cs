using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TransportServiceTests
{
    [TestMethod]
    public void PlaybackUsesExactSamplesAndStopsAtProjectEnd()
    {
        var clock = new TestClock();
        var transport = new TransportService(clock);
        transport.Configure("project", 48_000, 96_000, 24_000);

        transport.Play();
        TransportState? terminalState = null;
        transport.StateChanged += (_, state) => terminalState = state;
        clock.Advance(TimeSpan.FromSeconds(1));
        Assert.AreEqual(72_000L, transport.State.PositionSamples);
        clock.Advance(TimeSpan.FromSeconds(1));
        Assert.AreEqual(96_000L, transport.State.PositionSamples);
        Assert.AreEqual(TransportMode.Stopped, transport.State.Mode);
        Assert.IsNotNull(terminalState);
        Assert.AreEqual(TransportMode.Stopped, terminalState.Mode);
    }

    [TestMethod]
    public void LoopWrapsWithoutLosingOvershoot()
    {
        var clock = new TestClock();
        var transport = new TransportService(clock);
        transport.Configure("project", 48_000, 480_000, 95_000);
        transport.SetLoop(true, 48_000, 96_000);

        transport.Play();
        clock.Advance(TimeSpan.FromMilliseconds(125));

        Assert.AreEqual(53_000L, transport.State.PositionSamples);
        Assert.AreEqual(TransportMode.Playing, transport.State.Mode);
    }

    [TestMethod]
    public void SeekWhilePlayingReanchorsTheClock()
    {
        var clock = new TestClock();
        var transport = new TransportService(clock);
        transport.Configure("project", 48_000, 480_000);
        transport.Play();
        clock.Advance(TimeSpan.FromSeconds(2));

        transport.Seek(240_000);
        clock.Advance(TimeSpan.FromSeconds(1));

        Assert.AreEqual(288_000L, transport.State.PositionSamples);
    }

    private sealed class TestClock : IMonotonicClock
    {
        public long Timestamp { get; private set; }

        public TimeSpan Elapsed(long startTimestamp, long endTimestamp) =>
            TimeSpan.FromTicks(endTimestamp - startTimestamp);

        public void Advance(TimeSpan duration) => Timestamp += duration.Ticks;
    }
}
