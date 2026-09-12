using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed record InsertRenderResultRequest(
    [property: JsonPropertyName("job_id")] string JobId,
    [property: JsonPropertyName("expected_revision")] long ExpectedRevision,
    [property: JsonPropertyName("track_id")]
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? TrackId = null,
    [property: JsonPropertyName("start_s")]
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    double? StartSeconds = null);

public sealed class InsertRenderResultResponse
{
    [JsonPropertyName("ok")] public bool Ok { get; init; } = true;
    [JsonPropertyName("revision")] public long Revision { get; init; }
    [JsonPropertyName("track_id")] public string? TrackId { get; init; }
    [JsonPropertyName("clip_id")] public string? ClipId { get; init; }
    [JsonPropertyName("media_asset_id")] public string? MediaAssetId { get; init; }
    [JsonPropertyName("replayed")] public bool Replayed { get; init; }
    [JsonPropertyName("timeline")] public JsonElement? Timeline { get; init; }
}

public sealed record RenderResultDescriptor(
    string JobId,
    string OutputPath,
    double? DurationSeconds = null,
    JsonObject? Metadata = null,
    string? ArtifactId = null,
    string? RendererId = null,
    string? ProviderId = null,
    string? ModelId = null,
    string? ModelRevision = null,
    string? ProjectRevision = null,
    string? PlanRevision = null,
    IReadOnlyList<string>? ParentArtifactIds = null,
    IReadOnlyList<string>? SourceAssetIds = null)
{
    public static RenderResultDescriptor FromJob(StudioJob job, string outputPath)
    {
        ArgumentNullException.ThrowIfNull(job);
        var metadata = new JsonObject();
        if (job.Payload is JsonElement payload && payload.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined)
        {
            metadata["job_payload"] = JsonNode.Parse(payload.GetRawText());
        }

        if (job.Result is JsonElement result && result.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined)
        {
            metadata["job_result"] = JsonNode.Parse(result.GetRawText());
        }

        return new RenderResultDescriptor(job.Id, outputPath, Metadata: metadata);
    }
}

public sealed record CanonicalTimelineInsertionResult(
    CanonicalProject Project,
    string TrackId,
    string ClipId,
    string MediaAssetId,
    bool Replayed);

public static class RenderResultTimelineInsertion
{
    public static CanonicalTimelineInsertionResult Insert(
        CanonicalProject project,
        RenderResultDescriptor renderResult,
        TimelinePosition playhead,
        string? targetTrackId = null)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentNullException.ThrowIfNull(renderResult);
        if (string.IsNullOrWhiteSpace(renderResult.JobId)) throw new ArgumentException("A render job ID is required.", nameof(renderResult));
        if (string.IsNullOrWhiteSpace(renderResult.OutputPath)) throw new ArgumentException("A render output path is required.", nameof(renderResult));
        if (playhead.Samples < 0) throw new ArgumentOutOfRangeException(nameof(playhead));

        string identity = StableId(project.Id, renderResult.JobId);
        string assetId = $"render-asset-{identity}";
        string clipId = $"render-clip-{identity}";
        Track? replayTrack = project.Tracks.FirstOrDefault(track => track.Events.Any(item =>
            string.Equals(item.Id, clipId, StringComparison.Ordinal) ||
            string.Equals(ReadString(item.Data["data"]?["render_job_id"]), renderResult.JobId, StringComparison.Ordinal)));
        if (replayTrack is not null)
        {
            return new CanonicalTimelineInsertionResult(project, replayTrack.Id, clipId, assetId, true);
        }

        Track? target = !string.IsNullOrWhiteSpace(targetTrackId)
            ? project.Tracks.FirstOrDefault(track => string.Equals(track.Id, targetTrackId.Trim(), StringComparison.Ordinal))
            : project.Tracks.FirstOrDefault(IsUnlockedVideoTrack);
        if (target is not null && !IsUnlockedVideoTrack(target))
        {
            target = project.Tracks.FirstOrDefault(IsUnlockedVideoTrack);
        }

