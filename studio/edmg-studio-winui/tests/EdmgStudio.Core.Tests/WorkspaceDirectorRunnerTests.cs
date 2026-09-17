using System.Net;
using System.Text;
using System.Text.Json;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WorkspaceDirectorRunnerTests
{
    [TestMethod]
    public async Task SuccessfulJobIsReviewedAtExpectedRevisionAndNeverApplied()
    {
        int polls = 0;
        var requests = new List<string>();
        using var http = new HttpClient(new Handler(async (request, token) =>
        {
            string path = request.RequestUri!.AbsolutePath;
            requests.Add(path);
            if (path.EndsWith("/jobs"))
                return Json(Jobs(++polls == 1 ? "running" : "succeeded"));
            Assert.IsTrue(path.EndsWith("/drafts/job-1/review"));
            using var body = JsonDocument.Parse(await request.Content!.ReadAsStringAsync(token));
            Assert.AreEqual(12, body.RootElement.GetProperty("expected_revision").GetInt32());
            return Json("""{"revision":13,"document":{"scenes":[]}}""");
        }));
        using var api = new StudioApiClient(new Endpoint(), new Token(), http);
        var progress = new List<string>();
        var result = await new WorkspaceDirectorRunner(api).WaitForReviewAsync("p1", "job-1", 12,
            job => progress.Add(job.Status), pollInterval: TimeSpan.Zero);
        Assert.AreEqual(13, result.GetProperty("revision").GetInt32());
        CollectionAssert.AreEqual(new[] { "running", "succeeded" }, progress);
        Assert.IsFalse(requests.Any(path => path.EndsWith("/apply")));
    }

    [TestMethod]
    [DataRow("failed")]
    [DataRow("canceled")]
    public async Task FailedOrCanceledJobIsNeverReviewed(string status)
    {
        using var http = new HttpClient(new Handler((request, _) =>
        {
            Assert.IsTrue(request.RequestUri!.AbsolutePath.EndsWith("/jobs"));
            return Task.FromResult(Json(Jobs(status)));
        }));
        using var api = new StudioApiClient(new Endpoint(), new Token(), http);
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new WorkspaceDirectorRunner(api).WaitForReviewAsync("p1", "job-1", 12));
    }

    [TestMethod]
    public async Task CancelWhileWaitingDoesNotReviewOrApply()
    {
        using var cancellation = new CancellationTokenSource();
        using var http = new HttpClient(new Handler((request, _) =>
        {
            Assert.IsTrue(request.RequestUri!.AbsolutePath.EndsWith("/jobs"));
            return Task.FromResult(Json(Jobs("running")));
        }));
        using var api = new StudioApiClient(new Endpoint(), new Token(), http);
        await Assert.ThrowsAsync<TaskCanceledException>(() =>
            new WorkspaceDirectorRunner(api).WaitForReviewAsync("p1", "job-1", 12,
                _ => cancellation.Cancel(), cancellation.Token));
    }

    [TestMethod]
    public void SelectedQwenModelIsSerializedWithoutChangingLegacyRequests()
    {
        var legacy = JsonSerializer.SerializeToElement(new DirectorGenerationRequest(12, "op", "Direct"));
        Assert.IsFalse(legacy.TryGetProperty("model_id", out _));
        var selected = JsonSerializer.SerializeToElement(new DirectorGenerationRequest(12, "op", "Direct",
            ModelId: "hf_qwen3_vl_30b_gguf_director"));
        Assert.AreEqual("hf_qwen3_vl_30b_gguf_director", selected.GetProperty("model_id").GetString());
    }

    private static string Jobs(string status) => $$"""
        {"jobs":[{"id":"job-1","project_id":"p1","type":"qwen_director","status":"{{status}}"}]}
        """;
    private static HttpResponseMessage Json(string value) => new(HttpStatusCode.OK)
        { Content = new StringContent(value, Encoding.UTF8, "application/json") };
    private sealed class Endpoint : IBackendEndpointProvider
    {
        public Uri CurrentBackendUri { get; } = new("http://127.0.0.1:7863/");
    }
    private sealed class Token : IBackendTokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<string?>(null);
    }
    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> respond) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => respond(request, cancellationToken);
    }
}
