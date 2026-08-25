using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class RenderRuntimeCapabilitiesTests
{
    [TestMethod]
    public void Evaluate_ProjectsActiveRtxCudaWithoutOverstatingRuntimeUse()
    {
        using JsonDocument document = JsonDocument.Parse(
            """
            {
              "backend": "cuda",
              "device_name": "NVIDIA GeForce RTX 4050 Laptop GPU",
              "available_backends": ["cpu", "cuda"],
              "vram_gb": 6,
              "cuda_runtime_ready": true,
              "cuda_enabled": true,
              "cuda_tf32_enabled": true,
              "recommended_tier": "balanced"
            }
            """);
        var catalogue = new ModelCatalogueResponse
        {
            TensorRtMigration = CreateTensorRtStatus(rendererReady: true),
        };

        RenderRuntimeCapabilities result = RenderRuntimeCapabilities.Evaluate(
            document.RootElement,
            catalogue);

        Assert.IsTrue(result.CudaActive);
        Assert.IsTrue(result.RtxClassDevice);
        Assert.IsTrue(result.TensorRtRendererReady);
        StringAssert.Contains(result.AcceleratorSummary, "RTX 4050");
        StringAssert.Contains(result.CudaSummary, "TF32 enabled");
        StringAssert.Contains(result.TensorCoreSummary, "depends on the selected model and engine");
        StringAssert.Contains(result.TensorRtSummary, "installed and verified");
        StringAssert.Contains(result.TritonSummary, "backend-managed");
    }

    [TestMethod]
    public void Evaluate_ReportsAvailableButDisabledCudaTruthfully()
    {
        using JsonDocument document = JsonDocument.Parse(
            """
            {
              "backend": "cpu",
              "device_name": "CPU",
              "available_backends": ["cpu", "cuda"],
              "cuda_runtime_ready": true,
              "cuda_enabled": false,
              "cuda_device_name": "NVIDIA RTX 3060",
              "cuda_vram_gb": "12"
            }
            """);

        RenderRuntimeCapabilities result = RenderRuntimeCapabilities.Evaluate(document.RootElement);

        Assert.IsFalse(result.CudaActive);
        Assert.IsTrue(result.CudaRuntimeReady);
        Assert.AreEqual(12, result.VramGb);
        StringAssert.Contains(result.CudaSummary, "disabled");
        StringAssert.Contains(result.TensorRtSummary, "waiting");
    }

    [TestMethod]
    public void Evaluate_UnwrapsHardwareApiEnvelope()
    {
        using JsonDocument document = JsonDocument.Parse(
            """
            {
              "ok": true,
              "hardware": {
                "backend": "cuda",
                "device_name": "NVIDIA GeForce RTX 4050 Laptop GPU",
                "available_backends": ["cpu", "cuda"],
                "vram_gb": 6,
                "cuda_runtime_ready": true,
                "cuda_enabled": true,
                "recommended_tier": "balanced"
              },
              "render_tier_plan": {
                "recommended": "balanced"
              }
            }
            """);

        RenderRuntimeCapabilities result = RenderRuntimeCapabilities.Evaluate(document.RootElement);

        Assert.AreEqual("cuda", result.Backend);
        Assert.IsTrue(result.CudaActive);
        Assert.IsTrue(result.RtxClassDevice);
        Assert.AreEqual(6, result.VramGb);
        StringAssert.Contains(result.AcceleratorSummary, "RTX 4050");
    }

    [TestMethod]
    public void Evaluate_DistinguishesRtxHardwareFromUnavailableCudaExecution()
    {
        using JsonDocument document = JsonDocument.Parse(
            """
            {
              "backend": "cpu",
              "device_name": "NVIDIA GeForce RTX 4050 Laptop GPU",
              "cuda_runtime_ready": false,
              "cuda_enabled": true
            }
            """);

        RenderRuntimeCapabilities result = RenderRuntimeCapabilities.Evaluate(document.RootElement);

        Assert.IsTrue(result.RtxClassDevice);
        Assert.IsFalse(result.CudaRuntimeReady);
        StringAssert.Contains(result.TensorCoreSummary, "hardware detected");
        StringAssert.Contains(result.TensorCoreSummary, "CUDA execution is unavailable");
    }

    [TestMethod]
    public void Evaluate_RejectsNonObjectHardwarePayload()
    {
        using JsonDocument document = JsonDocument.Parse("[]");

        Assert.ThrowsExactly<ArgumentException>(() =>
            RenderRuntimeCapabilities.Evaluate(document.RootElement));
    }

    private static TensorRtMigrationStatus CreateTensorRtStatus(bool rendererReady) =>
        new(
            1,
            "local_sd15_tensorrt_bundle",
            new TensorRtLegacyStatus(false, "missing", 0, 0, [], [], []),
            new TensorRtCanonicalStatus(rendererReady, rendererReady, rendererReady ? [] : ["missing"]),
            new TensorRtMigrationAvailability(
                false,
                null,
                true,
                true,
                new TensorRtDiskStatus(0, 0, 0, 0, true)));
}
