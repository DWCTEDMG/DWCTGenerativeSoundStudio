using System.Collections.Immutable;
using System.Globalization;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public enum AutomationMode { Read, Write, Touch }
public enum AutomationCurve { Step, Linear, Smooth }
public enum FadeCurve { Linear, EqualPower, SCurve }
public enum ProcessAlgorithm { Resample, PhaseVocoder }

public sealed record AutomationPoint(string Id, long Sample, double Value, AutomationCurve Curve, double Tension, JsonObject Metadata);
public sealed record AutomationLane(string Id, string TrackId, string Target, AutomationMode Mode, double Minimum, double Maximum,
    ImmutableArray<AutomationPoint> Points, JsonObject Metadata);
public sealed record TakeVersion(string Id, string ClipId, string MediaAssetId, SourceRange? Source, JsonObject Metadata);
public sealed record CompRange(string Id, string ClipId, string TakeId, long StartSample, long EndSample, JsonObject Metadata);
public sealed record Crossfade(string Id, string TrackId, string LeftClipId, string RightClipId, long StartSample, long EndSample, FadeCurve Curve, JsonObject Metadata);
public sealed record FadeDescriptor(long InSamples, long OutSamples, FadeCurve Curve, JsonObject Metadata);
public sealed record ProcessDescriptor(double PlaybackRate, double StretchRatio, ProcessAlgorithm Algorithm, JsonObject Metadata);
public sealed record ClipEditingDescriptor(string ClipId, string? ActiveTakeId, FadeDescriptor? Fades, ProcessDescriptor? Process);
public sealed record ProfessionalEditingDocument(int SchemaVersion, ImmutableArray<AutomationLane> AutomationLanes,
    ImmutableArray<TakeVersion> Takes, ImmutableArray<CompRange> CompRanges, ImmutableArray<Crossfade> Crossfades,
    ImmutableArray<ClipEditingDescriptor> Clips, JsonObject Metadata);

public static class ProfessionalEditingContracts
{
    public const int SchemaVersion = 1;
    public const int MaximumPointsPerLane = 100_000;
    private const int MaximumCollectionItems = 10_000;
    private static readonly HashSet<string> BuiltInTargets = new(StringComparer.Ordinal) { "volume", "pan", "mute" };

    public static ProfessionalEditingDocument Read(JsonObject timeline)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        if (timeline["editing"] is null)
            return new(SchemaVersion, [], [], [], [], [], new JsonObject());
        if (timeline["editing"] is not JsonObject editing)
            throw new InvalidDataException("Timeline editing document must be an object.");
        int version = RequiredInt(editing, "schema_version");
        if (version != SchemaVersion)
            throw new InvalidDataException($"Unsupported editing schema version '{version}'.");

        var identifiers = new HashSet<string>(StringComparer.Ordinal);
        var lanes = ImmutableArray.CreateBuilder<AutomationLane>();
        foreach (JsonObject lane in Objects(editing, "automation_lanes"))
        {
            string id = Id(lane, "automation lane", identifiers);
            string trackId = RequiredString(lane, "track_id");
            string target = RequiredString(lane, "target");
            ValidateTarget(target);
            AutomationMode mode = ParseMode(RequiredString(lane, "mode"));
            double minimum = RequiredFinite(lane, "min_value");
            double maximum = RequiredFinite(lane, "max_value");
            if (maximum <= minimum)
                throw new InvalidDataException("Automation maximum must exceed minimum.");
            var points = ImmutableArray.CreateBuilder<AutomationPoint>();
            long previous = -1;
            foreach (JsonObject point in Objects(lane, "points", MaximumPointsPerLane))
            {
                string pointId = Id(point, "automation point", identifiers);
                long sample = Sample(point, "sample");
                if (sample <= previous)
                    throw new InvalidDataException("Automation points must have unique, increasing samples.");
                double value = RequiredFinite(point, "value");
                if (value < minimum || value > maximum)
                    throw new InvalidDataException("Automation point is outside its lane bounds.");
                AutomationCurve curve = ParseAutomationCurve(OptionalString(point, "curve") ?? "linear");
                double tension = point["tension"] is null ? 0 : RequiredFinite(point, "tension");
                if (tension is < -1 or > 1)
                    throw new InvalidDataException("Automation tension must be between -1 and 1.");
                points.Add(new(pointId, sample, value, curve, tension, point.DeepClone().AsObject()));
                previous = sample;
            }
            lanes.Add(new(id, trackId, target, mode, minimum, maximum, points.ToImmutable(), lane.DeepClone().AsObject()));
        }

