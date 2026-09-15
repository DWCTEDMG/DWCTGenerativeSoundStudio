using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class MixerGraphTests
{
    [TestMethod]
    public void LegacyMasterRouteDoesNotCollideWithTrackIdentity()
    {
        var config = new AudioEngineConfiguration("project", "default", 48_000, 512,
            [new("master", "MASTER", 1, 0, false, false, [])]);
        MixerGraphPlan plan = MixerGraphBuilder.FromAudioRoutes(config);
        Assert.AreEqual("_master", plan.Routes.Single().DestinationId);
        Assert.AreEqual(0L, plan.TotalLatencySamples);
    }
    private static MixerChannel Track(string id, int latency, string output = "master") =>
        new(id, id, MixerChannelKind.Track, output, [new("insert", latency)], []);
    private static MixerChannel Master => new("master", "Master", MixerChannelKind.Master, null, [], []);

    [TestMethod]
    public void ParallelTracksAndBusAreAlignedInSamples()
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            Track("dry", 64), Track("wet", 128, "bus"),
            new("bus", "Bus", MixerChannelKind.Group, "master", [new("effect", 32)], []), Master]);
        Assert.AreEqual(160L, plan.TotalLatencySamples);
        Assert.AreEqual(96L, plan.Routes.Single(route => route.SourceId == "dry").DelaySamples);
        Assert.AreEqual(0L, plan.Routes.Single(route => route.SourceId == "bus").DelaySamples);
    }

    [TestMethod]
    public void PreAndPostSendsKeepTheirTapGainAndIndependentCompensation()
    {
        MixerChannel source = Track("source", 10) with { Sends = [new("verb", "fx", MixerTap.PreFader, 0.25f)] };
        MixerGraphPlan plan = MixerGraphBuilder.Build([source,
            new("fx", "Reverb", MixerChannelKind.FxReturn, "master", [new("reverb", 30)], []), Master]);
        MixerRouteDelay send = plan.Routes.Single(route => route.Id == "send:verb");
        Assert.AreEqual(MixerTap.PreFader, send.Tap);
        Assert.AreEqual(0.25f, send.Gain);
        Assert.AreEqual(30L, plan.Routes.Single(route => route.SourceId == "source" && route.Id == "output").DelaySamples);
    }

    [TestMethod]
    public void CyclesMissingDestinationsAndDuplicateIdsAreRejected()
    {
        Assert.Throws<ArgumentException>(() => MixerGraphBuilder.Build([Track("a", 0, "missing"), Master]));
        Assert.Throws<ArgumentException>(() => MixerGraphBuilder.Build([Track("a", 0), Track("a", 0), Master]));
        Assert.Throws<ArgumentException>(() => MixerGraphBuilder.Build([
            new("a", "A", MixerChannelKind.Group, "b", [], []),
            new("b", "B", MixerChannelKind.Group, "a", [], []), Master]));
    }

    [TestMethod]
    public void InvalidGainLatencyAndMasterFeedbackFailBeforePlanning()
    {
        Assert.Throws<ArgumentException>(() => MixerGraphBuilder.Build([Track("a", -1), Master]));
        Assert.Throws<ArgumentException>(() => MixerGraphBuilder.Build([
            Track("a", 0) with { Sends = [new("send", "master", MixerTap.PostFader, float.NaN)] }, Master]));
        Assert.Throws<ArgumentException>(() => MixerGraphBuilder.Build([
            Track("a", 0), Master with { OutputId = "a" }]));
    }

    [TestMethod]
    public void PublishedPlanDoesNotObserveLaterInputListChanges()
    {
        var channels = new List<MixerChannel> { Track("a", 50), Master };
        MixerGraphPlan plan = MixerGraphBuilder.Build(channels);
        channels.Clear();
        Assert.HasCount(2, plan.ProcessingOrder);
        Assert.AreEqual(50L, plan.TotalLatencySamples);
    }

    [TestMethod]
    public void OrderingIsDeterministicAndBypassRetainsLatency()
    {
        MixerChannel[] channels = [Track("b", 12) with { Inserts = [new("bypass", 12, Bypassed: true), new("disabled", 100, Enabled: false)] }, Track("a", 3), Master];
        MixerGraphPlan first = MixerGraphBuilder.Build(channels);
        MixerGraphPlan second = MixerGraphBuilder.Build(channels.Reverse());
        CollectionAssert.AreEqual(first.ProcessingOrder.Select(channel => channel.Id).ToArray(), second.ProcessingOrder.Select(channel => channel.Id).ToArray());
        CollectionAssert.AreEqual(first.Routes.ToArray(), second.Routes.ToArray());
        Assert.AreEqual(12L, first.TotalLatencySamples);
    }
}
