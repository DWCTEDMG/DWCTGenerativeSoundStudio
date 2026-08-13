using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
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
            JsonContent.Create(new CreateProjectRequest(normalized), options: StudioJson.Options),
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
            JsonContent.Create(request, options: StudioJson.Options),
            true,
            cancellationToken);
    }

    public Task<JsonElement> GetConfigAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/config", null, true, cancellationToken);

    public Task<JsonElement> GetSetupStatusAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/setup/status", null, true, cancellationToken);

    public Task<JsonElement> GetEdmgStatusAsync(CancellationToken cancellationToken = default) =>
        SendJsonElementAsync(HttpMethod.Get, "/v1/edmg/status", null, true, cancellationToken);

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
        var result = await JsonSerializer.DeserializeAsync<T>(stream, StudioJson.Options, cancellationToken).ConfigureAwait(false);
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
