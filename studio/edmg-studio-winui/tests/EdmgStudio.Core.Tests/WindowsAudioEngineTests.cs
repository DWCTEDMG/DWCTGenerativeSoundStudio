using System.Threading.Channels;
using EdmgStudio.Core.Audio;
using EdmgStudio.WinUI.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WindowsAudioEngineTests
{
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