        var takes = ImmutableArray.CreateBuilder<TakeVersion>();
        foreach (JsonObject take in Objects(editing, "takes"))
            takes.Add(new(Id(take, "take", identifiers), RequiredString(take, "clip_id"),
                RequiredString(take, "media_asset_id"), ReadSourceRange(take["source_range"]), take.DeepClone().AsObject()));

        var comps = ImmutableArray.CreateBuilder<CompRange>();
        foreach (JsonObject comp in Objects(editing, "comp_ranges"))
        {
            string id = Id(comp, "comp range", identifiers);
            long start = Sample(comp, "start_sample");
            long end = Sample(comp, "end_sample");
            if (end <= start)
                throw new InvalidDataException("Comp range must have positive duration.");
            string takeId = RequiredString(comp, "take_id");
            string clipId = RequiredString(comp, "clip_id");
            if (!takes.Any(t => t.Id == takeId && t.ClipId == clipId))
                throw new InvalidDataException("Comp range references a missing take for its clip.");
            comps.Add(new(id, clipId, takeId, start, end, comp.DeepClone().AsObject()));
        }
        foreach (IGrouping<string, CompRange> group in comps.GroupBy(c => c.ClipId))
        {
            long end = -1;
            foreach (CompRange comp in group.OrderBy(c => c.StartSample))
            {
                if (comp.StartSample < end)
                    throw new InvalidDataException("Comp ranges for a clip cannot overlap.");
                end = comp.EndSample;
            }
        }

