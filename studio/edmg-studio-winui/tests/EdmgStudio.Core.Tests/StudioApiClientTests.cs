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

    [TestMethod]
    public async Task TimelineRecoveryAndSecrets_UseExactBackendRequestBodies()
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
            return JsonResponse("""{"ok":true}""");
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);
        using var timeline = JsonDocument.Parse("""{"layers":[{"id":"layer-1"}]}""");
        using var metadata = JsonDocument.Parse("""{"playhead":12.5}""");

        await client.AutosaveTimelineAsync(
            "project one",
            timeline.RootElement.Clone(),
            metadata.RootElement.Clone(),
            "interval");
        await client.ApplyRecoveryAsync(
            "project one",
            new RecoveryApplyRequest("snapshot", "snapshot-2026-08-12"));
        await client.SetSecretAsync("foundry_api_key", "secret-value");
        await client.ClearSecretAsync("foundry_api_key");

        var autosave = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/autosave", StringComparison.Ordinal));
        Assert.AreEqual("/v1/projects/project%20one/autosave", autosave.Uri.AbsolutePath);
        Assert.IsNotNull(autosave.Authorization);
        using (var payload = JsonDocument.Parse(autosave.Body))
        {
            Assert.IsTrue(payload.RootElement.TryGetProperty("meta", out var serializedMetadata));
            Assert.AreEqual(12.5, serializedMetadata.GetProperty("playhead").GetDouble());
            Assert.IsFalse(payload.RootElement.TryGetProperty("metadata", out _));
            Assert.AreEqual(
                "layer-1",
                payload.RootElement.GetProperty("timeline").GetProperty("layers")[0].GetProperty("id").GetString());
        }

        var recovery = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/recovery/apply", StringComparison.Ordinal));
        using (var payload = JsonDocument.Parse(recovery.Body))
        {
            Assert.AreEqual("snapshot", payload.RootElement.GetProperty("source").GetString());
            Assert.AreEqual("snapshot-2026-08-12", payload.RootElement.GetProperty("snapshot_name").GetString());
            Assert.IsFalse(payload.RootElement.TryGetProperty("prefer_journal", out _));
        }

        var setSecret = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/secrets/set", StringComparison.Ordinal));
        using (var payload = JsonDocument.Parse(setSecret.Body))
        {
            Assert.AreEqual("foundry_api_key", payload.RootElement.GetProperty("name").GetString());
            Assert.AreEqual("secret-value", payload.RootElement.GetProperty("value").GetString());
            Assert.IsFalse(payload.RootElement.TryGetProperty("key", out _));
        }

        var clearSecret = captured.Single(item => item.Uri.AbsolutePath.EndsWith("/secrets/clear", StringComparison.Ordinal));
        using (var payload = JsonDocument.Parse(clearSecret.Body))
        {
            Assert.AreEqual("foundry_api_key", payload.RootElement.GetProperty("name").GetString());
            Assert.IsFalse(payload.RootElement.TryGetProperty("key", out _));
        }
    }

    [TestMethod]
    public async Task GetJobsAsync_PreservesProgressAndExposesValidActions()
    {
        using var httpClient = new HttpClient(new RecordingHandler((request, _) =>
        {
            Assert.AreEqual("/v1/jobs", request.RequestUri!.AbsolutePath);
            return Task.FromResult(JsonResponse(
                """
                {
                  "jobs": [{
                    "id": "job-42",
                    "project_id": "project-alpha",
                    "type": "internal_video",
                    "status": "running",
                    "created_at": "2026-08-12T08:00:00Z",
                    "progress": {
                      "percent": 37.5,
                      "stage": "render",
                      "message": "Rendering frames",
                      "current": 45,
                      "total": 120
                    }
                  }]
                }
                """));
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        var result = await client.GetJobsAsync();

        var job = result.Jobs.Single();
        Assert.AreEqual("job-42", job.Id);
        Assert.IsTrue(job.IsActive);
        Assert.IsTrue(job.CanCancel);
        Assert.IsFalse(job.CanRetry);
        Assert.AreEqual(37.5, job.Progress?.Percent);
    }

    [TestMethod]
    public async Task DownloadProjectFileAsync_UsesAuthenticationEscapingAndPreservesBytes()
    {
        byte[] expected = [0x00, 0x7F, 0x80, 0xFF];
        CapturedRequest? captured = null;
        using var httpClient = new HttpClient(new RecordingHandler(async (request, _) =>
        {
            captured = new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync());
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(expected)
            };
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        var actual = await client.DownloadProjectFileAsync("project /#1", "renders/final take #1.mp4");

        CollectionAssert.AreEqual(expected, actual);
        Assert.IsNotNull(captured);
        Assert.AreEqual(HttpMethod.Get, captured.Method);
        Assert.AreEqual("/v1/projects/project%20%2F%231/file", captured.Uri.AbsolutePath);
        Assert.AreEqual("?path=renders%2Ffinal%20take%20%231.mp4", captured.Uri.Query);
        Assert.IsNotNull(captured.Authorization);
    }

    [TestMethod]
    public async Task ModelActions_UseExactPathsAndBodies()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, _) =>
        {
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync()));
            return JsonResponse("""{"ok":true}""");
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        await client.AcceptModelLicenseAsync("model /#1", "license /#1");
        await client.RestoreLocalModelAsync("local /#2");

        Assert.HasCount(2, captured);
        Assert.AreEqual("/v1/models/accept", captured[0].Uri.AbsolutePath);
        Assert.AreEqual("""{"model_id":"model /#1","license_id":"license /#1"}""", captured[0].Body);
        Assert.AreEqual("/v1/models/restore_local", captured[1].Uri.AbsolutePath);
        Assert.AreEqual("""{"model_id":"local /#2"}""", captured[1].Body);
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
