using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class JuceGeneratedTransportTests
{
  [TestMethod]
  [DataRow(44_100, 64)]
  [DataRow(48_000, 256)]
  [DataRow(96_000, 1024)]
  public void AdvancesExactlyAcrossSampleRatesAndBufferSizes(int sampleRate, int bufferFrames)
  {
    JuceGeneratedTransport transport = new();
    _ = transport.Configure(new(7, sampleRate, sampleRate * 2L));
    _ = transport.Apply(new("play"));

    JuceTransportPosition position = transport.Advance(bufferFrames);

    Assert.AreEqual(bufferFrames, position.PositionSamples);
    Assert.AreEqual(sampleRate, position.SampleRate);
    Assert.AreEqual("playing", position.State);
  }

  [TestMethod]
  public void PauseSeekResumeAndStopPreserveExactSampleSemantics()
  {
    JuceGeneratedTransport transport = new();
    _ = transport.Configure(new(3, 48_000, 96_000));
    _ = transport.Apply(new("play"));
    _ = transport.Advance(512);
    _ = transport.Apply(new("pause"));
    Assert.AreEqual(512L, transport.Advance(512).PositionSamples);

    JuceTransportPosition seek = transport.Apply(new("seek", PositionSamples: 24_001, SeekSequence: 1));
    Assert.AreEqual(24_001L, seek.PositionSamples);
    Assert.AreEqual(1L, seek.SeekSequence);
    _ = transport.Apply(new("play"));
    Assert.AreEqual(24_257L, transport.Advance(256).PositionSamples);

    JuceTransportPosition stopped = transport.Apply(new("stop"));
    Assert.AreEqual(0L, stopped.PositionSamples);
    Assert.AreEqual("stopped", stopped.State);
  }

  [TestMethod]
  public void LoopWrapsWithOvershootAndRejectsStaleSeeks()
  {
    JuceGeneratedTransport transport = new();
    _ = transport.Configure(new(11, 48_000, 100_000));
    _ = transport.Apply(new("loop", LoopEnabled: true, LoopStartSample: 1_000, LoopEndSample: 1_500));
    _ = transport.Apply(new("seek", PositionSamples: 1_400, SeekSequence: 5));
    _ = transport.Apply(new("play"));

    JuceTransportPosition wrapped = transport.Advance(256);

    Assert.AreEqual(1_156L, wrapped.PositionSamples);
    _ = Assert.ThrowsExactly<ArgumentException>(() =>
        transport.Apply(new("seek", PositionSamples: 200, SeekSequence: 5)));
  }

  [TestMethod]
  public void EndOfStreamStopsAtExactDuration()
  {
    JuceGeneratedTransport transport = new();
    _ = transport.Configure(new(1, 48_000, 1_000));
    _ = transport.Apply(new("seek", PositionSamples: 900, SeekSequence: 1));
    _ = transport.Apply(new("play"));

    JuceTransportPosition ended = transport.Advance(256);

    Assert.AreEqual(1_000L, ended.PositionSamples);
    Assert.AreEqual("stopped", ended.State);
  }
}
