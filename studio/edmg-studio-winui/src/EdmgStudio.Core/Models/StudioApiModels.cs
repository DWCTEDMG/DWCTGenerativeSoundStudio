using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.Json.Serialization.Metadata;

namespace EdmgStudio.Core.Models;

public sealed record HealthResponse(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("version")] string Version);

public sealed class ProjectListResponse
{
    [JsonPropertyName("projects")]
    public List<ProjectDto> Projects { get; init; } = [];
}

public sealed class ProjectResponse
{
    [JsonPropertyName("project")]
    public required ProjectDto Project { get; init; }

    [JsonPropertyName("visual_dna")]
    public JsonElement VisualDna { get; init; }

    [JsonPropertyName("visual_dna_hints")]
    public JsonElement VisualDnaHints { get; init; }
}

public sealed class ProjectDto
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;

    [JsonPropertyName("meta")]
    public JsonElement Meta { get; init; }

    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; init; }

    [JsonIgnore]
    public bool HasAudio => TryGetMetaObject("audio", out _);

    [JsonIgnore]
    public bool HasAnalysis => TryGetMetaObject("analysis", out _);

    [JsonIgnore]
    public bool HasPlan => TryGetMetaObject("last_plan", out _);

    [JsonIgnore]
    public string AudioFileName =>
        TryGetMetaObject("audio", out var audio) && audio.TryGetProperty("filename", out var filename)
            ? filename.GetString() ?? string.Empty
            : string.Empty;

    [JsonIgnore]
    public long? AudioSizeBytes =>
        TryGetMetaObject("audio", out var audio) && audio.TryGetProperty("size_bytes", out var size) && size.TryGetInt64(out var value)
            ? value
            : null;

    [JsonIgnore]
    public double? Bpm =>
        GetAnalysisNumber("bpm") ??
        GetAnalysisNumber("tempo_bpm") ??
        GetAnalysisNumber("tempo");

    [JsonIgnore]
    public double? DurationSeconds =>
        GetAnalysisNumber("duration_s") ??
        GetAnalysisNumber("duration") ??
        GetTopLevelAnalysisNumber("duration_s") ??
        GetTopLevelAnalysisNumber("duration");

    [JsonIgnore]
    public int SectionCount =>
        TryGetMetaObject("analysis", out var analysis) &&
        analysis.TryGetProperty("sections", out var sections) &&
        sections.ValueKind == JsonValueKind.Array
            ? sections.GetArrayLength()
            : 0;

    [JsonIgnore]
    public string TranscriptStatus
    {
        get
        {
            if (!TryGetMetaObject("analysis", out var analysis) ||
                !analysis.TryGetProperty("transcript", out var transcript) ||
                transcript.ValueKind is not (JsonValueKind.Object or JsonValueKind.String))
            {
                return "Waiting for analysis";
            }

            if (transcript.ValueKind == JsonValueKind.String)
            {
                return string.IsNullOrWhiteSpace(transcript.GetString()) ? "Audio-only analysis" : "Transcript ready";
            }

            if (transcript.TryGetProperty("text", out var text) && !string.IsNullOrWhiteSpace(text.GetString()))
            {
                return "Transcript ready";
            }

            if (transcript.TryGetProperty("note", out var note) && !string.IsNullOrWhiteSpace(note.GetString()))
            {
                return note.GetString()!;
            }

            if (transcript.TryGetProperty("error", out var error) && !string.IsNullOrWhiteSpace(error.GetString()))
            {
                return "Transcription failed; audio analysis is still available";
            }

            return HasAnalysis ? "Audio-only analysis" : "Waiting for analysis";
        }
    }

    [JsonIgnore]
    public IReadOnlyList<PlanVariantDto> PlanVariants
    {
        get
        {
            if (!TryGetMetaObject("last_plan", out var plan) ||
                !plan.TryGetProperty("variants", out var variants) ||
                variants.ValueKind != JsonValueKind.Array)
            {
                return [];
            }

            return JsonSerializer.Deserialize(
                variants.GetRawText(),
                StudioJson.GetTypeInfo<List<PlanVariantDto>>()) ?? [];
        }
    }

    private bool TryGetMetaObject(string propertyName, out JsonElement value)
    {
        value = default;
        return Meta.ValueKind == JsonValueKind.Object &&
               Meta.TryGetProperty(propertyName, out value) &&
               value.ValueKind == JsonValueKind.Object &&
               value.EnumerateObject().Any();
    }

    private double? GetAnalysisNumber(string propertyName)
    {
        if (!TryGetMetaObject("analysis", out var analysis) ||
            !analysis.TryGetProperty("features", out var features) ||
            features.ValueKind != JsonValueKind.Object ||
            !features.TryGetProperty(propertyName, out var value) ||
            !value.TryGetDouble(out var number))
        {
            return null;
        }

        return number;
    }

    private double? GetTopLevelAnalysisNumber(string propertyName)
    {
        return TryGetMetaObject("analysis", out var analysis) &&
               analysis.TryGetProperty(propertyName, out var value) &&
               value.TryGetDouble(out var number)
            ? number
            : null;
    }
}

public sealed record CreateProjectRequest(
    [property: JsonPropertyName("name")] string Name);

