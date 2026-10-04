using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;
using System.Collections.Immutable;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class JuceTimelineSnapshotTests
{
  [TestMethod]
  public async Task BuilderLoadsEachAuthorizedSourceOnceAndPreservesCanonicalOffsets()
  {
    AudioRenderGraph graph = Graph([
        new AudioClipSource("a", "asset", "authorized.wav", 10, 14, 2, 48_000),
        new AudioClipSource("b", "asset", "authorized.wav", 20, 24, 6, 48_000)]);
    StubReader reader = new(new JuceTimelineSource("authorized.wav", 48_000, 1, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]));

    JuceTimelineSnapshot snapshot = await JuceTimelineSnapshotBuilder.BuildAsync(
        3, graph, EmptyEditing(), reader);

    Assert.AreEqual(1, reader.ReadCount);
    Assert.AreEqual(24, snapshot.DurationSamples);
    Assert.HasCount(2, snapshot.Tracks.Single().Clips);
    Assert.AreEqual(6, snapshot.Tracks.Single().Clips[1].SourceStartSample);
  }

  [TestMethod]
  public void RendererMapsOffsetsResamplesAndMapsMonoToStereo()
  {
    JuceTimelineSource source = new("source.wav", 24_000, 1, [0, 1, 2, 3, 4]);
    JuceTimelineSnapshot snapshot = Snapshot(1, 48_000,
        new("clip", 2, 6, 1, 1, 0, 0, FadeCurve.Linear, source));
    JuceTimelineRenderer renderer = new(snapshot);
    float[] output = new float[12];

    JuceTimelineRenderResult result = renderer.ProcessBlock(output, 0, 6);

    CollectionAssert.AreEqual(new float[] { 0, 0, 0, 0, 1, 1, 1.5f, 1.5f, 2, 2, 2.5f, 2.5f }, output);
    Assert.IsTrue(result.SnapshotChanged);
  }

  [TestMethod]
  public void RendererAppliesLinearFadesAndMixesOverlappingClips()
  {
    JuceTimelineSource source = new("source.wav", 48_000, 2,
        [1, .5f, 1, .5f, 1, .5f, 1, .5f]);
    JuceTimelineSnapshot snapshot = new(1, 48_000, 4,
        [new JuceTimelineTrackSnapshot("track", 1, 0,
          [new("a", 0, 4, 0, 1, 2, 2, FadeCurve.Linear, source),
           new("b", 1, 3, 0, 1, 0, 0, FadeCurve.Linear, source)])]);
    JuceTimelineRenderer renderer = new(snapshot);
    float[] output = new float[8];

    _ = renderer.ProcessBlock(output, 0, 4);

    CollectionAssert.AreEqual(new float[] { 0, 0, 1.5f, .75f, 1.5f, .75f, 0, 0 }, output);
  }

  [TestMethod]
  public void RendererSeeksLoopsAndSwapsSnapshotAtBlockBoundary()
  {
    JuceTimelineSource source = new("source.wav", 48_000, 1, [1, 2, 3, 4, 5]);
    JuceTimelineRenderer renderer = new(Snapshot(1, 48_000,
        new("clip", 0, 4, 0, 1, 0, 0, FadeCurve.Linear, source)));
    float[] output = new float[4];

    JuceTimelineRenderResult first = renderer.ProcessBlock(output, 2, 2);
    CollectionAssert.AreEqual(new float[] { 3, 3, 4, 4 }, output);
    Assert.IsTrue(first.SnapshotChanged);

    _ = renderer.ProcessBlock(output, 0, 2);
    CollectionAssert.AreEqual(new float[] { 1, 1, 2, 2 }, output);
    renderer.Publish(Snapshot(2, 48_000,
        new("clip", 0, 4, 1, 1, 0, 0, FadeCurve.Linear, source)));
    JuceTimelineRenderResult replacement = renderer.ProcessBlock(output, 0, 2);
    CollectionAssert.AreEqual(new float[] { 2, 2, 3, 3 }, output);
    Assert.IsTrue(replacement.SnapshotChanged);
    _ = Assert.ThrowsExactly<ArgumentException>(() => renderer.Publish(renderer.Published));
  }

  [TestMethod]
  public async Task BuilderPreservesMissingMediaAndUnsupportedLayoutErrors()
  {
    AudioRenderGraph graph = Graph([new AudioClipSource("clip", "asset", "missing.wav", 0, 4, 0, 48_000)]);
    FailingReader missing = new(new FileNotFoundException("Authorized media is missing."));

    await Assert.ThrowsAsync<FileNotFoundException>(async () =>
        await JuceTimelineSnapshotBuilder.BuildAsync(1, graph, EmptyEditing(), missing));

    _ = Assert.ThrowsExactly<InvalidDataException>(() =>
        new JuceTimelineSource("surround.wav", 48_000, 6, new float[6]));
  }

  [TestMethod]
  public async Task BuilderRejectsUnsupportedPhaseVocoderWithoutChangingProjectData()
  {
    AudioRenderGraph graph = Graph([new AudioClipSource("clip", "asset", "source.wav", 0, 4, 0, 48_000)]);
    ClipEditingDescriptor descriptor = new("clip", null, null,
        new ProcessDescriptor(1, 1, ProcessAlgorithm.PhaseVocoder, []));
    ProfessionalEditingDocument editing = EmptyEditing() with { Clips = [descriptor] };
    StubReader reader = new(new JuceTimelineSource("source.wav", 48_000, 1, [1, 2, 3, 4]));

    await Assert.ThrowsAsync<NotSupportedException>(async () =>
        await JuceTimelineSnapshotBuilder.BuildAsync(1, graph, editing, reader));
  }

  [TestMethod]
  public async Task BuilderRejectsMismatchedRatesInvalidProcessAndInsufficientMedia()
  {
    AudioRenderGraph graph = Graph([new AudioClipSource("clip", "asset", "source.wav", 0, 4, 0, 48_000)]);
    StubReader wrongRate = new(new JuceTimelineSource("source.wav", 44_100, 1, [1, 2, 3, 4]));
    await Assert.ThrowsAsync<InvalidDataException>(async () =>
        await JuceTimelineSnapshotBuilder.BuildAsync(1, graph, EmptyEditing(), wrongRate));

    ClipEditingDescriptor invalidProcess = new("clip", null, null,
        new ProcessDescriptor(double.NaN, 1, ProcessAlgorithm.Resample, []));
    StubReader source = new(new JuceTimelineSource("source.wav", 48_000, 1, [1, 2, 3, 4]));
    await Assert.ThrowsAsync<InvalidDataException>(async () =>
        await JuceTimelineSnapshotBuilder.BuildAsync(1, graph, EmptyEditing() with { Clips = [invalidProcess] }, source));

    AudioRenderGraph tooLong = Graph([new AudioClipSource("clip", "asset", "source.wav", 0, 5, 0, 48_000)]);
    await Assert.ThrowsAsync<InvalidDataException>(async () =>
        await JuceTimelineSnapshotBuilder.BuildAsync(1, tooLong, EmptyEditing(), source));
  }

  [TestMethod]
  public void RendererPreservesStereoAndAppliesPanAcrossAudibleTracks()
  {
    JuceTimelineSource stereo = new("stereo.wav", 48_000, 2, [1, .25f, 1, .25f]);
    JuceTimelineSource mono = new("mono.wav", 48_000, 1, [.5f, .5f]);
    JuceTimelineSnapshot snapshot = new(1, 48_000, 2,
        [new JuceTimelineTrackSnapshot("left", 1, -1, [new("a", 0, 2, 0, 1, 0, 0, FadeCurve.Linear, stereo)]),
         new JuceTimelineTrackSnapshot("right", 1, 1, [new("b", 0, 2, 0, 1, 0, 0, FadeCurve.Linear, mono)])]);
    JuceTimelineRenderer renderer = new(snapshot);
    float[] output = new float[4];

    _ = renderer.ProcessBlock(output, 0, 2);

    CollectionAssert.AreEqual(new float[] { 1, .5f, 1, .5f }, output);
  }

  [TestMethod]
  public async Task BuilderProjectsMuteAndSoloBeforeSnapshotActivation()
  {
    JuceTimelineSource source = new("source.wav", 48_000, 1, [1]);
    AudioRenderGraph graph = new(new AudioEngineConfiguration("project", "device", 48_000, 256,
        [new AudioTrackRoute("muted", "master", 1, 0, true, false,
             [new AudioClipSource("a", "asset", "source.wav", 0, 1, 0, 48_000)]),
         new AudioTrackRoute("solo", "master", 1, 0, false, true,
             [new AudioClipSource("b", "asset", "source.wav", 0, 1, 0, 48_000)]),
         new AudioTrackRoute("plain", "master", 1, 0, false, false,
             [new AudioClipSource("c", "asset", "source.wav", 0, 1, 0, 48_000)])]));

    JuceTimelineSnapshot snapshot = await JuceTimelineSnapshotBuilder.BuildAsync(1, graph, EmptyEditing(), new StubReader(source));

    Assert.HasCount(1, snapshot.Tracks);
    Assert.AreEqual("solo", snapshot.Tracks[0].TrackId);
  }

  [TestMethod]
  public void RendererRejectsInvalidSnapshotsAndOverflowingBlocks()
  {
    JuceTimelineSource source = new("source.wav", 48_000, 1, [1]);
    JuceTimelineClipSnapshot invalid = new("clip", 0, 2, 0, 1, 0, 0, FadeCurve.Linear, source);
    _ = Assert.ThrowsExactly<InvalidDataException>(() => new JuceTimelineRenderer(Snapshot(1, 48_000, invalid)));

    JuceTimelineRenderer renderer = new(Snapshot(1, 48_000,
        new JuceTimelineClipSnapshot("clip", 0, 1, 0, 1, 0, 0, FadeCurve.Linear, source)));
    _ = Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
        renderer.ProcessBlock(new float[4], long.MaxValue, 2));
  }

  [TestMethod]
  public void PreparedProjectionDeduplicatesSourcesAndRoundTrips()
  {
    JuceTimelineSource source = new("source.wav", 48_000, 1, [1, 2]);
    JuceTimelineSnapshot snapshot = new(7, 48_000, 2,
        [new JuceTimelineTrackSnapshot("track", 1, 0,
          [new("a", 0, 1, 0, 1, 0, 0, FadeCurve.Linear, source),
           new("b", 1, 2, 1, 1, 0, 0, FadeCurve.EqualPower, source)])]);

    JucePreparedTimelineSnapshot prepared = JucePreparedTimelineProjection.Create(snapshot);
    JucePreparedTimelineSnapshot roundTrip = JuceAudioEngineProtocol.Parse<JucePreparedTimelineSnapshot>(
        JuceAudioEngineProtocol.Serialize(prepared));

    Assert.AreEqual(7, roundTrip.Revision);
    Assert.HasCount(1, roundTrip.Sources);
    Assert.HasCount(2, roundTrip.Tracks[0].Clips);
    Assert.AreEqual("equal_power", roundTrip.Tracks[0].Clips[1].FadeCurve);
  }

  [TestMethod]
  public void PreparedProjectionRejectsPayloadBeyondProtocolLimit()
  {
    float[] samples = Enumerable.Range(0, 300_000).Select(index => (float)(index % 997) / 997).ToArray();
    JuceTimelineSource source = new("source.wav", 48_000, 1, samples);
    JuceTimelineSnapshot snapshot = Snapshot(1, 48_000,
        new JuceTimelineClipSnapshot("clip", 0, samples.Length, 0, 1, 0, 0, FadeCurve.Linear, source));

    _ = Assert.ThrowsExactly<InvalidDataException>(() => JucePreparedTimelineProjection.Create(snapshot));
  }

  [TestMethod]
  public void PreparedProjectionUsesFileDescriptorWithoutEmbeddingProductionPcm()
  {
    string path = Path.Combine(Path.GetTempPath(), $"juce-file-source-{Guid.NewGuid():N}.wav");
    try
    {
      File.WriteAllBytes(path, [0]);
      JuceTimelineSource source = new(path, 48_000, 1, [1, 2, 3, 4]);
      JuceTimelineSnapshot snapshot = Snapshot(1, 48_000,
          new JuceTimelineClipSnapshot("clip", 0, 4, 0, 1, 0, 0, FadeCurve.Linear, source));

      JucePreparedTimelineSnapshot prepared = JucePreparedTimelineProjection.Create(snapshot, preferFileBackedMedia: true);
      JucePreparedTimelineSource preparedSource = prepared.Sources.Single();

      Assert.AreEqual(Path.GetFullPath(path), preparedSource.AuthorizedPath);
      Assert.AreEqual(4, preparedSource.FrameCount);
      Assert.IsTrue(preparedSource.InterleavedSamples.IsEmpty);
      Assert.IsLessThan(1024, JuceAudioEngineProtocol.Serialize(prepared).Length);
    }
    finally
    {
      File.Delete(path);
    }
  }

  [TestMethod]
  public async Task FileBackedReaderInspectsOnlyWaveMetadata()
  {
    string path = Path.Combine(Path.GetTempPath(), $"juce-file-source-{Guid.NewGuid():N}.wav");
    try
    {
      await File.WriteAllBytesAsync(path, WavePcmExtractorTests.Wave(1, 16, 1, [0, .5f, 1, -.5f]));

      JuceTimelineSource source = await new FileBackedWaveTimelineSourceReader().ReadAsync(path);

      Assert.IsTrue(source.IsFileBacked);
      Assert.AreEqual(48_000, source.SampleRate);
      Assert.AreEqual(1, source.Channels);
      Assert.AreEqual(4, source.FrameCount);
      _ = Assert.ThrowsExactly<InvalidOperationException>(() => source.ReadLinear(0, out _, out _));
    }
    finally
    {
      File.Delete(path);
    }
  }

  [TestMethod]
  public void RendererLongPlaybackIsContinuousAndAllocationFreeAfterWarmup()
  {
    const int framesPerBlock = 256;
    const int blocks = 10_000;
    float[] sourceSamples = Enumerable.Range(0, framesPerBlock * blocks).Select(index => (float)(index % 97) / 97).ToArray();
    JuceTimelineSource source = new("long.wav", 48_000, 1, sourceSamples);
    JuceTimelineRenderer renderer = new(Snapshot(1, 48_000,
        new JuceTimelineClipSnapshot("clip", 0, sourceSamples.Length, 0, 1, 0, 0, FadeCurve.Linear, source)));
    float[] output = new float[framesPerBlock * 2];
    _ = renderer.ProcessBlock(output, 0, framesPerBlock);
    long before = GC.GetAllocatedBytesForCurrentThread();
    bool continuous = true;
    for (int block = 1; block < blocks; block++)
    {
      long start = (long)block * framesPerBlock;
      JuceTimelineRenderResult result = renderer.ProcessBlock(output, start, framesPerBlock);
      continuous &= result.StartSample == start && !result.SnapshotChanged;
    }
    long allocated = GC.GetAllocatedBytesForCurrentThread() - before;

    Assert.IsTrue(continuous);
    Assert.AreEqual(0, allocated);
  }

  private static AudioRenderGraph Graph(ImmutableArray<AudioClipSource> clips)
  {
    return new(new AudioEngineConfiguration("project", "device", 48_000, 256,
        [new AudioTrackRoute("track", "master", 1, 0, false, false, clips)]));
  }

  private static JuceTimelineSnapshot Snapshot(long revision, int sampleRate, JuceTimelineClipSnapshot clip)
  {
    return new(revision, sampleRate, clip.TimelineEndSample,
        [new JuceTimelineTrackSnapshot("track", 1, 0, [clip])]);
  }

  private static ProfessionalEditingDocument EmptyEditing() => new(1, [], [], [], [], [], []);

  private sealed class StubReader(JuceTimelineSource source) : IJuceTimelineSourceReader
  {
    public int ReadCount { get; private set; }

    public ValueTask<JuceTimelineSource> ReadAsync(string authorizedPath, CancellationToken cancellationToken = default)
    {
      cancellationToken.ThrowIfCancellationRequested();
      ReadCount++;
      return ValueTask.FromResult(source);
    }
  }

  private sealed class FailingReader(Exception exception) : IJuceTimelineSourceReader
  {
    public ValueTask<JuceTimelineSource> ReadAsync(string authorizedPath, CancellationToken cancellationToken = default)
    {
      return ValueTask.FromException<JuceTimelineSource>(exception);
    }
  }
}
