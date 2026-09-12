using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Models;

public sealed record ReviewRequest(
    [property: JsonPropertyName("expected_revision")] long ExpectedRevision,
    [property: JsonPropertyName("artifact_path")] string ArtifactPath,
    [property: JsonPropertyName("sample_count")] int SampleCount = 6,
    [property: JsonPropertyName("threshold")] double Threshold = 0.75,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts = 2,
    [property: JsonPropertyName("request_clip_understanding")] bool RequestClipUnderstanding = false,
    [property: JsonPropertyName("target_scene_id")] string? TargetSceneId = null,
    [property: JsonPropertyName("retry_of_report_id")] string? RetryOfReportId = null);

public sealed class DirectorReviewResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("replayed")]
    public bool Replayed { get; init; }

    [JsonPropertyName("report")]
    public required ReviewReport Report { get; init; }
}

public sealed class DirectorReviewListResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("reports")]
    public List<ReviewReport> Reports { get; init; } = [];
}

public sealed class DirectorReviewApplyResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("replayed")]
    public bool Replayed { get; init; }

    [JsonPropertyName("revision")]
    public long Revision { get; init; }

    [JsonPropertyName("report")]
    public required ReviewReport Report { get; init; }
}

public sealed class ReviewReport
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("report_id")]
    public string ReportId { get; init; } = string.Empty;

    [JsonPropertyName("request_fingerprint")]
    public string RequestFingerprint { get; init; } = string.Empty;

    [JsonPropertyName("project_id")]
    public string ProjectId { get; init; } = string.Empty;

    [JsonPropertyName("project_revision")]
    public long ProjectRevision { get; init; }

    [JsonPropertyName("source_draft_id")]
    public string? SourceDraftId { get; init; }

    [JsonPropertyName("source_draft_fingerprint")]
    public string? SourceDraftFingerprint { get; init; }

    [JsonPropertyName("retry_chain_id")]
    public string RetryChainId { get; init; } = string.Empty;

    [JsonPropertyName("artifact_path")]
    public string ArtifactPath { get; init; } = string.Empty;

    [JsonPropertyName("artifact_sha256")]
    public string ArtifactSha256 { get; init; } = string.Empty;

    [JsonPropertyName("artifact_bytes")]
    public long ArtifactBytes { get; init; }

    [JsonPropertyName("status")]
    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("disposition")]
    public string Disposition { get; init; } = string.Empty;

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;

    [JsonPropertyName("duration_seconds")]
    public double DurationSeconds { get; init; }

    [JsonPropertyName("samples")]
    public List<FrameEvidence> Samples { get; init; } = [];

    [JsonPropertyName("dimensions")]
    public List<DimensionScore> Dimensions { get; init; } = [];

    [JsonPropertyName("aggregate_score")]
    public double? AggregateScore { get; init; }

    [JsonPropertyName("continuity_score")]
    public double? ContinuityScore { get; init; }

    [JsonPropertyName("threshold")]
    public double Threshold { get; init; }

    [JsonPropertyName("findings")]
    public List<ReviewFinding> Findings { get; init; } = [];

    [JsonPropertyName("correction_plan")]
    public CorrectionPlan CorrectionPlan { get; init; } = new();

    [JsonPropertyName("retry")]
    public RetryPolicy Retry { get; init; } = new(0.75, 2, 1, string.Empty, []);

    [JsonPropertyName("clip_understanding")]
    public ClipUnderstandingResult ClipUnderstanding { get; init; } = new(false, "disabled", "clip_understanding", string.Empty);

    [JsonPropertyName("provenance")]
    public Dictionary<string, JsonElement> Provenance { get; init; } = [];
}

public sealed record FrameEvidence(
    [property: JsonPropertyName("timestamp_seconds")] double TimestampSeconds,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("bytes")] long Bytes);

public sealed record DimensionScore(
    [property: JsonPropertyName("dimension")] string Dimension,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("score")] double? Score,
    [property: JsonPropertyName("evidence")] List<string> Evidence);

public sealed record ReviewFinding(
    [property: JsonPropertyName("code")] string Code,
    [property: JsonPropertyName("severity")] string Severity,
    [property: JsonPropertyName("dimension")] string Dimension,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("scene_id")] string? SceneId);

public sealed record ClipUnderstandingResult(
    [property: JsonPropertyName("requested")] bool Requested,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("capability")] string Capability,
    [property: JsonPropertyName("detail")] string Detail);

public sealed class CorrectionPlan
{
    [JsonPropertyName("state")]
    public string State { get; set; } = string.Empty;

    [JsonPropertyName("target_scene_id")]
    public string? TargetSceneId { get; init; }

    [JsonPropertyName("guidance")]
    public List<string> Guidance { get; init; } = [];

    [JsonPropertyName("director_document")]
    public JsonElement? DirectorDocument { get; init; }

    [JsonPropertyName("applied_revision")]
    public long? AppliedRevision { get; set; }
}

public sealed record RetryAttempt(
    [property: JsonPropertyName("attempt")] int Attempt,
    [property: JsonPropertyName("report_id")] string ReportId,
    [property: JsonPropertyName("created_at")] string CreatedAt,
    [property: JsonPropertyName("aggregate_score")] double? AggregateScore,
    [property: JsonPropertyName("disposition")] string Disposition);

public sealed record RetryPolicy(
    [property: JsonPropertyName("threshold")] double Threshold,
    [property: JsonPropertyName("max_attempts")] int MaxAttempts,
    [property: JsonPropertyName("attempt")] int Attempt,
    [property: JsonPropertyName("result")] string Result,
    [property: JsonPropertyName("history")] List<RetryAttempt> History);

public sealed record ApplyCorrectionRequest(
    [property: JsonPropertyName("expected_revision")] long ExpectedRevision);

public static class DirectorReviewPresentation
{
    public static string FormatScore(double? score, string? state = "assessed") =>
        !string.Equals(state, "assessed", StringComparison.OrdinalIgnoreCase) || score is null
            ? "Not assessed"
            : score.Value.ToString("P0", CultureInfo.CurrentCulture);

    public static string FormatThreshold(double threshold) =>
        Math.Clamp(threshold, 0, 1).ToString("P0", CultureInfo.CurrentCulture);

    public static bool CanRunNextAttempt(ReviewReport? report) =>
        report is not null &&
        string.Equals(report.Retry.Result, "recommended", StringComparison.OrdinalIgnoreCase) &&
        report.Retry.Attempt < report.Retry.MaxAttempts;

    public static bool CanApplyCorrection(ReviewReport? report) =>
        report is not null &&
        string.Equals(report.CorrectionPlan.State, "proposed", StringComparison.OrdinalIgnoreCase) &&
        report.CorrectionPlan.DirectorDocument is { ValueKind: JsonValueKind.Object };
}
