using System.Net;
using System.Text.Json;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class DirectorReviewContractsTests
{
    private const string ReportId = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    [TestMethod]
    public void Presentation_DistinguishesUnassessedScoresAndEligibility()
    {
        ReviewReport report = CreateReport("recommended", "proposed");
        Assert.AreEqual("Not assessed", DirectorReviewPresentation.FormatScore(null, "not_assessed"));
        Assert.AreEqual("Not assessed", DirectorReviewPresentation.FormatScore(0, "not_assessed"));
        Assert.AreEqual("75%", DirectorReviewPresentation.FormatThreshold(0.75));
        Assert.IsTrue(DirectorReviewPresentation.CanRunNextAttempt(report));
        Assert.IsTrue(DirectorReviewPresentation.CanApplyCorrection(report));
        Assert.IsFalse(DirectorReviewPresentation.CanRunNextAttempt(CreateReport("approved", "not_needed")));
        Assert.IsFalse(DirectorReviewPresentation.CanRunNextAttempt(CreateReport("exhausted", "proposed")));
        Assert.IsFalse(DirectorReviewPresentation.CanApplyCorrection(CreateReport("recommended", "applied")));
    }

    [TestMethod]
    public async Task Client_UsesExactDirectorReviewRoutesAndSnakeCasePayloads()
    {
        var requests = new List<(HttpMethod Method, Uri Uri, string Body)>();
        using var httpClient = new HttpClient(new RecordingHandler(async (request, token) =>
        {
            requests.Add((request.Method, request.RequestUri!, request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(token)));
            return request.RequestUri!.AbsolutePath.EndsWith("/apply", StringComparison.Ordinal) ? JsonResponse(ApplyJson)
                : request.Method == HttpMethod.Get && request.RequestUri.AbsolutePath.EndsWith("/reviews", StringComparison.Ordinal) ? JsonResponse(ListJson)
                : JsonResponse(ResponseJson);
        }));
        using var client = new StudioApiClient(new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")), new StaticTokenProvider("token"), httpClient);
        var request = new ReviewRequest(4, "renders/final.mp4", 8, 0.8, 3, true, "scene-2", ReportId);

        DirectorReviewResponse created = await client.CreateDirectorReviewAsync("project /1", request);
        DirectorReviewListResponse listed = await client.GetDirectorReviewsAsync("project /1");
        DirectorReviewResponse loaded = await client.GetDirectorReviewAsync("project /1", ReportId);
        DirectorReviewApplyResponse applied = await client.ApplyDirectorReviewCorrectionAsync("project /1", ReportId, new ApplyCorrectionRequest(4));

        Assert.AreEqual(ReportId, created.Report.ReportId);
        Assert.AreEqual(1, listed.Reports.Count);
        Assert.AreEqual("not_assessed", loaded.Report.Dimensions[0].State);
        Assert.AreEqual(5L, applied.Revision);
        Assert.AreEqual("/v1/projects/project%20%2F1/director/reviews", requests[0].Uri.AbsolutePath);
        using JsonDocument body = JsonDocument.Parse(requests[0].Body);
        Assert.AreEqual(4L, body.RootElement.GetProperty("expected_revision").GetInt64());
        Assert.AreEqual("renders/final.mp4", body.RootElement.GetProperty("artifact_path").GetString());
        Assert.AreEqual(0.8, body.RootElement.GetProperty("threshold").GetDouble());
        Assert.AreEqual(ReportId, body.RootElement.GetProperty("retry_of_report_id").GetString());
        StringAssert.EndsWith(requests[2].Uri.AbsolutePath, $"/director/reviews/{ReportId}");
        StringAssert.EndsWith(requests[3].Uri.AbsolutePath, $"/director/reviews/{ReportId}/apply");
    }

    [TestMethod]
    public async Task Client_RejectsInvalidDirectorReviewInputsBeforeSending()
    {
        var calls = 0;
        using var httpClient = new HttpClient(new RecordingHandler((_, _) => { calls++; return Task.FromResult(JsonResponse(ResponseJson)); }));
        using var client = new StudioApiClient(new StaticEndpointProvider(new Uri("http://127.0.0.1:7863/")), new StaticTokenProvider(null), httpClient);
        await Assert.ThrowsExactlyAsync<ArgumentOutOfRangeException>(() => client.CreateDirectorReviewAsync("p", new ReviewRequest(1, "a.mp4", 13)));
        await Assert.ThrowsExactlyAsync<ArgumentOutOfRangeException>(() => client.CreateDirectorReviewAsync("p", new ReviewRequest(1, "a.mp4", Threshold: 1.1)));
        await Assert.ThrowsExactlyAsync<ArgumentException>(() => client.GetDirectorReviewAsync("p", "bad-id"));
        await Assert.ThrowsExactlyAsync<ArgumentOutOfRangeException>(() => client.ApplyDirectorReviewCorrectionAsync("p", ReportId, new ApplyCorrectionRequest(0)));
        Assert.AreEqual(0, calls);
    }

    private static ReviewReport CreateReport(string retryResult, string correctionState)
    {
        using JsonDocument document = JsonDocument.Parse("{\"schema_version\":1}");
        return new ReviewReport
        {
            ReportId = ReportId, ProjectId = "p", ProjectRevision = 4, ArtifactPath = "renders/final.mp4",
            Status = "completed", Disposition = "correction_recommended", CreatedAt = "2026-09-12T00:00:00Z", DurationSeconds = 2,
            Dimensions = [new DimensionScore("character_consistency", "not_assessed", null, [])],
            CorrectionPlan = new CorrectionPlan { State = correctionState, DirectorDocument = correctionState == "proposed" ? document.RootElement.Clone() : null },
            Retry = new RetryPolicy(0.75, 3, retryResult == "exhausted" ? 3 : 1, retryResult, []),
            ClipUnderstanding = new ClipUnderstandingResult(false, "disabled", "clip_understanding", "Not requested")
        };
    }

    private const string ReportJson = """
        {"schema_version":1,"report_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","request_fingerprint":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","project_id":"project /1","project_revision":4,"source_draft_id":"draft-1","source_draft_fingerprint":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","retry_chain_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","artifact_path":"renders/final.mp4","artifact_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","artifact_bytes":100,"status":"completed","disposition":"correction_recommended","created_at":"2026-09-12T00:00:00Z","duration_seconds":2,"samples":[{"timestamp_seconds":1,"path":"reviews/frame.jpg","sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","bytes":10}],"dimensions":[{"dimension":"character_consistency","state":"not_assessed","score":null,"evidence":[]}],"aggregate_score":null,"continuity_score":null,"threshold":0.8,"findings":[],"correction_plan":{"state":"proposed","target_scene_id":"scene-2","guidance":["Preserve identity"],"director_document":{"schema_version":1},"applied_revision":null},"retry":{"threshold":0.8,"max_attempts":3,"attempt":1,"result":"recommended","history":[]},"clip_understanding":{"requested":true,"state":"unavailable","capability":"clip_understanding","detail":"Provider unavailable"},"provenance":{}}
        """;
    private const string ResponseJson = "{\"ok\":true,\"replayed\":false,\"report\":" + ReportJson + "}";
    private const string ListJson = "{\"ok\":true,\"reports\":[" + ReportJson + "]}";
    private const string ApplyJson = "{\"ok\":true,\"replayed\":false,\"revision\":5,\"report\":" + ReportJson + "}";

    private static HttpResponseMessage JsonResponse(string json) => new(HttpStatusCode.OK)
    {
        Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json")
    };

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
