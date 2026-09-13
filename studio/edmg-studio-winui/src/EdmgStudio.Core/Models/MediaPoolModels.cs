using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed class MediaPoolResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("assets")]
    public List<MediaPoolAsset> Assets { get; init; } = [];
}

public sealed class MediaPoolActionResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("cached")]
    public bool Cached { get; init; }

    [JsonPropertyName("asset")]
    public required MediaPoolAsset Asset { get; init; }

    [JsonPropertyName("derivative")]
    public MediaDerivative? Derivative { get; init; }
}

public sealed class MediaPoolAsset
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    [JsonPropertyName("display_name")]
    public string DisplayName { get; init; } = string.Empty;

    [JsonPropertyName("original_filename")]
    public string OriginalFilename { get; init; } = string.Empty;

    [JsonPropertyName("path")]
    public string Path { get; init; } = string.Empty;

    [JsonPropertyName("kind")]
    public string Kind { get; init; } = string.Empty;

    [JsonPropertyName("content_type")]
    public string ContentType { get; init; } = string.Empty;

    [JsonPropertyName("size_bytes")]
    public long SizeBytes { get; init; }

    [JsonPropertyName("sha256")]
    public string Sha256 { get; init; } = string.Empty;

    [JsonPropertyName("status")]
    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("missing")]
    public bool Missing { get; init; }

    [JsonPropertyName("probe")]
    public JsonElement Probe { get; init; }

    [JsonPropertyName("derivatives")]
    public Dictionary<string, MediaDerivative> Derivatives { get; init; } = [];
}

public sealed class MediaDerivative
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("path")]
    public string? Path { get; init; }

    [JsonPropertyName("cache_key")]
    public string? CacheKey { get; init; }

    [JsonPropertyName("error")]
    public string? Error { get; init; }
}

public sealed record MediaWaveformRequest(
    [property: JsonPropertyName("bins")] int Bins);

public sealed record MediaThumbnailRequest(
    [property: JsonPropertyName("width")] int Width);

public sealed record MediaProxyRequest(
    [property: JsonPropertyName("width")] int Width);