public sealed record PlanRequest(
    [property: JsonPropertyName("title")] string? Title,
    [property: JsonPropertyName("user_notes")] string? UserNotes,
    [property: JsonPropertyName("style_prefs")] string? StylePreferences,
    [property: JsonPropertyName("num_variants")] int NumberOfVariants = 3,
    [property: JsonPropertyName("max_scenes")] int MaximumScenes = 12);

public sealed class AnalysisResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("analysis")]
    public JsonElement Analysis { get; init; }
}

public sealed class PlanDto
{
    [JsonPropertyName("source")]
    public string Source { get; init; } = string.Empty;

    [JsonPropertyName("duration_s")]
    public double? DurationSeconds { get; init; }

    [JsonPropertyName("variants")]
    public List<PlanVariantDto> Variants { get; init; } = [];

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? AdditionalData { get; set; }
}

public sealed class PlanVariantDto
{
    [JsonPropertyName("index")]
    public int? Index { get; init; }

    [JsonPropertyName("name")]
    public string? Name { get; init; }

    [JsonPropertyName("logline")]
    public string? Logline { get; init; }

    [JsonPropertyName("duration_s")]
    public double? DurationSeconds { get; init; }

    [JsonPropertyName("scenes")]
    public List<PlanSceneDto> Scenes { get; init; } = [];

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? AdditionalData { get; set; }

    [JsonIgnore]
    public string DisplayName => !string.IsNullOrWhiteSpace(Name) ? Name! : $"Variant {(Index ?? 0) + 1}";

    [JsonIgnore]
    public int SceneCount => Scenes.Count;
}

public sealed class PlanSceneDto
{
    [JsonPropertyName("start_s")]
    public double StartSeconds { get; init; }

    [JsonPropertyName("end_s")]
    public double EndSeconds { get; init; }

    [JsonPropertyName("prompt")]
    public string Prompt { get; init; } = string.Empty;

    [JsonPropertyName("negative_prompt")]
    public string? NegativePrompt { get; init; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? AdditionalData { get; set; }
}

public sealed record StudioJobListResponse(
    [property: JsonPropertyName("jobs")] IReadOnlyList<StudioJob> Jobs);

public sealed record StudioJobActionResponse(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("job")] StudioJob Job);

public sealed record StudioJob(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("project_id")] string ProjectId,
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("created_at")] string? CreatedAt,
    [property: JsonPropertyName("updated_at")] string? UpdatedAt,
    [property: JsonPropertyName("started_at")] string? StartedAt,
    [property: JsonPropertyName("finished_at")] string? FinishedAt,
    [property: JsonPropertyName("error")] string? Error,
    [property: JsonPropertyName("progress")] StudioJobProgress? Progress,
    [property: JsonPropertyName("result")] JsonElement? Result,
    [property: JsonPropertyName("payload")] JsonElement? Payload,
    [property: JsonPropertyName("attempt")] int Attempt = 0)
{
    public bool IsActive => Status is "queued" or "paused" or "running";

    public bool CanPause => Status == "queued";

    public bool CanResume => Status == "paused";

    public bool CanCancel => IsActive;

    public bool CanRetry => Status is "succeeded" or "failed" or "canceled";
}

public sealed record StudioJobProgress(
    [property: JsonPropertyName("percent")] double? Percent,
    [property: JsonPropertyName("stage")] string? Stage,
    [property: JsonPropertyName("message")] string? Message,
    [property: JsonPropertyName("current")] double? Current,
    [property: JsonPropertyName("total")] double? Total);

public sealed record TimelineUpdateRequest(
    [property: JsonPropertyName("timeline")] JsonElement Timeline);

public sealed record TimelineAutosaveRequest(
    [property: JsonPropertyName("timeline")] JsonElement Timeline,
    [property: JsonPropertyName("meta")] JsonElement? Metadata = null,
    [property: JsonPropertyName("reason")] string? Reason = null);

public sealed record RecoveryApplyRequest(
    [property: JsonPropertyName("source")] string Source = "journal",
    [property: JsonPropertyName("snapshot_name")] string? SnapshotName = null);

public static class StudioJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    public static readonly StudioJsonContext Context = new(Options);

    public static JsonTypeInfo<T> GetTypeInfo<T>()
        => Context.GetTypeInfo(typeof(T)) as JsonTypeInfo<T>
           ?? throw new InvalidOperationException(
               $"JSON metadata is not registered for {typeof(T).FullName}.");
}

[JsonSourceGenerationOptions(GenerationMode = JsonSourceGenerationMode.Metadata)]
[JsonSerializable(typeof(HealthResponse))]
[JsonSerializable(typeof(ProjectListResponse))]
[JsonSerializable(typeof(ProjectResponse))]
[JsonSerializable(typeof(CreateProjectRequest))]
[JsonSerializable(typeof(AnalysisResponse))]
[JsonSerializable(typeof(PlanRequest))]
[JsonSerializable(typeof(PlanDto))]
[JsonSerializable(typeof(List<PlanVariantDto>))]
[JsonSerializable(typeof(StudioJobListResponse))]
[JsonSerializable(typeof(StudioJobActionResponse))]
[JsonSerializable(typeof(StudioJob))]
[JsonSerializable(typeof(TimelineUpdateRequest))]
[JsonSerializable(typeof(TimelineAutosaveRequest))]
[JsonSerializable(typeof(RecoveryApplyRequest))]
public sealed partial class StudioJsonContext : JsonSerializerContext;
