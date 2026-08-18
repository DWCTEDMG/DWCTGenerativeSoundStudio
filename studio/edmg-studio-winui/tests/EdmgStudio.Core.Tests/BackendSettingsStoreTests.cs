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

    [TestMethod]
    public void LoadFoundrySettings_UsesRepresentedDefaultsWhenBootstrapIsMissing()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var settings = BackendSettingsStore.LoadFoundrySettings(Path.Combine(root, "missing.json"));

            Assert.AreEqual("jonlong-1185", settings.ProjectName);
            Assert.AreEqual("Azuredwct", settings.SubscriptionName);
            Assert.AreEqual(
                "https://jonlong-1185-resource.services.ai.azure.com/api/projects/jonlong-1185",
                settings.ProjectEndpoint.AbsoluteUri.TrimEnd('/'));
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }

    [TestMethod]
    public void SaveFoundrySettings_RoundTripsAndPreservesUnknownFields()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var bootstrapPath = Path.Combine(root, "bootstrap.json");
            File.WriteAllText(
                bootstrapPath,
                """
                {
                  "aiSettings": {
                    "provider": "foundry",
                    "customProviderSetting": 42
                  },
                  "storageSettings": {
                    "models": "D:\\EDMG\\Models"
                  },
                  "unknownRoot": true
                }
                """);
            var expected = new FoundryProjectSettings(
                "production-project",
                "Production subscription",
                new Uri("https://foundry.example/api/projects/production-project/"));

            BackendSettingsStore.SaveFoundrySettings(expected, bootstrapPath);
            var actual = BackendSettingsStore.LoadFoundrySettings(bootstrapPath);

            Assert.AreEqual("production-project", actual.ProjectName);
            Assert.AreEqual("Production subscription", actual.SubscriptionName);
            Assert.AreEqual(
                "https://foundry.example/api/projects/production-project",
                actual.ProjectEndpoint.AbsoluteUri.TrimEnd('/'));
            using var document = JsonDocument.Parse(File.ReadAllText(bootstrapPath));
            var json = document.RootElement;
            Assert.AreEqual("foundry", json.GetProperty("aiSettings").GetProperty("provider").GetString());
            Assert.AreEqual(42, json.GetProperty("aiSettings").GetProperty("customProviderSetting").GetInt32());
            Assert.AreEqual("D:\\EDMG\\Models", json.GetProperty("storageSettings").GetProperty("models").GetString());
            Assert.IsTrue(json.GetProperty("unknownRoot").GetBoolean());
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }

    [TestMethod]
    public void SaveFoundrySettings_RejectsInvalidEndpointWithoutChangingBootstrap()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var bootstrapPath = Path.Combine(root, "bootstrap.json");
            const string original = """{"customSetting":{"preserve":true}}""";
            File.WriteAllText(bootstrapPath, original);
            var settings = new FoundryProjectSettings(
                "project",
                "subscription",
                new Uri("ftp://user:secret@foundry.example/project"));

            Assert.ThrowsExactly<ArgumentException>(
                () => BackendSettingsStore.SaveFoundrySettings(settings, bootstrapPath));
            Assert.AreEqual(original, File.ReadAllText(bootstrapPath));
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }

    [TestMethod]
    public void LoadFoundrySettings_RejectsInvalidPersistedEndpoint()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var bootstrapPath = Path.Combine(root, "bootstrap.json");
            File.WriteAllText(
                bootstrapPath,
                """{"aiSettings":{"foundryProjectEndpoint":"relative/project"}}""");

            Assert.ThrowsExactly<ArgumentException>(
                () => BackendSettingsStore.LoadFoundrySettings(bootstrapPath));
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
    }
}
