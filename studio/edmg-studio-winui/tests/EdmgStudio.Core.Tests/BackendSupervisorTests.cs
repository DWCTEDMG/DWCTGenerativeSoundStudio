using System.Net;
using System.Text;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class BackendSupervisorTests
{
    [TestMethod]
    public async Task ExternalMode_RequiresAValidHealthEnvelopeAndNeverOwnsTheService()
    {
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            var requests = new List<Uri>();
            using var handler = new HealthHandler(requests, ok: true);
            var configuration = new BackendConfiguration(
                RequestedBackendMode.External,
                "remote.example",
                443,
                new Uri("https://remote.example/studio/"),
                "cpu",
                null,
                BackendConfigurationTests.CreatePaths(root),
                "test");
            await using var supervisor = new BackendSupervisor(configuration, handler);

            var status = await supervisor.StartAsync();

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
        var root = BackendConfigurationTests.CreateTemporaryRoot();
        try
        {
            using var handler = new HealthHandler([], ok: false);
            var configuration = new BackendConfiguration(
                RequestedBackendMode.External,
                "127.0.0.1",
                7863,
                new Uri("http://127.0.0.1:7863/"),
                "cpu",
                null,
                BackendConfigurationTests.CreatePaths(root),
                "test");
            await using var supervisor = new BackendSupervisor(configuration, handler);

            var status = await supervisor.StartAsync();

            Assert.AreEqual(BackendLifecycleState.Unavailable, status.State);
            Assert.AreEqual("EXTERNAL_BACKEND_UNAVAILABLE", status.FailureCode);
        }
        finally
        {
            BackendConfigurationTests.DeleteTemporaryRoot(root);
        }
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
