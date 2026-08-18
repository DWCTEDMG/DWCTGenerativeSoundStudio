using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed class SetupStatusResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("ai_config")]
    public JsonElement AiConfig { get; init; }

    [JsonPropertyName("toolchain")]
    public JsonElement Toolchain { get; init; }

    [JsonPropertyName("backend_bundle")]
    public JsonElement BackendBundle { get; init; }

    [JsonPropertyName("ollama")]
    public JsonElement Ollama { get; init; }

    [JsonPropertyName("comfyui")]
    public JsonElement ComfyUi { get; init; }

    [JsonPropertyName("ffmpeg")]
    public JsonElement Ffmpeg { get; init; }

    [JsonPropertyName("edmg")]
    public JsonElement Edmg { get; init; }

    [JsonPropertyName("sevenzip")]
    public JsonElement SevenZip { get; init; }

    [JsonPropertyName("hardware")]
    public JsonElement Hardware { get; init; }

    [JsonPropertyName("system_readiness")]
    public JsonElement SystemReadiness { get; init; }

    [JsonPropertyName("tasks")]
    public List<SetupTaskDto> Tasks { get; init; } = [];

    [JsonPropertyName("status_cache")]
    public SetupStatusCache? StatusCache { get; init; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? AdditionalData { get; set; }
}

public sealed record SetupStatusCache(
    [property: JsonPropertyName("cached")] bool Cached,
    [property: JsonPropertyName("age_seconds")] double AgeSeconds,
    [property: JsonPropertyName("ttl_seconds")] double TtlSeconds);

public sealed class SetupTaskDto
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("status")]
    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("progress")]
    public double? Progress { get; init; }

    [JsonPropertyName("last_log")]
    public string? LastLog { get; init; }

    [JsonPropertyName("error")]
    public string? Error { get; init; }

    [JsonPropertyName("started_at")]
    public double? StartedAt { get; init; }

    [JsonPropertyName("ended_at")]
    public double? EndedAt { get; init; }

    [JsonPropertyName("cancel_requested")]
    public bool CancelRequested { get; init; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? AdditionalData { get; set; }

    [JsonIgnore]
    public bool IsActive => Status is "queued" or "running";
}

public sealed record SetupTaskListResponse(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("active")] bool Active,
    [property: JsonPropertyName("tasks")] IReadOnlyList<SetupTaskDto> Tasks);

public sealed record SetupTaskActionResponse(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("task")] SetupTaskDto Task);

public sealed record SetupOperationResponse(
    [property: JsonPropertyName("ok")] bool Ok);

public sealed record SetupOllamaPullRequest(
    [property: JsonPropertyName("model")] string Model = "qwen3:8b");

public sealed record SetupProfileRequest(
    [property: JsonPropertyName("accelerator_profile")] string AcceleratorProfile = "cpu");

public sealed record SetupFullInstallRequest(
    [property: JsonPropertyName("accelerator_profile")] string AcceleratorProfile = "cpu",
    [property: JsonPropertyName("comfy_port")] int ComfyPort = 8188,
    [property: JsonPropertyName("model")] string Model = "qwen3:8b");

public sealed record SetupComfyUiInstallRequest(
    [property: JsonPropertyName("flavor")] string Flavor = "cpu");

public sealed record SetupComfyUiStartRequest(
    [property: JsonPropertyName("flavor")] string Flavor = "auto",
    [property: JsonPropertyName("port")] int Port = 8188);

public sealed record SetupEdmgInstallRequest(
    [property: JsonPropertyName("mode")] string Mode = "standard",
    [property: JsonPropertyName("backend")] string Backend = "cpu");
