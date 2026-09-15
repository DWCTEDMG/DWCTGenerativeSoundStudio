using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TimelineMixerProjectionTests
{
    [TestMethod]
    public void Project_UsesSafeDefaultsForLegacyTracks()
    {
        CanonicalProject project = Project("""{"tracks":[{"id":"audio","name":"Audio","type":"audio","clips":[]}]}""");

        TimelineTrackMixerState state = TimelineMixerProjection.Project(project).Single();

        Assert.AreEqual(1f, state.Gain);
        Assert.AreEqual(0f, state.Pan);
        Assert.IsFalse(state.Muted);
        Assert.IsFalse(state.Solo);
        Assert.IsFalse(state.RecordArmed);
        Assert.IsFalse(state.InputMonitoring);
        Assert.AreEqual("master", state.OutputId);
    }

    [TestMethod]
    public void UpdateTrack_PreservesUnknownFieldsClipsAndOtherTracks()
    {
        JsonObject timeline = JsonNode.Parse("""
            {"vendor":{"keep":true},"tracks":[
              {"id":"audio","name":"Audio","type":"audio","vendor":{"track":true},
               "routing":{"bus":"legacy","vendor":"route"},"clips":[{"id":"clip","start_s":0,"end_s":1,"vendor":7}]},
              {"id":"other","name":"Other","type":"audio","gain":0.25,"clips":[]}]}
            """)!.AsObject();
        var state = new TimelineTrackMixerState("audio", "Audio", 0.75f, -0.5f, true, true, true, true, "master");

        JsonObject updated = TimelineMixerProjection.UpdateTrack(timeline, "audio", state);

        Assert.IsTrue(updated["vendor"]!["keep"]!.GetValue<bool>());
        Assert.IsTrue(updated["tracks"]![0]!["vendor"]!["track"]!.GetValue<bool>());
        Assert.AreEqual(7, updated["tracks"]![0]!["clips"]![0]!["vendor"]!.GetValue<int>());
        Assert.AreEqual("route", updated["tracks"]![0]!["routing"]!["vendor"]!.GetValue<string>());
        Assert.AreEqual("master", updated["tracks"]![0]!["routing"]!["bus"]!.GetValue<string>());
        Assert.AreEqual(0.75f, updated["tracks"]![0]!["gain"]!.GetValue<float>());
        Assert.AreEqual(-0.5f, updated["tracks"]![0]!["pan"]!.GetValue<float>());
        Assert.IsTrue(updated["tracks"]![0]!["muted"]!.GetValue<bool>());
        Assert.AreEqual(0.25, updated["tracks"]![1]!["gain"]!.GetValue<double>());
        Assert.AreEqual("legacy", timeline["tracks"]![0]!["routing"]!["bus"]!.GetValue<string>());
    }

    [TestMethod]
    public void UpdateTrack_RejectsInvalidValuesAndRoutes()
    {
        JsonObject timeline = JsonNode.Parse("""{"tracks":[{"id":"audio","type":"audio","clips":[]}]}""")!.AsObject();
        var valid = new TimelineTrackMixerState("audio", "Audio", 1, 0, false, false, false, false, "master");

        Assert.Throws<ArgumentOutOfRangeException>(() =>
            TimelineMixerProjection.UpdateTrack(timeline, "audio", valid with { Gain = float.NaN }));
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            TimelineMixerProjection.UpdateTrack(timeline, "audio", valid with { Pan = 1.1f }));
        Assert.Throws<ArgumentException>(() =>
            TimelineMixerProjection.UpdateTrack(timeline, "audio", valid with { OutputId = "effects" }));
        Assert.IsNull(timeline["tracks"]![0]!["gain"]);
    }

    [TestMethod]
    public void ToMixerChannels_ProducesGraphCompatibleAudioTracks()
    {
        CanonicalProject project = Project("""
            {"tracks":[
              {"id":"audio","name":"Dialog","type":"audio","gain":0.8,"pan":0.25,"muted":true,
               "solo":true,"record_armed":true,"input_monitoring":true,"routing":{"bus":"master"},"clips":[]},
              {"id":"video","name":"Picture","type":"video","clips":[]}]}
            """);

        var channels = TimelineMixerProjection.ToMixerChannels(project);
        MixerGraphPlan plan = MixerGraphBuilder.Build(channels);
        MixerChannel audio = channels.Single(channel => channel.Kind == MixerChannelKind.Track);

        Assert.AreEqual("Dialog", audio.Name);
        Assert.AreEqual(0.8f, audio.Gain);
        Assert.AreEqual(0.25f, audio.Pan);
        Assert.IsTrue(audio.Muted);
        Assert.IsTrue(audio.Solo);
        Assert.IsTrue(audio.RecordArmed);
        Assert.IsTrue(audio.InputMonitoring);
        Assert.AreEqual("master", audio.OutputId);
        Assert.HasCount(2, plan.ProcessingOrder);
    }

    private static CanonicalProject Project(string timeline)
    {
        string json = "{\"id\":\"project\",\"name\":\"Project\",\"meta\":{\"timeline\":" + timeline + "}}";
        return JsonSerializer.Deserialize<ProjectDto>(json, StudioJson.Options)!.CanonicalProject;
    }
}
