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

    [TestMethod]
    public void EnabledInsertsExecuteInDeclaredOrder()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [new("double", 0), new("add", 0)], [], Pan: -1), Master]);
        var multiply = new FakeInsertProcessor("double", samples => { for (int i = 0; i < samples.Length; i++) samples[i] *= 2; });
        var add = new FakeInsertProcessor("add", samples => { for (int i = 0; i < samples.Length; i++) samples[i] += 1; });
        var processor = new MixerProcessor(plan, 1, [new("track", "double", multiply), new("track", "add", add)]);
        float[] output = new float[2];

        processor.ProcessBlock([new("track", new float[] { 1, 0 })], output, 1);

        Assert.AreEqual(3f, output[0], 0.0001f);
        Assert.AreEqual(1, multiply.ProcessCalls);
        Assert.AreEqual(1, add.ProcessCalls);
    }

    [TestMethod]
    public void BypassedAndFailedInsertsPreserveLatencyWhileDisabledInsertDoesNothing()
    {
        var failed = new FakeInsertProcessor("failed", _ => { }, succeeds: false);
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new("track", "Track", MixerChannelKind.Track, "master", [
                new("bypass", 1, Bypassed: true), new("failed", 1), new("disabled", 10, Enabled: false)], [], Pan: -1), Master]);
        var processor = new MixerProcessor(plan, 1, [
            new("track", "bypass", new FakeInsertProcessor("bypass", _ => Assert.Fail("Bypassed insert executed."))),
            new("track", "failed", failed),
            new("track", "disabled", new FakeInsertProcessor("disabled", _ => Assert.Fail("Disabled insert executed.")))]);
        float[] first = new float[2];
        float[] second = new float[2];
        float[] third = new float[2];

        processor.ProcessBlock([new("track", new float[] { 1, 0 })], first, 1);
        processor.ProcessBlock(ReadOnlySpan<MixerInputBlock>.Empty, second, 1);
        processor.ProcessBlock(ReadOnlySpan<MixerInputBlock>.Empty, third, 1);

        Assert.AreEqual(0f, first[0], 0.0001f);
        Assert.AreEqual(0f, second[0], 0.0001f);
        Assert.AreEqual(1f, third[0], 0.0001f);
        Assert.AreEqual(1, failed.ProcessCalls);
    }

    private sealed class FakeInsertProcessor(string instanceId, Action<Span<float>> process, bool succeeds = true) : IVst3InsertProcessor
    {
        public string InstanceId { get; } = instanceId;
        public string ModulePath => "fake.vst3";
        public string PluginId => "fake-plugin";
        public int SampleRate => 48_000;
        public int MaximumFrames => 1024;
        public int ReportedLatencySamples => 0;
        public Vst3WorkerHealth Health { get; private set; } = Vst3WorkerHealth.Ready;
        public string? Diagnostic => null;
        public int ProcessCalls { get; private set; }
        public bool TryProcessInPlace(Span<float> interleavedStereo, int frames)
        {
            if (Health != Vst3WorkerHealth.Ready) return false;
            ProcessCalls++;
            if (!succeeds) { Health = Vst3WorkerHealth.Failed; return false; }
            process(interleavedStereo[..(frames * 2)]);
            return true;
        }
        public void Reset() { }
        public void Dispose() { }
    }
}
