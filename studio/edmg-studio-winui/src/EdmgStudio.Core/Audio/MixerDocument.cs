using System.Collections.Immutable;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public sealed record MixerPluginInstanceDocument(
    string Id, string PluginId, bool Enabled, bool Bypassed, int ReportedLatencySamples,
    string? PresetName, string? StateBase64, JsonObject Extensions,
    string? ModulePath = null, string? ModuleSha256 = null);
public sealed record MixerSendDocument(
    string Id, string DestinationId, MixerTap Tap, float Gain, bool Enabled, JsonObject Extensions);
public sealed record MixerChannelDocument(
    string Id, string Name, MixerChannelKind Kind, string Color, bool Visible, string? OutputId,
    float Gain, float Pan, bool Muted, bool Solo, bool RecordArmed, bool InputMonitoring,
    ImmutableArray<MixerPluginInstanceDocument> Inserts,
    ImmutableArray<MixerSendDocument> Sends,
    JsonObject Extensions);
public sealed record MixerDocument(int SchemaVersion, ImmutableArray<MixerChannelDocument> Channels, JsonObject Extensions)
{
    public const int CurrentSchemaVersion = 1;
}

public static class MixerDocumentCodec
{
    public const string PropertyName = "mixer";

    public static MixerDocument ReadOrMigrate(JsonObject timeline, CanonicalProject project)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentNullException.ThrowIfNull(project);
        if (timeline[PropertyName] is not JsonObject mixer) return CreateDefault(project);
        int version = ReadInt(mixer["schema_version"], 0);
        if (version != MixerDocument.CurrentSchemaVersion)
            throw new InvalidDataException($"Unsupported mixer schema version '{version}'.");
        if (mixer["channels"] is not JsonArray array) throw new InvalidDataException("Mixer channels are missing.");
        ImmutableArray<MixerChannelDocument> channels = ReconcileTracks(array.Select(ReadChannel).ToImmutableArray(), project);
        Validate(channels);
        return new(version, channels, CopyUnknown(mixer, "schema_version", "channels"));
    }

    public static MixerDocument CreateDefault(CanonicalProject project)
    {
        string masterId = TimelineMixerProjection.MasterOutputId;
        while (project.Tracks.Any(track => string.Equals(track.Id, masterId, StringComparison.Ordinal)))
            masterId = "_" + masterId;

        var channels = project.Tracks.Where(IsAudioTrack).OrderBy(track => track.Order).Select(track =>
        {
            TimelineTrackMixerState state = TimelineMixerProjection.Project(track);
            return new MixerChannelDocument(track.Id, track.Name, MixerChannelKind.Track, "#607D8B", true,
                masterId, state.Gain, state.Pan, state.Muted, state.Solo, state.RecordArmed,
                state.InputMonitoring, [], [], []);
        }).Append(new MixerChannelDocument(masterId, "Master", MixerChannelKind.Master, "#D4A72C", true,
            null, 1, 0, false, false, false, false, [], [], [])).ToImmutableArray();
        return new(MixerDocument.CurrentSchemaVersion, channels, []);
    }

    public static JsonObject Write(JsonObject timeline, MixerDocument document)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentNullException.ThrowIfNull(document);
        if (document.SchemaVersion != MixerDocument.CurrentSchemaVersion) throw new InvalidDataException("Unsupported mixer schema version.");
        Validate(document.Channels);
        var mixer = document.Extensions.DeepClone().AsObject();
        mixer["schema_version"] = document.SchemaVersion;
        var channels = new JsonArray();
        foreach (MixerChannelDocument channel in document.Channels) channels.Add(WriteChannel(channel));
        mixer["channels"] = channels;
        var updated = timeline.DeepClone().AsObject();
        updated[PropertyName] = mixer;
        return updated;
    }

    public static ImmutableArray<MixerChannel> ToMixerChannels(MixerDocument document) => document.Channels.Select(channel =>
        new MixerChannel(channel.Id, channel.Name, channel.Kind, channel.OutputId,
            channel.Inserts.Select(insert => new MixerInsert(insert.Id, insert.ReportedLatencySamples, insert.Enabled, insert.Bypassed,
                insert.PluginId, insert.PresetName, insert.StateBase64, insert.ModulePath, insert.ModuleSha256)).ToImmutableArray(),
            channel.Sends.Where(send => send.Enabled).Select(send => new MixerSend(send.Id, send.DestinationId, send.Tap, send.Gain)).ToImmutableArray(),
            channel.Gain, channel.Pan, channel.Muted, channel.Solo, channel.RecordArmed, channel.InputMonitoring,
            channel.Color, channel.Visible)).ToImmutableArray();

    private static ImmutableArray<MixerChannelDocument> ReconcileTracks(
        ImmutableArray<MixerChannelDocument> channels,
        CanonicalProject project)
    {
        string masterId = channels.SingleOrDefault(channel => channel.Kind == MixerChannelKind.Master)?.Id
            ?? throw new InvalidDataException("The mixer document requires exactly one master channel.");
        var existingIds = channels.Select(channel => channel.Id).ToHashSet(StringComparer.Ordinal);
        ImmutableArray<MixerChannelDocument>.Builder additions = ImmutableArray.CreateBuilder<MixerChannelDocument>();
        foreach (Track track in project.Tracks.Where(IsAudioTrack).OrderBy(track => track.Order))
        {
            if (existingIds.Contains(track.Id)) continue;
            TimelineTrackMixerState state = TimelineMixerProjection.Project(track);
            additions.Add(new MixerChannelDocument(track.Id, track.Name, MixerChannelKind.Track, "#607D8B", true,
                masterId, state.Gain, state.Pan, state.Muted, state.Solo, state.RecordArmed,
                state.InputMonitoring, [], [], []));
        }
        if (additions.Count == 0) return channels;
        int firstBus = -1;
        for (int index = 0; index < channels.Length; index++)
        {
            if (channels[index].Kind == MixerChannelKind.Track) continue;
            firstBus = index;
            break;
        }
        return firstBus < 0
            ? channels.AddRange(additions)
            : channels.InsertRange(firstBus, additions);
    }

    private static MixerChannelDocument ReadChannel(JsonNode? node)
    {
        JsonObject value = node as JsonObject ?? throw new InvalidDataException("A mixer channel is malformed.");
        string id = ReadRequired(value, "id");
        MixerChannelKind kind = Enum.TryParse(ReadRequired(value, "kind"), true, out MixerChannelKind parsed) && Enum.IsDefined(parsed)
            ? parsed : throw new InvalidDataException($"Mixer channel '{id}' has an invalid kind.");
        var inserts = (value["inserts"] as JsonArray ?? []).Select(ReadInsert).ToImmutableArray();
        var sends = (value["sends"] as JsonArray ?? []).Select(ReadSend).ToImmutableArray();
        return new(id, ReadString(value["name"]) ?? id, kind, ReadString(value["color"]) ?? "#607D8B",
            ReadBool(value["visible"], true), ReadString(value["output_id"]), ReadFloat(value["gain"], 1),
            ReadFloat(value["pan"], 0), ReadBool(value["muted"]), ReadBool(value["solo"]),
            ReadBool(value["record_armed"]), ReadBool(value["input_monitoring"]), inserts, sends,
            CopyUnknown(value, "id", "name", "kind", "color", "visible", "output_id", "gain", "pan", "muted", "solo", "record_armed", "input_monitoring", "inserts", "sends"));
    }

    private static MixerPluginInstanceDocument ReadInsert(JsonNode? node)
    {
        JsonObject value = node as JsonObject ?? throw new InvalidDataException("A mixer insert is malformed.");
        return new(ReadRequired(value, "id"), ReadRequired(value, "plugin_id"), ReadBool(value["enabled"], true),
            ReadBool(value["bypassed"]), ReadInt(value["latency_samples"], 0), ReadString(value["preset_name"]),
            ReadString(value["state_base64"]), CopyUnknown(value, "id", "plugin_id", "enabled", "bypassed", "latency_samples", "preset_name", "state_base64", "module_path", "module_sha256"),
            ReadString(value["module_path"]), ReadString(value["module_sha256"]));
    }

    private static MixerSendDocument ReadSend(JsonNode? node)
    {
        JsonObject value = node as JsonObject ?? throw new InvalidDataException("A mixer send is malformed.");
        if (!Enum.TryParse(ReadRequired(value, "tap"), true, out MixerTap tap) || !Enum.IsDefined(tap))
            throw new InvalidDataException("A mixer send has an invalid tap.");
        return new(ReadRequired(value, "id"), ReadRequired(value, "destination_id"), tap,
            ReadFloat(value["gain"], 1), ReadBool(value["enabled"], true),
            CopyUnknown(value, "id", "destination_id", "tap", "gain", "enabled"));
    }

    private static JsonObject WriteChannel(MixerChannelDocument channel)
    {
        JsonObject value = channel.Extensions.DeepClone().AsObject();
        value["id"] = channel.Id; value["name"] = channel.Name; value["kind"] = channel.Kind.ToString();
        value["color"] = channel.Color; value["visible"] = channel.Visible; value["output_id"] = channel.OutputId;
        value["gain"] = channel.Gain; value["pan"] = channel.Pan; value["muted"] = channel.Muted; value["solo"] = channel.Solo;
        value["record_armed"] = channel.RecordArmed; value["input_monitoring"] = channel.InputMonitoring;
        var inserts = new JsonArray();
        foreach (MixerPluginInstanceDocument insert in channel.Inserts)
        {
            JsonObject item = insert.Extensions.DeepClone().AsObject();
            item["id"] = insert.Id; item["plugin_id"] = insert.PluginId; item["enabled"] = insert.Enabled; item["bypassed"] = insert.Bypassed;
            item["latency_samples"] = insert.ReportedLatencySamples; item["preset_name"] = insert.PresetName; item["state_base64"] = insert.StateBase64;
            item["module_path"] = insert.ModulePath; item["module_sha256"] = insert.ModuleSha256;
            inserts.Add(item);
        }
        var sends = new JsonArray();
        foreach (MixerSendDocument send in channel.Sends)
        {
            JsonObject item = send.Extensions.DeepClone().AsObject();
            item["id"] = send.Id; item["destination_id"] = send.DestinationId; item["tap"] = send.Tap.ToString(); item["gain"] = send.Gain; item["enabled"] = send.Enabled;
            sends.Add(item);
        }
        value["inserts"] = inserts; value["sends"] = sends;
        return value;
    }

    private static void Validate(ImmutableArray<MixerChannelDocument> channels)
    {
        if (channels.IsDefault) throw new InvalidDataException("Mixer channels are uninitialized.");
        try { _ = MixerGraphBuilder.Build(ToMixerChannels(new(MixerDocument.CurrentSchemaVersion, channels, []))); }
        catch (ArgumentException exception) { throw new InvalidDataException("The mixer document contains an invalid graph.", exception); }
    }

    private static JsonObject CopyUnknown(JsonObject source, params string[] known)
    {
        var result = new JsonObject();
        var names = known.ToHashSet(StringComparer.Ordinal);
        foreach ((string key, JsonNode? value) in source) if (!names.Contains(key)) result[key] = value?.DeepClone();
        return result;
    }
    private static string ReadRequired(JsonObject value, string name) => ReadString(value[name]) ?? throw new InvalidDataException($"Mixer field '{name}' is required.");
    private static string? ReadString(JsonNode? node) => node is JsonValue value && value.TryGetValue(out string? text) && !string.IsNullOrWhiteSpace(text) ? text.Trim() : null;
    private static bool ReadBool(JsonNode? node, bool fallback = false) => node is JsonValue value && value.TryGetValue(out bool result) ? result : fallback;
    private static int ReadInt(JsonNode? node, int fallback) => node is JsonValue value && value.TryGetValue(out int result) ? result : fallback;
    private static float ReadFloat(JsonNode? node, float fallback) => node is JsonValue value && value.TryGetValue(out float result) && float.IsFinite(result) ? result : fallback;
    private static bool IsAudioTrack(Track track) => string.Equals(track.Type, "audio", StringComparison.OrdinalIgnoreCase) || track.Events.Any(item => string.Equals(item.Type, "audio", StringComparison.OrdinalIgnoreCase));
}
