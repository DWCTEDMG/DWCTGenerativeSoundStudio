using System.Threading.Channels;
using EdmgStudio.Core.Audio;
using EdmgStudio.WinUI.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WindowsAudioEngineTests
{
    [TestMethod]
    public async Task CoreProcessorBoundaryIsAvailableWithoutClaimingAudioGraphProcessing()
    {
        var configuration = new AudioEngineConfiguration("project", "{default}", 48_000, 256,
            [new AudioTrackRoute("track", "master", 1, 0, false, false, [])]);
        MixerProcessor processor = WindowsAudioEngine.CreateCoreProcessor(configuration);
        await using var engine = new WindowsAudioEngine();

        Assert.AreEqual(256, processor.MaximumFrames);
        StringAssert.Contains(engine.MixerProcessingCapability, "file nodes do not expose decoded per-track quantum buffers");
        StringAssert.Contains(engine.MixerProcessingCapability, "does not execute bus/send/PDC/automation DSP");
    }

    [TestMethod]
    public void DirectPlaybackProjectionPreservesModeledConfiguration()
    {
        var configuration = new AudioEngineConfiguration("project", "{default}", 48_000, 256,
            [new AudioTrackRoute("track", "group", 0.8f, 0.5f, false, false, [])]);

        AudioEngineConfiguration playback = configuration.ForDirectMasterPlayback();

        Assert.AreEqual("group", configuration.Tracks[0].OutputBusId);
        Assert.AreEqual(0.5f, configuration.Tracks[0].Pan);
        Assert.AreEqual("master", playback.Tracks[0].OutputBusId);
        Assert.AreEqual(0f, playback.Tracks[0].Pan);
        Assert.AreEqual(0.8f, playback.Tracks[0].Gain);
    }

    [TestMethod]
    public async Task WorkerFailureClosesTransportQueueAndRejectsReconfiguration()
    {
        var failure = new InvalidOperationException("Injected playback failure");
        await using var engine = new WindowsAudioEngine(() => throw failure);
        var state = new TransportState("project", 48_000, 48_000, 0,
            TransportMode.Playing, new(false, 0, 48_000));
        await engine.EnqueueTransportStateAsync(state);
        await engine.WorkerCompletion.WaitAsync(TimeSpan.FromSeconds(5));

        await Assert.ThrowsAsync<ChannelClosedException>(async () =>
            await engine.EnqueueTransportStateAsync(state).AsTask().WaitAsync(TimeSpan.FromSeconds(5)));
        var configuration = new AudioEngineConfiguration("project", "{default}", 48_000, 512, []);
        InvalidOperationException reported = await Assert.ThrowsAsync<InvalidOperationException>(async () =>
            await engine.ConfigureAsync(configuration).WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.AreSame(failure, reported.InnerException);
        Assert.IsNotNull(engine.FailureMessage);
        Assert.IsNull(engine.Configuration);
    }
}
