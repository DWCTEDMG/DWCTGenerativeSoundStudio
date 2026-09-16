using System.Collections.Immutable;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class LiveMixerCallbackAdapterTests
{
    [TestMethod]
    public void ProcessesVariableQuantaWithSampleAccurateAutomationAndDiscontinuityReset()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [new("latency", 1)], [], Pan: -1),
            new("master", "Master", MixerChannelKind.Master, null, [], [], Pan: -1)]);
        var automation = new AudioAutomationSnapshot([
            new("volume", "track", "volume", AutomationMode.Read, 1,
                [new(0, 0, AutomationCurve.Linear, 0), new(4, 1, AutomationCurve.Linear, 0)])]);
        var adapter = new LiveMixerCallbackAdapter(new(1, plan, automation, 4), 100);
        float[] first = new float[4], second = new float[6], seek = new float[2];

        LiveMixerQuantumResult firstResult = adapter.ProcessQuantum(
            [new("track", [1, 0, 1, 0])], first, 0, 2);
        LiveMixerQuantumResult secondResult = adapter.ProcessQuantum(
            [new("track", [1, 0, 1, 0, 1, 0])], second, 2, 3);
        LiveMixerQuantumResult seekResult = adapter.ProcessQuantum(
            [new("track", [1, 0])], seek, 20, 1, transportDiscontinuity: true);

        Assert.IsTrue(firstResult.Callback.StateReset);
        Assert.IsFalse(secondResult.Callback.StateReset);
        Assert.AreEqual(.25f, first[2], .0001f);
        Assert.AreEqual(.5f, second[0], .0001f);
        Assert.AreEqual(1f, second[4], .0001f);
        Assert.IsTrue(seekResult.Callback.StateReset);
        Assert.AreEqual(0f, seek[0]);

        adapter.Publish(new(2, MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [], [], Gain: .5f, Pan: -1),
            new("master", "Master", MixerChannelKind.Master, null, [], [], Pan: -1)]), AudioAutomationSnapshot.Empty, 4));
        LiveMixerQuantumResult swapped = adapter.ProcessQuantum([new("track", [1, 0])], seek, 21, 1);
        Assert.AreEqual(2L, swapped.Callback.Revision);
        Assert.IsTrue(swapped.Callback.StateReset);
        Assert.AreEqual(.5f, seek[0], .0001f);
    }

    [TestMethod]
    public void PublishesThrottledMetersFromProcessedMasterBlocks()
    {
        LiveMixerCallbackAdapter adapter = CreateAdapter(maximumFrames: 4, meterIntervalSamples: 4);
        var meters = new MixerMeterSnapshot[2];
        long sequence = 0;

        LiveMixerQuantumResult first = adapter.ProcessQuantum([new("track", [.5f, -.25f, 0, 0])], new float[4], 10, 2);
        Assert.IsTrue(first.MeterSnapshotPublished);
        Assert.IsTrue(adapter.TryCopyMeters(meters, out int count, out long sample, ref sequence));
        Assert.AreEqual(2, count);
        Assert.AreEqual(10L, sample);
        Assert.AreEqual(.5f, meters.Single(meter => meter.ChannelId == "master").PeakLeft, .0001f);
        Assert.IsFalse(adapter.TryCopyMeters(meters, out _, out _, ref sequence));

        LiveMixerQuantumResult throttled = adapter.ProcessQuantum([new("track", [1f, 0])], new float[2], 12, 1);
        LiveMixerQuantumResult published = adapter.ProcessQuantum([new("track", [1f, 0, 0, 0])], new float[4], 13, 2);
        Assert.IsFalse(throttled.MeterSnapshotPublished);
        Assert.IsTrue(published.MeterSnapshotPublished);
    }

    [TestMethod]
    public void FailureSilencesOutputAndRecoveryResetsState()
    {
        LiveMixerCallbackAdapter adapter = CreateAdapter(maximumFrames: 2, meterIntervalSamples: 2);
        float[] output = [1, 1, 1, 1, 1, 1];

        LiveMixerQuantumResult failed = adapter.ProcessQuantum([new("track", [1, 0, 1, 0, 1, 0])], output, 0, 3);
        Assert.AreEqual(LiveMixerCallbackState.Failed, failed.State);
        CollectionAssert.AreEqual(new float[6], output);
        Assert.IsNotNull(adapter.Failure);

        LiveMixerQuantumResult stillFailed = adapter.ProcessQuantum([], output, 3, 2);
        Assert.AreEqual(LiveMixerCallbackState.Failed, stillFailed.State);
        adapter.Recover(Snapshot(maximumFrames: 2));
        LiveMixerQuantumResult recovered = adapter.ProcessQuantum([new("track", [1, 0])], output, 0, 1);
        Assert.AreEqual(LiveMixerCallbackState.Ready, recovered.State);
        Assert.IsTrue(recovered.Callback.StateReset);
        Assert.AreEqual(1f, output[0]);
    }

    private static LiveMixerCallbackAdapter CreateAdapter(int maximumFrames, int meterIntervalSamples) =>
        new(Snapshot(maximumFrames), meterIntervalSamples);

    private static AudioCallbackSnapshot Snapshot(int maximumFrames) => new(1, MixerGraphBuilder.Build([
        new("track", "Track", MixerChannelKind.Track, "master", [], [], Pan: -1),
        new("master", "Master", MixerChannelKind.Master, null, [], [], Pan: -1)]),
        AudioAutomationSnapshot.Empty, maximumFrames);
}
