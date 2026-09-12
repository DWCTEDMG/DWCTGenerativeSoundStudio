using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public sealed record ProjectTimelineMutation(CanonicalProject Project, JsonObject Operation);

public enum TimelineSnapMode
{
    Off,
    Sample,
    Frame,
    Beat,
    HalfBeat,
    QuarterBeat,
}

public static class ProjectTimelineOperations
{
    private static readonly HashSet<string> SupportedTrackTypes = new(StringComparer.Ordinal)
    {
        "audio", "video", "midi", "instrument", "folder", "group", "fx", "marker", "tempo",
        "signature", "automation", "ai_visual", "prompt", "scene", "reference", "master"
    };

    public static ProjectTimelineMutation AddTrack(CanonicalProject project, string id, string type, string? name = null)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentException.ThrowIfNullOrWhiteSpace(id);
        ArgumentException.ThrowIfNullOrWhiteSpace(type);
        if (!SupportedTrackTypes.Contains(type))
        {
            throw new ArgumentOutOfRangeException(nameof(type), "Unsupported track type.");
        }

        EnsureIdAvailable(project, id);

        string trackName = string.IsNullOrWhiteSpace(name)
            ? char.ToUpperInvariant(type[0]) + type[1..]
            : name.Trim();
        var trackMetadata = new JsonObject
        {
            ["id"] = id,
            ["type"] = type,
            ["name"] = trackName,
            ["clips"] = new JsonArray()
        };
        var track = new Track(
            id,
            trackName,
            type,
            project.Tracks.Count,
            false,
            false,
            false,
            false,
            false,
            [],
            trackMetadata);
        CanonicalProject updated = WithTracks(project, [.. project.Tracks, track]);
        return new ProjectTimelineMutation(updated, new JsonObject
        {
            ["kind"] = "add_track",
            ["track_type"] = type,
            ["new_id"] = id,
            ["name"] = trackName
        });
    }

    public static ProjectTimelineMutation ReorderTrack(CanonicalProject project, string trackId, int destinationIndex)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentException.ThrowIfNullOrWhiteSpace(trackId);
        if (destinationIndex < 0 || destinationIndex >= project.Tracks.Count)
        {
            throw new ArgumentOutOfRangeException(nameof(destinationIndex));
        }

        var tracks = project.Tracks.ToList();
        int sourceIndex = tracks.FindIndex(track => string.Equals(track.Id, trackId, StringComparison.Ordinal));
        if (sourceIndex < 0)
        {
            throw new InvalidOperationException($"Track '{trackId}' was not found.");
        }

        if (tracks[sourceIndex].Locked)
        {
            throw new InvalidOperationException($"Unlock track '{trackId}' before reordering it.");
        }

        Track moved = tracks[sourceIndex];
        tracks.RemoveAt(sourceIndex);
        tracks.Insert(destinationIndex, moved);
        return new ProjectTimelineMutation(WithTracks(project, tracks), new JsonObject
        {
            ["kind"] = "reorder_track",
            ["track_id"] = trackId,
            ["index"] = destinationIndex
        });
    }

    public static ProjectTimelineMutation SetTrackState(
        CanonicalProject project,
        string trackId,
        bool? locked = null,
        bool? muted = null,
        bool? solo = null,
        bool? recordArmed = null,
        bool? inputMonitoring = null)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentException.ThrowIfNullOrWhiteSpace(trackId);
        if (locked is null && muted is null && solo is null && recordArmed is null && inputMonitoring is null)
        {
            throw new ArgumentException("At least one track state value is required.", nameof(trackId));
        }

        var tracks = project.Tracks.ToList();
        int index = tracks.FindIndex(track => string.Equals(track.Id, trackId, StringComparison.Ordinal));
        if (index < 0)
        {
            throw new InvalidOperationException($"Track '{trackId}' was not found.");
        }

        Track current = tracks[index];
        bool unlockOnly = locked is false && muted is null && solo is null && recordArmed is null && inputMonitoring is null;
        if (current.Locked && !unlockOnly)
        {
            throw new InvalidOperationException($"Unlock track '{trackId}' before changing its state.");
        }

        JsonObject metadata = current.Metadata.DeepClone().AsObject();
        SetOptional(metadata, "locked", locked);
        SetOptional(metadata, "muted", muted);
        SetOptional(metadata, "solo", solo);
        SetOptional(metadata, "record_armed", recordArmed);
        SetOptional(metadata, "input_monitoring", inputMonitoring);
        tracks[index] = current with
        {
            Locked = locked ?? current.Locked,
            Muted = muted ?? current.Muted,
            Solo = solo ?? current.Solo,
            RecordArmed = recordArmed ?? current.RecordArmed,
            InputMonitoring = inputMonitoring ?? current.InputMonitoring,
            Metadata = metadata
        };

        var operation = new JsonObject { ["kind"] = "set_track_state", ["track_id"] = trackId };
        SetOptional(operation, "locked", locked);
        SetOptional(operation, "muted", muted);
        SetOptional(operation, "solo", solo);
        SetOptional(operation, "record_armed", recordArmed);
        SetOptional(operation, "input_monitoring", inputMonitoring);
        return new ProjectTimelineMutation(WithTracks(project, tracks), operation);
    }

    public static ProjectTimelineMutation MoveEvent(
        CanonicalProject project,
        string trackId,
        string eventId,
        TimelinePosition position)
    {
        var (tracks, trackIndex, eventIndex, track, item) = FindEditableEvent(project, trackId, eventId);
        if (position.Samples < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(position));
        }

        TimelineEvent moved = item with
        {
            Start = position,
            End = new TimelinePosition(checked(position.Samples + item.Duration.Samples)),
        };
        tracks[trackIndex] = track with { Events = ReplaceEvent(track.Events, eventIndex, moved) };
        return Mutation(project, tracks, Operation("move", trackId, eventId, position));
    }

    public static ProjectTimelineMutation TrimEvent(
        CanonicalProject project,
        string trackId,
        string eventId,
        string edge,
        TimelinePosition position)
    {
        var (tracks, trackIndex, eventIndex, track, item) = FindEditableEvent(project, trackId, eventId);
        TimelineEvent trimmed;
        if (edge == "start" && position.Samples >= item.Start.Samples && position.Samples < item.End.Samples)
        {
            trimmed = item with
            {
                Start = position,
                Source = AdvanceSource(item, checked(position.Samples - item.Start.Samples), project.Timebase),
            };
        }
        else if (edge == "end" && position.Samples > item.Start.Samples && position.Samples <= item.End.Samples)
        {
            trimmed = item with
            {
                End = position,
                Source = SetSourceEnd(item, checked(position.Samples - item.Start.Samples), project.Timebase),
            };
        }
        else
        {
            throw new ArgumentOutOfRangeException(nameof(position), "Trim must shorten the selected edge within the event.");
        }

        tracks[trackIndex] = track with { Events = ReplaceEvent(track.Events, eventIndex, trimmed) };
        JsonObject operation = Operation("trim", trackId, eventId, position);
        operation["edge"] = edge;
        return Mutation(project, tracks, operation);
    }

    public static ProjectTimelineMutation SplitEvent(
        CanonicalProject project,
        string trackId,
        string eventId,
        TimelinePosition position,
        string newId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(newId);
        EnsureIdAvailable(project, newId);
        var (tracks, trackIndex, eventIndex, track, item) = FindEditableEvent(project, trackId, eventId);
        if (position.Samples <= item.Start.Samples || position.Samples >= item.End.Samples)
        {
            throw new ArgumentOutOfRangeException(nameof(position), "Split must be inside the event.");
        }

        long offset = checked(position.Samples - item.Start.Samples);
        TimelineEvent left = item with { End = position, Source = SetSourceEnd(item, offset, project.Timebase) };
        TimelineEvent right = item with
        {
            Id = newId,
            Start = position,
            Source = AdvanceSource(item, offset, project.Timebase),
            Data = item.Data.DeepClone().AsObject(),
        };
        var events = track.Events.ToList();
        events[eventIndex] = left;
        events.Insert(eventIndex + 1, right);
        tracks[trackIndex] = track with { Events = events };
        JsonObject operation = Operation("split", trackId, eventId, position);
        operation["new_id"] = newId;
        return Mutation(project, tracks, operation);
    }

    public static ProjectTimelineMutation DuplicateEvent(
        CanonicalProject project,
        string trackId,
        string eventId,
        string newId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(newId);
        EnsureIdAvailable(project, newId);
        var (tracks, trackIndex, _, track, item) = FindEditableEvent(project, trackId, eventId);
        TimelinePosition start = item.End;
        TimelineEvent duplicate = item with
        {
            Id = newId,
            Start = start,
            End = new TimelinePosition(checked(start.Samples + item.Duration.Samples)),
            Data = item.Data.DeepClone().AsObject(),
        };
        tracks[trackIndex] = track with { Events = [.. track.Events, duplicate] };
        JsonObject operation = Operation("duplicate", trackId, eventId);
        operation["new_id"] = newId;
        return Mutation(project, tracks, operation);
    }

    public static ProjectTimelineMutation DeleteEvent(CanonicalProject project, string trackId, string eventId)
    {
        var (tracks, trackIndex, eventIndex, track, _) = FindEditableEvent(project, trackId, eventId);
        var events = track.Events.ToList();
        events.RemoveAt(eventIndex);
        tracks[trackIndex] = track with { Events = events };
        return Mutation(project, tracks, Operation("delete", trackId, eventId));
    }

    public static ProjectTimelineMutation AddMarker(
        CanonicalProject project,
        string id,
        string name,
        TimelinePosition position,
        string? color = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(id);
        EnsureIdAvailable(project, id);
        ValidatePosition(position);
        string markerName = string.IsNullOrWhiteSpace(name) ? "Marker" : name.Trim();
        var marker = new TimelineMarker(id, markerName, position, color, new JsonObject());
        var markers = project.Markers.Append(marker).OrderBy(item => item.Position.Samples).ToArray();
        var operation = new JsonObject
        {
            ["kind"] = "add_marker",
            ["new_id"] = id,
            ["name"] = markerName,
            ["position"] = SampleText(position),
        };
        if (!string.IsNullOrWhiteSpace(color)) operation["color"] = color;
        return new ProjectTimelineMutation(project with { Markers = markers }, operation);
    }

    public static ProjectTimelineMutation MoveMarker(CanonicalProject project, string markerId, TimelinePosition position)
    {
        ArgumentNullException.ThrowIfNull(project);
        ValidatePosition(position);
        var markers = project.Markers.ToList();
        int index = markers.FindIndex(marker => marker.Id == markerId);
        if (index < 0) throw new InvalidOperationException($"Marker '{markerId}' was not found.");
        markers[index] = markers[index] with { Position = position };
        return new ProjectTimelineMutation(
            project with { Markers = markers.OrderBy(item => item.Position.Samples).ToArray() },
            new JsonObject { ["kind"] = "move_marker", ["marker_id"] = markerId, ["position"] = SampleText(position) });
    }

    public static ProjectTimelineMutation DeleteMarker(CanonicalProject project, string markerId)
    {
        ArgumentNullException.ThrowIfNull(project);
        TimelineMarker marker = project.Markers.FirstOrDefault(item => item.Id == markerId)
            ?? throw new InvalidOperationException($"Marker '{markerId}' was not found.");
        return new ProjectTimelineMutation(
            project with { Markers = project.Markers.Where(item => item != marker).ToArray() },
            new JsonObject { ["kind"] = "delete_marker", ["marker_id"] = markerId });
    }

    public static TimelinePosition Snap(
        ProjectTimebase timebase,
        TimelinePosition position,
        TimelineSnapMode mode,
        decimal beatsPerMinute = 120)
    {
        ArgumentNullException.ThrowIfNull(timebase);
        ValidatePosition(position);
        return mode switch
        {
            TimelineSnapMode.Off or TimelineSnapMode.Sample => position,
            TimelineSnapMode.Frame => timebase.FromFrame(timebase.ToFrame(position)),
            TimelineSnapMode.Beat => SnapBeat(timebase, position, beatsPerMinute, 1),
            TimelineSnapMode.HalfBeat => SnapBeat(timebase, position, beatsPerMinute, 2),
            TimelineSnapMode.QuarterBeat => SnapBeat(timebase, position, beatsPerMinute, 4),
            _ => throw new ArgumentOutOfRangeException(nameof(mode)),
        };
    }

    private static CanonicalProject WithTracks(CanonicalProject project, IReadOnlyList<Track> tracks)
    {
        Track[] ordered = tracks.Select((track, index) => track with { Order = index }).ToArray();
        return project with { Tracks = ordered };
    }

    private static ProjectTimelineMutation Mutation(CanonicalProject project, IReadOnlyList<Track> tracks, JsonObject operation) =>
        new(WithTracks(project, tracks), operation);

    private static JsonObject Operation(string kind, string trackId, string eventId, TimelinePosition? position = null)
    {
        var operation = new JsonObject { ["kind"] = kind, ["track_id"] = trackId, ["clip_id"] = eventId };
        if (position.HasValue) operation["position"] = SampleText(position.Value);
        return operation;
    }

    private static (List<Track> Tracks, int TrackIndex, int EventIndex, Track Track, TimelineEvent Event) FindEditableEvent(
        CanonicalProject project,
        string trackId,
        string eventId)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentException.ThrowIfNullOrWhiteSpace(trackId);
        ArgumentException.ThrowIfNullOrWhiteSpace(eventId);
        var tracks = project.Tracks.ToList();
        int trackIndex = tracks.FindIndex(track => track.Id == trackId);
        if (trackIndex < 0) throw new InvalidOperationException($"Track '{trackId}' was not found.");
        Track track = tracks[trackIndex];
        if (track.Locked) throw new InvalidOperationException($"Unlock track '{trackId}' before editing it.");
        int eventIndex = track.Events.ToList().FindIndex(item => item.Id == eventId);
        if (eventIndex < 0) throw new InvalidOperationException($"Timeline event '{eventId}' was not found.");
        TimelineEvent item = track.Events[eventIndex];
        if (ReadBoolean(item.Data["locked"])) throw new InvalidOperationException($"Unlock event '{eventId}' before editing it.");
        return (tracks, trackIndex, eventIndex, track, item);
    }

    private static IReadOnlyList<TimelineEvent> ReplaceEvent(IReadOnlyList<TimelineEvent> source, int index, TimelineEvent item)
    {
        var events = source.ToList();
        events[index] = item;
        return events;
    }

    private static SourceRange? AdvanceSource(TimelineEvent item, long projectSampleDelta, ProjectTimebase timebase)
    {
        if (item.Source is null) return null;
        SourcePosition start = AddSourceDelta(item.Source.Start, projectSampleDelta, item, timebase);
        return new SourceRange(start, item.Source.End);
    }

    private static SourceRange? SetSourceEnd(TimelineEvent item, long projectSampleDelta, ProjectTimebase timebase)
    {
        if (item.Source is null) return null;
        return new SourceRange(item.Source.Start, AddSourceDelta(item.Source.Start, projectSampleDelta, item, timebase));
    }

    private static SourcePosition AddSourceDelta(
        SourcePosition source,
        long projectSampleDelta,
        TimelineEvent item,
        ProjectTimebase timebase)
    {
        decimal speed = ReadDecimal(item.Data["data"]?["speed"] ?? item.Data["speed"], 1);
        if (speed <= 0) throw new InvalidDataException("Timeline event speed must be positive.");
        (BigInteger speedNumerator, BigInteger speedDenominator) = DecimalFraction(speed);
        (BigInteger remainderNumerator, BigInteger remainderDenominator) = ParseFraction(source.Remainder);
        BigInteger denominator = timebase.SampleRate;
        BigInteger commonDenominator = remainderDenominator * denominator * speedDenominator;
        BigInteger numerator = (new BigInteger(source.Samples) * remainderDenominator + remainderNumerator) * denominator * speedDenominator
            + new BigInteger(projectSampleDelta) * source.SampleRate * speedNumerator * remainderDenominator;
        BigInteger rounded = RoundAwayFromZero(numerator, commonDenominator);
        BigInteger remainder = numerator - rounded * commonDenominator;
        if (rounded < 0 || rounded > long.MaxValue) throw new OverflowException("Source position exceeds the supported range.");
        return new SourcePosition(source.SampleRate, (long)rounded, CanonicalFraction(remainder, commonDenominator));
    }

    private static void EnsureIdAvailable(CanonicalProject project, string id)
    {
        if (project.Tracks.Any(track => track.Id == id || track.Events.Any(item => item.Id == id)) ||
            project.Markers.Any(marker => marker.Id == id))
        {
            throw new InvalidOperationException($"The timeline ID '{id}' is already in use.");
        }
    }

    private static TimelinePosition SnapBeat(
        ProjectTimebase timebase,
        TimelinePosition position,
        decimal beatsPerMinute,
        int subdivision)
    {
        (BigInteger bpmNumerator, BigInteger bpmDenominator) = DecimalFraction(beatsPerMinute);
        if (bpmNumerator <= 0) throw new ArgumentOutOfRangeException(nameof(bpmNumerator), "Tempo must be positive.");
        BigInteger gridNumerator = new BigInteger(timebase.SampleRate) * 60 * bpmDenominator;
        BigInteger gridDenominator = bpmNumerator * subdivision;
        BigInteger snappedIndex = RoundAwayFromZero(new BigInteger(position.Samples) * gridDenominator, gridNumerator);
        BigInteger samples = RoundAwayFromZero(snappedIndex * gridNumerator, gridDenominator);
        if (samples > long.MaxValue) throw new OverflowException("Snapped position exceeds the supported range.");
        return new TimelinePosition((long)samples);
    }

    private static (BigInteger Numerator, BigInteger Denominator) DecimalFraction(decimal value)
    {
        int[] bits = decimal.GetBits(value);
        int scale = (bits[3] >> 16) & 0x7F;
        BigInteger numerator = ((new BigInteger((uint)bits[2]) << 64) |
                                (new BigInteger((uint)bits[1]) << 32) |
                                (uint)bits[0]);
        if ((bits[3] & int.MinValue) != 0) numerator = -numerator;
        BigInteger denominator = BigInteger.Pow(10, scale);
        BigInteger divisor = BigInteger.GreatestCommonDivisor(BigInteger.Abs(numerator), denominator);
        return (numerator / divisor, denominator / divisor);
    }

    private static (BigInteger Numerator, BigInteger Denominator) ParseFraction(string value)
    {
        if (value == "0") return (BigInteger.Zero, BigInteger.One);
        string[] parts = value.Split('/');
        return (BigInteger.Parse(parts[0], CultureInfo.InvariantCulture), BigInteger.Parse(parts[1], CultureInfo.InvariantCulture));
    }

    private static BigInteger RoundAwayFromZero(BigInteger numerator, BigInteger denominator)
    {
        BigInteger sign = numerator.Sign < 0 ? -1 : 1;
        return sign * BigInteger.DivRem(BigInteger.Abs(numerator) * 2 + denominator, denominator * 2, out _);
    }

    private static string CanonicalFraction(BigInteger numerator, BigInteger denominator)
    {
        if (numerator.IsZero) return "0";
        BigInteger divisor = BigInteger.GreatestCommonDivisor(BigInteger.Abs(numerator), denominator);
        return $"{numerator / divisor}/{denominator / divisor}";
    }

    private static decimal ReadDecimal(JsonNode? node, decimal fallback) =>
        node is JsonValue value && value.TryGetValue<decimal>(out decimal result) ? result : fallback;

    private static bool ReadBoolean(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue<bool>(out bool result) && result;

    private static string SampleText(TimelinePosition position) => position.Samples.ToString(CultureInfo.InvariantCulture);

    private static void ValidatePosition(TimelinePosition position)
    {
        if (position.Samples < 0) throw new ArgumentOutOfRangeException(nameof(position));
    }

    private static void SetOptional(JsonObject target, string propertyName, bool? value)
    {
        if (value.HasValue)
        {
            target[propertyName] = value.Value;
        }
    }
}
