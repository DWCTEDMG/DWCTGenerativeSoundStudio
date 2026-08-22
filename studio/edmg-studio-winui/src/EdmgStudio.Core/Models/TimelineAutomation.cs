using System.IO;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public sealed record TimelineAutomationResult(
    JsonObject Timeline,
    string Operation,
    int ChangedClipCount,
    string Summary);

public static class TimelineAutomation
{
    public static TimelineAutomationResult AssignSource(
        JsonObject timeline,
        string stableId,
        string sourcePath)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentException.ThrowIfNullOrWhiteSpace(stableId);
        ArgumentException.ThrowIfNullOrWhiteSpace(sourcePath);

        var lanes = TimelineProjection.Project(timeline).ToList();
        TimelineLaneDocument lane = lanes.FirstOrDefault(
            item => string.Equals(item.StableId, stableId, StringComparison.Ordinal))
            ?? throw new InvalidOperationException("The selected timeline clip no longer exists.");
        if (!lane.IsLayer && TimelineProjection.IsTrackLocked(timeline, lane.TrackIndex))
        {
            throw new InvalidOperationException($"Track {lane.TrackIndex + 1} is locked.");
        }

        lane.SourcePath = sourcePath.Trim();

        return new TimelineAutomationResult(
            TimelineProjection.Rebuild(timeline, lanes),
            "assign_source",
            1,
            $"Assigned {Path.GetFileName(sourcePath)} to {lane.Name}.");
    }

    public static TimelineAutomationResult AddSourceClip(
        JsonObject timeline,
        string sourcePath,
        double startSeconds,
        double durationSeconds,
        int trackIndex)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentException.ThrowIfNullOrWhiteSpace(sourcePath);
        if (!double.IsFinite(startSeconds) || startSeconds < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(startSeconds));
        }

        if (!double.IsFinite(durationSeconds) ||
            durationSeconds < TimelineProjection.MinimumDurationSeconds)
        {
            throw new ArgumentOutOfRangeException(nameof(durationSeconds));
        }

        ArgumentOutOfRangeException.ThrowIfNegative(trackIndex);
        if (TimelineProjection.IsTrackLocked(timeline, trackIndex))
        {
            throw new InvalidOperationException($"Track {trackIndex + 1} is locked.");
        }

        string normalizedPath = sourcePath.Trim();
        string type = InferMediaType(normalizedPath);
        string name = Path.GetFileNameWithoutExtension(normalizedPath);
        TimelineLaneDocument lane = TimelineProjection.CreateLane(
            string.IsNullOrWhiteSpace(name) ? "Imported source" : name,
            type,
            startSeconds,
            startSeconds + durationSeconds);
        lane = TimelineProjection.ReassignTrack(lane, trackIndex);
        lane.SourcePath = normalizedPath;
        lane.SourceInSeconds = 0;
        lane.SourceOutSeconds = durationSeconds;

        var lanes = TimelineProjection.Project(timeline).Append(lane).ToList();
        return new TimelineAutomationResult(
            TimelineProjection.Rebuild(timeline, lanes),
            "add_source_clip",
            1,
            $"Added {Path.GetFileName(normalizedPath)} to track {trackIndex + 1}.");
    }

    public static TimelineAutomationResult SequenceTrack(
        JsonObject timeline,
        int trackIndex,
        double startSeconds,
        double gapSeconds)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentOutOfRangeException.ThrowIfNegative(trackIndex);
        if (TimelineProjection.IsTrackLocked(timeline, trackIndex))
        {
            throw new InvalidOperationException($"Track {trackIndex + 1} is locked.");
        }

        if (!double.IsFinite(startSeconds) || startSeconds < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(startSeconds));
        }

        if (!double.IsFinite(gapSeconds) || gapSeconds < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(gapSeconds));
        }

        var lanes = TimelineProjection.Project(timeline).ToList();
        var trackLanes = lanes
            .Where(lane => lane.TrackIndex == trackIndex)
            .OrderBy(lane => lane.StartSeconds)
            .ThenBy(lane => lane.EndSeconds)
            .ThenBy(lane => lane.StableId, StringComparer.Ordinal)
            .ToList();
        if (trackLanes.Count == 0)
        {
            throw new InvalidOperationException($"Track {trackIndex + 1} has no clips to sequence.");
        }

        double cursor = startSeconds;
        foreach (TimelineLaneDocument lane in trackLanes)
        {
            double duration = Math.Max(
                TimelineProjection.MinimumDurationSeconds,
                lane.EndSeconds - lane.StartSeconds);
            lane.StartSeconds = cursor;
            lane.EndSeconds = cursor + duration;
            cursor = lane.EndSeconds + gapSeconds;
        }

        return new TimelineAutomationResult(
            TimelineProjection.Rebuild(timeline, lanes),
            "sequence_track",
            trackLanes.Count,
            $"Sequenced {trackLanes.Count} clips on track {trackIndex + 1} with a {gapSeconds:0.###} s gap.");
    }

    private static string InferMediaType(string sourcePath)
    {
        string extension = Path.GetExtension(sourcePath);
        return extension.ToLowerInvariant() switch
        {
            ".wav" or ".mp3" or ".flac" or ".aac" or ".m4a" or ".ogg" => "audio",
            _ => "video",
        };
    }
}
