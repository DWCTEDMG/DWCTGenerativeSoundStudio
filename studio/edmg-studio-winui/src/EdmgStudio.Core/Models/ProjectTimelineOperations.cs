using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public sealed record ProjectTimelineMutation(CanonicalProject Project, JsonObject Operation);

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

        if (project.Tracks.Any(track => string.Equals(track.Id, id, StringComparison.Ordinal)) ||
            project.Tracks.SelectMany(track => track.Events).Any(item => string.Equals(item.Id, id, StringComparison.Ordinal)))
        {
            throw new InvalidOperationException($"The timeline ID '{id}' is already in use.");
        }

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

    private static CanonicalProject WithTracks(CanonicalProject project, IReadOnlyList<Track> tracks)
    {
        Track[] ordered = tracks.Select((track, index) => track with { Order = index }).ToArray();
        return project with { Tracks = ordered };
    }

    private static void SetOptional(JsonObject target, string propertyName, bool? value)
    {
        if (value.HasValue)
        {
            target[propertyName] = value.Value;
        }
    }
}
