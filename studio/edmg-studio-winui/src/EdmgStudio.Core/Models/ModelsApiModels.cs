using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed class ModelCatalogueResponse
{
    [JsonPropertyName("catalog")]
    public IReadOnlyList<ModelCatalogueEntry>? Catalog { get; set; }

    [JsonPropertyName("user")]
    public IReadOnlyList<ModelCatalogueEntry>? User { get; set; }

    [JsonPropertyName("packs")]
    public IReadOnlyList<ModelPackEntry>? Packs { get; set; }

    [JsonPropertyName("accepted")]
    public IReadOnlyDictionary<string, JsonElement>? Accepted { get; set; }

    [JsonPropertyName("installed")]
    public IReadOnlyDictionary<string, JsonElement>? Installed { get; set; }

    [JsonPropertyName("cloud")]
    public JsonElement Cloud { get; set; }

    [JsonPropertyName("lanes")]
    public JsonElement Lanes { get; set; }

    [JsonPropertyName("storage_mode")]
    public string? StorageMode { get; set; }

    [JsonPropertyName("model_cache")]
    public string? ModelCache { get; set; }

    [JsonPropertyName("tensorrt_migration")]
    public TensorRtMigrationStatus? TensorRtMigration { get; set; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

public sealed class ModelCatalogueEntry
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("kind")]
    public string? Kind { get; set; }

    [JsonPropertyName("source")]
    public string? Source { get; set; }

    [JsonPropertyName("license_id")]
    public string? LicenseId { get; set; }

    [JsonPropertyName("license_name")]
    public string? LicenseName { get; set; }

    [JsonPropertyName("license_url")]
    public string? LicenseUrl { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("path")]
    public string? Path { get; set; }

    [JsonPropertyName("installed")]
    public bool Installed { get; set; }

    [JsonPropertyName("available")]
    public bool Available { get; set; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

public sealed class ModelPackEntry
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("models")]
    public IReadOnlyList<string>? Models { get; set; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

public sealed record ModelTask(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("progress")] double? Progress,
    [property: JsonPropertyName("last_log")] string? LastLog,
    [property: JsonPropertyName("error")] string? Error,
    [property: JsonPropertyName("started_at")] double? StartedAt,
    [property: JsonPropertyName("ended_at")] double? EndedAt,
    [property: JsonPropertyName("model_id")] string? ModelId,
    [property: JsonPropertyName("stage")] string? Stage,
    [property: JsonPropertyName("bytes_completed")] long BytesCompleted,
    [property: JsonPropertyName("bytes_total")] long? BytesTotal,
    [property: JsonPropertyName("files_completed")] int FilesCompleted,
    [property: JsonPropertyName("files_total")] int? FilesTotal,
    [property: JsonPropertyName("cancel_requested")] bool CancelRequested)
{
    public bool IsActive =>
        string.Equals(Status, "queued", StringComparison.OrdinalIgnoreCase)
        || string.Equals(Status, "running", StringComparison.OrdinalIgnoreCase);

    public double ClampedProgress => Math.Clamp(Progress ?? 0, 0, 1);

    public bool HasProgress => Progress.HasValue;

    public string DisplayStage =>
        !string.IsNullOrWhiteSpace(Stage) ? Stage :
        !string.IsNullOrWhiteSpace(LastLog) ? LastLog :
        Status;

    public static string Fingerprint(IEnumerable<ModelTask> tasks) =>
        string.Join("|", tasks.Select(task => $"{task.Id}:{task.Status}"));
}

public sealed record ModelTaskListResponse(
    [property: JsonPropertyName("tasks")] IReadOnlyList<ModelTask>? Tasks);

public sealed record ModelTaskActionResponse(
    [property: JsonPropertyName("task")] ModelTask Task);

public sealed record ModelBenchmarkRequest(
    [property: JsonPropertyName("model_id")] string ModelId,
    [property: JsonPropertyName("summary")] string Summary,
    [property: JsonPropertyName("passed")] bool Passed,
    [property: JsonPropertyName("metrics")] IReadOnlyDictionary<string, string> Metrics);

public sealed record ModelBenchmarkResponse(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("benchmark")] JsonElement Benchmark);

public sealed record CivitaiImportRequest(
    [property: JsonPropertyName("url")] string Url);

public sealed record LocalModelImportRequest(
    [property: JsonPropertyName("file_path")] string FilePath,
    [property: JsonPropertyName("folder")] string Folder,
    [property: JsonPropertyName("name")] string? Name = null);

public sealed record ModelImportResponse(
    [property: JsonPropertyName("entry")] JsonElement Entry);

public sealed record TensorRtCancelImportRequest(
    [property: JsonPropertyName("task_id")] string TaskId);

public sealed record TensorRtMigrationStatus(
    [property: JsonPropertyName("schema_version")] int SchemaVersion,
    [property: JsonPropertyName("model_id")] string ModelId,
    [property: JsonPropertyName("legacy")] TensorRtLegacyStatus Legacy,
    [property: JsonPropertyName("canonical")] TensorRtCanonicalStatus Canonical,
    [property: JsonPropertyName("migration")] TensorRtMigrationAvailability Migration);

public sealed record TensorRtLegacyStatus(
    [property: JsonPropertyName("detected")] bool Detected,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("usable_file_count")] int UsableFileCount,
    [property: JsonPropertyName("total_bytes")] long TotalBytes,
    [property: JsonPropertyName("files")] IReadOnlyList<TensorRtLegacyFile>? Files,
    [property: JsonPropertyName("missing_roles")] IReadOnlyList<string>? MissingRoles,
    [property: JsonPropertyName("unusable_roles")] IReadOnlyList<string>? UnusableRoles);

public sealed record TensorRtLegacyFile(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("name")] string? Name,
    [property: JsonPropertyName("present")] bool Present,
    [property: JsonPropertyName("non_empty")] bool NonEmpty,
    [property: JsonPropertyName("safe_regular_file")] bool SafeRegularFile,
    [property: JsonPropertyName("size_bytes")] long SizeBytes,
    [property: JsonPropertyName("sha256")] string? Sha256);

public sealed record TensorRtCanonicalStatus(
    [property: JsonPropertyName("exists")] bool Exists,
    [property: JsonPropertyName("renderer_ready")] bool RendererReady,
    [property: JsonPropertyName("gaps")] IReadOnlyList<string>? Gaps);

public sealed record TensorRtMigrationAvailability(
    [property: JsonPropertyName("available")] bool Available,
    [property: JsonPropertyName("blocked_reason")] string? BlockedReason,
    [property: JsonPropertyName("copy_only")] bool CopyOnly,
    [property: JsonPropertyName("source_will_be_preserved")] bool SourceWillBePreserved,
    [property: JsonPropertyName("disk")] TensorRtDiskStatus Disk);

public sealed record TensorRtDiskStatus(
    [property: JsonPropertyName("source_bytes")] long SourceBytes,
    [property: JsonPropertyName("safety_bytes")] long SafetyBytes,
    [property: JsonPropertyName("required_free_bytes")] long RequiredFreeBytes,
    [property: JsonPropertyName("available_free_bytes")] long? AvailableFreeBytes,
    [property: JsonPropertyName("enough_space")] bool EnoughSpace);
