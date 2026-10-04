using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;
using System.Collections.Immutable;

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
    DeterministicAudioCallbackHarness harness = new(new(1, plan, AudioAutomationSnapshot.Empty, 2));
    float[] first = new float[4], second = new float[4];

    AudioCallbackResult firstResult = harness.ProcessBlock([
        new("dry", [1, 0, 0, 0]), new("wet", [1, 0, 0, 0])], first, 0, 2);
    AudioCallbackResult secondResult = harness.ProcessBlock([], second, 2, 2);

    CollectionAssert.AreEqual(new float[] { 0, 0, 0, 0 }, first);
    Assert.AreEqual(2.5f, second[0], .0001f);
    Assert.IsTrue(firstResult.StateReset);
    Assert.IsFalse(secondResult.StateReset);
    MixerMeterSnapshot[] meters = new MixerMeterSnapshot[5];
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
    AudioAutomationSnapshot automation = new([
            Lane("volume", 1, new(0, 0, AutomationCurve.Linear, 0), new(4, 1, AutomationCurve.Linear, 0)),
            Lane("pan", 0, new(0, -1, AutomationCurve.Step, 0), new(2, 1, AutomationCurve.Step, 0)),
            Lane("send:fx", 0, new(0, 0, AutomationCurve.Step, 0), new(2, 1, AutomationCurve.Step, 0))]);
    DeterministicAudioCallbackHarness harness = new(new(1, plan, automation, 2));
    float[] first = new float[4], second = new float[4];

    _ = harness.ProcessBlock([new("track", [1, 1, 1, 1])], first, 0, 2);
    _ = harness.ProcessBlock([new("track", [1, 1, 1, 1])], second, 2, 2);

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
    DeterministicAudioCallbackHarness harness = new(new(1, delayed, AudioAutomationSnapshot.Empty, 2));
    float[] output = new float[4];
    _ = harness.ProcessBlock([new("track", [1, 0, 0, 0])], output, 0, 2);

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
    _ = Assert.ThrowsExactly<ArgumentException>(() => harness.Publish(new(2, delayed, AudioAutomationSnapshot.Empty, 2)));
  }

  [TestMethod]
  public void RejectsMissingAndDeletedAutomationTargetsBeforeActivation()
  {
    MixerGraphPlan withSend = MixerGraphBuilder.Build([
        new("track", "Track", MixerChannelKind.Track, "master", [], [new("fx-send", "fx", MixerTap.PostFader, 1)]),
        new("fx", "Fx", MixerChannelKind.FxReturn, "master", [], []),
        new("master", "Master", MixerChannelKind.Master, null, [], [])]);
    AudioAutomationSnapshot sendAutomation = new([Lane("send:fx", 1)]);
    DeterministicAudioCallbackHarness harness = new(new(1, withSend, sendAutomation, 2));

    MixerGraphPlan deletedSend = MixerGraphBuilder.Build([
        new("track", "Track", MixerChannelKind.Track, "master", [], []),
        new("fx", "Fx", MixerChannelKind.FxReturn, "master", [], []),
        new("master", "Master", MixerChannelKind.Master, null, [], [])]);
    _ = Assert.ThrowsExactly<ArgumentException>(() => harness.Publish(new(2, deletedSend, sendAutomation, 2)));

    AudioAutomationSnapshot missingTrack = new([
        new("missing-lane", "missing", "volume", AutomationMode.Read, 1, [])]);
    _ = Assert.ThrowsExactly<ArgumentException>(() => harness.Publish(new(2, withSend, missingTrack, 2)));
  }

  [TestMethod]
  public void CompleteMixerCallbackIsAllocationFreeAfterWarmup()
  {
    MixerGraphPlan plan = MixerGraphBuilder.Build([
        new("track", "Track", MixerChannelKind.Track, "master", [], [], Pan: -.25f),
        new("master", "Master", MixerChannelKind.Master, null, [], [])]);
    DeterministicAudioCallbackHarness harness = new(new(1, plan, AudioAutomationSnapshot.Empty, 256));
    MixerInputBlock[] inputs = [new("track", new float[512])];
    float[] output = new float[512];
    for (int index = 0; index < 32; index++)
    {
      _ = harness.ProcessBlock(inputs, output, index * 256L, 256);
    }

    long before = GC.GetAllocatedBytesForCurrentThread();
    for (int index = 32; index < 10_032; index++)
    {
      _ = harness.ProcessBlock(inputs, output, index * 256L, 256);
    }

    Assert.AreEqual(0L, GC.GetAllocatedBytesForCurrentThread() - before);
  }

  private static AutomationLaneSnapshot Lane(string target, double defaultValue, params AutomationSamplePoint[] points)
  {
    return new("lane-" + target, "track", target, AutomationMode.Read, defaultValue, points.ToImmutableArray());
  }
}
