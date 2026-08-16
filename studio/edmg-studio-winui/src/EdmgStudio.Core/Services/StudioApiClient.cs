using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization.Metadata;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Services;

public interface IBackendTokenProvider
{
    ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default);
}

public sealed class EnvironmentBackendTokenProvider : IBackendTokenProvider
{
    public ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var token = Environment.GetEnvironmentVariable("EDMG_BACKEND_AUTH_TOKEN");
        if (string.IsNullOrWhiteSpace(token))
        {
            token = Environment.GetEnvironmentVariable("EDMG_STUDIO_BACKEND_AUTH_TOKEN");
        }

        return ValueTask.FromResult<string?>(string.IsNullOrWhiteSpace(token) ? null : token.Trim());
    }
}

/// <summary>
/// Provides callback-scoped access to a streamed project file. The stream and
/// headers are valid only until the callback supplied to
/// <see cref="StudioApiClient.StreamProjectFileAsync{TResult}"/> completes.
/// </summary>
public sealed class StudioFileStream
{
    internal StudioFileStream(
        Stream stream,
        HttpContentHeaders contentHeaders,
        HttpResponseHeaders responseHeaders,
        HttpStatusCode statusCode)
    {
        Stream = stream;
        ContentHeaders = contentHeaders;
        ResponseHeaders = responseHeaders;
        StatusCode = statusCode;
    }

    public Stream Stream { get; }

    public HttpContentHeaders ContentHeaders { get; }

    public HttpResponseHeaders ResponseHeaders { get; }

    public HttpStatusCode StatusCode { get; }
}

public sealed class StudioApiClient : IDisposable
{
    private readonly IBackendEndpointProvider _endpointProvider;
    private readonly IBackendTokenProvider _tokenProvider;
    private readonly HttpClient _httpClient;
    private readonly bool _ownsClient;

    public StudioApiClient(
        IBackendEndpointProvider endpointProvider,
        IBackendTokenProvider tokenProvider,
        HttpClient? httpClient = null)
    {
        _endpointProvider = endpointProvider;
        _tokenProvider = tokenProvider;
        _httpClient = httpClient ?? new HttpClient();
        _ownsClient = httpClient is null;
        _httpClient.Timeout = Timeout.InfiniteTimeSpan;
    }

    public Task<HealthResponse> GetHealthAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync<HealthResponse>(HttpMethod.Get, "/health", null, includeCredentials: false, cancellationToken);

    public Task<ProjectListResponse> GetProjectsAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProjectListResponse>(HttpMethod.Get, "/v1/projects", null, true, cancellationToken);

    public async Task<ProjectResponse> CreateProjectAsync(string name, CancellationToken cancellationToken = default)
    {
        var normalized = (name ?? string.Empty).Trim();
        if (normalized.Length is < 1 or > 200)
        {
            throw new ArgumentException("Project name must contain between 1 and 200 characters.", nameof(name));
        }

        return await SendJsonAsync<ProjectResponse>(
            HttpMethod.Post,
            "/v1/projects",
            JsonContent.Create(
                new CreateProjectRequest(normalized),
                StudioJson.GetTypeInfo<CreateProjectRequest>()),
            true,
            cancellationToken).ConfigureAwait(false);
    }

