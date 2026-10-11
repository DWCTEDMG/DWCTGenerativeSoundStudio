using EdmgStudio.Core.Models;
using System.Text.Json;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ExecutionPlaneTests
{
  [TestMethod]
  public void HybridVideo_SourceGeneratedContractPreservesBackupAndEngineSelection()
  {
    HybridVideoSettings settings = new()
    {
      Remote = new() { Enabled = true, Host = "100.1.2.3", Port = 2200, IdentityFile = "C:\\Keys\\vast" },
      WslBackup = new() { Enabled = true, Distro = "Ubuntu", Python = "/venv/bin/python" },
      Engines = ["hunyuan_video15"], AllowLocalFallback = false
    };
    string json = JsonSerializer.Serialize(settings, StudioJson.GetTypeInfo<HybridVideoSettings>());
    HybridVideoSettings parsed = JsonSerializer.Deserialize(json, StudioJson.GetTypeInfo<HybridVideoSettings>())!;
    Assert.AreEqual(2200, parsed.Remote.Port);
    Assert.AreEqual("C:\\Keys\\vast", parsed.Remote.IdentityFile);
    Assert.AreEqual("/venv/bin/python", parsed.WslBackup.Python);
    CollectionAssert.AreEqual(new[] { "hunyuan_video15" }, parsed.Engines);
    Assert.IsFalse(parsed.AllowLocalFallback);
  }

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
    ExecutionInventory installed = new() { Wsl = new() { Readiness = new() { ModelInstalled = true } } };
    ExecutionInventory qualified = new() { Wsl = new() { Readiness = new() { RuntimeQualified = true } } };
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
