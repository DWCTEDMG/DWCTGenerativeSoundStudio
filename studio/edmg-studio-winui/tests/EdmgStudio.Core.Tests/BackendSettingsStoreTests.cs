using System.Text.Json;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class BackendSettingsStoreTests
{
    [TestMethod]
    public void LoadFromBootstrap_RejectsMissingAndInvalidExternalUrls()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var missingUrlPath = Path.Combine(root, "missing-url.json");
            File.WriteAllText(missingUrlPath, """{"backendSettings":{"mode":"external"}}""");
            var missingUrl = BackendConfiguration.LoadFromBootstrap(missingUrlPath);

            Assert.AreEqual(RequestedBackendMode.External, missingUrl.Mode);
            Assert.AreEqual("bootstrap", missingUrl.BackendModeSource);
            Assert.IsTrue(missingUrl.ValidationErrors.Any(error => error.Contains("requires a backend URL", StringComparison.Ordinal)));

            var invalidUrlPath = Path.Combine(root, "invalid-url.json");
            File.WriteAllText(
                invalidUrlPath,
                """{"backendSettings":{"mode":"external","url":"ftp://studio.example/render"}}""");
            var invalidUrl = BackendConfiguration.LoadFromBootstrap(invalidUrlPath);

            Assert.AreEqual("ftp://studio.example/render", invalidUrl.ConfiguredBackendUrl);
            Assert.AreEqual("bootstrap", invalidUrl.BackendAddressSource);
            Assert.IsTrue(invalidUrl.ValidationErrors.Any(error => error.Contains("is invalid", StringComparison.Ordinal)));
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }

    [TestMethod]
    public void ResetToManaged_PreservesUnrelatedBootstrapSettings()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var bootstrapPath = Path.Combine(root, "bootstrap.json");
            File.WriteAllText(
                bootstrapPath,
                """
                {
                  "backendSettings": {
                    "mode": "external",
                    "url": "https://studio.example/v1"
                  },
                  "storageSettings": {
                    "models": "D:\\EDMG\\Models"
                  },
                  "aiSettings": {
                    "provider": "foundry",
                    "foundryProjectEndpoint": "https://example.services.ai.azure.com/api/projects/example"
                  },
                  "customSetting": {
                    "preserve": true
                  }
                }
                """);

            BackendSettingsStore.ResetToManaged(bootstrapPath);

            using var document = JsonDocument.Parse(File.ReadAllText(bootstrapPath));
            var json = document.RootElement;
            var backend = json.GetProperty("backendSettings");
            Assert.AreEqual("managed", backend.GetProperty("mode").GetString());
            Assert.AreEqual("127.0.0.1", backend.GetProperty("host").GetString());
            Assert.AreEqual("7863", backend.GetProperty("port").GetString());
            Assert.AreEqual("D:\\EDMG\\Models", json.GetProperty("storageSettings").GetProperty("models").GetString());
            Assert.AreEqual("foundry", json.GetProperty("aiSettings").GetProperty("provider").GetString());
            Assert.IsTrue(json.GetProperty("customSetting").GetProperty("preserve").GetBoolean());

            var reset = BackendConfiguration.LoadFromBootstrap(bootstrapPath);
            Assert.AreEqual(RequestedBackendMode.Managed, reset.Mode);
            Assert.AreEqual(new Uri("http://127.0.0.1:7863/"), reset.BackendUri);
            Assert.IsEmpty(reset.ValidationErrors);
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }

    [TestMethod]
    public void ResetToManaged_DoesNotOverwriteMalformedBootstrap()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var bootstrapPath = Path.Combine(root, "bootstrap.json");
            const string malformed = "{not-json";
            File.WriteAllText(bootstrapPath, malformed);

            Assert.ThrowsExactly<InvalidDataException>(() => BackendSettingsStore.ResetToManaged(bootstrapPath));
            Assert.AreEqual(malformed, File.ReadAllText(bootstrapPath));
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }
}
