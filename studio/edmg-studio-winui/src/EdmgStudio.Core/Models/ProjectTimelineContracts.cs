using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public readonly record struct FrameRate
{
    public FrameRate(int numerator, int denominator)
    {
        if (numerator <= 0 || denominator <= 0 || (long)numerator > 240L * denominator)
        {
            throw new ArgumentOutOfRangeException(nameof(numerator), "Frame rate must be greater than zero and at most 240 fps.");
        }

        int divisor = GreatestCommonDivisor(numerator, denominator);
        Numerator = numerator / divisor;
        Denominator = denominator / divisor;
    }

    public int Numerator { get; }
    public int Denominator { get; }
    public double FramesPerSecond => (double)Numerator / Denominator;

    private static int GreatestCommonDivisor(int left, int right)
    {
        while (right != 0)
        {
            (left, right) = (right, left % right);
        }

        return Math.Abs(left);
    }
}

public readonly record struct TimelinePosition(long Samples);

public sealed record ProjectTimebase
{
    public ProjectTimebase(int sampleRate = 48_000, FrameRate? frameRate = null)
    {
        if (sampleRate is < 8_000 or > 384_000)
        {
            throw new ArgumentOutOfRangeException(nameof(sampleRate), "Sample rate must be between 8000 and 384000 Hz.");
        }

        SampleRate = sampleRate;
        FrameRate = frameRate ?? new FrameRate(30, 1);
    }

    public int SampleRate { get; }
    public FrameRate FrameRate { get; }

    public TimelinePosition FromSeconds(double seconds)
    {
        if (!double.IsFinite(seconds))
        {
            throw new ArgumentOutOfRangeException(nameof(seconds), "Time must be finite.");
        }

        return new TimelinePosition(checked((long)Math.Round(seconds * SampleRate, MidpointRounding.AwayFromZero)));
    }

    public double ToSeconds(TimelinePosition position) => (double)position.Samples / SampleRate;

    public TimelinePosition FromFrame(long frame) => new(checked((long)Math.Round(
        (decimal)frame * SampleRate * FrameRate.Denominator / FrameRate.Numerator,
        MidpointRounding.AwayFromZero)));

    public long ToFrame(TimelinePosition position) => checked((long)Math.Round(
        (decimal)position.Samples * FrameRate.Numerator / (SampleRate * FrameRate.Denominator),
        MidpointRounding.AwayFromZero));
}

public sealed record SourcePosition
{
    public SourcePosition(int sampleRate, long samples, string remainder = "0")
    {
        if (sampleRate <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(sampleRate), "Source sample rate must be positive.");
        }

        if (samples < 0 || !ProjectTimelineContracts.IsCanonicalFraction(remainder))
        {
            throw new ArgumentOutOfRangeException(nameof(samples), "Source position must be nonnegative with a canonical rational remainder.");
        }

        SampleRate = sampleRate;
        Samples = samples;
        Remainder = remainder;
    }

    public int SampleRate { get; init; }
    public long Samples { get; init; }
    public string Remainder { get; init; }
}

public sealed record SourceRange
{
    public SourceRange(SourcePosition start, SourcePosition? end)
    {
        ArgumentNullException.ThrowIfNull(start);
        if (end is not null && end.SampleRate != start.SampleRate)
        {
            throw new ArgumentException("Source range positions must use the same sample rate.", nameof(end));
        }

        if (end is not null && ProjectTimelineContracts.CompareSourcePositions(end, start) < 0)
        {
            throw new ArgumentException("Source range end cannot precede its start.", nameof(end));
        }

        Start = start;
        End = end;
    }

    public SourcePosition Start { get; init; }
    public SourcePosition? End { get; init; }
}

public sealed record ArtifactProvenance(
    string? ArtifactId,
    string? ManifestPath,
    string? ContentHash,
    string? RendererId,
    string? ProviderId,
    string? ModelId,
    string? ModelRevision,
    string? ProjectRevision,
    string? PlanRevision,
    IReadOnlyList<string> ParentArtifactIds,
    IReadOnlyList<string> SourceAssetIds);

public sealed record MediaAsset(
    string Id,
    string Path,
    string Kind,
    JsonObject Metadata,
    string? VersionId = null,
    ArtifactProvenance? Provenance = null);

