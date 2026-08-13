using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class BackendConfigurationTests
{
    [TestMethod]
    public void NormalizeBackendUri_RemovesKnownApiSuffixesAndSecrets()
    {
        var fromHealth = BackendConfiguration.NormalizeBackendUri("https://studio.example:9443/health?token=secret#fragment");
        var fromApiRoot = BackendConfiguration.NormalizeBackendUri("http://127.0.0.1:7863/v1/");

        Assert.AreEqual(new Uri("https://studio.example:9443/"), fromHealth);
        Assert.AreEqual(new Uri("http://127.0.0.1:7863/"), fromApiRoot);
        Assert.IsNull(BackendConfiguration.NormalizeBackendUri("ftp://studio.example/backend"));
    }

    [TestMethod]
    public void NormalizeAcceleratorProfile_UsesSupportedRuntimeNames()
    {
        Assert.AreEqual("cuda", BackendConfiguration.NormalizeAcceleratorProfile("NVIDIA"));
        Assert.AreEqual("directml", BackendConfiguration.NormalizeAcceleratorProfile("amd"));
        Assert.AreEqual("cpu", BackendConfiguration.NormalizeAcceleratorProfile(null));
        Assert.ThrowsExactly<ArgumentException>(() => BackendConfiguration.NormalizeAcceleratorProfile("unsupported"));
    }

    [TestMethod]
    public void CreateSourceSpec_MatchesTheFrozenBackendLaunchContract()
    {
        var root = CreateTemporaryRoot();
        try
        {
            var paths = CreatePaths(root);
            var configuration = new BackendConfiguration(
                RequestedBackendMode.Managed,
                "127.0.0.1",
                7863,
                new Uri("http://127.0.0.1:7863/"),
                "nvidia",
                root,
                paths,
                "test");
            var factory = new BackendLaunchSpecFactory(configuration);

            var spec = factory.CreateSourceSpec(root, "127.0.0.1", 7863);

            Assert.AreEqual(BackendMode.ManagedSource, spec.Mode);
            Assert.AreEqual("uv", spec.FileName);
            Assert.AreEqual("cuda", spec.AcceleratorProfile);
            CollectionAssert.AreEqual(
                new[]
                {
                    "run", "--frozen", "--no-default-groups", "--python", "3.12",
                    "--extra", "cuda",
                    "--extra", "core",
                    "--extra", "audio",
                    "--extra", "asr",
                    "--extra", "internal-video",
                    "--extra", "aws",
                    "python", "-m", "edmg_studio_backend", "serve",
                    "--host", "127.0.0.1", "--port", "7863"
                },
                spec.Arguments.ToArray());
            Assert.AreEqual(paths.StudioHome, spec.Environment["EDMG_STUDIO_HOME"]);
            Assert.AreEqual(Path.Combine(paths.CacheDirectory, "xdg"), spec.Environment["XDG_CACHE_HOME"]);
            Assert.AreEqual("1", spec.Environment["NVIDIA_TENSORRT_DISABLE_INTERNAL_PIP"]);

            var startInfo = spec.CreateProcessStartInfo();
            Assert.IsFalse(startInfo.UseShellExecute);
            Assert.IsTrue(startInfo.CreateNoWindow);
            Assert.IsTrue(startInfo.RedirectStandardOutput);
            Assert.HasCount(spec.Arguments.Count, startInfo.ArgumentList);
        }
        finally
        {
            DeleteTemporaryRoot(root);
        }
    }

    internal static StudioPaths CreatePaths(string root) => new(
        root,
        Path.Combine(root, "data"),
        Path.Combine(root, "models"),
        Path.Combine(root, "cache"),
        Path.Combine(root, "logs"),
        Path.Combine(root, "external"));

    internal static string CreateTemporaryRoot()
    {
        var root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "edmg-winui-tests", Guid.NewGuid().ToString("N")));
        Directory.CreateDirectory(root);
        return root;
    }

    internal static void DeleteTemporaryRoot(string root)
    {
        var expectedParent = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "edmg-winui-tests")) + Path.DirectorySeparatorChar;
        var resolved = Path.GetFullPath(root);
        if (resolved.StartsWith(expectedParent, StringComparison.OrdinalIgnoreCase) && Directory.Exists(resolved))
        {
            Directory.Delete(resolved, recursive: true);
        }
    }
}
