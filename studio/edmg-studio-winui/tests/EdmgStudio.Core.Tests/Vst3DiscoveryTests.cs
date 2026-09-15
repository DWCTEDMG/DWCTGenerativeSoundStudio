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
}
