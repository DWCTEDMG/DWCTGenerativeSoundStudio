using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using System.Net;
using System.Text;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class BackendSupervisorTests
{
  [TestMethod]
  public async Task ExternalMode_RequiresAValidHealthEnvelopeAndNeverOwnsTheService()
  {
    string root = BackendConfigurationTests.CreateTemporaryRoot();
    try
    {
      List<Uri> requests = [];
      using HealthHandler handler = new(requests, ok: true);
      BackendConfiguration configuration = new(
          RequestedBackendMode.External,
          "remote.example",
          443,
          new Uri("https://remote.example/studio/"),
          "cpu",
          null,
          BackendConfigurationTests.CreatePaths(root),
          "test");
      await using BackendSupervisor supervisor = new(configuration, handler);

      BackendStatus status = await supervisor.StartAsync();

      Assert.AreEqual(BackendLifecycleState.Ready, status.State);
      Assert.AreEqual(BackendMode.External, status.Mode);
      Assert.IsFalse(status.OwnsProcess);
      Assert.AreEqual(new Uri("https://remote.example/studio/health"), requests.Single());

      await supervisor.StopAsync();
      Assert.AreEqual(BackendLifecycleState.Stopped, supervisor.Status.State);
      Assert.IsFalse(supervisor.Status.OwnsProcess);
    }
    finally
    {
      BackendConfigurationTests.DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public async Task ExternalMode_RejectsTwoHundredResponsesWhoseHealthFlagIsFalse()
  {
    string root = BackendConfigurationTests.CreateTemporaryRoot();
    try
    {
      using HealthHandler handler = new([], ok: false);
      BackendConfiguration configuration = new(
          RequestedBackendMode.External,
          "127.0.0.1",
          7863,
          new Uri("http://127.0.0.1:7863/"),
          "cpu",
          null,
          BackendConfigurationTests.CreatePaths(root),
          "test");
      await using BackendSupervisor supervisor = new(configuration, handler);

      BackendStatus status = await supervisor.StartAsync();

      Assert.AreEqual(BackendLifecycleState.Unavailable, status.State);
      Assert.AreEqual("EXTERNAL_BACKEND_UNAVAILABLE", status.FailureCode);
    }
    finally
    {
      BackendConfigurationTests.DeleteTemporaryRoot(root);
    }
  }

  [TestMethod]
  public async Task InstalledPackage_MissingRuntimeNeverAttachesToForeignBackendOrSource()
  {
    string root = BackendConfigurationTests.CreateTemporaryRoot();
    try
    {
      File.WriteAllText(Path.Combine(root, "pyproject.toml"), "[project]");
      List<Uri> requests = [];
      using HealthHandler handler = new(requests, ok: true);
      BackendConfiguration configuration = new(RequestedBackendMode.Managed, "127.0.0.1", 7863,
          new Uri("http://127.0.0.1:7863/"), "cuda", root,
          BackendConfigurationTests.CreatePaths(root), "test")
      { RequirePackagedBackend = true, ApplicationDirectory = root };
      await using BackendSupervisor supervisor = new(configuration, handler);
      BackendStatus status = await supervisor.StartAsync();
      Assert.AreEqual("PACKAGED_BACKEND_MISSING", status.FailureCode);
      Assert.IsFalse(status.OwnsProcess);
      Assert.IsEmpty(requests);
    }
    finally { BackendConfigurationTests.DeleteTemporaryRoot(root); }
  }

  private sealed class HealthHandler(List<Uri> requests, bool ok) : HttpMessageHandler
  {
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
      requests.Add(request.RequestUri!);
      return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
      {
        Content = new StringContent($"{{\"ok\":{ok.ToString().ToLowerInvariant()},\"version\":\"1.2.0\"}}", Encoding.UTF8, "application/json")
      });
    }
  }
}
