using EdmgStudio.Core.Runtime;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class LocalRuntimeOrchestratorTests
{
    [TestMethod]
    public async Task StartAsync_ReusesHealthyExternalRuntimeAndNeverStopsIt()
    {
        using var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, true, "external-model", null, null));

        await fixture.Orchestrator.StartAsync();
        await fixture.Orchestrator.StopAsync();

        Assert.AreEqual(RuntimeState.Ready, fixture.Orchestrator.CurrentStatus.State);
        Assert.IsFalse(fixture.Orchestrator.CurrentStatus.StartedByStudio);
        Assert.AreEqual(0, fixture.Runtime.StartCount);
        Assert.AreEqual(0, fixture.Runtime.StopCount);
        StringAssert.Contains(fixture.Orchestrator.CurrentStatus.Error!, "left running");
    }

    [TestMethod]
    public async Task StartAsync_LaunchesAndWaitsUntilModelIsReady()
    {
        using var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(false, false, null, null, "offline"));
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, false, null, null, "loading"));
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, true, "ready-model", null, null));

        await fixture.Orchestrator.StartAsync();

        Assert.AreEqual(RuntimeState.Ready, fixture.Orchestrator.CurrentStatus.State);
        Assert.IsTrue(fixture.Orchestrator.CurrentStatus.StartedByStudio);
        Assert.AreEqual("ready-model", fixture.Orchestrator.CurrentStatus.Model);
        Assert.AreEqual(1, fixture.Runtime.StartCount);
    }

    [TestMethod]
    public async Task RestartAsync_StopsOwnedRuntimeBeforeStartingAgain()
    {
        using var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(false, false, null, null, "offline"));
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, true, "model", null, null));
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(false, false, null, null, "offline"));
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, true, "model", null, null));

        await fixture.Orchestrator.StartAsync();
        await fixture.Orchestrator.RestartAsync();

        Assert.AreEqual(2, fixture.Runtime.StartCount);
        Assert.AreEqual(1, fixture.Runtime.StopCount);
        Assert.AreEqual(RuntimeState.Ready, fixture.Orchestrator.CurrentStatus.State);
    }

    [TestMethod]
    public async Task StartAsync_ReportsPortCollisionWithoutLaunching()
    {
        using var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, false, null, null, "not an inference server"));

        InvalidOperationException exception = await Assert.ThrowsExactlyAsync<InvalidOperationException>(() => fixture.Orchestrator.StartAsync());

        StringAssert.Contains(exception.Message, "Port 8080 is occupied");
        Assert.AreEqual(RuntimeState.Failed, fixture.Orchestrator.CurrentStatus.State);
        Assert.AreEqual(0, fixture.Runtime.StartCount);
    }

    [TestMethod]
    public async Task StartAsync_StopsOwnedProcessAfterReadinessTimeout()
    {
        using var fixture = new RuntimeFixture(autoStart: false, startupTimeout: TimeSpan.FromMilliseconds(15));
        fixture.Health.DefaultResult = new RuntimeHealthResult(false, false, null, null, "still loading");

        await Assert.ThrowsExactlyAsync<TimeoutException>(() => fixture.Orchestrator.StartAsync());

        Assert.AreEqual(1, fixture.Runtime.StartCount);
        Assert.AreEqual(1, fixture.Runtime.StopCount);
        Assert.AreEqual(RuntimeState.Failed, fixture.Orchestrator.CurrentStatus.State);
    }

    [TestMethod]
    public async Task StartAsync_StopsOwnedProcessWhenReadinessIsCanceled()
    {
        using var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(false, false, null, null, "offline"));
        fixture.Health.BlockUntilCanceled = true;
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(25));

        await Assert.ThrowsAsync<OperationCanceledException>(() => fixture.Orchestrator.StartAsync(cancellationToken: cancellation.Token));

        Assert.AreEqual(1, fixture.Runtime.StartCount);
        Assert.AreEqual(1, fixture.Runtime.StopCount);
        Assert.AreEqual(RuntimeState.Stopped, fixture.Orchestrator.CurrentStatus.State);
    }

    [TestMethod]
    public async Task StartAsync_ReportsRuntimeNotInstalledWithoutLaunching()
    {
        using var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(false, false, null, null, "offline"));
        fixture.Runtime.Installed = false;

        InvalidOperationException exception = await Assert.ThrowsExactlyAsync<InvalidOperationException>(() => fixture.Orchestrator.StartAsync());

        StringAssert.Contains(exception.Message, "llama.cpp is not installed");
        Assert.AreEqual(0, fixture.Runtime.StartCount);
        Assert.AreEqual(RuntimeState.Failed, fixture.Orchestrator.CurrentStatus.State);
    }

    [TestMethod]
    public async Task DisposeAsync_StopsOwnedRuntimeWhenConfigured()
    {
        var fixture = new RuntimeFixture(autoStart: false);
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(false, false, null, null, "offline"));
        fixture.Health.Results.Enqueue(new RuntimeHealthResult(true, true, "model", null, null));
        await fixture.Orchestrator.StartAsync();

        await fixture.Orchestrator.DisposeAsync();

        Assert.AreEqual(1, fixture.Runtime.StopCount);
        fixture.SuppressDispose = true;
    }

    private sealed class RuntimeFixture : IDisposable
    {
        private readonly string _root;

        public RuntimeFixture(bool autoStart, TimeSpan? startupTimeout = null)
        {
            _root = BackendConfigurationTests.CreateTemporaryRoot();
            var store = new LocalRuntimeSettingsStore(Path.Combine(_root, "bootstrap.json"));
            store.Save(new LocalRuntimeSettings { AutoStart = autoStart, StartupTimeout = startupTimeout ?? TimeSpan.FromSeconds(1) });
            Runtime = new FakeRuntime();
            Health = new FakeHealth();
            Orchestrator = new LocalRuntimeOrchestrator(
                [Runtime],
                new FakeRunner(),
                new FakeGpuDiscovery(),
                Health,
                new RuntimeProfileResolver(),
                store,
                TimeSpan.FromMilliseconds(1));
            if (startupTimeout is not null)
            {
                Orchestrator.UpdateSettings(Orchestrator.Settings with { StartupTimeout = startupTimeout.Value });
            }
        }

        public FakeRuntime Runtime { get; }
        public FakeHealth Health { get; }
        public LocalRuntimeOrchestrator Orchestrator { get; }
        public bool SuppressDispose { get; set; }

        public void Dispose()
        {
            if (!SuppressDispose) Orchestrator.DisposeAsync().AsTask().GetAwaiter().GetResult();
            BackendConfigurationTests.DeleteTemporaryRoot(_root);
        }
    }

    private sealed class FakeRuntime : ILocalInferenceRuntime
    {
        public LocalRuntimeType RuntimeType => LocalRuntimeType.LlamaCpp;
        public int StartCount { get; private set; }
        public int StopCount { get; private set; }
        public bool Installed { get; set; } = true;
        public Task<bool> IsInstalledAsync(CancellationToken cancellationToken = default) => Task.FromResult(Installed);

        public Task<RuntimeLaunchResult> StartAsync(ResolvedRuntimeProfile profile, CancellationToken cancellationToken = default)
        {
            StartCount++;
            return Task.FromResult(new RuntimeLaunchResult(RuntimeType, profile.Model, new Uri($"http://127.0.0.1:{profile.Port}/"), new RuntimeOwnership(true, null, 1234, DateTimeOffset.UtcNow), "/tmp/runtime.log"));
        }

        public Task StopAsync(RuntimeOwnership ownership, CancellationToken cancellationToken = default)
        {
            Assert.IsTrue(ownership.StartedByStudio);
            StopCount++;
            return Task.CompletedTask;
        }
    }

    private sealed class FakeHealth : IRuntimeHealthService
    {
        public Queue<RuntimeHealthResult> Results { get; } = new();
        public RuntimeHealthResult DefaultResult { get; set; } = new(false, false, null, null, "offline");
        public bool BlockUntilCanceled { get; set; }

        public async Task<RuntimeHealthResult> ProbeAsync(Uri endpoint, LocalRuntimeType runtime, CancellationToken cancellationToken = default)
        {
            if (Results.Count > 0) return Results.Dequeue();
            if (BlockUntilCanceled) await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            return DefaultResult;
        }
    }

    private sealed class FakeGpuDiscovery : IGpuDiscoveryService
    {
        public Task<GpuTopology> DetectAsync(CancellationToken cancellationToken = default) => Task.FromResult(new GpuTopology(true, [new GpuInfo(0, "Test GPU", 8192, 4096, "590")]));
    }

    private sealed class FakeRunner : IWslCommandRunner
    {
        public Task<CommandResult> RunAsync(string command, TimeSpan timeout, CancellationToken cancellationToken = default) => Task.FromResult(new CommandResult(0, string.Empty, string.Empty, false));
        public Task<DetachedCommandResult> StartDetachedAsync(string command, string logPath, TimeSpan timeout, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}
