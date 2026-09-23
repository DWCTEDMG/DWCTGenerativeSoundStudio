using EdmgStudio.Core.Audio;
using EdmgStudio.WinUI.Services;
using System.Threading.Channels;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WindowsAudioEngineTests
{
  [TestMethod]
  public async Task CoreProcessorBoundaryReportsLiveAudioGraphMixerProcessing()
  {
    AudioEngineConfiguration configuration = new("project", "{default}", 48_000, 256,
            [new AudioTrackRoute("track", "master", 1, 0, false, false, [])]);
    MixerProcessor processor = WindowsAudioEngine.CreateCoreProcessor(configuration);
    await using WindowsAudioEngine engine = new();

    Assert.AreEqual(256, processor.MaximumFrames);
    StringAssert.Contains(engine.MixerProcessingCapability, "decoded per-track float quanta");
    StringAssert.Contains(engine.MixerProcessingCapability, "ordered isolated VST3 inserts");
    StringAssert.Contains(engine.MixerProcessingCapability, "processed stereo master");
  }

  [TestMethod]
  public void CoreProcessorUsesAuthoritativeMixerChannelsWhenProvided()
  {
    AudioEngineConfiguration configuration = new("project", "{default}", 48_000, 256,
        [new AudioTrackRoute("route-track", "master", 1, 0, false, false, [])],
        [new MixerChannel("snapshot-track", "Snapshot", MixerChannelKind.Track, "master", [], []),
         new MixerChannel("master", "Master", MixerChannelKind.Master, null, [], [])]);

    MixerProcessor processor = WindowsAudioEngine.CreateCoreProcessor(configuration);

    CollectionAssert.Contains(processor.ChannelIds.ToArray(), "snapshot-track");
    CollectionAssert.DoesNotContain(processor.ChannelIds.ToArray(), "route-track");
  }

  [TestMethod]
  public void CoreProcessorAcceptsNegotiatedQuantumCapacity()
  {
    AudioEngineConfiguration configuration = new("project", "{default}", 48_000, 256, []);

    MixerProcessor processor = WindowsAudioEngine.CreateCoreProcessor(configuration, maximumFrames: 480);

    Assert.AreEqual(480, processor.MaximumFrames);
  }

  [TestMethod]
  public void WorkerCompatibilityRequiresIdentityFormatAndCapacity()
  {
    var insert = new MixerInsert("insert", 0, PluginId: "plugin", ModulePath: @"C:\Plugins\effect.vst3");
    using var processor = new FakeInsertProcessor(@"C:\Plugins\effect.vst3", "plugin", 48_000, 512);

    Assert.IsTrue(WindowsAudioEngine.IsProcessorCompatible(processor, insert, 48_000, 256));
    Assert.IsFalse(WindowsAudioEngine.IsProcessorCompatible(processor, insert, 44_100, 256));
    Assert.IsFalse(WindowsAudioEngine.IsProcessorCompatible(processor, insert, 48_000, 1024));
    Assert.IsFalse(WindowsAudioEngine.IsProcessorCompatible(processor, insert with { PluginId = "other" }, 48_000, 256));
  }

  [TestMethod]
  public void DirectPlaybackProjectionPreservesModeledConfiguration()
  {
    AudioEngineConfiguration configuration = new("project", "{default}", 48_000, 256,
            [new AudioTrackRoute("track", "group", 0.8f, 0.5f, false, false, [])]);

    AudioEngineConfiguration playback = configuration.ForDirectMasterPlayback();

    Assert.AreEqual("group", configuration.Tracks[0].OutputBusId);
    Assert.AreEqual(0.5f, configuration.Tracks[0].Pan);
    Assert.AreEqual("master", playback.Tracks[0].OutputBusId);
    Assert.AreEqual(0f, playback.Tracks[0].Pan);
    Assert.AreEqual(0.8f, playback.Tracks[0].Gain);
  }

  [TestMethod]
  public void SharedGraphUsesRenderDeviceFormatInsteadOfForcingProjectPcmFormat()
  {
    AudioEngineConfiguration configuration = new("project", "{default}", 48_000, 256, []);

    Windows.Media.Audio.AudioGraphSettings settings = WindowsAudioEngine.CreateGraphSettings(configuration, null);

    Assert.IsNull(settings.EncodingProperties);
    Assert.AreEqual(256, settings.DesiredSamplesPerQuantum);
    Assert.IsNull(settings.PrimaryRenderDevice);
  }

  [TestMethod]
  public async Task WorkerFailureClosesTransportQueueAndRejectsReconfiguration()
  {
    InvalidOperationException failure = new("Injected playback failure");
    await using WindowsAudioEngine engine = new(() => throw failure);
    TransportState state = new("project", 48_000, 48_000, 0,
            TransportMode.Playing, new(false, 0, 48_000));
    await engine.EnqueueTransportStateAsync(state);
    await engine.WorkerCompletion.WaitAsync(TimeSpan.FromSeconds(5));

    _ = await Assert.ThrowsAsync<ChannelClosedException>(async () =>
        await engine.EnqueueTransportStateAsync(state).AsTask().WaitAsync(TimeSpan.FromSeconds(5)));
    AudioEngineConfiguration configuration = new("project", "{default}", 48_000, 512, []);
    InvalidOperationException reported = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
        await engine.ConfigureAsync(configuration).WaitAsync(TimeSpan.FromSeconds(5)));
    Assert.AreSame(failure, reported.InnerException);
    Assert.IsNotNull(engine.FailureMessage);
    Assert.IsNull(engine.Configuration);
  }

  private sealed class FakeInsertProcessor(string modulePath, string pluginId, int sampleRate, int maximumFrames) : IVst3InsertProcessor
  {
    public string InstanceId => "fake";
    public string ModulePath { get; } = modulePath;
    public string PluginId { get; } = pluginId;
    public int SampleRate { get; } = sampleRate;
    public int MaximumFrames { get; } = maximumFrames;
    public int ReportedLatencySamples => 0;
    public Vst3WorkerHealth Health => Vst3WorkerHealth.Ready;
    public string? Diagnostic => null;
    public bool TryProcessInPlace(Span<float> interleavedStereo, int frames) => true;
    public void Reset() { }
    public void Dispose() { }
  }
}
