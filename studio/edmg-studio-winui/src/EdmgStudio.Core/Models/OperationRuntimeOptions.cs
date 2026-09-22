using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

/// <summary>Overrides for one render; null values inherit Studio settings.</summary>
public sealed record OperationRuntimeOptions
{
    [JsonPropertyName("mode")]
    public string? Mode { get; init; }
    [JsonPropertyName("enabled")]
    public bool? Enabled { get; init; }
    [JsonPropertyName("precision")]
    public string? Precision { get; init; }
    [JsonPropertyName("allow_fallback")]
    public bool? AllowFallback { get; init; }
    [JsonPropertyName("strict")]
    public bool? Strict { get; init; }
    [JsonPropertyName("device")]
    public int? Device { get; init; }
}