        var crossfades = ImmutableArray.CreateBuilder<Crossfade>();
        foreach (JsonObject crossfade in Objects(editing, "crossfades"))
        {
            string id = Id(crossfade, "crossfade", identifiers);
            long start = Sample(crossfade, "start_sample");
            long end = Sample(crossfade, "end_sample");
            if (end <= start)
                throw new InvalidDataException("Crossfade must have positive duration.");
            crossfades.Add(new(id, RequiredString(crossfade, "track_id"), RequiredString(crossfade, "left_clip_id"),
                RequiredString(crossfade, "right_clip_id"), start, end,
                ParseFadeCurve(OptionalString(crossfade, "curve") ?? "equal_power"), crossfade.DeepClone().AsObject()));
        }
        return new(version, lanes.ToImmutable(), takes.ToImmutable(), comps.ToImmutable(), crossfades.ToImmutable(),
            ReadClipDescriptors(timeline), editing.DeepClone().AsObject());
    }

    public static void ValidateAgainstProject(CanonicalProject project, ProfessionalEditingDocument document)
    {
        var tracks = project.Tracks.ToDictionary(t => t.Id, StringComparer.Ordinal);
        var clips = project.Tracks.SelectMany(t => t.Events).ToDictionary(c => c.Id, StringComparer.Ordinal);
        var assets = project.MediaAssets.Select(a => a.Id).ToHashSet(StringComparer.Ordinal);
        var globalIds = tracks.Keys.Concat(clips.Keys).Concat(project.Markers.Select(m => m.Id))
            .Concat(project.MediaAssets.Select(asset => asset.Id)).ToHashSet(StringComparer.Ordinal);
        foreach (string id in document.AutomationLanes.SelectMany(l => l.Points.Select(p => p.Id).Prepend(l.Id))
                     .Concat(document.Takes.Select(t => t.Id)).Concat(document.CompRanges.Select(c => c.Id))
                     .Concat(document.Crossfades.Select(c => c.Id)))
            if (!globalIds.Add(id))
                throw new InvalidDataException($"Editing ID '{id}' collides with another project identifier.");

        foreach (AutomationLane lane in document.AutomationLanes)
        {
            if (!tracks.ContainsKey(lane.TrackId))
                throw new InvalidDataException($"Automation lane '{lane.Id}' references a missing track.");
            ValidateTargetReference(lane.Target, tracks);
        }
        foreach (TakeVersion take in document.Takes)
            if (!clips.ContainsKey(take.ClipId) || !assets.Contains(take.MediaAssetId))
                throw new InvalidDataException($"Take '{take.Id}' has an invalid clip or asset reference.");
        foreach (CompRange comp in document.CompRanges)
        {
            if (!clips.TryGetValue(comp.ClipId, out TimelineEvent? clip) ||
                comp.StartSample < clip.Start.Samples || comp.EndSample > clip.End.Samples)
                throw new InvalidDataException($"Comp range '{comp.Id}' lies outside its clip.");
        }
        foreach (Crossfade crossfade in document.Crossfades)
        {
            if (!tracks.TryGetValue(crossfade.TrackId, out Track? track) ||
                track.Events.FirstOrDefault(item => item.Id == crossfade.LeftClipId) is not TimelineEvent left ||
                track.Events.FirstOrDefault(item => item.Id == crossfade.RightClipId) is not TimelineEvent right || left.Id == right.Id ||
                crossfade.StartSample < Math.Max(left.Start.Samples, right.Start.Samples) ||
                crossfade.EndSample > Math.Min(left.End.Samples, right.End.Samples))
                throw new InvalidDataException($"Crossfade '{crossfade.Id}' is outside two overlapping clips on its track.");
        }
        foreach (ClipEditingDescriptor descriptor in document.Clips)
        {
            TimelineEvent clip = clips[descriptor.ClipId];
            if (descriptor.ActiveTakeId is not null && !document.Takes.Any(t => t.Id == descriptor.ActiveTakeId && t.ClipId == clip.Id))
                throw new InvalidDataException($"Active take on clip '{clip.Id}' is not owned by that clip.");
            if (descriptor.Fades is { } fades && fades.InSamples > clip.Duration.Samples - fades.OutSamples)
                throw new InvalidDataException($"Fades on clip '{clip.Id}' exceed its duration.");
        }
    }

    public static string SampleText(long sample)
    {
        if (sample < 0) throw new ArgumentOutOfRangeException(nameof(sample));
        return sample.ToString(CultureInfo.InvariantCulture);
    }

    internal static void ValidateTarget(string target)
    {
        string[] parts = target.Split(':');
        if (BuiltInTargets.Contains(target) ||
            (parts.Length == 2 && parts[1].Length > 0 && parts[0] is "send" or "render") ||
            (parts.Length == 3 && parts[0] == "plugin" && parts[1].Length > 0 && parts[2].Length > 0)) return;
        throw new InvalidDataException("Automation target must be volume, pan, mute, send:<track-id>, plugin:<id>:<parameter>, or render:<parameter>.");
    }

    internal static string FadeCurveText(FadeCurve curve) => curve switch
    {
        FadeCurve.Linear => "linear", FadeCurve.EqualPower => "equal_power", FadeCurve.SCurve => "s_curve",
        _ => throw new ArgumentOutOfRangeException(nameof(curve))
    };

    internal static string ProcessAlgorithmText(ProcessAlgorithm algorithm) => algorithm switch
    {
        ProcessAlgorithm.Resample => "resample", ProcessAlgorithm.PhaseVocoder => "phase_vocoder",
        _ => throw new ArgumentOutOfRangeException(nameof(algorithm))
    };

    private static ImmutableArray<ClipEditingDescriptor> ReadClipDescriptors(JsonObject timeline)
    {
        var result = ImmutableArray.CreateBuilder<ClipEditingDescriptor>();
        if (timeline["tracks"] is not JsonArray tracks) return result.ToImmutable();
        foreach (JsonObject track in tracks.OfType<JsonObject>())
        foreach (JsonObject clip in (track["clips"] as JsonArray ?? []).OfType<JsonObject>())
        {
            string clipId = RequiredString(clip, "id");
            JsonObject data = clip["data"] as JsonObject ?? clip;
            string? activeTake = OptionalString(data, "active_take_id");
            FadeDescriptor? fades = null;
            if (data["fades"] is JsonNode fadeNode)
            {
                if (fadeNode is not JsonObject fade) throw new InvalidDataException("Clip fades must be an object.");
                fades = new(Sample(fade, "in_samples"), Sample(fade, "out_samples"),
                    ParseFadeCurve(OptionalString(fade, "curve") ?? "equal_power"), fade.DeepClone().AsObject());
            }
            ProcessDescriptor? process = null;
            if (data["process"] is JsonNode processNode)
            {
                if (processNode is not JsonObject value) throw new InvalidDataException("Clip process must be an object.");
                double rate = RequiredFinite(value, "playback_rate");
                double ratio = RequiredFinite(value, "stretch_ratio");
                if (rate is < .25 or > 4 || ratio is < .25 or > 4)
                    throw new InvalidDataException("Process rates must be between 0.25 and 4.");
                process = new(rate, ratio, ParseProcessAlgorithm(RequiredString(value, "algorithm")), value.DeepClone().AsObject());
            }
            if (activeTake is not null || fades is not null || process is not null)
                result.Add(new(clipId, activeTake, fades, process));
        }
        return result.ToImmutable();
    }

    private static SourceRange? ReadSourceRange(JsonNode? node)
    {
        if (node is null) return null;
        if (node is not JsonObject value) throw new InvalidDataException("Take source range must be an object.");
        int rate = RequiredInt(value, "sample_rate");
        if (rate <= 0) throw new InvalidDataException("Take source sample rate must be positive.");
        var start = new SourcePosition(rate, Sample(value, "start_sample"), OptionalString(value, "start_remainder") ?? "0");
        SourcePosition? end = value["end_sample"] is null ? null : new SourcePosition(rate, Sample(value, "end_sample"), OptionalString(value, "end_remainder") ?? "0");
        try { return new SourceRange(start, end); }
        catch (ArgumentException exception) { throw new InvalidDataException("Take source range is invalid.", exception); }
    }

    private static void ValidateTargetReference(string target, IReadOnlyDictionary<string, Track> tracks)
    {
        string[] parts = target.Split(':');
        if (parts.Length == 2 && parts[0] == "send" && !tracks.ContainsKey(parts[1]))
            throw new InvalidDataException($"Automation target '{target}' references a missing track.");
    }

    private static AutomationMode ParseMode(string value) => value switch
    {
        "read" => AutomationMode.Read, "write" => AutomationMode.Write, "touch" => AutomationMode.Touch,
        _ => throw new InvalidDataException("Automation mode must be read, write, or touch.")
    };
    private static AutomationCurve ParseAutomationCurve(string value) => value switch
    {
        "step" => AutomationCurve.Step, "linear" => AutomationCurve.Linear, "smooth" => AutomationCurve.Smooth,
        _ => throw new InvalidDataException("Automation curve must be step, linear, or smooth.")
    };
    private static FadeCurve ParseFadeCurve(string value) => value switch
    {
        "linear" => FadeCurve.Linear, "equal_power" => FadeCurve.EqualPower, "s_curve" => FadeCurve.SCurve,
        _ => throw new InvalidDataException("Fade curve must be linear, equal_power, or s_curve.")
    };
    private static ProcessAlgorithm ParseProcessAlgorithm(string value) => value switch
    {
        "resample" => ProcessAlgorithm.Resample, "phase_vocoder" => ProcessAlgorithm.PhaseVocoder,
        _ => throw new InvalidDataException("Process algorithm must be resample or phase_vocoder.")
    };
    private static IEnumerable<JsonObject> Objects(JsonObject owner, string name, int maximum = MaximumCollectionItems)
    {
        if (owner[name] is null) yield break;
        if (owner[name] is not JsonArray array || array.Count > maximum) throw new InvalidDataException($"'{name}' must be a bounded array.");
        foreach (JsonNode? node in array) yield return node as JsonObject ?? throw new InvalidDataException($"'{name}' entries must be objects.");
    }
    private static string Id(JsonObject value, string kind, HashSet<string> ids)
    {
        string id = RequiredString(value, "id");
        if (!ids.Add(id)) throw new InvalidDataException($"Duplicate {kind} ID '{id}'.");
        return id;
    }
    private static long Sample(JsonObject value, string name)
    {
        string text = RequiredString(value, name);
        if (!long.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out long sample) || sample < 0 || text != sample.ToString(CultureInfo.InvariantCulture))
            throw new InvalidDataException($"'{name}' must be a canonical nonnegative int64 sample string.");
        return sample;
    }
    private static int RequiredInt(JsonObject value, string name) => value[name] is JsonValue node && node.TryGetValue<int>(out int result) ? result : throw new InvalidDataException($"'{name}' must be an integer.");
    private static double RequiredFinite(JsonObject value, string name) => value[name] is JsonValue node && node.TryGetValue<double>(out double result) && double.IsFinite(result) ? result : throw new InvalidDataException($"'{name}' must be finite.");
    private static string RequiredString(JsonObject value, string name) => OptionalString(value, name) is { Length: > 0 } result ? result : throw new InvalidDataException($"'{name}' is required.");
    private static string? OptionalString(JsonObject value, string name) => value[name] is null ? null : value[name] is JsonValue node && node.TryGetValue<string>(out string? result) ? result : throw new InvalidDataException($"'{name}' must be a string.");
}
