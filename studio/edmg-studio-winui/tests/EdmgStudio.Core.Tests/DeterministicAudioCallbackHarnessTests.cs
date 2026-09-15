using System.Collections.Immutable;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class DeterministicAudioCallbackHarnessTests
{
    private static MixerChannel Master => new("master", "Master", MixerChannelKind.Master, null, [], [], Pan: -1);

    [TestMethod]
    public void ProcessesBusSendPdcAndMetersAcrossBlockBoundaries()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("dry", "Dry", MixerChannelKind.Track, "bus", [], [new("verb", "fx", MixerTap.PostFader, .5f)], Pan: -1),
            new("wet", "Wet", MixerChannelKind.Track, "bus", [new("latent", 2)], [], Pan: -1),
            new("bus", "Bus", MixerChannelKind.Group, "master", [], [], Pan: -1),
            new("fx", "Fx", MixerChannelKind.FxReturn, "master", [], [], Pan: -1), Master]);
        var harness = new DeterministicAudioCallbackHarness(new(1, plan, AudioAutomationSnapshot.Empty, 2));
        float[] first = new float[4], second = new float[4];

        AudioCallbackResult firstResult = harness.ProcessBlock([
            new("dry", [1, 0, 0, 0]), new("wet", [1, 0, 0, 0])], first, 0, 2);
        AudioCallbackResult secondResult = harness.ProcessBlock([], second, 2, 2);

        CollectionAssert.AreEqual(new float[] { 0, 0, 0, 0 }, first);
        Assert.AreEqual(2.5f, second[0], .0001f);
        Assert.IsTrue(firstResult.StateReset);
        Assert.IsFalse(secondResult.StateReset);
        var meters = new MixerMeterSnapshot[5];
        Assert.AreEqual(5, harness.CopyMeterSnapshots(meters));
        Assert.AreEqual(2.5f, meters.Single(m => m.ChannelId == "master").PeakLeft, .0001f);
    }

    [TestMethod]
    public void AutomationIsSampleAccurateAcrossBlocksForVolumePanAndSend()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [], [new("fx-send", "fx", MixerTap.PostFader, 1)]),
            new("fx", "Fx", MixerChannelKind.FxReturn, "master", [], []),
            new("master", "Master", MixerChannelKind.Master, null, [], [])]);
        var automation = new AudioAutomationSnapshot([
            Lane("volume", 1, new(0, 0, AutomationCurve.Linear, 0), new(4, 1, AutomationCurve.Linear, 0)),
            Lane("pan", 0, new(0, -1, AutomationCurve.Step, 0), new(2, 1, AutomationCurve.Step, 0)),
            Lane("send:fx", 0, new(0, 0, AutomationCurve.Step, 0), new(2, 1, AutomationCurve.Step, 0))]);
        var harness = new DeterministicAudioCallbackHarness(new(1, plan, automation, 2));
        float[] first = new float[4], second = new float[4];

        harness.ProcessBlock([new("track", [1, 1, 1, 1])], first, 0, 2);
        harness.ProcessBlock([new("track", [1, 1, 1, 1])], second, 2, 2);

        CollectionAssert.AreEqual(new float[] { 0, 0, .25f, 0 }, first);
        Assert.AreEqual(0f, second[0], .0001f);
        Assert.AreEqual(1f, second[1], .0001f);
        Assert.AreEqual(0f, second[2], .0001f);
        Assert.AreEqual(1.5f, second[3], .0001f);
    }

    [TestMethod]
    public void SeekLoopAndGraphSwapResetDelayStateAndAdoptAtomicSnapshot()
    {
        MixerGraphPlan delayed = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [new("delay", 2)], [], Pan: -1), Master]);
        MixerGraphPlan immediate = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [], [], Gain: .5f, Pan: -1), Master]);
        var harness = new DeterministicAudioCallbackHarness(new(1, delayed, AudioAutomationSnapshot.Empty, 2));
        float[] output = new float[4];
        harness.ProcessBlock([new("track", [1, 0, 0, 0])], output, 0, 2);

        Array.Clear(output);
        AudioCallbackResult seek = harness.ProcessBlock([], output, 10, 2);
        CollectionAssert.AreEqual(new float[4], output);
        Assert.IsTrue(seek.StateReset);
        AudioCallbackResult loop = harness.ProcessBlock([], output, 4, 2, transportDiscontinuity: true);
        Assert.IsTrue(loop.StateReset);

        harness.Publish(new(2, immediate, AudioAutomationSnapshot.Empty, 2));
        AudioCallbackResult swap = harness.ProcessBlock([new("track", [1, 0, 0, 0])], output, 6, 2);
        Assert.AreEqual(2L, swap.Revision);
        Assert.IsTrue(swap.StateReset);
        Assert.AreEqual(.5f, output[0], .0001f);
        Assert.ThrowsExactly<ArgumentException>(() => harness.Publish(new(2, delayed, AudioAutomationSnapshot.Empty, 2)));
    }

    private static AutomationLaneSnapshot Lane(string target, double defaultValue, params AutomationSamplePoint[] points) =>
        new("lane-" + target, "track", target, AutomationMode.Read, defaultValue, points.ToImmutableArray());
}
