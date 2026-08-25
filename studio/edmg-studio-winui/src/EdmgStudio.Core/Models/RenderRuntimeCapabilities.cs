using System.Globalization;
using System.Text.Json;

namespace EdmgStudio.Core.Models;

/// <summary>
/// User-facing projection of the backend's render hardware report. The backend remains the
/// authority; this type deliberately avoids inferring that an installed runtime is active for
/// every model or render path.
/// </summary>
public sealed record RenderRuntimeCapabilities(
    string Backend,
    string DeviceName,
    double VramGb,
    string RecommendedTier,
    bool CudaRuntimeReady,
    bool CudaEnabled,
    bool CudaActive,
    bool Tf32Enabled,
    bool RtxClassDevice,
    bool? TensorRtRendererReady,
    bool? TritonRuntimeReady)
{
    public string AcceleratorSummary =>
        $"{Backend.ToUpperInvariant()} · {DeviceName} · "
        + (VramGb > 0 ? $"{VramGb:0.##} GB VRAM" : "VRAM not reported");

    public string CudaSummary => CudaRuntimeReady switch
    {
        false => "CUDA runtime is not available; CPU or another configured backend remains usable.",
        true when !CudaEnabled => "CUDA is installed but disabled in Studio render settings.",
        true when CudaActive =>
            $"CUDA is active{(Tf32Enabled ? " with TF32 enabled" : string.Empty)}. Recommended tier: {RecommendedTier}.",
        _ => "CUDA is available but is not the active automatic render backend.",
    };

    public string TensorCoreSummary => RtxClassDevice switch
    {
        false => "RTX Tensor Core hardware was not confirmed by the backend device report.",
        true when !CudaRuntimeReady =>
            "RTX Tensor Core hardware detected, but CUDA execution is unavailable until the CUDA runtime is ready.",
        _ => "RTX Tensor Core hardware detected. Actual Tensor Core use depends on the selected model and engine.",
    };

    public string TensorRtSummary => TensorRtRendererReady switch
    {
        true => "TensorRT SD 1.5 keyframe renderer is installed and verified.",
        false => "TensorRT runtime bundle is not ready; install or repair it from Models.",
        null => "TensorRT readiness is waiting for the model catalogue.",
    };

    public string TritonSummary => TritonRuntimeReady switch
    {
        true => "Triton runtime is available for compatible backend model paths.",
        false => "Triton runtime was explicitly reported unavailable.",
        null => "Triton is backend-managed and has no independent Studio render switch.",
    };

    public static RenderRuntimeCapabilities Evaluate(
        JsonElement hardware,
        ModelCatalogueResponse? catalogue = null)
    {
        if (hardware.ValueKind != JsonValueKind.Object)
        {
            throw new ArgumentException("Hardware capabilities must be a JSON object.", nameof(hardware));
        }

        // /v1/hardware returns an envelope so it can include the render-tier plan next to the
        // device report. Accept either that public response shape or the device object itself;
        // callers such as tests and cached profiles may legitimately provide the latter.
        if (hardware.TryGetProperty("hardware", out JsonElement nestedHardware)
            && nestedHardware.ValueKind == JsonValueKind.Object)
        {
            hardware = nestedHardware;
        }

        string backend = ReadString(hardware, "backend") ?? "cpu";
        string deviceName = ReadString(hardware, "cuda_device_name")
            ?? ReadString(hardware, "device_name")
            ?? backend.ToUpperInvariant();
        double vramGb = ReadNumber(hardware, "cuda_vram_gb")
            ?? ReadNumber(hardware, "vram_gb")
            ?? 0;
        bool cudaRuntimeReady = ReadBoolean(hardware, "cuda_runtime_ready")
            ?? HasBackend(hardware, "cuda")
            ?? backend.Equals("cuda", StringComparison.OrdinalIgnoreCase);
        bool cudaEnabled = ReadBoolean(hardware, "cuda_enabled") ?? true;
        bool cudaActive = cudaRuntimeReady
            && cudaEnabled
            && backend.Equals("cuda", StringComparison.OrdinalIgnoreCase);
        bool tf32Enabled = ReadBoolean(hardware, "cuda_tf32_enabled") ?? false;
        bool rtxClassDevice = deviceName.Contains("RTX", StringComparison.OrdinalIgnoreCase);
        bool? tensorRtReady = catalogue?.TensorRtMigration?.Canonical.RendererReady;
        bool? tritonReady = ReadBoolean(hardware, "triton_runtime_ready")
            ?? ReadBoolean(hardware, "triton_available");

        return new RenderRuntimeCapabilities(
            backend,
            deviceName,
            Math.Max(0, vramGb),
            ReadString(hardware, "recommended_tier") ?? "draft",
            cudaRuntimeReady,
            cudaEnabled,
            cudaActive,
            tf32Enabled,
            rtxClassDevice,
            tensorRtReady,
            tritonReady);
    }

    private static string? ReadString(JsonElement source, string propertyName)
    {
        if (!source.TryGetProperty(propertyName, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String
            ? value.GetString()?.Trim()
            : null;
    }

    private static bool? ReadBoolean(JsonElement source, string propertyName)
    {
        if (!source.TryGetProperty(propertyName, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.String when bool.TryParse(value.GetString(), out bool parsed) => parsed,
            _ => null,
        };
    }

    private static double? ReadNumber(JsonElement source, string propertyName)
    {
        if (!source.TryGetProperty(propertyName, out JsonElement value))
        {
            return null;
        }

        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out double number))
        {
            return double.IsFinite(number) ? number : null;
        }

        return value.ValueKind == JsonValueKind.String
            && double.TryParse(value.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out number)
            && double.IsFinite(number)
                ? number
                : null;
    }

    private static bool? HasBackend(JsonElement source, string backend)
    {
        if (!source.TryGetProperty("available_backends", out JsonElement values)
            || values.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        return values.EnumerateArray().Any(value =>
            value.ValueKind == JsonValueKind.String
            && string.Equals(value.GetString(), backend, StringComparison.OrdinalIgnoreCase));
    }
}
