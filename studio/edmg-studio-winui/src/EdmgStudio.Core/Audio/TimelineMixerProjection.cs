using System.Collections.Immutable;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public sealed record TimelineTrackMixerState(
    string TrackId,
    string Name,
    float Gain,
    float Pan,
    bool Muted,
    bool Solo,
    bool RecordArmed,
    bool InputMonitoring,
    string OutputId);

public static class TimelineMixerProjection
{
    public const string MasterOutputId = "master";

    public static ImmutableArray<TimelineTrackMixerState> Project(CanonicalProject project)
    {
        ArgumentNullException.ThrowIfNull(project);
        return project.Tracks
            .OrderBy(track => track.Order)
            .Select(Project)
            .ToImmutableArray();
    }

    public static TimelineTrackMixerState Project(Track track)
    {
        ArgumentNullException.ThrowIfNull(track);
        return new TimelineTrackMixerState(
            track.Id,
            track.Name,
            ReadGain(track.Metadata["gain"]),
            ReadPan(track.Metadata["pan"]),
            track.Muted,
            track.Solo,
            track.RecordArmed,
            track.InputMonitoring,
            ReadOutput(track.Metadata["routing"]?["bus"]));
    }

    public static JsonObject UpdateTrack(
        JsonObject timeline,
        string trackId,
        TimelineTrackMixerState state)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentException.ThrowIfNullOrWhiteSpace(trackId);
        ArgumentNullException.ThrowIfNull(state);
        if (!string.Equals(trackId, state.TrackId, StringComparison.Ordinal))
        {
            throw new ArgumentException("The mixer state must identify the track being updated.", nameof(state));
        }
        if (!float.IsFinite(state.Gain) || state.Gain < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(state), "Track gain must be finite and nonnegative.");
        }
        if (!float.IsFinite(state.Pan) || state.Pan is < -1 or > 1)
        {
            throw new ArgumentOutOfRangeException(nameof(state), "Track pan must be between -1 and 1.");
        }
        if (string.IsNullOrWhiteSpace(state.OutputId))
        {
            throw new ArgumentException("A mixer output route is required.", nameof(state));
        }
        JsonObject? persistedMixer = timeline[MixerDocumentCodec.PropertyName] as JsonObject;
        if (persistedMixer is null &&
            !string.Equals(state.OutputId, MasterOutputId, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("Legacy mixer state can route only to the master channel.", nameof(state));
        }
        if (persistedMixer?["channels"] is JsonArray persistedChannels &&
            !persistedChannels.OfType<JsonObject>().Any(candidate =>
                string.Equals(ReadString(candidate["id"]), state.OutputId, StringComparison.Ordinal) &&
                !string.Equals(ReadString(candidate["kind"]), MixerChannelKind.Track.ToString(), StringComparison.OrdinalIgnoreCase)))
        {
            throw new ArgumentException($"Mixer output '{state.OutputId}' is not a bus or master channel.", nameof(state));
        }

        var updated = timeline.DeepClone().AsObject();
        if (updated["tracks"] is not JsonArray tracks)
        {
            throw new InvalidDataException("The timeline does not contain a track collection.");
        }

        JsonObject? track = tracks
            .OfType<JsonObject>()
            .SingleOrDefault(candidate => string.Equals(ReadString(candidate["id"]), trackId, StringComparison.Ordinal));
        if (track is null)
        {
            throw new KeyNotFoundException($"Timeline track '{trackId}' was not found.");
        }

        track["gain"] = state.Gain;
        track["pan"] = state.Pan;
        track["muted"] = state.Muted;
        track["solo"] = state.Solo;
        track["record_armed"] = state.RecordArmed;
        track["input_monitoring"] = state.InputMonitoring;
        JsonObject routing = track["routing"] as JsonObject ?? [];
        routing["bus"] = state.OutputId;
        track["routing"] = routing;
        if (updated[MixerDocumentCodec.PropertyName] is JsonObject mixer && mixer["channels"] is JsonArray channels)
        {
            JsonObject? channel = channels.OfType<JsonObject>().SingleOrDefault(candidate =>
                string.Equals(ReadString(candidate["id"]), trackId, StringComparison.Ordinal));
            if (channel is not null)
            {
                channel["gain"] = state.Gain;
                channel["pan"] = state.Pan;
                channel["muted"] = state.Muted;
                channel["solo"] = state.Solo;
                channel["record_armed"] = state.RecordArmed;
                channel["input_monitoring"] = state.InputMonitoring;
                channel["output_id"] = state.OutputId;
            }
        }
        return updated;
    }

    public static ImmutableArray<MixerChannel> ToMixerChannels(CanonicalProject project)
    {
        string masterId = MasterOutputId;
        while (project.Tracks.Any(track => track.Id == masterId))
        {
            masterId = "_" + masterId;
        }

        ImmutableArray<MixerChannel>.Builder channels = ImmutableArray.CreateBuilder<MixerChannel>();
        foreach (Track track in project.Tracks.Where(IsAudioTrack).OrderBy(track => track.Order))
        {
            TimelineTrackMixerState state = Project(track);
            channels.Add(new MixerChannel(
                state.TrackId,
                state.Name,
                MixerChannelKind.Track,
                string.Equals(state.OutputId, MasterOutputId, StringComparison.OrdinalIgnoreCase)
                    ? masterId
                    : state.OutputId,
                [],
                [],
                state.Gain,
                state.Pan,
                state.Muted,
                state.Solo,
                state.RecordArmed,
                state.InputMonitoring));
        }
        channels.Add(new MixerChannel(masterId, "Master", MixerChannelKind.Master, null, [], []));
        return channels.ToImmutable();
    }

    private static bool IsAudioTrack(Track track) =>
        string.Equals(track.Type, "audio", StringComparison.OrdinalIgnoreCase) ||
        track.Events.Any(item => string.Equals(item.Type, "audio", StringComparison.OrdinalIgnoreCase));

    private static float ReadGain(JsonNode? node) =>
        TryReadSingle(node, out float value) && value >= 0 ? value : 1;

    private static float ReadPan(JsonNode? node) =>
        TryReadSingle(node, out float value) ? Math.Clamp(value, -1, 1) : 0;

    private static string ReadOutput(JsonNode? node) =>
        ReadString(node) ?? MasterOutputId;

    private static bool TryReadSingle(JsonNode? node, out float value)
    {
        value = 0;
        return node is JsonValue jsonValue &&
               jsonValue.TryGetValue(out value) &&
               float.IsFinite(value);
    }

    private static string? ReadString(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue(out string? result) && !string.IsNullOrWhiteSpace(result)
            ? result.Trim()
            : null;
}
