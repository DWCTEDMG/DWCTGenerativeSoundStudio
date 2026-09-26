using System.Text.Json;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ExecutionPlaneTests
{
    [TestMethod]
    public void Inventory_ParsesAdditiveBackendFields()
    {
        const string json = """{"wsl":{"configured":true,"distribution":"Ubuntu","readiness":{"wsl_installed":true,"distribution_running":true,"worker_environment_present":true,"gpu_visible":true,"model_installed":true,"worker_launchable":true,"generation_started":false,"artifact_validated":false,"runtime_qualified":false},"future":1},"physical_gpus":[],"blockers":[],"probe_performed":true,"future_root":true}""";
        ExecutionInventory inventory = JsonSerializer.Deserialize<ExecutionInventory>(json)!;
        Assert.AreEqual("Ubuntu", inventory.Wsl.Distribution);
        Assert.AreEqual("Worker launchable", ExecutionPlanePresentation.Describe(inventory).Title);
    }

    [TestMethod]
    public void Presentation_DistinguishesInstalledAndQualified()
    {
        var installed = new ExecutionInventory { Wsl = new() { Readiness = new() { ModelInstalled = true } } };
        var qualified = new ExecutionInventory { Wsl = new() { Readiness = new() { RuntimeQualified = true } } };
        Assert.AreEqual("Model installed", ExecutionPlanePresentation.Describe(installed).Title);
        Assert.AreEqual(ExecutionReadinessTone.Ready, ExecutionPlanePresentation.Describe(qualified).Tone);
    }

    [TestMethod]
    public void RequestPreference_IsOmittedByDefaultAndPreservesNoFallback()
    {
        JsonElement omitted = InternalVideoRenderRequestBuilder.Build(new());
        Assert.AreEqual(JsonValueKind.Null, omitted.GetProperty("execution_preference").ValueKind);
        JsonElement explicitWsl = InternalVideoRenderRequestBuilder.Build(new() { ExecutionPreference = new() { Environment = "wsl", AllowEnvironmentFallback = false } });
        Assert.AreEqual("wsl", explicitWsl.GetProperty("execution_preference").GetProperty("environment").GetString());
        Assert.IsFalse(explicitWsl.GetProperty("execution_preference").GetProperty("allow_environment_fallback").GetBoolean());
    }
}
