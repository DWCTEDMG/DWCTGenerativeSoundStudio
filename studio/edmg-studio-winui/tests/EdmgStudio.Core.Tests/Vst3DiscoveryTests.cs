using System.Collections.Immutable;
using System.Text.Json;
using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class Vst3DiscoveryTests
{
    [TestMethod]
    public async Task FingerprintChangesWhenModuleContentChanges()
    {
        string root = CreateRoot();
        try
        {
            string module = Path.Combine(root, "test.vst3");
            await File.WriteAllTextAsync(module, "first");
            Vst3ModuleFingerprint first = await Vst3ModuleFingerprinting.CreateAsync(module);
            await File.WriteAllTextAsync(module, "second-content");
            Vst3ModuleFingerprint second = await Vst3ModuleFingerprinting.CreateAsync(module);

            Assert.AreNotEqual(first.Sha256, second.Sha256);
            Assert.AreNotEqual(first.Length, second.Length);
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    [TestMethod]
    public async Task FingerprintSupportsWindowsDirectoryBundles()
    {
        string root = CreateRoot();
        try
        {
            string module = Path.Combine(root, "Bundle.vst3");
            string binaryDirectory = Path.Combine(module, "Contents", "x86_64-win");
            Directory.CreateDirectory(binaryDirectory);
            string binary = Path.Combine(binaryDirectory, "Bundle.vst3");
            await File.WriteAllTextAsync(binary, "first");
            Vst3ModuleFingerprint first = await Vst3ModuleFingerprinting.CreateAsync(module);
            await File.WriteAllTextAsync(binary, "second-content");
            Vst3ModuleFingerprint second = await Vst3ModuleFingerprinting.CreateAsync(module);

            Assert.AreEqual(Path.GetFullPath(module), first.ModulePath);
            Assert.AreEqual(5, first.Length);
            Assert.AreEqual(14, second.Length);
            Assert.AreNotEqual(first.Sha256, second.Sha256);
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    [TestMethod]
    public async Task FingerprintRejectsDirectoryBundleReparsePoints()
    {
        string root = CreateRoot();
        string external = CreateRoot();
        try
        {
            string module = Path.Combine(root, "Bundle.vst3");
            Directory.CreateDirectory(module);
            await File.WriteAllTextAsync(Path.Combine(external, "external.bin"), "external");
            string link = Path.Combine(module, "escaped");
            try { Directory.CreateSymbolicLink(link, external); }
            catch (UnauthorizedAccessException) { Assert.Inconclusive("Symbolic-link creation is unavailable on this Windows host."); return; }

            InvalidDataException exception = await Assert.ThrowsAsync<InvalidDataException>(async () =>
                await Vst3ModuleFingerprinting.CreateAsync(module));
            StringAssert.Contains(exception.Message, "reparse point");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
            Directory.Delete(external, recursive: true);
        }
    }

    [TestMethod]
    public void CatalogInvalidatesOldFingerprintAndPersistsQuarantine()
    {
        string root = CreateRoot();
        try
        {
            string path = Path.Combine(root, "catalog.json");
            var store = new Vst3CatalogStore(path);
            Vst3ModuleFingerprint first = Fingerprint("module.vst3", "aa");
            Vst3ModuleFingerprint changed = first with { Length = 20, Sha256 = "bb" };
            store.RecordSuccess(new(1, first, [Plugin("plugin-a")]));
            Assert.IsTrue(store.TryGetCached(first, out _));

            store.RecordFailure(changed, "scanner crashed");
            var reopened = new Vst3CatalogStore(path);
            Assert.IsFalse(reopened.TryGetCached(first, out _));
            Assert.IsTrue(reopened.IsQuarantined(changed));
            Assert.AreEqual(1, reopened.Load().Quarantine.Single().FailureCount);

            reopened.RecordFailure(changed, "scanner crashed again");
            Assert.AreEqual(2, reopened.Load().Quarantine.Single().FailureCount);
            reopened.ClearQuarantine();
            Assert.IsEmpty(reopened.Load().Quarantine);
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    [TestMethod]
    public void MalformedAndMismatchedScannerResponsesAreRejected()
    {
        Vst3ModuleFingerprint fingerprint = Fingerprint("module.vst3", "aa");
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3ScannerClient.ParseResponse("not-json", fingerprint));
        string mismatch = JsonSerializer.Serialize(new Vst3ScanResponse(
            1, fingerprint with { Sha256 = "bb" }, ImmutableArray.Create(Plugin("plugin-a"))));
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3ScannerClient.ParseResponse(mismatch, fingerprint));
    }

    [TestMethod]
    public void ScannerResponseRejectsUnknownOversizedAndDuplicateMetadata()
    {
        Vst3ModuleFingerprint fingerprint = Fingerprint("module.vst3", "aa");
        string valid = JsonSerializer.Serialize(new Vst3ScanResponse(1, fingerprint, [Plugin("duplicate"), Plugin("duplicate")]));
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3ScannerClient.ParseResponse(valid, fingerprint));
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3ScannerClient.ParseResponse(valid[..^1] + ",\"unknown\":true}", fingerprint));
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3ScannerClient.ParseResponse(new string('x', 4 * 1024 * 1024 + 1), fingerprint));
    }

    [TestMethod]
    public void UnavailableHostNeverClaimsScannerOrProcessingReadiness()
    {
        var host = new UnavailableVst3HostSession();
        Assert.AreEqual(Vst3CapabilityState.Unavailable, host.Capabilities.State);
        Assert.IsFalse(host.Capabilities.CanInstantiate);
        Assert.IsFalse(host.Capabilities.CanProcessAudio);
        Assert.IsFalse(host.Capabilities.IsCrashIsolated);
    }

    [TestMethod]
    public async Task MissingScannerReportsCapabilityFailureWithoutQuarantiningModule()
    {
        string root = CreateRoot();
        try
        {
            string module = Path.Combine(root, "test.vst3");
            await File.WriteAllTextAsync(module, "module");
            var store = new Vst3CatalogStore(Path.Combine(root, "catalog.json"));
            var client = new Vst3ScannerClient(Path.Combine(root, "missing-scanner.exe"), store);

            Vst3ScanResult result = await client.ScanAsync(module, TimeSpan.FromSeconds(1));

            Assert.AreEqual(Vst3CapabilityState.Unavailable, client.CapabilityState);
            Assert.AreEqual(Vst3ScanStatus.Failed, result.Status);
            Assert.IsFalse(store.IsQuarantined(result.Fingerprint));
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    [TestMethod]
    public async Task UnsupportedModuleIsCachedWithoutQuarantine()
    {
        string root = CreateRoot();
        try
        {
            string module = Path.Combine(root, "unsupported.vst3");
            string scanner = Path.Combine(root, "EdmgStudio.Vst3Scanner.exe");
            await File.WriteAllTextAsync(module, "module");
            await File.WriteAllTextAsync(scanner, "stub");
            Vst3ModuleFingerprint fingerprint = await Vst3ModuleFingerprinting.CreateAsync(module);
            string response = JsonSerializer.Serialize(new Vst3ScanResponse(1, fingerprint, [], "unsupported"));
            var store = new Vst3CatalogStore(Path.Combine(root, "catalog.json"));
            var runner = new CapturingRunner(new Vst3ScannerProcessResult(0, response, string.Empty));
            var client = new Vst3ScannerClient(scanner, store, runner);

            Vst3ScanResult first = await client.ScanAsync(module, TimeSpan.FromSeconds(1));
            Vst3ScanResult cached = await client.ScanAsync(module, TimeSpan.FromSeconds(1));

            Assert.AreEqual(Vst3ScanStatus.Unsupported, first.Status);
            Assert.AreEqual(Vst3ScanStatus.Unsupported, cached.Status);
            Assert.IsFalse(store.IsQuarantined(fingerprint));
            Assert.AreEqual("--scan-module", runner.StartInfo!.ArgumentList[0]);
            Assert.AreEqual(Path.GetFullPath(scanner), runner.StartInfo.FileName);
            Assert.AreEqual(1, runner.CallCount);
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    [TestMethod]
    public async Task ScannerCrashIsReportedAndQuarantined()
    {
        await AssertScannerFailureAsync(
            new StubRunner(new Vst3ScannerProcessResult(23, string.Empty, "access violation")),
            Vst3ScanStatus.Failed,
            "code 23");
    }

    [TestMethod]
    public async Task ScannerTimeoutIsReportedAndQuarantined()
    {
        await AssertScannerFailureAsync(
            new StubRunner(new TimeoutException("scanner timed out")),
            Vst3ScanStatus.TimedOut,
            "timed out");
    }

    [TestMethod]
    public async Task MalformedScannerOutputIsReportedAndQuarantined()
    {
        await AssertScannerFailureAsync(
            new StubRunner(new Vst3ScannerProcessResult(0, "not-json", string.Empty)),
            Vst3ScanStatus.MalformedResponse,
            "malformed JSON");
    }

    [TestMethod]
    public void MalformedCatalogIsPreserved()
    {
        string root = CreateRoot();
        try
        {
            string path = Path.Combine(root, "catalog.json");
            File.WriteAllText(path, "{broken");
            var store = new Vst3CatalogStore(path);
            Assert.ThrowsExactly<InvalidDataException>(() => store.ClearQuarantine());
            Assert.AreEqual("{broken", File.ReadAllText(path));
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private static Vst3ModuleFingerprint Fingerprint(string path, string hash) =>
        new(Path.GetFullPath(path), 10, 20, hash);

    private static Vst3PluginMetadata Plugin(string id) =>
        new(id, "Plugin", "Vendor", "1.0", "Fx", 2, 2, true, true, 64);

    private static string CreateRoot()
    {
        string root = Path.Combine(Path.GetTempPath(), "edmg-vst3-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }

    private static async Task AssertScannerFailureAsync(
        IVst3ScannerProcessRunner runner,
        Vst3ScanStatus expectedStatus,
        string diagnosticFragment)
    {
        string root = CreateRoot();
        try
        {
            string module = Path.Combine(root, "test.vst3");
            string scanner = Path.Combine(root, "scanner.exe");
            await File.WriteAllTextAsync(module, "module");
            await File.WriteAllTextAsync(scanner, "stub");
            var store = new Vst3CatalogStore(Path.Combine(root, "catalog.json"));
            var client = new Vst3ScannerClient(scanner, store, runner);

            Vst3ScanResult result = await client.ScanAsync(module, TimeSpan.FromMilliseconds(10));

            Assert.AreEqual(expectedStatus, result.Status);
            StringAssert.Contains(result.Diagnostic, diagnosticFragment);
            Assert.IsTrue(store.IsQuarantined(result.Fingerprint));
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private sealed class StubRunner : IVst3ScannerProcessRunner
    {
        private readonly Vst3ScannerProcessResult? _result;
        private readonly Exception? _exception;

        public StubRunner(Vst3ScannerProcessResult result) => _result = result;
        public StubRunner(Exception exception) => _exception = exception;

        public Task<Vst3ScannerProcessResult> RunAsync(
            System.Diagnostics.ProcessStartInfo startInfo,
            TimeSpan timeout,
            CancellationToken cancellationToken) =>
            _exception is null
                ? Task.FromResult(_result!)
                : Task.FromException<Vst3ScannerProcessResult>(_exception);
    }

    private sealed class CapturingRunner(Vst3ScannerProcessResult result) : IVst3ScannerProcessRunner
    {
        public System.Diagnostics.ProcessStartInfo? StartInfo { get; private set; }
        public int CallCount { get; private set; }

        public Task<Vst3ScannerProcessResult> RunAsync(
            System.Diagnostics.ProcessStartInfo startInfo,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            StartInfo = startInfo;
            CallCount++;
            return Task.FromResult(result);
        }
    }
}