public sealed record TimelineEvent(
    string Id,
    string Name,
    string Type,
    TimelinePosition Start,
    TimelinePosition End,
    string? MediaAssetId,
    JsonObject Data,
    SourceRange? Source = null)
{
    public TimelinePosition Duration => new(checked(End.Samples - Start.Samples));
}

public sealed record TimelineMarker(
    string Id,
    string Name,
    TimelinePosition Position,
    string? Color,
    JsonObject Metadata);

public sealed record Track(
    string Id,
    string Name,
    string Type,
    int Order,
    bool Locked,
    bool Muted,
    bool Solo,
    bool RecordArmed,
    bool InputMonitoring,
    IReadOnlyList<TimelineEvent> Events,
    JsonObject Metadata);

public sealed record CanonicalProject(
    string Id,
    string Name,
    long Revision,
    int SchemaVersion,
    ProjectTimebase Timebase,
    IReadOnlyList<Track> Tracks,
    IReadOnlyList<MediaAsset> MediaAssets,
    IReadOnlyList<TimelineMarker> Markers,
    JsonObject Metadata,
    JsonObject Timeline);

public static class ProjectTimelineContracts
{
    public static CanonicalProject FromProject(ProjectDto project)
    {
        ArgumentNullException.ThrowIfNull(project);
        JsonObject metadata = project.Meta.ValueKind == JsonValueKind.Object
            ? JsonNode.Parse(project.Meta.GetRawText())!.AsObject()
            : [];
        JsonObject timeline = metadata["timeline"] is JsonObject sourceTimeline
            ? sourceTimeline.DeepClone().AsObject()
            : [];
        return FromTimeline(project, metadata, timeline);
    }