        var tracks = project.Tracks.ToList();
        if (target is null)
        {
            string trackId = $"render-video-{identity}";
            target = new Track(trackId, "Generated Video", "video", tracks.Count, false, false, false, false, false, [],
                new JsonObject { ["id"] = trackId, ["name"] = "Generated Video", ["type"] = "video", ["locked"] = false });
            tracks.Add(target);
        }

        long durationSamples = renderResult.DurationSeconds is > 0 and double duration && double.IsFinite(duration)
            ? Math.Max(1, project.Timebase.FromSeconds(duration).Samples)
            : Math.Max(1, project.Timebase.FromFrame(1).Samples);
        var eventData = new JsonObject
        {
            ["id"] = clipId,
            ["type"] = "video",
            ["data"] = new JsonObject
            {
                ["name"] = Path.GetFileName(renderResult.OutputPath),
                ["render_job_id"] = renderResult.JobId,
                ["render_result"] = true
            }
        };
        var timelineEvent = new TimelineEvent(
            clipId,
            Path.GetFileName(renderResult.OutputPath),
            "video",
            playhead,
            new TimelinePosition(checked(playhead.Samples + durationSamples)),
            assetId,
            eventData);
        int targetIndex = tracks.IndexOf(target);
        tracks[targetIndex] = target with { Events = target.Events.Concat([timelineEvent]).ToArray() };

