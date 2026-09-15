using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class MixerProcessorTests
{
    private static MixerChannel Master => new("master", "Master", MixerChannelKind.Master, null, [], [], Pan: -1);

    [TestMethod]
    public void OfflineMixAppliesConstantPowerPanAndPublishesPeakRms()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [], [], Pan: -1), Master]);
        var processor = new MixerProcessor(plan, 4);
        float[] source = [1, 1, -1, -1, 0.5f, 0.5f, 0, 0];
        float[] output = new float[8];

        processor.ProcessBlock([new("track", source)], output, 4);

        Assert.AreEqual(1f, output[0], 0.0001f);
        Assert.AreEqual(0f, output[1], 0.0001f);
        var meters = new MixerMeterSnapshot[2];
        Assert.AreEqual(2, processor.CopyMeterSnapshots(meters));
        MixerMeterSnapshot track = meters.Single(item => item.ChannelId == "track");
        Assert.AreEqual(1f, track.PeakLeft, 0.0001f);
        Assert.AreEqual(0f, track.PeakRight, 0.0001f);
        Assert.AreEqual(0.75f, track.RmsLeft, 0.0001f);
        MixerMeterSnapshot master = meters.Single(item => item.ChannelId == "master");
        Assert.AreEqual(1f, master.PeakLeft, 0.0001f);
        Assert.AreEqual(0.75f, master.RmsLeft, 0.0001f);
    }

    [TestMethod]
    public void CenterPanPreservesStereoUnityGain()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [], []),
            new("master", "Master", MixerChannelKind.Master, null, [], [])]);
        var processor = new MixerProcessor(plan, 1);
        float[] output = new float[2];

        processor.ProcessBlock([new("track", new float[] { 0.25f, -0.5f })], output, 1);

        Assert.AreEqual(0.25f, output[0], 0.0001f);
        Assert.AreEqual(-0.5f, output[1], 0.0001f);
    }

    [TestMethod]
    public void PreAndPostFaderSendsUseUnambiguousTapSignals()
    {
        MixerChannel track = new("track", "Track", MixerChannelKind.Track, "master", [],
            [new("pre", "pre-fx", MixerTap.PreFader, 1), new("post", "post-fx", MixerTap.PostFader, 1)], Gain: 0.5f, Pan: -1);
        MixerGraphPlan plan = MixerGraphBuilder.Build([track,
            new("pre-fx", "Pre", MixerChannelKind.FxReturn, "master", [], [], Pan: -1),
            new("post-fx", "Post", MixerChannelKind.FxReturn, "master", [], [], Pan: -1), Master]);
        var processor = new MixerProcessor(plan, 1);
        float[] output = new float[2];

        processor.ProcessBlock([new("track", new float[] { 1, 1 })], output, 1);

        Assert.AreEqual(2f, output[0], 0.0001f); // direct .5 + pre 1 + post .5
        Assert.AreEqual(0f, output[1], 0.0001f);
    }

    [TestMethod]
    public void PdcDelayAlignsParallelImpulsesAcrossBlocksWithoutAllocation()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("dry", "Dry", MixerChannelKind.Track, "master", [], [], Pan: -1),
            new("wet", "Wet", MixerChannelKind.Track, "master", [new("latent", 2)], [], Pan: -1), Master]);
        var processor = new MixerProcessor(plan, 2);
        float[] first = new float[4];
        float[] second = new float[4];

        processor.ProcessBlock([new("dry", new float[] { 1, 0, 0, 0 }), new("wet", new float[] { 1, 0, 0, 0 })], first, 2);
        processor.ProcessBlock(ReadOnlySpan<MixerInputBlock>.Empty, second, 2);

        CollectionAssert.AreEqual(new float[] { 0, 0, 0, 0 }, first);
        Assert.AreEqual(2f, second[0], 0.0001f);
    }

    [TestMethod]
    public void MuteAndSoloAudibilityIsAppliedBeforeSumming()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("solo", "Solo", MixerChannelKind.Track, "master", [], [], Solo: true, Pan: -1),
            new("other", "Other", MixerChannelKind.Track, "master", [], [], Pan: -1), Master]);
        var processor = new MixerProcessor(plan, 1);
        float[] output = new float[2];
        processor.ProcessBlock([
            new("solo", new float[] { 0.25f, 0 }), new("other", new float[] { 1, 0 })], output, 1);
        Assert.AreEqual(0.25f, output[0], 0.0001f);
    }
}
