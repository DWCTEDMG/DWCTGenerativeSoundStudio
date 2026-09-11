using System.Globalization;
using System.Text.Json;

namespace EdmgStudio.Core.Models;

public enum DashboardProjectHealth
{
    NeedsAudio,
    NeedsAnalysis,
    NeedsPlan,
    Ready,
    Rendering,
    Attention,
}

public sealed record DashboardWaveformBar(double Height);

public sealed record DashboardProjectCard(
    string ProjectId,
    string Name,
    string UpdatedLabel,
    string DurationLabel,
    string HealthLabel,
    string HealthMessage,
    DashboardProjectHealth Health,
    string LastRenderLabel,
    string? ArtworkPath,
    bool HasRender,
    IReadOnlyList<DashboardWaveformBar> Waveform)
{
    private const int WaveformBarCount = 28;

    public static DashboardProjectCard Create(
        ProjectDto project,
        IReadOnlyList<StudioJob>? jobs = null,
        JsonElement outputs = default,
        DateTimeOffset? now = null)
    {
        ArgumentNullException.ThrowIfNull(project);
        DateTimeOffset referenceTime = now ?? DateTimeOffset.Now;
        StudioJob? lastRender = (jobs ?? [])
            .Where(IsRenderJob)
            .OrderByDescending(job => ParseTimestamp(job.FinishedAt ?? job.UpdatedAt ?? job.CreatedAt))
            .FirstOrDefault();

        DashboardProjectHealth health = ResolveHealth(project, lastRender);
        string? artworkPath = outputs.ValueKind == JsonValueKind.Object
            ? StudioOutputCatalog.Project(outputs)
                .Where(item => item.IsImage)
                .OrderByDescending(item => item.ModifiedAt ?? item.CreatedAt ?? double.MinValue)
                .Select(item => item.Path)
                .FirstOrDefault()
            : null;

        return new DashboardProjectCard(
            project.Id,
            string.IsNullOrWhiteSpace(project.Name) ? "Untitled project" : project.Name,
            FormatRelativeTime(ParseTimestamp(project.UpdatedAt.Length > 0 ? project.UpdatedAt : project.CreatedAt), referenceTime),
            FormatDuration(project.DurationSeconds),
            HealthLabelFor(health),
            HealthMessageFor(health),
            health,
            FormatLastRender(lastRender, referenceTime),
            artworkPath,
            lastRender is not null,
            CreateWaveform(project.Id));
    }

    private static DashboardProjectHealth ResolveHealth(ProjectDto project, StudioJob? lastRender)
    {
        if (lastRender?.Status.Equals("failed", StringComparison.OrdinalIgnoreCase) == true)
        {
            return DashboardProjectHealth.Attention;
        }

        if (lastRender?.IsActive == true)
        {
            return DashboardProjectHealth.Rendering;
        }

        if (!project.HasAudio)
        {
            return DashboardProjectHealth.NeedsAudio;
        }

        if (!project.HasAnalysis)
        {
            return DashboardProjectHealth.NeedsAnalysis;
        }

        return project.HasPlan ? DashboardProjectHealth.Ready : DashboardProjectHealth.NeedsPlan;
    }

    private static bool IsRenderJob(StudioJob job) =>
        job.Type.Contains("render", StringComparison.OrdinalIgnoreCase)
        || job.Type.Contains("video", StringComparison.OrdinalIgnoreCase)
        || job.Type.Contains("deforum", StringComparison.OrdinalIgnoreCase);

    private static string HealthLabelFor(DashboardProjectHealth health) => health switch
    {
        DashboardProjectHealth.NeedsAudio => "Needs audio",
        DashboardProjectHealth.NeedsAnalysis => "Needs analysis",
        DashboardProjectHealth.NeedsPlan => "Needs plan",
        DashboardProjectHealth.Rendering => "Rendering",
        DashboardProjectHealth.Attention => "Needs attention",
        _ => "Ready",
    };

    private static string HealthMessageFor(DashboardProjectHealth health) => health switch
    {
        DashboardProjectHealth.NeedsAudio => "Upload a track to begin.",
        DashboardProjectHealth.NeedsAnalysis => "Analyze the track to unlock reactive tools.",
        DashboardProjectHealth.NeedsPlan => "Create a visual plan before rendering.",
        DashboardProjectHealth.Rendering => "A render is currently in progress.",
        DashboardProjectHealth.Attention => "The latest render failed. Open Review or Queue for details.",
        _ => "Audio, analysis, and visual plan are ready.",
    };

    private static string FormatDuration(double? durationSeconds)
    {
        if (durationSeconds is null || !double.IsFinite(durationSeconds.Value) || durationSeconds.Value < 0)
        {
            return "Duration pending";
        }

        TimeSpan duration = TimeSpan.FromSeconds(durationSeconds.Value);
        return duration.TotalHours >= 1
            ? duration.ToString(@"h\:mm\:ss", CultureInfo.InvariantCulture)
            : duration.ToString(@"m\:ss", CultureInfo.InvariantCulture);
    }

    private static string FormatLastRender(StudioJob? render, DateTimeOffset now)
    {
        if (render is null)
        {
            return "No renders yet";
        }

        DateTimeOffset timestamp = ParseTimestamp(render.FinishedAt ?? render.UpdatedAt ?? render.CreatedAt);
        string status = render.Status.Length == 0
            ? "Unknown"
            : char.ToUpperInvariant(render.Status[0]) + render.Status[1..].ToLowerInvariant();
        return $"{status} · {FormatRelativeTime(timestamp, now)}";
    }

    private static string FormatRelativeTime(DateTimeOffset timestamp, DateTimeOffset now)
    {
        if (timestamp == DateTimeOffset.MinValue)
        {
            return "Updated recently";
        }

        TimeSpan age = now - timestamp;
        if (age < TimeSpan.Zero || age < TimeSpan.FromMinutes(1))
        {
            return "Updated just now";
        }

        if (age < TimeSpan.FromHours(1))
        {
            return $"Updated {(int)age.TotalMinutes}m ago";
        }

        if (age < TimeSpan.FromDays(1))
        {
            return $"Updated {(int)age.TotalHours}h ago";
        }

        if (age < TimeSpan.FromDays(7))
        {
            return $"Updated {(int)age.TotalDays}d ago";
        }

        return $"Updated {timestamp.ToLocalTime():MMM d}";
    }

    private static DateTimeOffset ParseTimestamp(string? value) =>
        DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out DateTimeOffset parsed)
            ? parsed
            : DateTimeOffset.MinValue;

    private static IReadOnlyList<DashboardWaveformBar> CreateWaveform(string projectId)
    {
        uint state = 2166136261;
        foreach (char character in projectId)
        {
            state = (state ^ character) * 16777619;
        }

        var bars = new DashboardWaveformBar[WaveformBarCount];
        for (var index = 0; index < bars.Length; index++)
        {
            state = (state * 1664525) + 1013904223;
            bars[index] = new DashboardWaveformBar(12 + (state % 35));
        }

        return bars;
    }
}
