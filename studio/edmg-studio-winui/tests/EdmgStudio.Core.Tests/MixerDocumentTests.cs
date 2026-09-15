using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class MixerDocumentTests
{
    [TestMethod]
    public void LegacyTimelineMigratesToTrackAndMasterDefaults()
    {
        JsonObject timeline = JsonNode.Parse("""{"tracks":[{"id":"audio","name":"Audio","type":"audio","clips":[]}]}""")!.AsObject();
        MixerDocument document = MixerDocumentCodec.ReadOrMigrate(timeline, Project(timeline));
        Assert.AreEqual(1, document.SchemaVersion);
        Assert.AreEqual(MixerChannelKind.Track, document.Channels[0].Kind);
        Assert.AreEqual("master", document.Channels[0].OutputId);
        Assert.AreEqual(MixerChannelKind.Master, document.Channels[1].Kind);
        Assert.IsNull(timeline["mixer"]);
    }

    [TestMethod]
    public void LegacyTimelineAvoidsMasterTrackIdentityCollision()
    {
        JsonObject timeline = JsonNode.Parse("""{"tracks":[{"id":"master","name":"Recorded master","type":"audio","routing":{"bus":"legacy"},"clips":[]}]}""")!.AsObject();

        MixerDocument document = MixerDocumentCodec.ReadOrMigrate(timeline, Project(timeline));

        Assert.AreEqual("_master", document.Channels.Single(channel => channel.Kind == MixerChannelKind.Track).OutputId);
        Assert.AreEqual("_master", document.Channels.Single(channel => channel.Kind == MixerChannelKind.Master).Id);
    }

    [TestMethod]
    public void PersistedMixerAddsNewAudioTracksWithoutDiscardingExistingState()
    {
        JsonObject timeline = JsonNode.Parse("""
            {"tracks":[{"id":"existing","name":"Existing","type":"audio","clips":[]},{"id":"added","name":"Added","type":"audio","gain":0.6,"clips":[]}],
             "mixer":{"schema_version":1,"channels":[
               {"id":"existing","name":"Existing","kind":"Track","output_id":"master","gain":0.25,"vendor_state":true},
               {"id":"master","name":"Master","kind":"Master"}]}}
            """)!.AsObject();

        MixerDocument document = MixerDocumentCodec.ReadOrMigrate(timeline, Project(timeline));

        Assert.AreEqual(0.25f, document.Channels.Single(channel => channel.Id == "existing").Gain);
        Assert.IsTrue(document.Channels.Single(channel => channel.Id == "existing").Extensions["vendor_state"]!.GetValue<bool>());
        MixerChannelDocument added = document.Channels.Single(channel => channel.Id == "added");
        Assert.AreEqual(0.6f, added.Gain);
        Assert.AreEqual("master", added.OutputId);
    }

    [TestMethod]
    public void RoundTripPreservesUnknownExtensionsAndPluginState()
    {
        JsonObject timeline = JsonNode.Parse("""
            {"tracks":[],"mixer":{"schema_version":1,"vendor_root":{"x":1},"channels":[
              {"id":"track","name":"Track","kind":"Track","output_id":"group","gain":0.8,"pan":-0.2,"vendor_channel":7,
               "inserts":[{"id":"i1","plugin_id":"vendor.plugin","enabled":true,"bypassed":false,"latency_samples":64,"preset_name":"Wide","state_base64":"AQI=","vendor_insert":true}],
               "sends":[{"id":"s1","destination_id":"fx","tap":"PreFader","gain":0.25,"enabled":true,"vendor_send":"keep"}]},
              {"id":"group","name":"Group","kind":"Group","output_id":"master"},
              {"id":"fx","name":"FX","kind":"FxReturn","output_id":"master"},
              {"id":"master","name":"Master","kind":"Master"}]}}
            """)!.AsObject();
        MixerDocument document = MixerDocumentCodec.ReadOrMigrate(timeline, Project(timeline));
        JsonObject written = MixerDocumentCodec.Write(timeline, document);
        Assert.AreEqual(1, written["mixer"]!["vendor_root"]!["x"]!.GetValue<int>());
        Assert.AreEqual(7, written["mixer"]!["channels"]![0]!["vendor_channel"]!.GetValue<int>());
        Assert.IsTrue(written["mixer"]!["channels"]![0]!["inserts"]![0]!["vendor_insert"]!.GetValue<bool>());
        Assert.AreEqual("keep", written["mixer"]!["channels"]![0]!["sends"]![0]!["vendor_send"]!.GetValue<string>());
        MixerChannel track = MixerDocumentCodec.ToMixerChannels(document).Single(channel => channel.Id == "track");
        Assert.AreEqual("AQI=", track.Inserts[0].StateBase64);
        Assert.AreEqual(MixerTap.PreFader, track.Sends[0].Tap);
    }

    [TestMethod]
    public void UnsupportedVersionAndInvalidGraphAreRejected()
    {
        JsonObject unsupported = JsonNode.Parse("""{"tracks":[],"mixer":{"schema_version":99,"channels":[]}}""")!.AsObject();
        Assert.ThrowsExactly<InvalidDataException>(() => MixerDocumentCodec.ReadOrMigrate(unsupported, Project(unsupported)));
        JsonObject invalid = JsonNode.Parse("""{"tracks":[],"mixer":{"schema_version":1,"channels":[{"id":"master","kind":"Master"},{"id":"bus","kind":"Group","output_id":"missing"}]}}""")!.AsObject();
        Assert.ThrowsExactly<InvalidDataException>(() => MixerDocumentCodec.ReadOrMigrate(invalid, Project(invalid)));
    }

    private static CanonicalProject Project(JsonObject timeline)
    {
        var root = new JsonObject { ["id"] = "project", ["name"] = "Project", ["meta"] = new JsonObject { ["timeline"] = timeline.DeepClone() } };
        return JsonSerializer.Deserialize<ProjectDto>(root.ToJsonString(), StudioJson.Options)!.CanonicalProject;
    }
}
