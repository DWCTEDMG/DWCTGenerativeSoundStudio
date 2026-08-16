using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed record ModelCatalogueResponse(
    [property: JsonPropertyName("catalog")] IReadOnlyList<ModelCatalogueEntry>? Catalog,
    [property: JsonPropertyName("user")] IReadOnlyList<ModelCatalogueEntry>? User,
    [property: JsonPropertyName("packs")] IReadOnlyList<ModelPackEntry>? Packs,
    [property: JsonPropertyName("accepted")] IReadOnlyDictionary<string, JsonElement>? Accepted,
    [property: JsonPropertyName("installed")] IReadOnlyDictionary<string, JsonElement>? Installed,
    [property: JsonPropertyName("cloud")] JsonElement Cloud,
    [property: JsonPropertyName("lanes")] JsonElement Lanes,
    [property: JsonPropertyName("storage_mode")] string? StorageMode,
    [property: JsonPropertyName("model_cache")] string? ModelCache,
    [property: JsonPropertyName("tensorrt_migration")] TensorRtMigrationStatus? TensorRtMigration)
{
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; init; }
}

public sealed record ModelCatalogueEntry(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string? Name,
    [property: JsonPropertyName("kind")] string? Kind,
    [property: JsonPropertyName("source")] string? Source,
    [property: JsonPropertyName("license_id")] string? LicenseId,
    [property: JsonPropertyName("license_name")] string? LicenseName,
    [property: JsonPropertyName("license_url")] string? LicenseUrl,
    [property: JsonPropertyName("description")] string? Description,
    [property: JsonPropertyName("path")] string? Path,
    [property: JsonPropertyName("installed")] bool Installed,
    [property: JsonPropertyName("available")] bool Available)
{
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; init; }
}

public sealed record ModelPackEntry(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string? Name,
    [property: JsonPropertyName("models")] IReadOnlyList<string>? Models)
{
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; init; }
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
