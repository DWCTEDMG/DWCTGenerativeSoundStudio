using System.Globalization;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public static class ProfessionalEditingOperations
{
    public static JsonObject AddAutomationLane(CanonicalProject project, string laneId, string trackId, string target,
        AutomationMode mode, double minimum, double maximum)
    {
        Track track = EditableTrack(project, trackId);
        RequireNewId(project, laneId);
        ProfessionalEditingContracts.ValidateTarget(target);
        ValidateEnum(mode);
        if (!double.IsFinite(minimum) || !double.IsFinite(maximum) || maximum <= minimum)
            throw new ArgumentOutOfRangeException(nameof(maximum));
        return new() { ["kind"] = "add_automation_lane", ["lane_id"] = laneId, ["track_id"] = track.Id,
            ["target"] = target, ["mode"] = Mode(mode), ["min_value"] = minimum, ["max_value"] = maximum };
    }

    public static JsonObject DeleteAutomationLane(CanonicalProject project, string laneId)
    {
        AutomationLane lane = Lane(project, laneId); EditableTrack(project, lane.TrackId);
        return new() { ["kind"] = "delete_automation_lane", ["lane_id"] = laneId };
    }

    public static JsonObject SetAutomationMode(CanonicalProject project, string laneId, AutomationMode mode)
    {
        AutomationLane lane = Lane(project, laneId); EditableTrack(project, lane.TrackId); ValidateEnum(mode);
        return new() { ["kind"] = "set_automation_mode", ["lane_id"] = laneId, ["mode"] = Mode(mode) };
    }

    public static JsonObject UpsertAutomationPoint(CanonicalProject project, string laneId, string pointId, long sample,
        double value, AutomationCurve curve = AutomationCurve.Linear, double tension = 0)
    {
        AutomationLane lane = Lane(project, laneId); EditableTrack(project, lane.TrackId); ValidateEnum(curve);
        bool existing = lane.Points.Any(point => point.Id == pointId);
        if (string.IsNullOrWhiteSpace(pointId) || (!existing && IdentifierExists(project, pointId)))
            throw new InvalidOperationException("Automation point ID must be nonempty and globally unique.");
        if (sample < 0 || !double.IsFinite(value) || value < lane.Minimum || value > lane.Maximum ||
            !double.IsFinite(tension) || tension is < -1 or > 1)
            throw new ArgumentOutOfRangeException(nameof(value));
        return new() { ["kind"] = "upsert_automation_point", ["lane_id"] = laneId, ["point_id"] = pointId,
            ["sample"] = Sample(sample), ["value"] = value, ["curve"] = Curve(curve), ["tension"] = tension };
    }

    public static JsonObject DeleteAutomationPoint(CanonicalProject project, string laneId, string pointId)
    {
        AutomationLane lane = Lane(project, laneId); EditableTrack(project, lane.TrackId);
        if (!lane.Points.Any(point => point.Id == pointId)) throw new InvalidOperationException("Automation point was not found.");
        return new() { ["kind"] = "delete_automation_point", ["lane_id"] = laneId, ["point_id"] = pointId };
    }

    public static JsonObject SetFades(CanonicalProject project, string trackId, string clipId, long fadeIn, long fadeOut,
        FadeCurve curve = FadeCurve.EqualPower)
    {
        TimelineEvent clip = EditableClip(project, trackId, clipId); ValidateEnum(curve);
        if (fadeIn < 0 || fadeOut < 0 || fadeIn > clip.Duration.Samples - fadeOut)
            throw new ArgumentOutOfRangeException(nameof(fadeIn));
        return Clip("set_fades", trackId, clipId, new() { ["fade_in_samples"] = Sample(fadeIn),
            ["fade_out_samples"] = Sample(fadeOut), ["curve"] = ProfessionalEditingContracts.FadeCurveText(curve) });
    }

    public static JsonObject SetCrossfade(CanonicalProject project, string trackId, string leftClipId, string rightClipId,
        long start, long end, FadeCurve curve = FadeCurve.EqualPower, string? crossfadeId = null)
    {
        TimelineEvent left = EditableClip(project, trackId, leftClipId), right = EditableClip(project, trackId, rightClipId);
        ValidateEnum(curve);
        string id = crossfadeId ?? $"crossfade-{Guid.NewGuid():N}";
        ProfessionalEditingDocument editing = Editing(project);
        Crossfade? existing = editing.Crossfades.FirstOrDefault(item => item.Id == id);
        if (string.IsNullOrWhiteSpace(id) || (existing is null && IdentifierExists(project, id)))
            throw new InvalidOperationException("Crossfade ID must be nonempty and globally unique.");
        if (existing is not null && (existing.TrackId != trackId || existing.LeftClipId != leftClipId ||
            existing.RightClipId != rightClipId))
            throw new InvalidOperationException("Crossfade ID is already owned by different endpoints.");
        if (left.Id == right.Id || start < Math.Max(left.Start.Samples, right.Start.Samples) ||
            end > Math.Min(left.End.Samples, right.End.Samples) || end <= start)
            throw new ArgumentOutOfRangeException(nameof(start));
        return new() { ["kind"] = "set_crossfade", ["crossfade_id"] = id, ["track_id"] = trackId,
            ["left_clip_id"] = leftClipId, ["right_clip_id"] = rightClipId, ["start_sample"] = Sample(start),
            ["end_sample"] = Sample(end), ["curve"] = ProfessionalEditingContracts.FadeCurveText(curve) };
    }

    public static JsonObject AddTake(CanonicalProject project, string trackId, string clipId, string takeId,
        string mediaAssetId, SourceRange? source = null)
    {
        EditableClip(project, trackId, clipId); RequireNewId(project, takeId);
        if (string.IsNullOrWhiteSpace(mediaAssetId) || !project.MediaAssets.Any(asset => asset.Id == mediaAssetId))
            throw new InvalidOperationException("Media asset was not found.");
        var extra = new JsonObject { ["take_id"] = takeId, ["media_asset_id"] = mediaAssetId };
        if (source is not null) extra["source_range"] = SourceRangeNode(source);
        return Clip("add_take", trackId, clipId, extra);
    }

    public static JsonObject SelectTake(CanonicalProject project, string trackId, string clipId, string takeId)
    {
        EditableClip(project, trackId, clipId);
        if (!Editing(project).Takes.Any(take => take.Id == takeId && take.ClipId == clipId))
            throw new InvalidOperationException("Take was not found for this clip.");
        return Clip("select_take", trackId, clipId, new() { ["take_id"] = takeId });
    }

    public static JsonObject SetCompRange(CanonicalProject project, string trackId, string clipId, string compId,
        string takeId, long start, long end)
    {
        TimelineEvent clip = EditableClip(project, trackId, clipId); ProfessionalEditingDocument editing = Editing(project);
        CompRange? existing = editing.CompRanges.FirstOrDefault(comp => comp.Id == compId);
        if (string.IsNullOrWhiteSpace(compId) || (existing is null && IdentifierExists(project, compId)))
            throw new InvalidOperationException("Comp range ID must be nonempty and globally unique.");
        if (existing is not null && existing.ClipId != clipId)
            throw new InvalidOperationException("Comp range ID is already owned by another clip.");
        if (!editing.Takes.Any(take => take.Id == takeId && take.ClipId == clipId))
            throw new InvalidOperationException("Take was not found for this clip.");
        if (start < clip.Start.Samples || end > clip.End.Samples || end <= start ||
            editing.CompRanges.Any(comp => comp.ClipId == clipId && comp.Id != compId && start < comp.EndSample && end > comp.StartSample))
            throw new ArgumentOutOfRangeException(nameof(start));
        return Clip("set_comp_range", trackId, clipId, new() { ["comp_id"] = compId, ["take_id"] = takeId,
            ["start_sample"] = Sample(start), ["end_sample"] = Sample(end) });
    }

    public static JsonObject SetProcess(CanonicalProject project, string trackId, string clipId, double playbackRate,
        double stretchRatio, ProcessAlgorithm algorithm = ProcessAlgorithm.Resample)
    {
        EditableClip(project, trackId, clipId); ValidateEnum(algorithm);
        if (!double.IsFinite(playbackRate) || playbackRate is < .25 or > 4 ||
            !double.IsFinite(stretchRatio) || stretchRatio is < .25 or > 4)
            throw new ArgumentOutOfRangeException(nameof(playbackRate));
        return Clip("set_process", trackId, clipId, new() { ["playback_rate"] = playbackRate,
            ["stretch_ratio"] = stretchRatio, ["algorithm"] = ProfessionalEditingContracts.ProcessAlgorithmText(algorithm) });
    }

    public static JsonObject Nudge(CanonicalProject project, string trackId, string clipId, long delta)
    {
        TimelineEvent clip = EditableClip(project, trackId, clipId);
        if (delta < -clip.Start.Samples) throw new ArgumentOutOfRangeException(nameof(delta));
        return Clip("nudge", trackId, clipId, new() { ["delta_samples"] = SignedSample(delta) });
    }

    public static JsonObject Ripple(CanonicalProject project, string trackId, long from, long delta)
    {
        Track track = EditableTrack(project, trackId);
        if (from < 0 || track.Events.Where(clip => clip.Start.Samples >= from).Any(clip => clip.Data["locked"]?.GetValue<bool>() == true || delta < -clip.Start.Samples))
            throw new ArgumentOutOfRangeException(nameof(from));
        return new() { ["kind"] = "ripple", ["track_id"] = trackId, ["from_sample"] = Sample(from), ["delta_samples"] = SignedSample(delta) };
    }

    public static JsonObject Slip(CanonicalProject project, string trackId, string clipId, long delta)
    {
        TimelineEvent clip = EditableClip(project, trackId, clipId);
        if (clip.Source is { } source && SourceDeltaWouldBeNegative(source.Start, delta, project.Timebase))
            throw new ArgumentOutOfRangeException(nameof(delta));
        return Clip("slip", trackId, clipId, new() { ["delta_samples"] = SignedSample(delta) });
    }

    public static JsonObject Slide(CanonicalProject project, string trackId, string clipId, long delta)
    {
        Track track = EditableTrack(project, trackId); TimelineEvent clip = EditableClip(project, trackId, clipId);
        TimelineEvent[] ordered = track.Events.OrderBy(item => item.Start.Samples).ToArray();
        int index = Array.IndexOf(ordered, clip);
        if (index <= 0 || index >= ordered.Length - 1) throw new InvalidOperationException("Slide requires adjacent clips.");
        TimelineEvent left = ordered[index - 1], right = ordered[index + 1];
        if (left.Data["locked"]?.GetValue<bool>() == true || right.Data["locked"]?.GetValue<bool>() == true ||
            delta <= left.Start.Samples - clip.Start.Samples || delta >= right.End.Samples - clip.End.Samples)
            throw new ArgumentOutOfRangeException(nameof(delta));
        return Clip("slide", trackId, clipId, new() { ["delta_samples"] = SignedSample(delta) });
    }

    public static JsonObject RangeEdit(CanonicalProject project, string trackId, long start, long end, string action, long delta = 0,
        IReadOnlyList<string>? newClipIds = null, IReadOnlyList<string>? newTakeIds = null,
        IReadOnlyList<string>? newCompIds = null)
    {
        Track track = EditableTrack(project, trackId);
        if (start < 0 || end <= start || action is not ("delete" or "move" or "duplicate"))
            throw new ArgumentOutOfRangeException(nameof(start));
        TimelineEvent[] selected = track.Events.Where(clip => clip.Start.Samples >= start && clip.End.Samples <= end).ToArray();
        if (selected.Any(clip => clip.Data["locked"]?.GetValue<bool>() == true))
            throw new InvalidOperationException("Unlock affected clips before range editing.");
        if (action != "delete" && selected.Any(clip => delta < -clip.Start.Samples))
            throw new ArgumentOutOfRangeException(nameof(delta));
        var operation = new JsonObject { ["kind"] = "range_edit", ["track_id"] = trackId,
            ["start_sample"] = Sample(start), ["end_sample"] = Sample(end), ["range_action"] = action,
            ["delta_samples"] = SignedSample(delta) };
        if (action == "duplicate")
        {
            ProfessionalEditingDocument editing = Editing(project);
            int takeCount = selected.Sum(clip => editing.Takes.Count(take => take.ClipId == clip.Id));
            int compCount = selected.Sum(clip => editing.CompRanges.Count(comp => comp.ClipId == clip.Id));
            ValidateDuplicateIds(project, selected.Length, takeCount, compCount, newClipIds, newTakeIds, newCompIds);
            operation["new_ids"] = Nodes(newClipIds!);
            operation["new_take_ids"] = Nodes(newTakeIds!);
            operation["new_comp_ids"] = Nodes(newCompIds!);
        }
        return operation;
    }

    public static void AddDuplicateEditingIds(CanonicalProject project, string clipId, JsonObject operation,
        IReadOnlyList<string> newTakeIds, IReadOnlyList<string> newCompIds)
    {
        ProfessionalEditingDocument editing = Editing(project);
        ValidateDuplicateIds(project, 1, editing.Takes.Count(take => take.ClipId == clipId),
            editing.CompRanges.Count(comp => comp.ClipId == clipId), [operation["new_id"]!.GetValue<string>()],
            newTakeIds, newCompIds);
        operation["new_take_ids"] = Nodes(newTakeIds);
        operation["new_comp_ids"] = Nodes(newCompIds);
    }

    private static Track EditableTrack(CanonicalProject project, string id)
    {
        if (string.IsNullOrWhiteSpace(id)) throw new ArgumentException("Track ID is required.", nameof(id));
        Track track = project.Tracks.FirstOrDefault(item => item.Id == id) ?? throw new InvalidOperationException("Track was not found.");
        if (track.Locked) throw new InvalidOperationException("Unlock the track before editing it.");
        return track;
    }

    private static TimelineEvent EditableClip(CanonicalProject project, string trackId, string clipId)
    {
        if (string.IsNullOrWhiteSpace(clipId)) throw new ArgumentException("Clip ID is required.", nameof(clipId));
        Track track = EditableTrack(project, trackId);
        TimelineEvent clip = track.Events.FirstOrDefault(item => item.Id == clipId) ?? throw new InvalidOperationException("Clip was not found.");
        if (clip.Data["locked"]?.GetValue<bool>() == true) throw new InvalidOperationException("Unlock the clip before editing it.");
        return clip;
    }

    private static AutomationLane Lane(CanonicalProject project, string id) =>
        Editing(project).AutomationLanes.FirstOrDefault(item => item.Id == id) ?? throw new InvalidOperationException("Automation lane was not found.");
    private static ProfessionalEditingDocument Editing(CanonicalProject project) => ProfessionalEditingContracts.Read(project.Timeline);
    private static void RequireNewId(CanonicalProject project, string id)
    {
        if (string.IsNullOrWhiteSpace(id) || IdentifierExists(project, id))
            throw new InvalidOperationException("Identifier must be nonempty and globally unique.");
    }
    private static bool IdentifierExists(CanonicalProject project, string id)
    {
        ProfessionalEditingDocument editing = Editing(project);
        return project.Tracks.Any(track => track.Id == id || track.Events.Any(clip => clip.Id == id)) ||
            project.Markers.Any(marker => marker.Id == id) || project.MediaAssets.Any(asset => asset.Id == id) ||
            editing.AutomationLanes.Any(lane => lane.Id == id || lane.Points.Any(point => point.Id == id)) ||
            editing.Takes.Any(take => take.Id == id) || editing.CompRanges.Any(comp => comp.Id == id) || editing.Crossfades.Any(crossfade => crossfade.Id == id);
    }
    private static void ValidateDuplicateIds(CanonicalProject project, int clipCount, int takeCount, int compCount,
        IReadOnlyList<string>? clipIds, IReadOnlyList<string>? takeIds, IReadOnlyList<string>? compIds)
    {
        if (clipIds?.Count != clipCount || takeIds?.Count != takeCount || compIds?.Count != compCount)
            throw new ArgumentException("Duplication requires deterministic IDs for every clip, take, and comp range.");
        string[] supplied = [.. clipIds!, .. takeIds!, .. compIds!];
        if (supplied.Any(string.IsNullOrWhiteSpace) || supplied.Distinct(StringComparer.Ordinal).Count() != supplied.Length ||
            supplied.Any(id => IdentifierExists(project, id)))
            throw new InvalidOperationException("Duplicate IDs must be nonempty, unique, and unused.");
    }
    private static JsonArray Nodes(IReadOnlyList<string> values) =>
        new(values.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
    private static JsonObject Clip(string kind, string trackId, string clipId, JsonObject extra)
    {
        extra["kind"] = kind; extra["track_id"] = trackId; extra["clip_id"] = clipId; return extra;
    }
    private static JsonObject SourceRangeNode(SourceRange source)
    {
        var value = new JsonObject { ["sample_rate"] = source.Start.SampleRate,
            ["start_sample"] = Sample(source.Start.Samples), ["start_remainder"] = source.Start.Remainder };
        if (source.End is { } end) { value["end_sample"] = Sample(end.Samples); value["end_remainder"] = end.Remainder; }
        return value;
    }
    private static bool SourceDeltaWouldBeNegative(SourcePosition source, long projectDelta, ProjectTimebase timebase)
    {
        decimal sourceDelta = (decimal)projectDelta * source.SampleRate / timebase.SampleRate;
        return source.Samples + sourceDelta < 0;
    }
    private static string Sample(long value) => ProfessionalEditingContracts.SampleText(value);
    private static string SignedSample(long value) => value.ToString(CultureInfo.InvariantCulture);
    private static string Mode(AutomationMode mode) => mode.ToString().ToLowerInvariant();
    private static string Curve(AutomationCurve curve) => curve.ToString().ToLowerInvariant();
    private static void ValidateEnum<T>(T value) where T : struct, Enum
    {
        if (!Enum.IsDefined(value)) throw new ArgumentOutOfRangeException(nameof(value));
    }
}
