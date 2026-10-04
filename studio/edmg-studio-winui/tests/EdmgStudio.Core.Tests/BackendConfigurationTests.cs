using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using System.Diagnostics;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class BackendConfigurationTests
{
  [TestMethod]
  public void NormalizeBackendUri_RemovesKnownApiSuffixesAndSecrets()
  {
    Uri? fromHealth = BackendConfiguration.NormalizeBackendUri("https://studio.example:9443/health?token=secret#fragment");
    Uri? fromApiRoot = BackendConfiguration.NormalizeBackendUri("http://127.0.0.1:7863/v1/");

    Assert.AreEqual(new Uri("https://studio.example:9443/"), fromHealth);
    Assert.AreEqual(new Uri("http://127.0.0.1:7863/"), fromApiRoot);
    Assert.IsNull(BackendConfiguration.NormalizeBackendUri("ftp://studio.example/backend"));
  }

  [TestMethod]
  public void NormalizeAcceleratorProfile_UsesSupportedRuntimeNames()
  {
    Assert.AreEqual("cuda", BackendConfiguration.NormalizeAcceleratorProfile("NVIDIA"));
    Assert.AreEqual("directml", BackendConfiguration.NormalizeAcceleratorProfile("amd"));
    Assert.AreEqual("cpu", BackendConfiguration.NormalizeAcceleratorProfile("cpu"));
    _ = Assert.ThrowsExactly<ArgumentException>(() => BackendConfiguration.NormalizeAcceleratorProfile("unsupported"));
  }

  [TestMethod]
  public void ResolveAcceleratorProfile_AutoSelectsHardwareWithoutOverridingExplicitChoice()
  {
    Assert.AreEqual("cuda", BackendConfiguration.ResolveAcceleratorProfile(null, () => true, isWindows: true));
    Assert.AreEqual("directml", BackendConfiguration.ResolveAcceleratorProfile(null, () => false, isWindows: true));
    _ = Assert.ThrowsExactly<ArgumentException>(() => BackendConfiguration.ResolveAcceleratorProfile(null, () => false, isWindows: false));
    Assert.AreEqual("cuda", BackendConfiguration.ResolveAcceleratorProfile("auto", () => true, isWindows: true));
    _ = Assert.ThrowsExactly<ArgumentException>(() => BackendConfiguration.NormalizeAcceleratorProfile(null));
    Assert.AreEqual("cpu", BackendConfiguration.ResolveAcceleratorProfile("cpu", () => true, isWindows: true));
  }

  [TestMethod]
  public void CreateSourceSpec_MatchesTheFrozenBackendLaunchContract()
  {
    string root = CreateTemporaryRoot();
    try
    {
      StudioPaths paths = CreatePaths(root);
      BackendConfiguration configuration = new(
          RequestedBackendMode.Managed,
          "127.0.0.1",
          7863,
          new Uri("http://127.0.0.1:7863/"),
          "nvidia",
          root,
          paths,
          "test");
      BackendLaunchSpecFactory factory = new(configuration);

      BackendLaunchSpec spec = factory.CreateSourceSpec(root, "127.0.0.1", 7863);

      Assert.AreEqual(BackendMode.ManagedSource, spec.Mode);
      Assert.AreEqual("uv", spec.FileName);
      Assert.AreEqual("cuda", spec.AcceleratorProfile);
      CollectionAssert.AreEqual(
          new[]
          {
                    "run", "--frozen", "--no-sync", "--no-default-groups", "--python", "3.12",
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

      ProcessStartInfo startInfo = spec.CreateProcessStartInfo();
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

  [TestMethod]
  public void InstallationLocator_ResolvesAValidExternalBackend()
  {
    string root = CreateTemporaryRoot();
    try
    {
      string installRoot = Path.Combine(root, "install");
      string backendDirectory = CreatePackagedBackend(installRoot, validManifest: true);
      string locatorPath = Path.Combine(root, "installation.json");
      File.WriteAllText(
          locatorPath,
          $$"""{"schemaVersion":1,"installRoot":{{System.Text.Json.JsonSerializer.Serialize(installRoot)}}}""");

      BackendConfiguration configuration = CreateConfiguration(root);
      BackendLaunchSpecFactory factory = new(configuration, locatorPath);

      Assert.AreEqual(backendDirectory, BackendInstallationLocator.TryResolveBackendDirectory(locatorPath));
      Assert.AreEqual(backendDirectory, factory.FindPackagedBackendDirectory());
    }
    finally
    {
      DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public void InstallationLocator_IgnoresMissingMalformedRelativeAndStaleValues()
  {
    string root = CreateTemporaryRoot();
    try
    {
      string locatorPath = Path.Combine(root, "installation.json");
      Assert.IsNull(BackendInstallationLocator.TryResolveBackendDirectory(locatorPath));

      File.WriteAllText(locatorPath, "{not-json");
      Assert.IsNull(BackendInstallationLocator.TryResolveBackendDirectory(locatorPath));

      File.WriteAllText(locatorPath, """{"schemaVersion":1,"installRoot":"relative"}""");
      Assert.IsNull(BackendInstallationLocator.TryResolveBackendDirectory(locatorPath));

      string missingRoot = Path.Combine(root, "missing");
      File.WriteAllText(
          locatorPath,
          $$"""{"schemaVersion":1,"installRoot":{{System.Text.Json.JsonSerializer.Serialize(missingRoot)}}}""");
      Assert.IsNull(BackendInstallationLocator.TryResolveBackendDirectory(locatorPath));
    }
    finally
    {
      DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public void FindPackagedBackendDirectory_RejectsInvalidLocatedBundle()
  {
    string root = CreateTemporaryRoot();
    try
    {
      string installRoot = Path.Combine(root, "install");
      _ = CreatePackagedBackend(installRoot, validManifest: false);
      string locatorPath = Path.Combine(root, "installation.json");
      File.WriteAllText(
          locatorPath,
          $$"""{"schemaVersion":1,"installRoot":{{System.Text.Json.JsonSerializer.Serialize(installRoot)}}}""");

      BackendLaunchSpecFactory factory = new(CreateConfiguration(root), locatorPath);

      Assert.IsNull(factory.FindPackagedBackendDirectory());
    }
    finally
    {
      DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public void InstalledPackage_UsesAdjacentBackendAndWritableUserStorage()
  {
    string root = CreateTemporaryRoot();
    try
    {
      string appDirectory = Path.Combine(root, "WindowsApps", "Studio");
      string staged = CreatePackagedBackend(root, validManifest: true);
      _ = Directory.CreateDirectory(appDirectory);
      string backend = Path.Combine(appDirectory, "backend");
      Directory.Move(staged, backend);
      BackendConfiguration configuration = CreateConfiguration(root) with
      {
        ApplicationDirectory = appDirectory,
        RequirePackagedBackend = true
      };
      BackendLaunchSpecFactory factory = new(configuration);
      Assert.AreEqual(backend, factory.FindPackagedBackendDirectory());
      Assert.IsNull(factory.FindSourceBackendDirectory());
      BackendLaunchSpec spec = factory.CreatePackagedSpec(backend, "127.0.0.1", 17863);
      Assert.AreEqual(Path.Combine(backend, "edmg-studio-backend.exe"), spec.FileName);
      Assert.AreEqual(BackendMode.ManagedPackaged, spec.Mode);
      CollectionAssert.AreEqual(new[] { "serve", "--host", "127.0.0.1", "--port", "17863" }, spec.Arguments.ToArray());
      Assert.AreEqual(configuration.Paths.DataDirectory, spec.Environment["EDMG_STUDIO_DATA_DIR"]);
      Assert.AreEqual("cuda", spec.Environment["EDMG_BACKEND_ACCELERATOR_PROFILE"]);
      Assert.IsFalse(spec.CreateProcessStartInfo().UseShellExecute);
      Directory.Delete(Path.Combine(backend, "_internal"));
      Assert.IsNull(factory.FindPackagedBackendDirectory());
    }
    finally { DeleteTemporaryRoot(root); }
  }

  private static BackendConfiguration CreateConfiguration(string root)
  {
    return new(
      RequestedBackendMode.Managed,
      "127.0.0.1",
      7863,
      new Uri("http://127.0.0.1:7863/"),
      "cuda",
      root,
      CreatePaths(root),
      "test");
  }

  private static string CreatePackagedBackend(string installRoot, bool validManifest)
  {
    string backendDirectory = Path.Combine(installRoot, "resources", "backend");
    _ = Directory.CreateDirectory(Path.Combine(backendDirectory, "_internal"));
    File.WriteAllText(Path.Combine(backendDirectory, "edmg-studio-backend.exe"), string.Empty);
    File.WriteAllText(
        Path.Combine(backendDirectory, "backend-bundle-manifest.json"),
        validManifest
            ? """
                  {
                    "ok": true,
                    "platform": "win32",
                    "bundleLayout": "onedir",
                    "backendEntryPoint": "edmg-studio-backend.exe",
                    "acceleratorProfile": "cuda",
                    "bundleEntries": ["edmg-studio-backend.exe"]
                  }
                  """
            : """{"ok":false}""");
    return backendDirectory;
  }

  internal static StudioPaths CreatePaths(string root)
  {
    return new(
      root,
      Path.Combine(root, "data"),
      Path.Combine(root, "models"),
      Path.Combine(root, "cache"),
      Path.Combine(root, "logs"),
      Path.Combine(root, "external"));
  }

  internal static string CreateTemporaryRoot()
  {
    string root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "edmg-winui-tests", Guid.NewGuid().ToString("N")));
    _ = Directory.CreateDirectory(root);
    return root;
  }

  internal static void DeleteTemporaryRoot(string root)
  {
    string expectedParent = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "edmg-winui-tests")) + Path.DirectorySeparatorChar;
    string resolved = Path.GetFullPath(root);
    if (resolved.StartsWith(expectedParent, StringComparison.OrdinalIgnoreCase) && Directory.Exists(resolved))
    {
      Directory.Delete(resolved, recursive: true);
    }
  }
}
