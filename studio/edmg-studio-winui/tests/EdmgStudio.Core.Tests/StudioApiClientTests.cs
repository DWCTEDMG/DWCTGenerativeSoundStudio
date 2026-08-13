using System.Net;
using System.Text;
using System.Text.Json;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioApiClientTests
{
    [TestMethod]
    public async Task ProjectWorkflow_UsesTheExactStudioHttpContract()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, cancellationToken) =>
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken);
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                body));

            return (request.Method.Method, request.RequestUri!.AbsolutePath) switch
            {
                ("GET", "/health") => JsonResponse("""{"ok":true,"version":"1.2.0"}"""),
                ("GET", "/v1/projects") => JsonResponse(ProjectListJson),
                ("POST", "/v1/projects") => JsonResponse(ProjectResponseJson),
                ("GET", "/v1/projects/p1") => JsonResponse(ProjectResponseJson),
                ("POST", "/v1/projects/p1/assets/audio") => JsonResponse("""{"ok":true}"""),
                ("POST", "/v1/projects/p1/analyze_audio") => JsonResponse("""{"ok":true,"analysis":{"features":{"bpm":128}}}"""),
                ("POST", "/v1/projects/p1/plan") => JsonResponse("""{"source":"local","duration_s":30,"variants":[{"index":0,"scenes":[]}]}"""),
                _ => new HttpResponseMessage(HttpStatusCode.NotFound)
            };
        }));
        var endpoint = new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/"));
        using var client = new StudioApiClient(endpoint, new StaticTokenProvider("test-token"), httpClient);

        var health = await client.GetHealthAsync();
        var projects = await client.GetProjectsAsync();
        var created = await client.CreateProjectAsync("  Native Project  ");
        var project = await client.GetProjectAsync("p1");
        await using var audio = new MemoryStream(Encoding.UTF8.GetBytes("audio-payload"));
        await client.UploadAudioAsync("p1", audio, "track.wav", "audio/wav");
        var analysis = await client.AnalyzeAudioAsync("p1");
        var plan = await client.GeneratePlanAsync(
            "p1",
            new PlanRequest("Native Project", "Keep the drop", "cinematic", 2, 8),
            "local");

        Assert.IsTrue(health.Ok);
        Assert.AreEqual("p1", projects.Projects.Single().Id);
        Assert.AreEqual("p1", created.Project.Id);
        Assert.AreEqual("p1", project.Project.Id);
        Assert.IsTrue(analysis.Ok);
        Assert.AreEqual("local", plan.Source);

        Assert.IsNull(captured.Single(item => item.Uri.AbsolutePath == "/health").Authorization);
        Assert.IsTrue(captured.Where(item => item.Uri.AbsolutePath != "/health")
            .All(item => item.Authorization == "Bearer test-token"));

        var createRequest = captured.Single(item => item.Method == HttpMethod.Post && item.Uri.AbsolutePath == "/v1/projects");
        using (var createJson = JsonDocument.Parse(createRequest.Body))
        {
            Assert.AreEqual("Native Project", createJson.RootElement.GetProperty("name").GetString());
        }

        var uploadRequest = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/assets/audio", StringComparison.Ordinal));
        Assert.AreEqual("multipart/form-data", uploadRequest.ContentType);
        StringAssert.Contains(uploadRequest.Body, "name=file");
        StringAssert.Contains(uploadRequest.Body, "filename=track.wav");
        StringAssert.Contains(uploadRequest.Body, "audio-payload");

        var analyzeRequest = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/analyze_audio", StringComparison.Ordinal));
        Assert.AreEqual("{}", analyzeRequest.Body);

        var planRequest = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/plan", StringComparison.Ordinal));
        Assert.AreEqual("?mode=local", planRequest.Uri.Query);
        using (var planJson = JsonDocument.Parse(planRequest.Body))
        {
            Assert.AreEqual(2, planJson.RootElement.GetProperty("num_variants").GetInt32());
            Assert.AreEqual(8, planJson.RootElement.GetProperty("max_scenes").GetInt32());
            Assert.AreEqual("cinematic", planJson.RootElement.GetProperty("style_prefs").GetString());
        }
    }

    [TestMethod]
    public async Task ErrorEnvelope_BecomesAnActionableStudioException()
    {
        using var httpClient = new HttpClient(new RecordingHandler((_, _) => Task.FromResult(
            JsonResponse(
                """{"error":{"code":"AUDIO_REQUIRED","message":"Audio is required.","hint":"Upload a track first."}}""",
                HttpStatusCode.UnprocessableEntity))));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider(null),
            httpClient);

        var exception = await Assert.ThrowsExactlyAsync<StudioApiException>(() => client.GetProjectsAsync());

        Assert.AreEqual(HttpStatusCode.UnprocessableEntity, exception.StatusCode);
        Assert.AreEqual("AUDIO_REQUIRED", exception.Code);
        Assert.AreEqual("Audio is required. Upload a track first.", exception.UserFacingMessage);
    }

    [TestMethod]
    public async Task InvalidProjectAndPlanInputs_AreRejectedBeforeNetworkUse()
    {
        var callCount = 0;
        using var httpClient = new HttpClient(new RecordingHandler((_, _) =>
        {
            callCount++;
            return Task.FromResult(JsonResponse("{}"));
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider(null),
            httpClient);

        await Assert.ThrowsExactlyAsync<ArgumentException>(() => client.CreateProjectAsync("   "));
        await Assert.ThrowsExactlyAsync<ArgumentOutOfRangeException>(() => client.GeneratePlanAsync(
            "p1",
            new PlanRequest(null, null, null, 11, 12)));
        Assert.AreEqual(0, callCount);
    }

    private static HttpResponseMessage JsonResponse(string json, HttpStatusCode statusCode = HttpStatusCode.OK) => new(statusCode)
    {
        Content = new StringContent(json, Encoding.UTF8, "application/json")
    };

    private const string ProjectListJson =
        """{"projects":[{"id":"p1","name":"Existing","created_at":"2026-08-12 08:00:00","meta":{},"schema_version":1}]}""";

    private const string ProjectResponseJson =
        """{"project":{"id":"p1","name":"Native Project","created_at":"2026-08-12 08:00:00","meta":{},"schema_version":1},"visual_dna":{},"visual_dna_hints":{}}""";

    private sealed record CapturedRequest(
        HttpMethod Method,
        Uri Uri,
        string? Authorization,
        string? ContentType,
        string Body);

    private sealed class StaticEndpointProvider(Uri backendUri) : IBackendEndpointProvider
    {
        public Uri CurrentBackendUri { get; } = backendUri;
    }

    private sealed class StaticTokenProvider(string? token) : IBackendTokenProvider
    {
        public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default) =>
            ValueTask.FromResult(token);
    }

    private sealed class RecordingHandler(
        Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> callback) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            callback(request, cancellationToken);
    }
}
