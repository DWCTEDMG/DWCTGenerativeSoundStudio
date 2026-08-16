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
    public async Task QueueTimelineRenderAsync_UsesTypedAuthenticatedContract()
    {
        CapturedRequest? captured = null;
        using var httpClient = new HttpClient(new RecordingHandler(async (request, cancellationToken) =>
        {
            captured = new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                await request.Content!.ReadAsStringAsync(cancellationToken));
            return JsonResponse(
                """
                {
                  "ok": true,
                  "job": {
                    "id": "timeline-job",
                    "project_id": "project one",
                    "type": "timeline_render",
                    "status": "queued"
                  }
                }
                """);
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        var response = await client.QueueTimelineRenderAsync(
            "project one",
            new TimelineRenderRequest(1920, 1080, 24, "H264", "AAC", "high", "edited-master"));

        Assert.IsTrue(response.Ok);
        Assert.AreEqual("timeline-job", response.Job.Id);
        Assert.IsNotNull(captured);
        Assert.AreEqual(HttpMethod.Post, captured.Method);
        Assert.AreEqual("/v1/projects/project%20one/timeline/render", captured.Uri.AbsolutePath);
        Assert.AreEqual("Bearer session-token", captured.Authorization);
        Assert.AreEqual("application/json", captured.ContentType);
        using var payload = JsonDocument.Parse(captured.Body);
        Assert.AreEqual(1920, payload.RootElement.GetProperty("width").GetInt32());
        Assert.AreEqual(1080, payload.RootElement.GetProperty("height").GetInt32());
        Assert.AreEqual(24, payload.RootElement.GetProperty("fps").GetDouble());
        Assert.AreEqual("h264", payload.RootElement.GetProperty("video_codec").GetString());
        Assert.AreEqual("aac", payload.RootElement.GetProperty("audio_codec").GetString());
        Assert.AreEqual("high", payload.RootElement.GetProperty("quality").GetString());
        Assert.AreEqual("edited-master", payload.RootElement.GetProperty("name").GetString());
    }

    [TestMethod]
    public async Task InvalidTimelineRenderRequests_AreRejectedBeforeNetworkUse()
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

        await Assert.ThrowsExactlyAsync<ArgumentOutOfRangeException>(() => client.QueueTimelineRenderAsync(
            "p1",
            new TimelineRenderRequest(1919, 1080, 24, "h264", "aac", "high", "master")));
        await Assert.ThrowsExactlyAsync<ArgumentException>(() => client.QueueTimelineRenderAsync(
            "p1",
            new TimelineRenderRequest(1920, 1080, 24, "prores", "aac", "high", "master")));
        await Assert.ThrowsExactlyAsync<ArgumentException>(() => client.QueueTimelineRenderAsync(
            "p1",
            new TimelineRenderRequest(1920, 1080, 24, "h264", "aac", "ultra", "master")));
        await Assert.ThrowsExactlyAsync<ArgumentException>(() => client.QueueTimelineRenderAsync(
            "p1",
            new TimelineRenderRequest(1920, 1080, 24, "h264", "aac", "high", "../master")));

        Assert.AreEqual(0, callCount);
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
    public async Task QueueRecoveryActions_UseExactProjectJobRoutes()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, cancellationToken) =>
        {
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                request.Content is null
                    ? string.Empty
                    : await request.Content.ReadAsStringAsync(cancellationToken)));
            return JsonResponse("""{"ok":true}""");
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        await client.ResumeJobFromCheckpointAsync("project one", "job one");
        await client.RestartJobCleanAsync("project one", "job one");
        await client.ClearJobCachedFramesAsync("project one", "job one");
        await client.DropJobCheckpointAsync("project one", "job one");

        var expectedPaths = new[]
        {
            "/v1/projects/project%20one/jobs/job%20one/resume_from_checkpoint",
            "/v1/projects/project%20one/jobs/job%20one/restart_clean",
            "/v1/projects/project%20one/jobs/job%20one/clear_cached_frames",
            "/v1/projects/project%20one/jobs/job%20one/drop_checkpoint",
        };
        CollectionAssert.AreEqual(expectedPaths, captured.Select(item => item.Uri.AbsolutePath).ToArray());
        Assert.IsTrue(captured.All(item => item.Method == HttpMethod.Post));
        Assert.IsTrue(captured.All(item => item.Authorization == "Bearer session-token"));
        Assert.IsTrue(captured.All(item => item.ContentType == "application/json"));
        Assert.IsTrue(captured.All(item => item.Body == "{}"));
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
    public async Task StreamProjectFileAsync_KeepsResponseAliveForAuthenticatedCallbackThenDisposesIt()
    {
        byte[] expected = [0x01, 0x02, 0xFE, 0xFF];
        var content = new TrackingContent(expected);
        string? authorization = null;
        using var httpClient = new HttpClient(new RecordingHandler((request, _) =>
        {
            authorization = request.Headers.Authorization?.ToString();
            var response = new HttpResponseMessage(HttpStatusCode.OK) { Content = content };
            response.Headers.TryAddWithoutValidation("X-Preview-Source", "stream");
            return Task.FromResult(response);
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("stream-token"),
            httpClient);

        var actual = await client.StreamProjectFileAsync(
            "p1",
            "renders/preview.png",
            async (file, cancellationToken) =>
            {
                Assert.IsFalse(content.IsDisposed);
                Assert.AreEqual(HttpStatusCode.OK, file.StatusCode);
                Assert.AreEqual(expected.Length, file.ContentHeaders.ContentLength);
                Assert.AreEqual("stream", file.ResponseHeaders.GetValues("X-Preview-Source").Single());

                using var copy = new MemoryStream();
                await file.Stream.CopyToAsync(copy, cancellationToken);
                Assert.IsFalse(content.IsDisposed);
                return copy.ToArray();
            });

        CollectionAssert.AreEqual(expected, actual);
        Assert.AreEqual("Bearer stream-token", authorization);
        Assert.IsTrue(content.IsDisposed);
        Assert.IsTrue(content.Stream.IsDisposed);
    }

    [TestMethod]
    public async Task StreamProjectFileAsync_CancellationDisposesTheResponseLifetime()
    {
        var content = new TrackingContent([0x01]);
        using var httpClient = new HttpClient(new RecordingHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content })));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("stream-token"),
            httpClient);
        using var cancellation = new CancellationTokenSource();

        var streaming = client.StreamProjectFileAsync(
            "p1",
            "renders/preview.png",
            async (_, cancellationToken) =>
            {
                cancellation.Cancel();
                await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                return false;
            },
            cancellation.Token);

        await Assert.ThrowsAsync<OperationCanceledException>(async () => await streaming);
        Assert.IsTrue(content.IsDisposed);
        Assert.IsTrue(content.Stream.IsDisposed);
    }

    [TestMethod]
    public async Task StreamTimelineFrameAsync_UsesAuthenticatedExactQueryAndCallbackLifetime()
    {
        byte[] expected = [0x89, 0x50, 0x4E, 0x47];
        var content = new TrackingContent(expected);
        CapturedRequest? captured = null;
        using var httpClient = new HttpClient(new RecordingHandler((request, _) =>
        {
            captured = new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                string.Empty);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("stream-token"),
            httpClient);

        var actual = await client.StreamTimelineFrameAsync(
            "project /#1",
            1.25,
            768,
            432,
            force: false,
            async (file, cancellationToken) =>
            {
                Assert.IsFalse(content.IsDisposed);
                using var copy = new MemoryStream();
                await file.Stream.CopyToAsync(copy, cancellationToken);
                return copy.ToArray();
            });

        CollectionAssert.AreEqual(expected, actual);
        Assert.IsNotNull(captured);
        Assert.AreEqual(HttpMethod.Get, captured.Method);
        Assert.AreEqual("/v1/projects/project%20%2F%231/preview/frame", captured.Uri.AbsolutePath);
        Assert.AreEqual("?t=1.25&w=768&h=432&force=0", captured.Uri.Query);
        Assert.AreEqual("Bearer " + "stream" + "-token", captured.Authorization);
        Assert.IsTrue(content.IsDisposed);
        Assert.IsTrue(content.Stream.IsDisposed);
    }

    [TestMethod]
    public async Task StreamTimelineFrameAsync_CancellationDisposesTheResponseLifetime()
    {
        var content = new TrackingContent([0x01]);
        using var httpClient = new HttpClient(new RecordingHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content })));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("stream-token"),
            httpClient);
        using var cancellation = new CancellationTokenSource();

        var streaming = client.StreamTimelineFrameAsync(
            "p1",
            0,
            768,
            432,
            force: false,
            async (_, cancellationToken) =>
            {
                cancellation.Cancel();
                await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                return false;
            },
            cancellation.Token);

        await Assert.ThrowsAsync<OperationCanceledException>(async () => await streaming);
        Assert.IsTrue(content.IsDisposed);
        Assert.IsTrue(content.Stream.IsDisposed);
    }

    [TestMethod]
    public void StreamTimelineFrameAsync_RejectsInvalidGeometryBeforeNetworkUse()
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

        Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
            client.StreamTimelineFrameAsync(
                "p1",
                double.NaN,
                768,
                432,
                false,
                (_, _) => Task.FromResult(true)));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
            client.StreamTimelineFrameAsync(
                "p1",
                0,
                0,
                432,
                false,
                (_, _) => Task.FromResult(true)));
        Assert.AreEqual(0, callCount);
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

    [TestMethod]
    public async Task ModelTasks_DeserializeProgressAndPresentationState()
    {
        using var httpClient = new HttpClient(new RecordingHandler((request, _) =>
        {
            Assert.AreEqual(HttpMethod.Get, request.Method);
            Assert.AreEqual("/v1/models/tasks", request.RequestUri!.AbsolutePath);
            return Task.FromResult(JsonResponse(
                """
                {"tasks":[{"id":"task-1","name":"Install model","status":"running","progress":1.4,"last_log":"Downloading","error":null,"started_at":1.0,"ended_at":null,"model_id":"sd15","stage":null,"bytes_completed":1024,"bytes_total":2048,"files_completed":1,"files_total":2,"cancel_requested":false}]}
                """));
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider(null),
            httpClient);

        var response = await client.GetModelTasksAsync();
        IReadOnlyList<ModelTask> tasks = response.Tasks!;
        var task = tasks.Single();

        Assert.IsTrue(task.IsActive);
        Assert.AreEqual(1d, task.ClampedProgress);
        Assert.AreEqual("Downloading", task.DisplayStage);
        Assert.AreEqual("task-1:running", ModelTask.Fingerprint(tasks));
    }

    [TestMethod]
    public async Task ModelManagement_UsesExactPathsBodiesAndTypedResponses()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, cancellationToken) =>
        {
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken)));

            return request.RequestUri!.AbsolutePath switch
            {
                "/v1/models/benchmark" => JsonResponse("""{"ok":true,"benchmark":{"passed":true}}"""),
                "/v1/models/import/civitai" => JsonResponse("""{"entry":{"id":"civitai-model"}}"""),
                "/v1/models/import/local" => JsonResponse("""{"entry":{"id":"local-model"}}"""),
                "/v1/models/tensorrt/cancel-import" => JsonResponse(ModelTaskActionJson),
                "/v1/models/tensorrt/import-legacy" => JsonResponse(ModelTaskActionJson),
                _ => throw new InvalidOperationException(request.RequestUri.AbsolutePath)
            };
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        var benchmark = await client.RecordModelBenchmarkAsync("model-1");
        var civitai = await client.ImportCivitaiModelAsync("https://civitai.com/models/1");
        var local = await client.ImportLocalModelAsync(@"C:\models\model.safetensors", "checkpoints");
        var migration = await client.ImportLegacyTensorRtAsync();
        var cancellation = await client.CancelLegacyTensorRtImportAsync("task-1");

        Assert.IsTrue(benchmark.Ok);
        Assert.AreEqual("civitai-model", civitai.Entry.GetProperty("id").GetString());
        Assert.AreEqual("local-model", local.Entry.GetProperty("id").GetString());
        Assert.AreEqual("task-1", migration.Task.Id);
        Assert.AreEqual("task-1", cancellation.Task.Id);
        Assert.AreEqual(
            """
            {"model_id":"model-1","summary":"manual_ui_benchmark","passed":true,"metrics":{"source":"models_page"}}
            """,
            captured[0].Body);
        Assert.AreEqual("""{"url":"https://civitai.com/models/1"}""", captured[1].Body);
        Assert.AreEqual("""{"file_path":"C:\\models\\model.safetensors","folder":"checkpoints"}""", captured[2].Body);
        Assert.AreEqual("{}", captured[3].Body);
        Assert.AreEqual("""{"task_id":"task-1"}""", captured[4].Body);
    }

    [TestMethod]
    public async Task PlannerAndReactiveLabs_UseAuthenticatedPreparedPayloadContracts()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, cancellationToken) =>
        {
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                await request.Content!.ReadAsStringAsync(cancellationToken)));
            return JsonResponse("""{"ok":true}""");
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);
        using var planner = JsonDocument.Parse(
            """{"analysis":{"basicInfo":{"title":"Signal"}},"plan":{"scenes":[{"id":"scene-1"}]},"settings":{"sceneCount":4},"apply_timeline":true,"overwrite_timeline":false}""");
        using var reactive = JsonDocument.Parse(
            """{"metadata":{"preset":"cinematic"},"keyframes":[{"frame":24}],"overwrite_motion_track":true,"overwrite_camera":false}""");

        await client.ImportPlannerLabAsync("project / one", planner.RootElement.Clone());
        await client.ApplyReactiveLabAsync("project / one", reactive.RootElement.Clone());

        Assert.HasCount(2, captured);
        Assert.IsTrue(captured.All(item => item.Method == HttpMethod.Post));
        Assert.IsTrue(captured.All(item =>
            item.Authorization is not null
            && item.Authorization.StartsWith("Bearer ", StringComparison.Ordinal)
            && item.Authorization.EndsWith("-token", StringComparison.Ordinal)));
        Assert.IsTrue(captured.All(item => item.ContentType == "application/json"));
        Assert.AreEqual(
            "/v1/projects/project%20%2F%20one/planner_lab/import",
            captured[0].Uri.AbsolutePath);
        Assert.AreEqual(
            "/v1/projects/project%20%2F%20one/reactive_lab/apply",
            captured[1].Uri.AbsolutePath);

        using (var payload = JsonDocument.Parse(captured[0].Body))
        {
            Assert.AreEqual("Signal", payload.RootElement.GetProperty("analysis").GetProperty("basicInfo").GetProperty("title").GetString());
            Assert.AreEqual("scene-1", payload.RootElement.GetProperty("plan").GetProperty("scenes")[0].GetProperty("id").GetString());
            Assert.AreEqual(4, payload.RootElement.GetProperty("settings").GetProperty("sceneCount").GetInt32());
            Assert.IsTrue(payload.RootElement.GetProperty("apply_timeline").GetBoolean());
            Assert.IsFalse(payload.RootElement.GetProperty("overwrite_timeline").GetBoolean());
        }

        using (var payload = JsonDocument.Parse(captured[1].Body))
        {
            Assert.AreEqual("cinematic", payload.RootElement.GetProperty("metadata").GetProperty("preset").GetString());
            Assert.AreEqual(24, payload.RootElement.GetProperty("keyframes")[0].GetProperty("frame").GetInt32());
            Assert.IsTrue(payload.RootElement.GetProperty("overwrite_motion_track").GetBoolean());
            Assert.IsFalse(payload.RootElement.GetProperty("overwrite_camera").GetBoolean());
        }
    }

    [TestMethod]
    public async Task CloudOperations_UseAuthenticatedJsonContracts()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, cancellationToken) =>
        {
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken)));
            return JsonResponse("""{"ok":true,"settings":{"enabled":true}}""");
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);
        using var awsTest = JsonDocument.Parse("""{"bucket":"studio-assets"}""");
        using var awsBundle = JsonDocument.Parse("""{"bucket":"studio-assets","key":"bundles/project.zip"}""");
        using var azureTest = JsonDocument.Parse("""{"container":"model-cache","prefix":"models"}""");
        using var hfSettings = JsonDocument.Parse(
            """{"enabled":true,"bucket":"hf-cache","prefix":"weights","storage_mode":"cloud_only"}""");
        using var hfTest = JsonDocument.Parse("""{"bucket":"hf-cache","prefix":"weights"}""");
        using var lightning = JsonDocument.Parse("""{"output_dir":"lightning/bundle"}""");

        await client.TestAwsCloudAsync(awsTest.RootElement.Clone());
        await client.BundleAwsCloudAsync(awsBundle.RootElement.Clone());
        await client.TestAzureCloudAsync(azureTest.RootElement.Clone());
        await client.GetHuggingFaceCloudSettingsAsync();
        await client.SaveHuggingFaceCloudSettingsAsync(hfSettings.RootElement.Clone());
        await client.TestHuggingFaceCloudAsync(hfTest.RootElement.Clone());
        await client.BundleLightningCloudAsync(lightning.RootElement.Clone());

        Assert.HasCount(7, captured);
        Assert.IsTrue(captured.All(item =>
            item.Authorization is not null
            && item.Authorization.StartsWith("Bearer ", StringComparison.Ordinal)
            && item.Authorization.EndsWith("-token", StringComparison.Ordinal)));
        Assert.AreEqual(
            "POST /v1/cloud/aws/test|POST /v1/cloud/aws/bundle|POST /v1/cloud/azure/test|GET /v1/cloud/hf/settings|POST /v1/cloud/hf/settings|POST /v1/cloud/hf/test|POST /v1/cloud/lightning/bundle",
            string.Join("|", captured.Select(item => $"{item.Method.Method} {item.Uri.AbsolutePath}")));
        Assert.IsTrue(captured.Where(item => item.Method == HttpMethod.Post)
            .All(item => item.ContentType == "application/json"));
        Assert.AreEqual(string.Empty, captured.Single(item => item.Method == HttpMethod.Get).Body);

        using (var payload = JsonDocument.Parse(captured[1].Body))
        {
            Assert.AreEqual("studio-assets", payload.RootElement.GetProperty("bucket").GetString());
            Assert.AreEqual("bundles/project.zip", payload.RootElement.GetProperty("key").GetString());
        }

        using (var payload = JsonDocument.Parse(captured[4].Body))
        {
            Assert.IsTrue(payload.RootElement.GetProperty("enabled").GetBoolean());
            Assert.AreEqual("cloud_only", payload.RootElement.GetProperty("storage_mode").GetString());
        }

        using (var payload = JsonDocument.Parse(captured[6].Body))
        {
            Assert.AreEqual("lightning/bundle", payload.RootElement.GetProperty("output_dir").GetString());
        }
    }

    [TestMethod]
    public async Task ForgeProbes_UseAuthenticatedEscapedProjectContracts()
    {
        var captured = new List<CapturedRequest>();
        using var httpClient = new HttpClient(new RecordingHandler((request, _) =>
        {
            captured.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!,
                request.Headers.Authorization?.ToString(),
                request.Content?.Headers.ContentType?.MediaType,
                string.Empty));
            return Task.FromResult(JsonResponse("""{"ok":true}"""));
        }));
        using var client = new StudioApiClient(
            new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")),
            new StaticTokenProvider("session-token"),
            httpClient);

        await client.GetAiStatusAsync();
        await client.GetComfyUiCapabilitiesAsync();
        await client.GetUnrealPreviewAsync("project / one", -3);
        await client.GetUnrealPreviewAsync("project / one", 2);
        await client.GetLiveCuePublishStatusAsync("project / one");

        Assert.HasCount(5, captured);
        Assert.IsTrue(captured.All(item => item.Method == HttpMethod.Get));
        Assert.IsTrue(captured.All(item =>
            item.Authorization is not null
            && item.Authorization.StartsWith("Bearer ", StringComparison.Ordinal)
            && item.Authorization.EndsWith("-token", StringComparison.Ordinal)));
        Assert.AreEqual("/v1/ai/status", captured[0].Uri.AbsolutePath);
        Assert.AreEqual("/v1/comfyui/capabilities", captured[1].Uri.AbsolutePath);
        Assert.AreEqual(
            "/v1/projects/project%20%2F%20one/unreal/preview",
            captured[2].Uri.AbsolutePath);
        Assert.AreEqual("?variant_index=0", captured[2].Uri.Query);
        Assert.AreEqual("?variant_index=2", captured[3].Uri.Query);
        Assert.AreEqual(
            "/v1/projects/project%20%2F%20one/live_cues/publish/status",
            captured[4].Uri.AbsolutePath);
    }

    private static HttpResponseMessage JsonResponse(string json, HttpStatusCode statusCode = HttpStatusCode.OK) => new(statusCode)
    {
        Content = new StringContent(json, Encoding.UTF8, "application/json")
    };

    private const string ProjectListJson =
        """{"projects":[{"id":"p1","name":"Existing","created_at":"2026-08-12 08:00:00","meta":{},"schema_version":1}]}""";

    private const string ProjectResponseJson =
        """{"project":{"id":"p1","name":"Native Project","created_at":"2026-08-12 08:00:00","meta":{},"schema_version":1},"visual_dna":{},"visual_dna_hints":{}}""";

    private const string ModelTaskActionJson =
        """{"task":{"id":"task-1","name":"Import TensorRT","status":"queued","progress":0.0,"last_log":null,"error":null,"started_at":null,"ended_at":null,"model_id":"local_sd15_tensorrt_bundle","stage":"queued","bytes_completed":0,"bytes_total":null,"files_completed":0,"files_total":null,"cancel_requested":false}}""";

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

    private sealed class TrackingContent : HttpContent
    {
        private readonly byte[] _bytes;

        public TrackingContent(byte[] bytes)
        {
            _bytes = bytes;
            Headers.ContentLength = bytes.Length;
            Stream = new TrackingStream(bytes);
        }

        public bool IsDisposed { get; private set; }

        public TrackingStream Stream { get; }

        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) =>
            stream.WriteAsync(_bytes).AsTask();

        protected override bool TryComputeLength(out long length)
        {
            length = _bytes.Length;
            return true;
        }

        protected override Task<Stream> CreateContentReadStreamAsync() =>
            Task.FromResult<Stream>(Stream);

        protected override void Dispose(bool disposing)
        {
            IsDisposed = true;
            base.Dispose(disposing);
        }
    }

    private sealed class TrackingStream(byte[] bytes) : MemoryStream(bytes)
    {
        public bool IsDisposed { get; private set; }

        protected override void Dispose(bool disposing)
        {
            IsDisposed = true;
            base.Dispose(disposing);
        }
    }
}
