using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed class RenderCapabilityEvidence
{
    [JsonPropertyName("ready")]
    public bool Ready { get; init; }

    [JsonPropertyName("route")]
    public string Route { get; init; } = string.Empty;

    [JsonPropertyName("renderer")]
    public string Renderer { get; init; } = string.Empty;

    [JsonPropertyName("model_id")]
    public string? ModelId { get; init; }

    [JsonPropertyName("device")]
    public string? Device { get; init; }

    [JsonPropertyName("capability_level")]
    public int CapabilityLevel { get; init; }

    [JsonPropertyName("evidence_receipt")]
    public string? EvidenceReceipt { get; init; }

    [JsonPropertyName("fallback_policy")]
    public string FallbackPolicy { get; init; } = string.Empty;

    [JsonPropertyName("blockers")]
    public IReadOnlyList<string> Blockers { get; init; } = [];

    [JsonPropertyName("warnings")]
    public IReadOnlyList<string> Warnings { get; init; } = [];

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

public sealed class InternalRenderPreflightResponse
{
    [JsonPropertyName("qualification")]
    public RenderCapabilityEvidence Qualification { get; init; } = new();

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}