    public static CanonicalProject FromTimeline(ProjectDto project, JsonObject timeline)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentNullException.ThrowIfNull(timeline);
        JsonObject metadata = project.Meta.ValueKind == JsonValueKind.Object
            ? JsonNode.Parse(project.Meta.GetRawText())!.AsObject()
            : [];
        metadata["timeline"] = timeline.DeepClone();
        return FromTimeline(project, metadata, timeline.DeepClone().AsObject());
    }

    private static CanonicalProject FromTimeline(ProjectDto project, JsonObject metadata, JsonObject timeline)
    {
        ProjectTimebase timebase = ReadTimebase(timeline);
        IReadOnlyList<Track> tracks = ReadTracks(timeline, timebase);
        return new CanonicalProject(
            project.Id,
            project.Name,
            project.Revision,
            project.SchemaVersion,
            timebase,
            tracks,
            ReadMediaAssets(metadata, timeline),
            ReadMarkers(timeline, timebase, tracks),
            metadata,
            timeline);
    }

    public static JsonObject RebuildTimeline(CanonicalProject project)
    {
        ArgumentNullException.ThrowIfNull(project);
        var timeline = project.Timeline.DeepClone().AsObject();
        timeline["timebase"] = new JsonObject
        {
            ["sample_rate"] = project.Timebase.SampleRate,
            ["frame_rate"] = new JsonObject
            {
                ["numerator"] = project.Timebase.FrameRate.Numerator,
                ["denominator"] = project.Timebase.FrameRate.Denominator
            }
        };

        var tracks = new JsonArray();
        foreach (Track track in project.Tracks)
        {
            tracks.Add(BuildTrack(project.Timebase, track));
        }

        timeline["tracks"] = tracks;
        var mediaPool = new JsonArray();
        foreach (MediaAsset asset in project.MediaAssets)
        {
            JsonObject assetNode = asset.Metadata.DeepClone().AsObject();
            assetNode["id"] = asset.Id;
            assetNode["path"] = asset.Path;
            assetNode["kind"] = asset.Kind;
            WriteOptionalString(assetNode, "version_id", asset.VersionId);
            WriteArtifactProvenance(assetNode, asset.Provenance);
            mediaPool.Add(assetNode);
        }

        timeline["media_pool"] = mediaPool;
        var markers = new JsonArray();
        foreach (TimelineMarker marker in project.Markers.OrderBy(item => item.Position.Samples))
        {
            JsonObject markerNode = marker.Metadata.DeepClone().AsObject();
            markerNode["id"] = marker.Id;
            markerNode["name"] = marker.Name;
            markerNode["position_sample"] = marker.Position.Samples.ToString(CultureInfo.InvariantCulture);
            markerNode["time_s"] = project.Timebase.ToSeconds(marker.Position);
            WriteOptionalString(markerNode, "color", marker.Color);
            markers.Add(markerNode);
        }

        timeline["markers"] = markers;
        return timeline;
    }

    private static JsonObject BuildTrack(ProjectTimebase timebase, Track track)
    {
        var trackNode = track.Metadata.DeepClone().AsObject();
        trackNode["id"] = track.Id;
        trackNode["name"] = track.Name;
        trackNode["type"] = track.Type;
        trackNode["locked"] = track.Locked;
        WriteOptionalBoolean(trackNode, "muted", track.Muted);
        WriteOptionalBoolean(trackNode, "solo", track.Solo);
        WriteOptionalBoolean(trackNode, "record_armed", track.RecordArmed);
        WriteOptionalBoolean(trackNode, "input_monitoring", track.InputMonitoring);
        var events = new JsonArray();
        foreach (TimelineEvent timelineEvent in track.Events)
        {
            var eventNode = timelineEvent.Data.DeepClone().AsObject();
            eventNode["id"] = timelineEvent.Id;
            eventNode["type"] = timelineEvent.Type;
            eventNode["start_sample"] = timelineEvent.Start.Samples.ToString(CultureInfo.InvariantCulture);
            eventNode["end_sample"] = timelineEvent.End.Samples.ToString(CultureInfo.InvariantCulture);
            eventNode["start_s"] = timebase.ToSeconds(timelineEvent.Start);
            eventNode["end_s"] = timebase.ToSeconds(timelineEvent.End);
            if (!string.IsNullOrWhiteSpace(timelineEvent.MediaAssetId))
            {
                eventNode["media_asset_id"] = timelineEvent.MediaAssetId;
            }
            else
            {
                eventNode.Remove("media_asset_id");
                if (eventNode["data"] is JsonObject eventData)
                {
                    eventData.Remove("media_asset_id");
                }
            }

            var data = eventNode["data"] as JsonObject ?? [];
            data["name"] = timelineEvent.Name;
            WriteSourceRange(data, timelineEvent.Source, timebase);
            eventNode["data"] = data;
            events.Add(eventNode);
        }

        trackNode["clips"] = events;
        return trackNode;
    }

    private static ProjectTimebase ReadTimebase(JsonObject timeline)
    {
        var timebase = timeline["timebase"] as JsonObject;
        int sampleRate = ReadInt32(timebase?["sample_rate"], 48_000);
        JsonNode? frameRateNode = timebase?["frame_rate"];
        FrameRate frameRate = frameRateNode is JsonObject rate
            ? new FrameRate(ReadInt32(rate["numerator"], 30), ReadInt32(rate["denominator"], 1))
            : FromDecimalFrameRate(ReadDouble(frameRateNode ?? timeline["fps"], 30));
        return new ProjectTimebase(sampleRate, frameRate);
    }

    private static IReadOnlyList<Track> ReadTracks(JsonObject timeline, ProjectTimebase timebase)
    {
        if (timeline["tracks"] is not JsonArray sourceTracks)
        {
            return [];
        }

        var tracks = new List<Track>(sourceTracks.Count);
        var identifiers = new HashSet<string>(StringComparer.Ordinal);
        for (int trackIndex = 0; trackIndex < sourceTracks.Count; trackIndex++)
        {
            if (sourceTracks[trackIndex] is not JsonObject sourceTrack)
            {
                continue;
            }

            string trackId = ReadString(sourceTrack["id"]) ?? $"track-{trackIndex}";
            AddUniqueIdentifier(identifiers, trackId, "track");
            string trackType = ReadString(sourceTrack["type"]) ?? "video";
            tracks.Add(new Track(
                trackId,
                ReadString(sourceTrack["name"]) ?? $"Track {trackIndex + 1}",
                trackType,
                trackIndex,
                ReadBoolean(sourceTrack["locked"]),
                ReadBoolean(sourceTrack["muted"]),
                ReadBoolean(sourceTrack["solo"]),
                ReadBoolean(sourceTrack["record_armed"]),
                ReadBoolean(sourceTrack["input_monitoring"]),
                ReadEvents(sourceTrack, trackId, trackType, timebase, identifiers),
                sourceTrack.DeepClone().AsObject()));
        }

        return tracks;
    }

    private static IReadOnlyList<TimelineEvent> ReadEvents(
        JsonObject sourceTrack,
        string trackId,
        string trackType,
        ProjectTimebase timebase,
        HashSet<string> identifiers)
    {
        if (sourceTrack["clips"] is not JsonArray sourceEvents)
        {
            return [];
        }

        var events = new List<TimelineEvent>(sourceEvents.Count);
        for (int eventIndex = 0; eventIndex < sourceEvents.Count; eventIndex++)
        {
            if (sourceEvents[eventIndex] is not JsonObject sourceEvent)
            {
                continue;
            }

            JsonObject? data = sourceEvent["data"] as JsonObject;
            TimelinePosition start = ReadPosition(sourceEvent, "start_sample", "start_s", timebase);
            TimelinePosition end = ReadPosition(sourceEvent, "end_sample", "end_s", timebase);
            if (end.Samples < start.Samples)
            {
                throw new InvalidDataException($"Timeline event '{ReadString(sourceEvent["id"])}' ends before it starts.");
            }

            string eventId = ReadString(sourceEvent["id"]) ?? $"{trackId}-event-{eventIndex}";
            AddUniqueIdentifier(identifiers, eventId, "timeline event");
            if (start.Samples < 0 || end.Samples < 0)
            {
                throw new InvalidDataException($"Timeline event '{eventId}' cannot start or end before zero.");
            }

            events.Add(new TimelineEvent(
                eventId,
                ReadString(data?["name"]) ?? ReadString(sourceEvent["name"]) ?? $"Event {eventIndex + 1}",
                ReadString(sourceEvent["type"]) ?? trackType,
                start,
                end,
                ReadString(sourceEvent["media_asset_id"]) ?? ReadString(data?["media_asset_id"]),
                sourceEvent.DeepClone().AsObject(),
                ReadSourceRange(data, timebase)));
        }

        return events;
    }

    private static IReadOnlyList<MediaAsset> ReadMediaAssets(JsonObject metadata, JsonObject timeline)
    {
        JsonArray? metadataAssets = metadata["media_pool"] as JsonArray;
        JsonArray? timelineAssets = timeline["media_pool"] as JsonArray;
        if (metadataAssets is null && timelineAssets is null)
        {
            return [];
        }

        var assets = new List<MediaAsset>((metadataAssets?.Count ?? 0) + (timelineAssets?.Count ?? 0));
        var assetIndexes = new Dictionary<string, int>(StringComparer.Ordinal);
        ReadMediaAssetPool(metadataAssets, assets, assetIndexes);
        ReadMediaAssetPool(timelineAssets, assets, assetIndexes);
        return assets;
    }

    private static IReadOnlyList<TimelineMarker> ReadMarkers(
        JsonObject timeline,
        ProjectTimebase timebase,
        IReadOnlyList<Track> tracks)
    {
        if (timeline["markers"] is not JsonArray sourceMarkers)
        {
            return [];
        }

        var markers = new List<TimelineMarker>(sourceMarkers.Count);
        var identifiers = tracks.Select(track => track.Id)
            .Concat(tracks.SelectMany(track => track.Events).Select(item => item.Id))
            .ToHashSet(StringComparer.Ordinal);
        for (int index = 0; index < sourceMarkers.Count; index++)
        {
            if (sourceMarkers[index] is not JsonObject sourceMarker)
            {
                continue;
            }

            string markerId = ReadString(sourceMarker["id"]) ?? $"marker-{index}";
            AddUniqueIdentifier(identifiers, markerId, "timeline marker");
            TimelinePosition position = sourceMarker["position_sample"] is null && sourceMarker["time_s"] is null
                ? timebase.FromSeconds(ReadDouble(sourceMarker["t"], 0))
                : ReadPosition(sourceMarker, "position_sample", "time_s", timebase);
            if (position.Samples < 0)
            {
                throw new InvalidDataException($"Timeline marker '{markerId}' cannot be before zero.");
            }

            markers.Add(new TimelineMarker(
                markerId,
                ReadString(sourceMarker["name"]) ?? ReadString(sourceMarker["label"]) ?? $"Marker {index + 1}",
                position,
                ReadString(sourceMarker["color"]),
                sourceMarker.DeepClone().AsObject()));
        }

        return markers.OrderBy(marker => marker.Position.Samples).ToArray();
    }

    private static void ReadMediaAssetPool(
        JsonArray? sourceAssets,
        List<MediaAsset> assets,
        Dictionary<string, int> assetIndexes)
    {
        if (sourceAssets is null)
        {
            return;
        }

        for (int index = 0; index < sourceAssets.Count; index++)
        {
            if (sourceAssets[index] is not JsonObject sourceAsset)
            {
                continue;
            }

            string assetId = ReadString(sourceAsset["id"]) ??
                ReadString(sourceAsset["artifact_id"]) ??
                ReadString(sourceAsset["path"]) ??
                $"asset-{assets.Count}";
            var asset = new MediaAsset(
                assetId,
                ReadString(sourceAsset["path"]) ?? ReadString(sourceAsset["source_path"]) ?? string.Empty,
                ReadString(sourceAsset["kind"]) ?? ReadString(sourceAsset["type"]) ?? "unknown",
                sourceAsset.DeepClone().AsObject(),
                ReadString(sourceAsset["version_id"]),
                ReadArtifactProvenance(sourceAsset));
            if (assetIndexes.TryGetValue(assetId, out int existingIndex))
            {
                assets[existingIndex] = asset;
            }
            else
            {
                assetIndexes.Add(assetId, assets.Count);
                assets.Add(asset);
            }
        }
    }

    private static TimelinePosition ReadPosition(
        JsonObject source,
        string sampleProperty,
        string secondsProperty,
        ProjectTimebase timebase)
    {
        if (source[sampleProperty] is JsonValue exact)
        {
            if (exact.TryGetValue<long>(out long integerSamples))
            {
                return new TimelinePosition(integerSamples);
            }

            if (exact.TryGetValue<string>(out string? text) &&
                text is not null &&
                long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long stringSamples) &&
                stringSamples.ToString(CultureInfo.InvariantCulture) == text)
            {
                return new TimelinePosition(stringSamples);
            }

            throw new InvalidDataException($"'{sampleProperty}' must be a decimal int64 string or integer.");
        }

        return timebase.FromSeconds(ReadDouble(source[secondsProperty], 0));
    }

    private static SourceRange? ReadSourceRange(JsonObject? data, ProjectTimebase timebase)
    {
        if (data is null || data["source_offset_sample"] is null && data["source_in_s"] is null)
        {
            return null;
        }

        int sampleRate = ReadInt32(data["source_sample_rate"], timebase.SampleRate);
        long startSamples = ReadSourceSamples(data, "source_offset_sample", "source_in_s", sampleRate);
        var start = new SourcePosition(sampleRate, startSamples, ReadString(data["source_offset_remainder"]) ?? "0");
        SourcePosition? end = data["source_end_sample"] is not null || data["source_out_s"] is not null
            ? new SourcePosition(
                sampleRate,
                ReadSourceSamples(data, "source_end_sample", "source_out_s", sampleRate),
                ReadString(data["source_end_remainder"]) ?? "0")
            : null;
        return new SourceRange(start, end);
    }

    private static long ReadSourceSamples(JsonObject data, string sampleProperty, string secondsProperty, int sampleRate)
    {
        if (data[sampleProperty] is not null)
        {
            return ReadExactInt64(data[sampleProperty], sampleProperty);
        }

        return checked((long)Math.Round(ReadDouble(data[secondsProperty], 0) * sampleRate, MidpointRounding.AwayFromZero));
    }

    private static void WriteSourceRange(JsonObject data, SourceRange? source, ProjectTimebase timebase)
    {
        if (source is null)
        {
            data.Remove("source_sample_rate");
            data.Remove("source_offset_sample");
            data.Remove("source_offset_remainder");
            data.Remove("source_end_sample");
            data.Remove("source_end_remainder");
            data.Remove("source_in_s");
            data.Remove("source_out_s");
            return;
        }

        data["source_sample_rate"] = source.Start.SampleRate;
        data["source_offset_sample"] = source.Start.Samples.ToString(CultureInfo.InvariantCulture);
        data["source_offset_remainder"] = source.Start.Remainder;
        data["source_in_s"] = SourceSeconds(source.Start);
        if (source.End is not null)
        {
            data["source_end_sample"] = source.End.Samples.ToString(CultureInfo.InvariantCulture);
            data["source_end_remainder"] = source.End.Remainder;
            data["source_out_s"] = SourceSeconds(source.End);
        }
        else
        {
            data.Remove("source_end_sample");
            data.Remove("source_end_remainder");
            data.Remove("source_out_s");
        }
    }

    private static ArtifactProvenance? ReadArtifactProvenance(JsonObject sourceAsset)
    {
        JsonObject? provenance = sourceAsset["provenance"] as JsonObject;
        JsonObject? model = sourceAsset["model"] as JsonObject ?? provenance?["model"] as JsonObject;
        JsonObject? lineage = sourceAsset["lineage"] as JsonObject ?? provenance?["lineage"] as JsonObject;
        string? artifactId = ReadString(sourceAsset["artifact_id"]) ?? ReadString(provenance?["artifact_id"]);
        string? manifestPath = ReadString(sourceAsset["manifest_path"]) ?? ReadString(provenance?["manifest_path"]);
        string? contentHash = ReadString(sourceAsset["content_hash"]) ?? ReadString(provenance?["content_hash"]);
        string? rendererId = ReadString(sourceAsset["renderer_id"]) ?? ReadString(sourceAsset["engine"]) ?? ReadString(provenance?["renderer_id"]);
        string? providerId = ReadString(sourceAsset["provider_id"]) ?? ReadString(sourceAsset["provider"]) ?? ReadString(provenance?["provider_id"]);
        string? modelId = ReadString(model?["id"]) ?? ReadString(sourceAsset["model_id"]);
        string? modelRevision = ReadString(model?["revision"]) ?? ReadString(sourceAsset["model_revision"]);
        string? projectRevision = ReadString(sourceAsset["project_revision"]) ?? ReadString(provenance?["project_revision"]);
        string? planRevision = ReadString(sourceAsset["plan_revision"]) ?? ReadString(provenance?["plan_revision"]);
        string[] parents = ReadStrings(lineage?["parents"] ?? sourceAsset["parent_artifact_ids"]);
        string[] sources = ReadSourceAssetIds(sourceAsset["source_assets"] ?? provenance?["source_assets"]);
        return new[] { artifactId, manifestPath, contentHash, rendererId, providerId, modelId, modelRevision, projectRevision, planRevision }
            .Any(value => !string.IsNullOrWhiteSpace(value)) || parents.Length > 0 || sources.Length > 0
            ? new ArtifactProvenance(artifactId, manifestPath, contentHash, rendererId, providerId, modelId,
                modelRevision, projectRevision, planRevision, parents, sources)
            : null;
    }

    private static string[] ReadSourceAssetIds(JsonNode? node) => node is JsonArray values
        ? values.Select(value => value is JsonObject item
                ? ReadString(item["id"]) ?? ReadString(item["asset_id"]) ?? ReadString(item["path"])
                : ReadString(value))
            .Where(value => !string.IsNullOrWhiteSpace(value)).Cast<string>().ToArray()
        : [];

    private static string[] ReadStrings(JsonNode? node) => node is JsonArray values
        ? values.Select(ReadString).Where(value => !string.IsNullOrWhiteSpace(value)).Cast<string>().ToArray()
        : [];

    private static void WriteArtifactProvenance(JsonObject target, ArtifactProvenance? provenance)
    {
        if (provenance is null)
        {
            return;
        }

        WriteOptionalString(target, "artifact_id", provenance.ArtifactId);
        WriteOptionalString(target, "manifest_path", provenance.ManifestPath);
        WriteOptionalString(target, "content_hash", provenance.ContentHash);
        WriteOptionalString(target, "renderer_id", provenance.RendererId);
        WriteOptionalString(target, "provider_id", provenance.ProviderId);
        WriteOptionalString(target, "project_revision", provenance.ProjectRevision);
        WriteOptionalString(target, "plan_revision", provenance.PlanRevision);
        target["model"] = new JsonObject { ["id"] = provenance.ModelId, ["revision"] = provenance.ModelRevision };
        target["lineage"] = new JsonObject
        {
            ["parents"] = new JsonArray(provenance.ParentArtifactIds.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray())
        };
        target["source_assets"] = new JsonArray(provenance.SourceAssetIds.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
    }

    private static void WriteOptionalString(JsonObject target, string propertyName, string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            target.Remove(propertyName);
        }
        else
        {
            target[propertyName] = value;
        }
    }

    internal static int CompareSourcePositions(SourcePosition left, SourcePosition right)
    {
        BigInteger leftNumerator = FractionNumerator(left.Remainder);
        BigInteger leftDenominator = FractionDenominator(left.Remainder);
        BigInteger rightNumerator = FractionNumerator(right.Remainder);
        BigInteger rightDenominator = FractionDenominator(right.Remainder);
        return ((new BigInteger(left.Samples) * leftDenominator + leftNumerator) * rightDenominator)
            .CompareTo((new BigInteger(right.Samples) * rightDenominator + rightNumerator) * leftDenominator);
    }

    private static double SourceSeconds(SourcePosition position) =>
        ((double)position.Samples + (double)FractionNumerator(position.Remainder) / (double)FractionDenominator(position.Remainder)) /
        position.SampleRate;

    private static BigInteger FractionNumerator(string value) => value == "0" ? BigInteger.Zero : BigInteger.Parse(value.Split('/')[0], CultureInfo.InvariantCulture);

    private static BigInteger FractionDenominator(string value) => value == "0" ? BigInteger.One : BigInteger.Parse(value.Split('/')[1], CultureInfo.InvariantCulture);

    private static long ReadExactInt64(JsonNode? node, string propertyName)
    {
        if (node is JsonValue value && value.TryGetValue<long>(out long integer)) return integer;
        string? text = ReadString(node);
        if (text is not null && long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long parsed) &&
            parsed.ToString(CultureInfo.InvariantCulture) == text) return parsed;
        throw new InvalidDataException($"'{propertyName}' must be a decimal int64 string or integer.");
    }

    internal static bool IsCanonicalFraction(string value)
    {
        if (value == "0") return true;
        string[] parts = value.Split('/');
        return parts.Length == 2 &&
               BigInteger.TryParse(parts[0], NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out BigInteger numerator) &&
               BigInteger.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out BigInteger denominator) &&
               denominator > 0 && BigInteger.Abs(numerator) < denominator &&
               BigInteger.GreatestCommonDivisor(BigInteger.Abs(numerator), denominator) == BigInteger.One;
    }

    private static FrameRate FromDecimalFrameRate(double fps)
    {
        if (Math.Abs(fps - 23.976) < 0.0005) return new FrameRate(24_000, 1_001);
        if (Math.Abs(fps - 29.97) < 0.0005) return new FrameRate(30_000, 1_001);
        if (Math.Abs(fps - 59.94) < 0.0005) return new FrameRate(60_000, 1_001);
        return new FrameRate(checked((int)Math.Round(fps, MidpointRounding.AwayFromZero)), 1);
    }

    private static string? ReadString(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue<string>(out string? text) ? text : null;

    private static int ReadInt32(JsonNode? node, int fallback) =>
        node is JsonValue value && value.TryGetValue<int>(out int result) ? result : fallback;

    private static double ReadDouble(JsonNode? node, double fallback) =>
        node is JsonValue value && value.TryGetValue<double>(out double result) ? result : fallback;

    private static bool ReadBoolean(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue<bool>(out bool result) && result;

    private static void WriteOptionalBoolean(JsonObject target, string propertyName, bool value)
    {
        if (value || target.ContainsKey(propertyName))
        {
            target[propertyName] = value;
        }
    }

    private static void AddUniqueIdentifier(HashSet<string> identifiers, string identifier, string kind)
    {
        if (string.IsNullOrWhiteSpace(identifier) || !identifiers.Add(identifier))
        {
            throw new InvalidDataException($"The {kind} ID '{identifier}' must be nonempty and unique.");
        }
    }
}
