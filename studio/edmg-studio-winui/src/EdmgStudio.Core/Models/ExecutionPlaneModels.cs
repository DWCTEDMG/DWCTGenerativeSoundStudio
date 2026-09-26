using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed record ExecutionProfile
{
    [JsonPropertyName("runtime_profile")] public string RuntimeProfile { get; init; } = "standard";
    [JsonPropertyName("model_environment_preferences")] public Dictionary<string, string> ModelEnvironmentPreferences { get; init; } = [];
}

public sealed record ExecutionPreference
{
    [JsonPropertyName("environment")] public string Environment { get; init; } = "auto";
    [JsonPropertyName("gpu_device_id"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] public string? GpuDeviceId { get; init; }
    [JsonPropertyName("allow_environment_fallback")] public bool AllowEnvironmentFallback { get; init; } = true;
}

public sealed record ExecutionReadiness
{
    [JsonPropertyName("wsl_installed")] public bool WslInstalled { get; init; }
    [JsonPropertyName("distribution_running")] public bool DistributionRunning { get; init; }
    [JsonPropertyName("worker_environment_present")] public bool WorkerEnvironmentPresent { get; init; }
    [JsonPropertyName("gpu_visible")] public bool GpuVisible { get; init; }
    [JsonPropertyName("model_installed")] public bool ModelInstalled { get; init; }
    [JsonPropertyName("worker_launchable")] public bool WorkerLaunchable { get; init; }
    [JsonPropertyName("generation_started")] public bool GenerationStarted { get; init; }
    [JsonPropertyName("artifact_validated")] public bool ArtifactValidated { get; init; }
    [JsonPropertyName("runtime_qualified")] public bool RuntimeQualified { get; init; }
}

public sealed record ExecutionWslStatus
{
    [JsonPropertyName("configured")] public bool Configured { get; init; }
    [JsonPropertyName("distribution")] public string? Distribution { get; init; }
    [JsonPropertyName("readiness")] public ExecutionReadiness Readiness { get; init; } = new();
}

public sealed record ExecutionBlocker
{
    [JsonPropertyName("code")] public string Code { get; init; } = "";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
}

public sealed record ExecutionInventory
{
    [JsonPropertyName("wsl")] public ExecutionWslStatus Wsl { get; init; } = new();
    [JsonPropertyName("physical_gpus")] public JsonElement[] PhysicalGpus { get; init; } = [];
    [JsonPropertyName("blockers")] public ExecutionBlocker[] Blockers { get; init; } = [];
    [JsonPropertyName("probe_performed")] public bool ProbePerformed { get; init; }
}