    public Task<ProjectResponse> GetProjectAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonAsync<ProjectResponse>(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}",
            null,
            true,
            cancellationToken);

    public async Task UploadAudioAsync(
        string projectId,
        Stream audioStream,
        string fileName,
        string? contentType = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(audioStream);
        if (!audioStream.CanRead)
        {
            throw new ArgumentException("The selected audio stream is not readable.", nameof(audioStream));
        }

        var safeFileName = Path.GetFileName(fileName);
        if (string.IsNullOrWhiteSpace(safeFileName))
        {
            throw new ArgumentException("The selected audio file must have a file name.", nameof(fileName));
        }

        using var multipart = new MultipartFormDataContent();
        using var streamContent = new StreamContent(audioStream);
        streamContent.Headers.ContentType = new MediaTypeHeaderValue(
            string.IsNullOrWhiteSpace(contentType) ? "application/octet-stream" : contentType);
        multipart.Add(streamContent, "file", safeFileName);

        using var request = await CreateRequestAsync(
            HttpMethod.Post,
            $"/v1/projects/{EscapeIdentifier(projectId)}/assets/audio",
            multipart,
            includeCredentials: true,
            cancellationToken).ConfigureAwait(false);
        using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);
        await EnsureSuccessAsync(response, cancellationToken).ConfigureAwait(false);
    }

    public Task<AnalysisResponse> AnalyzeAudioAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonAsync<AnalysisResponse>(
            HttpMethod.Post,
            $"/v1/projects/{EscapeIdentifier(projectId)}/analyze_audio",
            new StringContent("{}", Encoding.UTF8, "application/json"),
            true,
            cancellationToken);

    public Task<PlanDto> GeneratePlanAsync(
        string projectId,
        PlanRequest request,
        string mode = "auto",
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.NumberOfVariants is < 1 or > 10)
        {
            throw new ArgumentOutOfRangeException(nameof(request), "Plan variants must be between 1 and 10.");
        }

        if (request.MaximumScenes is < 1 or > 64)
        {
            throw new ArgumentOutOfRangeException(nameof(request), "Maximum scenes must be between 1 and 64.");
        }

        var normalizedMode = (mode ?? string.Empty).Trim().ToLowerInvariant();
        if (normalizedMode is not ("auto" or "ai" or "local"))
        {
            normalizedMode = "auto";
        }

        return SendJsonAsync<PlanDto>(
            HttpMethod.Post,
            $"/v1/projects/{EscapeIdentifier(projectId)}/plan?mode={Uri.EscapeDataString(normalizedMode)}",
            JsonContent.Create(request, StudioJson.GetTypeInfo<PlanRequest>()),
            true,
            cancellationToken);
    }

    public Task<JsonElement> ImportPlannerLabAsync(
        string projectId,
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/planner_lab/import",
            request,
            cancellationToken);

    public Task<JsonElement> ApplyReactiveLabAsync(
        string projectId,
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/reactive_lab/apply",
            request,
            cancellationToken);

    public Task<JsonElement> TestAwsCloudAsync(JsonElement request, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/cloud/aws/test", request, cancellationToken);

    public Task<JsonElement> BundleAwsCloudAsync(JsonElement request, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/cloud/aws/bundle", request, cancellationToken);

    public Task<JsonElement> TestAzureCloudAsync(JsonElement request, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/cloud/azure/test", request, cancellationToken);

    public Task<JsonElement> GetHuggingFaceCloudSettingsAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/cloud/hf/settings", null, true, cancellationToken);

    public Task<JsonElement> SaveHuggingFaceCloudSettingsAsync(JsonElement request, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/cloud/hf/settings", request, cancellationToken);

    public Task<JsonElement> TestHuggingFaceCloudAsync(JsonElement request, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/cloud/hf/test", request, cancellationToken);

    public Task<JsonElement> BundleLightningCloudAsync(JsonElement request, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/cloud/lightning/bundle", request, cancellationToken);

    public Task<JsonElement> GetAiStatusAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/ai/status", null, true, cancellationToken);

    public Task<JsonElement> GetComfyUiCapabilitiesAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/comfyui/capabilities", null, true, cancellationToken);

    public Task<JsonElement> GetUnrealPreviewAsync(
        string projectId,
        int variantIndex,
        CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/unreal/preview?variant_index={Math.Max(0, variantIndex)}",
            null,
            true,
            cancellationToken);

    public Task<JsonElement> GetLiveCuePublishStatusAsync(
        string projectId,
        CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/live_cues/publish/status",
            null,
            true,
            cancellationToken);

    public Task<JsonElement> GetConfigAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/config", null, true, cancellationToken);

    public Task<JsonElement> GetSetupStatusAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/setup/status", null, true, cancellationToken);

    public Task<JsonElement> GetEdmgStatusAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/edmg/status", null, true, cancellationToken);

    public Task<JsonElement> GetTimelineAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/timeline",
            null,
            true,
            cancellationToken);

    public Task<TResult> StreamTimelineFrameAsync<TResult>(
        string projectId,
        double timeSeconds,
        int width,
        int height,
        bool force,
        Func<StudioFileStream, CancellationToken, Task<TResult>> callback,
        CancellationToken cancellationToken = default)
    {
        if (!double.IsFinite(timeSeconds) || timeSeconds < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(timeSeconds),
                "Timeline preview time must be finite and non-negative.");
        }

        if (width is < 1 or > 16_384)
        {
            throw new ArgumentOutOfRangeException(nameof(width));
        }

        if (height is < 1 or > 16_384)
        {
            throw new ArgumentOutOfRangeException(nameof(height));
        }

        string requestPath =
            $"/v1/projects/{EscapeIdentifier(projectId)}/preview/frame" +
            $"?t={timeSeconds.ToString("R", CultureInfo.InvariantCulture)}" +
            $"&w={width.ToString(CultureInfo.InvariantCulture)}" +
            $"&h={height.ToString(CultureInfo.InvariantCulture)}" +
            $"&force={(force ? "1" : "0")}";
        return StreamResponseAsync(requestPath, callback, cancellationToken);
    }

    public Task<JsonElement> SaveTimelineAsync(
        string projectId,
        JsonElement timeline,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/timeline",
            new TimelineUpdateRequest(timeline),
            StudioJson.GetTypeInfo<TimelineUpdateRequest>(),
            cancellationToken);

    public Task<JsonElement> AutosaveTimelineAsync(
        string projectId,
        JsonElement timeline,
        JsonElement? metadata = null,
        string? reason = null,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/autosave",
            new TimelineAutosaveRequest(timeline, metadata, reason),
            StudioJson.GetTypeInfo<TimelineAutosaveRequest>(),
            cancellationToken);

    public Task<TimelineRenderResponse> QueueTimelineRenderAsync(
        string projectId,
        TimelineRenderRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        var normalized = NormalizeTimelineRenderRequest(request);
        return SendJsonAsync<TimelineRenderResponse>(
            HttpMethod.Post,
            $"/v1/projects/{EscapeIdentifier(projectId)}/timeline/render",
            JsonContent.Create(normalized, StudioJson.GetTypeInfo<TimelineRenderRequest>()),
            true,
            cancellationToken);
    }

    public Task<JsonElement> GetRecoveryAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/recovery",
            null,
            true,
            cancellationToken);

    public Task<JsonElement> ApplyRecoveryAsync(
        string projectId,
        RecoveryApplyRequest request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/recovery/apply",
            request,
            StudioJson.GetTypeInfo<RecoveryApplyRequest>(),
            cancellationToken);

    public Task<JsonElement> DiscardRecoveryAsync(string projectId, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/recovery/discard",
            new JsonObject(),
            cancellationToken);

    public Task<JsonElement> PreflightInternalRenderAsync(
        string projectId,
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/render/internal/preflight",
            request,
            cancellationToken);

    public Task<JsonElement> StartInternalRenderAsync(
        string projectId,
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/render/internal/video",
            request,
            cancellationToken);

    public Task<StudioJobListResponse> GetJobsAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync<StudioJobListResponse>(HttpMethod.Get, "/v1/jobs", null, true, cancellationToken);

    public Task<StudioJobListResponse> GetProjectJobsAsync(
        string projectId,
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<StudioJobListResponse>(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/jobs",
            null,
            true,
            cancellationToken);

    public Task<JsonElement> GetProjectJobAsync(
        string projectId,
        string jobId,
        int tailLines = 80,
        CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/jobs/{EscapeIdentifier(jobId)}?tail_lines={Math.Clamp(tailLines, 0, 5000)}",
            null,
            true,
            cancellationToken);

    public Task<StudioJobActionResponse> CancelJobAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostJobActionAsync(projectId, jobId, "cancel", cancellationToken);

    public Task<StudioJobActionResponse> PauseJobAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostJobActionAsync(projectId, jobId, "pause", cancellationToken);

    public Task<StudioJobActionResponse> ResumeJobAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostJobActionAsync(projectId, jobId, "resume", cancellationToken);

    public Task<StudioJobActionResponse> RetryJobAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostJobActionAsync(projectId, jobId, "retry", cancellationToken);

    public Task<JsonElement> ResumeJobFromCheckpointAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostProjectJobJsonAsync(projectId, jobId, "resume_from_checkpoint", cancellationToken);

    public Task<JsonElement> RestartJobCleanAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostProjectJobJsonAsync(projectId, jobId, "restart_clean", cancellationToken);

    public Task<JsonElement> ClearJobCachedFramesAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostProjectJobJsonAsync(projectId, jobId, "clear_cached_frames", cancellationToken);

    public Task<JsonElement> DropJobCheckpointAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        PostProjectJobJsonAsync(projectId, jobId, "drop_checkpoint", cancellationToken);

    public Task<JsonElement> GetJobLogAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        GetProjectJobJsonAsync(projectId, jobId, "log", cancellationToken);

    public Task<JsonElement> GetJobEventsAsync(
        string projectId,
        string jobId,
        CancellationToken cancellationToken = default) =>
        GetProjectJobJsonAsync(projectId, jobId, "events", cancellationToken);

    public Task<JsonElement> GetOutputsAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/outputs",
            null,
            true,
            cancellationToken);

    public async Task<byte[]> DownloadProjectFileAsync(
        string projectId,
        string relativePath,
        CancellationToken cancellationToken = default)
    {
        return await StreamProjectFileAsync(
                projectId,
                relativePath,
                async (file, callbackCancellationToken) =>
                {
                    using var destination = new MemoryStream();
                    await file.Stream.CopyToAsync(destination, callbackCancellationToken).ConfigureAwait(false);
                    return destination.ToArray();
                },
                cancellationToken)
            .ConfigureAwait(false);
    }

    public async Task<TResult> StreamProjectFileAsync<TResult>(
        string projectId,
        string relativePath,
        Func<StudioFileStream, CancellationToken, Task<TResult>> callback,
        CancellationToken cancellationToken = default)
    {
        var path = RequireValue(relativePath, nameof(relativePath));
        var requestPath =
            $"/v1/projects/{EscapeIdentifier(projectId)}/file?path={Uri.EscapeDataString(path)}";
        return await StreamResponseAsync(requestPath, callback, cancellationToken).ConfigureAwait(false);
    }

    private async Task<TResult> StreamResponseAsync<TResult>(
        string requestPath,
        Func<StudioFileStream, CancellationToken, Task<TResult>> callback,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(callback);
        using var request = await CreateRequestAsync(
                HttpMethod.Get,
                requestPath,
                null,
                true,
                cancellationToken)
            .ConfigureAwait(false);
        request.Headers.Accept.Clear();
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("*/*"));

        using var response = await _httpClient.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken)
            .ConfigureAwait(false);
        await EnsureSuccessAsync(response, cancellationToken).ConfigureAwait(false);

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        var scopedFile = new StudioFileStream(
            stream,
            response.Content.Headers,
            response.Headers,
            response.StatusCode);
        return await callback(scopedFile, cancellationToken).ConfigureAwait(false);
    }

    public Task<JsonElement> GetVariantReviewAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/variant_review",
            null,
            true,
            cancellationToken);

    public Task<JsonElement> SaveVariantDecisionAsync(
        string projectId,
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/variant_review/decision",
            request,
            cancellationToken);

    public Task<JsonElement> SaveVariantDecisionAsync(
        string projectId,
        JsonObject request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/variant_review/decision",
            request,
            cancellationToken);

    public Task<JsonElement> GetContinuityAsync(string projectId, CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/render/conductor/continuity",
            null,
            true,
            cancellationToken);

    public Task<JsonElement> GetModelCatalogAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/models/catalog", null, true, cancellationToken);

    public Task<ModelCatalogueResponse> GetTypedModelCatalogueAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync<ModelCatalogueResponse>(
            HttpMethod.Get,
            "/v1/models/catalog",
            null,
            true,
            cancellationToken);

    public Task<ModelTaskListResponse> GetModelTasksAsync(CancellationToken cancellationToken = default) =>
        SendJsonAsync<ModelTaskListResponse>(
            HttpMethod.Get,
            "/v1/models/tasks",
            null,
            true,
            cancellationToken);

    public Task<ModelBenchmarkResponse> RecordModelBenchmarkAsync(
        string modelId,
        CancellationToken cancellationToken = default) =>
        PostJsonAsync<ModelBenchmarkRequest, ModelBenchmarkResponse>(
            "/v1/models/benchmark",
            new ModelBenchmarkRequest(
                RequireValue(modelId, nameof(modelId)),
                "manual_ui_benchmark",
                true,
                new Dictionary<string, string> { ["source"] = "models_page" }),
            cancellationToken);

    public Task<ModelImportResponse> ImportCivitaiModelAsync(
        string url,
        CancellationToken cancellationToken = default) =>
        PostJsonAsync<CivitaiImportRequest, ModelImportResponse>(
            "/v1/models/import/civitai",
            new CivitaiImportRequest(RequireValue(url, nameof(url))),
            cancellationToken);

    public Task<ModelImportResponse> ImportLocalModelAsync(
        string filePath,
        string folder,
        string? name = null,
        CancellationToken cancellationToken = default) =>
        PostJsonAsync<LocalModelImportRequest, ModelImportResponse>(
            "/v1/models/import/local",
            new LocalModelImportRequest(
                RequireValue(filePath, nameof(filePath)),
                RequireValue(folder, nameof(folder)),
                string.IsNullOrWhiteSpace(name) ? null : name.Trim()),
            cancellationToken);

    public Task<TensorRtMigrationStatus> GetTensorRtLegacyStatusAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<TensorRtMigrationStatus>(
            HttpMethod.Get,
            "/v1/models/tensorrt/legacy-status",
            null,
            true,
            cancellationToken);

    public Task<ModelTaskActionResponse> ImportLegacyTensorRtAsync(
        CancellationToken cancellationToken = default) =>
        SendJsonAsync<ModelTaskActionResponse>(
            HttpMethod.Post,
            "/v1/models/tensorrt/import-legacy",
            new StringContent("{}", Encoding.UTF8, "application/json"),
            true,
            cancellationToken);

    public Task<ModelTaskActionResponse> CancelLegacyTensorRtImportAsync(
        string taskId,
        CancellationToken cancellationToken = default) =>
        PostJsonAsync<TensorRtCancelImportRequest, ModelTaskActionResponse>(
            "/v1/models/tensorrt/cancel-import",
            new TensorRtCancelImportRequest(RequireValue(taskId, nameof(taskId))),
            cancellationToken);

    public Task<JsonElement> InstallModelAsync(string modelId, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/models/install",
            new JsonObject { ["model_id"] = RequireValue(modelId, nameof(modelId)) },
            cancellationToken);

    public Task<JsonElement> AcceptModelLicenseAsync(
        string modelId,
        string licenseId,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/models/accept",
            new JsonObject
            {
                ["model_id"] = RequireValue(modelId, nameof(modelId)),
                ["license_id"] = RequireValue(licenseId, nameof(licenseId))
            },
            cancellationToken);

    public Task<JsonElement> RestoreLocalModelAsync(string modelId, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/models/restore_local",
            new JsonObject { ["model_id"] = RequireValue(modelId, nameof(modelId)) },
            cancellationToken);

    public Task<JsonElement> InstallModelPackAsync(string packId, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/models/install_pack",
            new JsonObject { ["pack_id"] = RequireValue(packId, nameof(packId)) },
            cancellationToken);

    public Task<JsonElement> PromoteModelAsync(
        string modelId,
        string lane,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/models/promote",
            new JsonObject
            {
                ["model_id"] = RequireValue(modelId, nameof(modelId)),
                ["lane"] = RequireValue(lane, nameof(lane))
            },
            cancellationToken);

    public Task<JsonElement> RemoveUserModelAsync(string modelId, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/models/remove_user",
            new JsonObject { ["model_id"] = RequireValue(modelId, nameof(modelId)) },
            cancellationToken);

    public Task<JsonElement> GetHardwareAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/hardware", null, true, cancellationToken);

    public Task<JsonElement> GetSystemReadinessAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/system/readiness", null, true, cancellationToken);

    public Task<JsonElement> GetBaselineMetricsAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/metrics/baseline", null, true, cancellationToken);

    public Task<JsonElement> GetRenderProfilesAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/settings/render_profiles", null, true, cancellationToken);

    public Task<JsonElement> GetRenderProvidersAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/settings/render_providers", null, true, cancellationToken);

    public Task<JsonElement> SaveRenderProvidersAsync(
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/settings/render_providers", request, cancellationToken);

    public Task<JsonElement> SaveRenderProvidersAsync(
        JsonObject request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/settings/render_providers", request, cancellationToken);

    public Task<JsonElement> GetRenderRouteAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/render/route", null, true, cancellationToken);

    public Task<JsonElement> SaveRenderRouteAsync(
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/render/route/preferences", request, cancellationToken);

    public Task<JsonElement> GetTranscriptionSettingsAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/settings/transcription", null, true, cancellationToken);

    public Task<JsonElement> SaveTranscriptionSettingsAsync(
        JsonElement request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/settings/transcription", request, cancellationToken);

    public Task<JsonElement> SaveTranscriptionSettingsAsync(
        JsonObject request,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync("/v1/settings/transcription", request, cancellationToken);

    public Task<JsonElement> GetSecretStatusAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/settings/secrets/status", null, true, cancellationToken);

    public Task<JsonElement> SetSecretAsync(
        string key,
        string value,
        CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/settings/secrets/set",
            new JsonObject
            {
                ["name"] = RequireValue(key, nameof(key)),
                ["value"] = RequireValue(value, nameof(value))
            },
            cancellationToken);

    public Task<JsonElement> ClearSecretAsync(string key, CancellationToken cancellationToken = default) =>
        PostJsonElementAsync(
            "/v1/settings/secrets/clear",
            new JsonObject { ["name"] = RequireValue(key, nameof(key)) },
            cancellationToken);

    private Task<JsonElement> PostJsonElementAsync(
        string relativePath,
        JsonElement request,
        CancellationToken cancellationToken) =>
        SendJsonElementAsync(
            HttpMethod.Post,
            relativePath,
            new StringContent(request.GetRawText(), Encoding.UTF8, "application/json"),
            true,
            cancellationToken);

    private Task<JsonElement> PostJsonElementAsync(
        string relativePath,
        JsonObject request,
        CancellationToken cancellationToken) =>
        SendJsonElementAsync(
            HttpMethod.Post,
            relativePath,
            new StringContent(request.ToJsonString(StudioJson.Options), Encoding.UTF8, "application/json"),
            true,
            cancellationToken);

    private Task<JsonElement> PostJsonElementAsync<T>(
        string relativePath,
        T request,
        JsonTypeInfo<T> typeInfo,
        CancellationToken cancellationToken) =>
        SendJsonElementAsync(
            HttpMethod.Post,
            relativePath,
            JsonContent.Create(request, typeInfo),
            true,
            cancellationToken);

    private Task<TResponse> PostJsonAsync<TRequest, TResponse>(
        string relativePath,
        TRequest request,
        CancellationToken cancellationToken) =>
        SendJsonAsync<TResponse>(
            HttpMethod.Post,
            relativePath,
            JsonContent.Create(request, StudioJson.GetTypeInfo<TRequest>()),
            true,
            cancellationToken);

    private Task<StudioJobActionResponse> PostJobActionAsync(
        string projectId,
        string jobId,
        string action,
        CancellationToken cancellationToken) =>
        SendJsonAsync<StudioJobActionResponse>(
            HttpMethod.Post,
            $"/v1/projects/{EscapeIdentifier(projectId)}/jobs/{EscapeIdentifier(jobId)}/{action}",
            new StringContent("{}", Encoding.UTF8, "application/json"),
            true,
            cancellationToken);

    private Task<JsonElement> PostProjectJobJsonAsync(
        string projectId,
        string jobId,
        string action,
        CancellationToken cancellationToken) =>
        PostJsonElementAsync(
            $"/v1/projects/{EscapeIdentifier(projectId)}/jobs/{EscapeIdentifier(jobId)}/{action}",
            new JsonObject(),
            cancellationToken);

    private Task<JsonElement> GetProjectJobJsonAsync(
        string projectId,
        string jobId,
        string suffix,
        CancellationToken cancellationToken) =>
        SendJsonElementAsync(
            HttpMethod.Get,
            $"/v1/projects/{EscapeIdentifier(projectId)}/jobs/{EscapeIdentifier(jobId)}/{suffix}",
            null,
            true,
            cancellationToken);

    private async Task<T> SendJsonAsync<T>(
        HttpMethod method,
        string relativePath,
        HttpContent? content,
        bool includeCredentials,
        CancellationToken cancellationToken)
    {
        using var request = await CreateRequestAsync(method, relativePath, content, includeCredentials, cancellationToken)
            .ConfigureAwait(false);
        using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);
        await EnsureSuccessAsync(response, cancellationToken).ConfigureAwait(false);

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        var result = await JsonSerializer.DeserializeAsync(
                stream,
                StudioJson.GetTypeInfo<T>(),
                cancellationToken)
            .ConfigureAwait(false);
        return result ?? throw new StudioApiException(
            response.StatusCode,
            "EMPTY_RESPONSE",
            "Studio returned an empty response.",
            "Retry the operation and review the backend logs if it continues.");
    }

    private async Task<JsonElement> SendJsonElementAsync(
        HttpMethod method,
        string relativePath,
        HttpContent? content,
        bool includeCredentials,
        CancellationToken cancellationToken)
    {
        using var request = await CreateRequestAsync(method, relativePath, content, includeCredentials, cancellationToken)
            .ConfigureAwait(false);
        using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken)
            .ConfigureAwait(false);
        await EnsureSuccessAsync(response, cancellationToken).ConfigureAwait(false);
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
        return document.RootElement.Clone();
    }

    private async Task<HttpRequestMessage> CreateRequestAsync(
        HttpMethod method,
        string relativePath,
        HttpContent? content,
        bool includeCredentials,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(relativePath) ||
            Uri.TryCreate(relativePath, UriKind.Absolute, out _))
        {
            throw new ArgumentException("Studio API requests must use a relative path.", nameof(relativePath));
        }

        var baseUri = _endpointProvider.CurrentBackendUri;
        var target = new Uri(baseUri, relativePath.TrimStart('/'));
        if (!SameOrigin(baseUri, target))
        {
            throw new InvalidOperationException("Refusing to send a Studio API request to a different origin.");
        }

        var request = new HttpRequestMessage(method, target) { Content = content };
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        if (includeCredentials)
        {
            var token = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(token))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            }
        }

        return request;
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        string body;
        try
        {
            body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            body = string.Empty;
        }

        var error = ParseError(body);
        throw new StudioApiException(
            response.StatusCode,
            error.Code,
            error.Message,
            error.Hint,
            response.Headers.WwwAuthenticate.Any());
    }

    private static (string Code, string Message, string Hint) ParseError(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            if (root.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.Object)
            {
                return (
                    ReadString(error, "code") ?? "HTTP_ERROR",
                    ReadString(error, "message") ?? "Studio request failed.",
                    ReadString(error, "hint") ?? "Review the request and backend status, then retry.");
            }

            if (root.TryGetProperty("detail", out var detail))
            {
                var message = detail.ValueKind == JsonValueKind.String
                    ? detail.GetString()
                    : detail.GetRawText();
                return ("VALIDATION_ERROR", message ?? "Studio rejected the request.", "Check the highlighted values and retry.");
            }
        }
        catch
        {
        }

        return ("HTTP_ERROR", "Studio request failed.", "Check the backend connection and retry.");
    }

    private static string EscapeIdentifier(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("A project ID is required.", nameof(value));
        }

        return Uri.EscapeDataString(value.Trim());
    }

    private static string RequireValue(string value, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("A value is required.", parameterName);
        }

        return value.Trim();
    }

    private static TimelineRenderRequest NormalizeTimelineRenderRequest(TimelineRenderRequest request)
    {
        ValidateTimelineDimension(request.Width, nameof(request.Width));
        ValidateTimelineDimension(request.Height, nameof(request.Height));
        if (!double.IsFinite(request.Fps) || request.Fps is < 1 or > 120)
        {
            throw new ArgumentOutOfRangeException(nameof(request.Fps), "Timeline FPS must be between 1 and 120.");
        }

        var videoCodec = RequireValue(request.VideoCodec, nameof(request.VideoCodec)).ToLowerInvariant();
        if (videoCodec is not ("h264" or "hevc" or "prores"))
        {
            throw new ArgumentException("Timeline video codec must be h264, hevc, or prores.", nameof(request.VideoCodec));
        }

        var audioCodec = RequireValue(request.AudioCodec, nameof(request.AudioCodec)).ToLowerInvariant();
        if (audioCodec is not ("aac" or "pcm_s16le"))
        {
            throw new ArgumentException("Timeline audio codec must be aac or pcm_s16le.", nameof(request.AudioCodec));
        }

        if ((videoCodec == "prores") != (audioCodec == "pcm_s16le"))
        {
            throw new ArgumentException(
                "ProRes requires pcm_s16le audio; H.264 and HEVC require AAC audio.",
                nameof(request.AudioCodec));
        }

        var quality = RequireValue(request.Quality, nameof(request.Quality)).ToLowerInvariant();
        if (quality is not ("low" or "medium" or "high") &&
            (!int.TryParse(quality, NumberStyles.None, CultureInfo.InvariantCulture, out var qualityNumber) ||
             qualityNumber is < 1 or > 51))
        {
            throw new ArgumentException(
                "Timeline quality must be low, medium, high, or a number from 1 through 51.",
                nameof(request.Quality));
        }

        var name = RequireValue(request.Name, nameof(request.Name));
        if (name.Length > 128 ||
            name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            name.Contains('/') ||
            name.Contains('\\'))
        {
            throw new ArgumentException("Timeline output name must be a valid file name of at most 128 characters.", nameof(request.Name));
        }

        return request with
        {
            VideoCodec = videoCodec,
            AudioCodec = audioCodec,
            Quality = quality,
            Name = name
        };
    }

    private static void ValidateTimelineDimension(int value, string parameterName)
    {
        if (value is < 256 or > 7680 || value % 2 != 0)
        {
            throw new ArgumentOutOfRangeException(parameterName, "Timeline dimensions must be even and between 256 and 7680.");
        }
    }

    private static bool SameOrigin(Uri left, Uri right) =>
        string.Equals(left.Scheme, right.Scheme, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.Host, right.Host, StringComparison.OrdinalIgnoreCase) &&
        left.Port == right.Port;

    private static string? ReadString(JsonElement parent, string name) =>
        parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    public void Dispose()
    {
        if (_ownsClient)
        {
            _httpClient.Dispose();
        }
    }
}

public sealed class StudioApiException : Exception
{
    public StudioApiException(
        HttpStatusCode statusCode,
        string code,
        string message,
        string hint,
        bool authenticationChallenge = false)
        : base(message)
    {
        StatusCode = statusCode;
        Code = code;
        Hint = hint;
        AuthenticationChallenge = authenticationChallenge;
    }

    public HttpStatusCode StatusCode { get; }
    public string Code { get; }
    public string Hint { get; }
    public bool AuthenticationChallenge { get; }

    public string UserFacingMessage => string.IsNullOrWhiteSpace(Hint) ? Message : $"{Message} {Hint}";
}