        JsonObject assetMetadata = renderResult.Metadata?.DeepClone().AsObject() ?? [];
        assetMetadata["id"] = assetId;
        assetMetadata["path"] = renderResult.OutputPath;
        assetMetadata["kind"] = "video";
        assetMetadata["render_job_id"] = renderResult.JobId;
        string artifactId = FirstValue(renderResult.ArtifactId, FindString(assetMetadata, "artifact_id")) ?? assetId;
        var provenance = new ArtifactProvenance(
            artifactId,
            FindString(assetMetadata, "manifest_path", "artifact_manifest"),
            FindString(assetMetadata, "content_hash"),
            FirstValue(renderResult.RendererId, FindString(assetMetadata, "renderer_id", "engine")),
            FirstValue(renderResult.ProviderId, FindString(assetMetadata, "provider_id", "provider")),
            FirstValue(renderResult.ModelId, FindString(assetMetadata, "model_id"), FindNestedString(assetMetadata, "model", "id")),
            FirstValue(renderResult.ModelRevision, FindString(assetMetadata, "model_revision"), FindNestedString(assetMetadata, "model", "revision")),
            FirstValue(renderResult.ProjectRevision, FindString(assetMetadata, "project_revision")),
            FirstValue(renderResult.PlanRevision, FindString(assetMetadata, "plan_revision")),
            renderResult.ParentArtifactIds?.ToArray() ?? FindStrings(assetMetadata, "parent_artifact_ids", "parents"),
            renderResult.SourceAssetIds?.ToArray() ?? FindSourceAssetIds(assetMetadata));
        assetMetadata["artifact_id"] = artifactId;
        assetMetadata["provenance"] = BuildProvenance(provenance);
        var assets = project.MediaAssets.Concat([
            new MediaAsset(assetId, renderResult.OutputPath, "video", assetMetadata, artifactId, provenance)
        ]).ToArray();
        var updated = project with { Tracks = tracks, MediaAssets = assets };
        return new CanonicalTimelineInsertionResult(updated, target.Id, clipId, assetId, false);
    }

    private static bool IsUnlockedVideoTrack(Track track) =>
        !track.Locked && string.Equals(track.Type, "video", StringComparison.OrdinalIgnoreCase);

    private static string? ReadString(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue<string>(out string? text) ? text :
        node is JsonValue integer && integer.TryGetValue<long>(out long number) ? number.ToString(System.Globalization.CultureInfo.InvariantCulture) : null;

    private static string? FirstValue(params string?[] values) =>
        values.FirstOrDefault(value => !string.IsNullOrWhiteSpace(value))?.Trim();

    private static string? FindString(JsonNode? node, params string[] names)
    {
        if (node is JsonObject item)
        {
            foreach (string name in names)
            {
                string? value = ReadString(item[name]);
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }

            foreach ((_, JsonNode? child) in item)
            {
                string? value = FindString(child, names);
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }
        }
        else if (node is JsonArray values)
        {
            foreach (JsonNode? child in values)
            {
                string? value = FindString(child, names);
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }
        }

        return null;
    }

    private static string? FindNestedString(JsonNode? node, string objectName, string propertyName)
    {
        if (node is JsonObject item)
        {
            if (item[objectName] is JsonObject nested)
            {
                string? value = ReadString(nested[propertyName]);
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }

            foreach ((_, JsonNode? child) in item)
            {
                string? value = FindNestedString(child, objectName, propertyName);
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }
        }
        else if (node is JsonArray values)
        {
            foreach (JsonNode? child in values)
            {
                string? value = FindNestedString(child, objectName, propertyName);
                if (!string.IsNullOrWhiteSpace(value)) return value;
            }
        }

        return null;
    }

    private static string[] FindStrings(JsonNode? node, params string[] names)
    {
        if (node is JsonObject item)
        {
            foreach (string name in names)
            {
                if (item[name] is JsonArray values)
                {
                    return values.Select(ReadString).Where(value => !string.IsNullOrWhiteSpace(value)).Cast<string>().ToArray();
                }
            }

            foreach ((_, JsonNode? child) in item)
            {
                string[] values = FindStrings(child, names);
                if (values.Length > 0) return values;
            }
        }
        else if (node is JsonArray values)
        {
            foreach (JsonNode? child in values)
            {
                string[] found = FindStrings(child, names);
                if (found.Length > 0) return found;
            }
        }

        return [];
    }

    private static string[] FindSourceAssetIds(JsonNode? node)
    {
        if (node is JsonObject item)
        {
            if (item["source_assets"] is JsonArray sourceAssets)
            {
                return sourceAssets.Select(value => value is JsonObject source
                        ? FirstValue(ReadString(source["id"]), ReadString(source["asset_id"]), ReadString(source["path"]))
                        : ReadString(value))
                    .Where(value => !string.IsNullOrWhiteSpace(value)).Cast<string>().ToArray();
            }

            foreach ((_, JsonNode? child) in item)
            {
                string[] values = FindSourceAssetIds(child);
                if (values.Length > 0) return values;
            }
        }
        else if (node is JsonArray values)
        {
            foreach (JsonNode? child in values)
            {
                string[] found = FindSourceAssetIds(child);
                if (found.Length > 0) return found;
            }
        }

        return [];
    }

    private static JsonObject BuildProvenance(ArtifactProvenance provenance) => new()
    {
        ["artifact_id"] = provenance.ArtifactId,
        ["manifest_path"] = provenance.ManifestPath,
        ["content_hash"] = provenance.ContentHash,
        ["renderer_id"] = provenance.RendererId,
        ["provider_id"] = provenance.ProviderId,
        ["model"] = new JsonObject { ["id"] = provenance.ModelId, ["revision"] = provenance.ModelRevision },
        ["project_revision"] = provenance.ProjectRevision,
        ["plan_revision"] = provenance.PlanRevision,
        ["lineage"] = new JsonObject
        {
            ["parents"] = new JsonArray(provenance.ParentArtifactIds.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray())
        },
        ["source_assets"] = new JsonArray(provenance.SourceAssetIds.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray())
    };

    private static string StableId(string projectId, string jobId)
    {
        byte[] hash = SHA256.HashData(Encoding.UTF8.GetBytes($"{projectId}\n{jobId}"));
        return Convert.ToHexString(hash.AsSpan(0, 10)).ToLowerInvariant();
    }
}
