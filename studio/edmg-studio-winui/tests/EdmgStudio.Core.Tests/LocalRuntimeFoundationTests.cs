using EdmgStudio.Core.Runtime;
using System.Net;
using System.Text;
using System.Text.Json;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class LocalRuntimeFoundationTests
{
  [TestMethod]
  public void GpuCsvParser_ParsesMultipleGpusAndTotals()
  {
    GpuTopology topology = GpuDiscoveryService.Parse("0, NVIDIA RTX 4090, 24564, 22000, 590.12\n1, NVIDIA RTX 4080, 16376, 12000, 590.12\n");

    Assert.IsTrue(topology.CudaAvailable);
    Assert.AreEqual(2, topology.GpuCount);
    Assert.AreEqual(40940L, topology.TotalMemoryMiB);
    Assert.AreEqual(34000L, topology.FreeMemoryMiB);
    Assert.AreEqual("NVIDIA RTX 4080", topology.Gpus[1].Name);
  }

  [TestMethod]
  public void GpuCsvParser_RejectsMalformedRows()
  {
    _ = Assert.ThrowsExactly<FormatException>(() => GpuDiscoveryService.Parse("0, incomplete"));
  }

  [TestMethod]
  public async Task GpuDiscovery_RetriesTransientWslStartupFailure()
  {
    TransientGpuRunner runner = new();
    GpuDiscoveryService discovery = new(runner, TimeSpan.Zero);

    GpuTopology topology = await discovery.DetectAsync();

    Assert.IsTrue(topology.CudaAvailable);
    Assert.AreEqual(1, topology.GpuCount);
    Assert.AreEqual(2, runner.CallCount);
  }

  [TestMethod]
  public async Task GpuDiscovery_WaitsForCudaDuringColdWslStartup()
  {
    DelayedGpuRunner runner = new(failuresBeforeReady: 6);
    GpuDiscoveryService discovery = new(runner, TimeSpan.Zero);

    GpuTopology topology = await discovery.DetectAsync();

    Assert.IsTrue(topology.CudaAvailable);
    Assert.AreEqual(3, topology.GpuCount);
    Assert.AreEqual(7, runner.CallCount);
  }

  [TestMethod]
  public void ProfileResolver_DefaultsToLlamaAndAllVisibleGpus()
  {
    GpuTopology topology = CreateTopology(2);
    ResolvedRuntimeProfile profile = new RuntimeProfileResolver().Resolve(new LocalRuntimeSettings(), topology);

    Assert.AreEqual(LocalRuntimeType.LlamaCpp, profile.RuntimeType);
    CollectionAssert.AreEqual(new[] { 0, 1 }, profile.GpuDevices.ToArray());
    Assert.IsTrue(profile.MultiGpu);
    Assert.AreEqual("layer", profile.SplitMode);
    Assert.AreEqual(8080, profile.Port);
  }

  [TestMethod]
  public void ProfileResolver_DisablesMultiGpuWithoutFallingBackToCpu()
  {
    ResolvedRuntimeProfile profile = new RuntimeProfileResolver().Resolve(
        new LocalRuntimeSettings { MultiGpuEnabled = false },
        CreateTopology(2));

    CollectionAssert.AreEqual(new[] { 0 }, profile.GpuDevices.ToArray());
    Assert.IsFalse(profile.MultiGpu);
    Assert.IsTrue(profile.Cuda);
  }

  [TestMethod]
  public void ProfileResolver_RejectsCudaWhenUnavailable()
  {
    InvalidOperationException exception = Assert.ThrowsExactly<InvalidOperationException>(
        () => new RuntimeProfileResolver().Resolve(new LocalRuntimeSettings(), GpuTopology.Unavailable));
    StringAssert.Contains(exception.Message, "CUDA is unavailable");
  }

  [TestMethod]
  public void ProfileResolver_RejectsGgufForTensorRt()
  {
    LocalRuntimeSettings settings = new()
    {
      PreferredRuntime = LocalRuntimeType.TensorRtLlm,
      TensorRtModel = "/models/qwen.gguf",
      TensorRtModelFormat = "gguf"
    };

    InvalidOperationException exception = Assert.ThrowsExactly<InvalidOperationException>(
        () => new RuntimeProfileResolver().Resolve(settings, CreateTopology(2)));
    StringAssert.Contains(exception.Message, "GGUF");
  }

  [TestMethod]
  public void ProfileResolver_ResolvesTensorParallelSizeFromTopology()
  {
    LocalRuntimeSettings settings = new()
    {
      PreferredRuntime = LocalRuntimeType.TensorRtLlm,
      TensorRtModel = "/models/qwen-engine",
      TensorRtModelFormat = "engine"
    };

    ResolvedRuntimeProfile profile = new RuntimeProfileResolver().Resolve(settings, CreateTopology(2));

    Assert.AreEqual(2, profile.TensorParallelSize);
    Assert.AreEqual(8081, profile.Port);
  }

  [TestMethod]
  public void Commands_QuoteUserControlledArgumentsAndApplyGpuSelection()
  {
    ResolvedRuntimeProfile profile = new(
            "test", LocalRuntimeType.LlamaCpp, "org/model with spaces", "gguf", 8080, true,
            [0, 2], true, "layer", "0.7,0.3", 1, "all", true, 8192, ["--no-webui"]);

    string command = LlamaCppRuntime.CreateCommand("~/.llama-app/llama", profile);

    StringAssert.Contains(command, "CUDA_VISIBLE_DEVICES='0,2'");
    StringAssert.Contains(command, "\"$HOME/.llama-app/llama\"");
    StringAssert.Contains(command, "'org/model with spaces'");
    StringAssert.Contains(command, "'--tensor-split' '0.7,0.3'");
  }

  [TestMethod]
  public void TensorRtCommand_QuotesModelAndUsesResolvedTensorParallelism()
  {
    ResolvedRuntimeProfile profile = new(
            "test", LocalRuntimeType.TensorRtLlm, "/models/qwen engine", "engine", 8081, true,
            [1, 3], true, "layer", null, 2, "all", true, 8192, ["--max_num_tokens", "4096"]);

    string command = TensorRtLlmRuntime.CreateCommand("trtllm-serve", profile);

    StringAssert.Contains(command, "CUDA_VISIBLE_DEVICES='1,3'");
    StringAssert.Contains(command, "'/models/qwen engine' '--tp_size' '2'");
    StringAssert.Contains(command, "'--max_num_tokens' '4096'");
  }

  [TestMethod]
  public void SettingsStore_RoundTripsAndPreservesUnrelatedJson()
  {
    string root = BackendConfigurationTests.CreateTemporaryRoot();
    try
    {
      string path = Path.Combine(root, "bootstrap.json");
      File.WriteAllText(path, """{"custom":{"preserve":true}}""");
      LocalRuntimeSettingsStore store = new(path);
      LocalRuntimeSettings expected = new()
      {
        PreferredRuntime = LocalRuntimeType.TensorRtLlm,
        TensorRtModel = "/models/qwen-engine",
        TensorParallelSize = 2,
        DeviceList = [0, 1],
        AutoStart = false,
        LlamaPort = 18080,
        StartupTimeout = TimeSpan.FromSeconds(47)
      };

      store.Save(expected);
      LocalRuntimeSettings actual = store.Load();

      Assert.AreEqual(expected.PreferredRuntime, actual.PreferredRuntime);
      Assert.AreEqual(expected.TensorRtModel, actual.TensorRtModel);
      Assert.AreEqual(2, actual.TensorParallelSize);
      Assert.AreEqual(TimeSpan.FromSeconds(47), actual.StartupTimeout);
      CollectionAssert.AreEqual(new[] { 0, 1 }, actual.DeviceList.ToArray());
      using JsonDocument json = JsonDocument.Parse(File.ReadAllText(path));
      Assert.IsTrue(json.RootElement.GetProperty("custom").GetProperty("preserve").GetBoolean());
    }
    finally
    {
      BackendConfigurationTests.DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public void SettingsStore_DoesNotOverwriteMalformedJson()
  {
    string root = BackendConfigurationTests.CreateTemporaryRoot();
    try
    {
      string path = Path.Combine(root, "bootstrap.json");
      const string malformed = "{not-json";
      File.WriteAllText(path, malformed);
      LocalRuntimeSettingsStore store = new(path);

      _ = Assert.ThrowsExactly<InvalidDataException>(() => store.Save(new LocalRuntimeSettings()));
      Assert.AreEqual(malformed, File.ReadAllText(path));
    }
    finally
    {
      BackendConfigurationTests.DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public async Task HealthService_RequiresHealthAndAtLeastOneModel()
  {
    using HttpClient client = new(new StubHttpHandler(request => request.RequestUri!.AbsolutePath switch
    {
      "/health" => JsonResponse("{}"),
      "/v1/models" => JsonResponse("{\"data\":[{\"id\":\"qwen-test\"}]}"),
      _ => new HttpResponseMessage(HttpStatusCode.NotFound)
    }));
    using RuntimeHealthService service = new(client);

    RuntimeHealthResult result = await service.ProbeAsync(new Uri("http://127.0.0.1:8080/"), LocalRuntimeType.LlamaCpp);

    Assert.IsTrue(result.IsReachable);
    Assert.IsTrue(result.IsReady);
    Assert.AreEqual("qwen-test", result.Model);
  }

  private sealed class TransientGpuRunner : IWslCommandRunner
  {
    public int CallCount { get; private set; }

    public Task<CommandResult> RunAsync(string command, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
      CallCount++;
      return Task.FromResult(CallCount == 1
          ? new CommandResult(1, string.Empty, "WSL is still starting", false)
          : new CommandResult(0, "0, NVIDIA RTX A6000, 49140, 47000, 597.06", string.Empty, false));
    }

    public Task<DetachedCommandResult> StartDetachedAsync(string command, string logPath, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
      throw new NotSupportedException();
    }
  }

  private sealed class DelayedGpuRunner(int failuresBeforeReady) : IWslCommandRunner
  {
    public int CallCount { get; private set; }

    public Task<CommandResult> RunAsync(string command, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
      CallCount++;
      return Task.FromResult(CallCount <= failuresBeforeReady
          ? new CommandResult(1, string.Empty, "WSL CUDA bridge is still starting", false)
          : new CommandResult(0, string.Join('\n',
              "0, NVIDIA RTX A6000, 49140, 47000, 597.06",
              "1, NVIDIA RTX A6000, 49140, 47000, 597.06",
              "2, NVIDIA RTX A6000, 49140, 47000, 597.06"), string.Empty, false));
    }

    public Task<DetachedCommandResult> StartDetachedAsync(string command, string logPath, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
      throw new NotSupportedException();
    }
  }

  [TestMethod]
  public async Task HealthService_ReportsMalformedModelsAsReachableButNotReady()
  {
    using HttpClient client = new(new StubHttpHandler(request => request.RequestUri!.AbsolutePath switch
    {
      "/health" => JsonResponse("{}"),
      "/v1/models" => JsonResponse("not-json"),
      _ => new HttpResponseMessage(HttpStatusCode.NotFound)
    }));
    using RuntimeHealthService service = new(client);

    RuntimeHealthResult result = await service.ProbeAsync(new Uri("http://127.0.0.1:8080/"), LocalRuntimeType.LlamaCpp);

    Assert.IsTrue(result.IsReachable);
    Assert.IsFalse(result.IsReady);
    StringAssert.Contains(result.Error!, "malformed model metadata");
  }

  private static HttpResponseMessage JsonResponse(string json)
  {
    return new(HttpStatusCode.OK)
    {
      Content = new StringContent(json, Encoding.UTF8, "application/json")
    };
  }

  private static GpuTopology CreateTopology(int count)
  {
    return new(true, [.. Enumerable.Range(0, count).Select(index => new GpuInfo(index, $"GPU {index}", 8192, 4096, "590"))]);
  }

  private sealed class StubHttpHandler(Func<HttpRequestMessage, HttpResponseMessage> responseFactory) : HttpMessageHandler
  {
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
      return Task.FromResult(responseFactory(request));
    }
  }
}
