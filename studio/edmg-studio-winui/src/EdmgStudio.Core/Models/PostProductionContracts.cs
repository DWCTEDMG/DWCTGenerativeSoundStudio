using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public enum SyncMethod { Timecode, Clap, Transient, WaveformCorrelation }
public enum AdrReviewStatus { Unreviewed, Approved, Rejected }
public enum AudioChannelLayout { Mono, Stereo, Surround51, Surround71, Object }
public enum CompatibilitySeverity { Information, Warning, Error }
public enum ReconformEditKind { Insert, Delete, Move }

public sealed record Timecode
{
    private Timecode(long frameNumber, FrameRate rate, bool dropFrame)
        => (FrameNumber, Rate, DropFrame) = (frameNumber, rate, dropFrame);

    public long FrameNumber { get; }
    public FrameRate Rate { get; }
    public bool DropFrame { get; }

    public static bool Supports(FrameRate rate) => rate is
        { Numerator: 24_000, Denominator: 1_001 } or
        { Numerator: 24 or 25 or 30 or 50 or 60, Denominator: 1 } or
        { Numerator: 30_000 or 60_000, Denominator: 1_001 };

    public static Timecode FromFrameNumber(long frameNumber, FrameRate rate, bool dropFrame = false)
    {
        ValidateRate(rate, dropFrame);
        if (frameNumber < 0) throw new ArgumentOutOfRangeException(nameof(frameNumber));
        return new(frameNumber, rate, dropFrame);
    }

    public static Timecode Parse(string value, FrameRate rate, bool? dropFrame = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(value);
        bool semicolon = value.Length == 11 && value[8] == ';';
        bool useDrop = dropFrame ?? semicolon;
        ValidateRate(rate, useDrop);
        if (value.Length != 11 || value[2] != ':' || value[5] != ':' || value[8] is not (':' or ';') || semicolon != useDrop)
            throw new FormatException("Timecode must be HH:MM:SS:FF, using ';' for drop-frame.");
        if (!int.TryParse(value.AsSpan(0, 2), out int hours) || !int.TryParse(value.AsSpan(3, 2), out int minutes) ||
            !int.TryParse(value.AsSpan(6, 2), out int seconds) || !int.TryParse(value.AsSpan(9, 2), out int frames))
            throw new FormatException("Timecode fields must be decimal digits.");
        int nominal = NominalRate(rate);
        if (hours > 23 || minutes > 59 || seconds > 59 || frames >= nominal)
            throw new FormatException("Timecode field is outside its valid range.");
        int dropped = nominal == 30 ? 2 : 4;
        if (useDrop && seconds == 0 && minutes % 10 != 0 && frames < dropped)
            throw new FormatException("Timecode identifies a dropped frame label.");
        long labels = (((long)hours * 60 + minutes) * 60 + seconds) * nominal + frames;
        long number = useDrop ? labels - dropped * (((long)hours * 60 + minutes) - ((long)hours * 60 + minutes) / 10) : labels;
        return new(number, rate, useDrop);
    }

    public override string ToString()
    {
        int nominal = NominalRate(Rate);
        long labels = FrameNumber;
        if (DropFrame)
        {
            int dropped = nominal == 30 ? 2 : 4;
            int framesPerTenMinutes = nominal * 600 - dropped * 9;
            int framesPerMinute = nominal * 60 - dropped;
            long blocks = labels / framesPerTenMinutes;
            long remainder = labels % framesPerTenMinutes;
            labels += dropped * 9 * blocks;
            if (remainder >= dropped)
                labels += dropped * ((remainder - dropped) / framesPerMinute);
        }
        long hours = labels / (nominal * 3600);
        labels %= nominal * 3600;
        long minutes = labels / (nominal * 60);
        labels %= nominal * 60;
        long seconds = labels / nominal;
        long frames = labels % nominal;
        return $"{hours % 24:00}:{minutes:00}:{seconds:00}{(DropFrame ? ';' : ':')}{frames:00}";
    }

    private static int NominalRate(FrameRate rate) => rate switch
    {
        { Numerator: 24_000, Denominator: 1_001 } or { Numerator: 24, Denominator: 1 } => 24,
        { Numerator: 25, Denominator: 1 } => 25,
        { Numerator: 30_000, Denominator: 1_001 } or { Numerator: 30, Denominator: 1 } => 30,
        { Numerator: 50, Denominator: 1 } => 50,
        { Numerator: 60_000, Denominator: 1_001 } or { Numerator: 60, Denominator: 1 } => 60,
        _ => throw new ArgumentException("Unsupported professional timecode frame rate.", nameof(rate))
    };

    private static void ValidateRate(FrameRate rate, bool dropFrame)
    {
        _ = NominalRate(rate);
        if (dropFrame && rate is not { Numerator: 30_000 or 60_000, Denominator: 1_001 })
            throw new ArgumentException("Drop-frame is supported only at 30000/1001 and 60000/1001.", nameof(dropFrame));
    }
}

public sealed record SyncAnchor(string Id, SyncMethod Method, string? ClipId, string? MediaAssetId, long OffsetSamples,
    double Confidence, JsonObject Metadata);
public sealed record AdrRecordingMetadata(string? Performer, string? Microphone, string? Input, string? RecordedAt,
    int SampleRate, int Channels, JsonObject Metadata);
public sealed record AdrTake(string Id, string CueId, string MediaAssetId, AdrReviewStatus ReviewStatus, bool Preferred,
    AdrRecordingMetadata Recording, JsonObject Metadata);
public sealed record AdrCue(string Id, string? ClipId, long StartSample, long EndSample, string Text, string? Performer,
    ImmutableArray<AdrTake> Takes, JsonObject Metadata);
public sealed record ReconformHistoryEntry(string Id, string AppliedAt, ImmutableArray<ReconformEdit> Edits, JsonObject Metadata);
public sealed record InterchangeHistoryEntry(string Id, string Format, string Direction, CompatibilityReport Compatibility, JsonObject Metadata);
public sealed record AudioLayoutDescriptor(string Id, AudioChannelLayout Layout, int Channels, string? MediaAssetId,
    ImmutableArray<ObjectAudioDescriptor> Objects, JsonObject Metadata);
public sealed record ObjectAudioDescriptor(string Id, string? MediaAssetId, double Azimuth, double Elevation, double Gain,
    JsonObject Metadata);
public sealed record PostProductionDocument(int SchemaVersion, ImmutableArray<SyncAnchor> SyncAnchors,
    ImmutableArray<AdrCue> AdrCues, ImmutableArray<ReconformHistoryEntry> ReconformHistory,
    ImmutableArray<InterchangeHistoryEntry> InterchangeHistory, ImmutableArray<AudioLayoutDescriptor> AudioLayouts,
    JsonObject Metadata);

public sealed record CompatibilityIssue(string Code, CompatibilitySeverity Severity, string Message);
public sealed record CompatibilityReport(ImmutableArray<CompatibilityIssue> Issues)
{
    public static CompatibilityReport Compatible { get; } = new([]);
    public bool IsCompatible => !Issues.Any(issue => issue.Severity == CompatibilitySeverity.Error);
    public bool IsLossless => Issues.IsEmpty;
}
public sealed record InterchangeResult<T>(T Value, CompatibilityReport Compatibility);

public static class PostProductionInterchangeConsent
{
    public static bool RequiresExplicitConsent(CompatibilityReport compatibility) => !compatibility.IsLossless;
}

public static class PostProductionHistory
{
    public static PostProductionDocument AppendInterchange(PostProductionDocument document, string format, string direction,
        CompatibilityReport compatibility, string? fileName = null)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (string.IsNullOrWhiteSpace(format)) throw new ArgumentException("Interchange format is required.", nameof(format));
        if (direction is not ("import" or "export")) throw new ArgumentException("Direction must be import or export.", nameof(direction));
        var metadata = new JsonObject { ["completed_at"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture) };
        if (!string.IsNullOrWhiteSpace(fileName)) metadata["file_name"] = Path.GetFileName(fileName);
        string id = $"interchange-{Guid.NewGuid():N}";
        return document with
        {
            InterchangeHistory = document.InterchangeHistory.Add(new(id, format.Trim(), direction, compatibility, metadata))
        };
    }
}

public static class PostProductionContracts
{
    public const int SchemaVersion = 1;
    private const int MaximumItems = 10_000;

    public static PostProductionDocument Read(JsonObject timeline)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        if (timeline["post"] is null) return Empty();
        if (timeline["post"] is not JsonObject post) throw new InvalidDataException("Timeline post document must be an object.");
        int version = Integer(post, "schema_version");
        if (version != SchemaVersion) throw new InvalidDataException($"Unsupported post schema version '{version}'.");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var anchors = Objects(post, "sync_anchors").Select(node => new SyncAnchor(
            Id(node, "sync anchor", ids), ParseSync(Required(node, "method")), Optional(node, "clip_id"), Optional(node, "media_asset_id"),
            SignedSample(node, "offset_samples"), Confidence(node), node.DeepClone().AsObject())).ToImmutableArray();
        var cues = ImmutableArray.CreateBuilder<AdrCue>();
        foreach (JsonObject node in Objects(post, "adr_cues"))
        {
            string cueId = Id(node, "ADR cue", ids);
            long start = Sample(node, "start_sample"), end = Sample(node, "end_sample");
            if (end <= start) throw new InvalidDataException($"ADR cue '{cueId}' must have positive duration.");
            var takes = ImmutableArray.CreateBuilder<AdrTake>();
            foreach (JsonObject take in Objects(node, "takes"))
            {
                string takeId = Id(take, "ADR take", ids);
                string owner = Required(take, "cue_id");
                if (owner != cueId) throw new InvalidDataException($"ADR take '{takeId}' belongs to another cue.");
                JsonObject recording = take["recording"] as JsonObject ?? throw new InvalidDataException("ADR take recording metadata is required.");
                int sampleRate = Integer(recording, "sample_rate"), channels = Integer(recording, "channels");
                if (sampleRate is < 8_000 or > 384_000 || channels is < 1 or > 64) throw new InvalidDataException("ADR recording format is invalid.");
                takes.Add(new(takeId, owner, Required(take, "media_asset_id"), ParseReview(Optional(take, "review_status") ?? "unreviewed"),
                    Boolean(take, "preferred"), new(Optional(recording, "performer"), Optional(recording, "microphone"),
                    Optional(recording, "input"), Optional(recording, "recorded_at"), sampleRate, channels, recording.DeepClone().AsObject()), take.DeepClone().AsObject()));
            }
            if (takes.Count(take => take.Preferred) > 1) throw new InvalidDataException($"ADR cue '{cueId}' has multiple preferred takes.");
            cues.Add(new(cueId, Optional(node, "clip_id"), start, end, Required(node, "text"), Optional(node, "performer"), takes.ToImmutable(), node.DeepClone().AsObject()));
        }
        var reconforms = Objects(post, "reconform_history").Select(node => new ReconformHistoryEntry(Id(node, "reconform", ids),
            Required(node, "applied_at"), ReadEdits(node), node.DeepClone().AsObject())).ToImmutableArray();
        var interchange = Objects(post, "interchange_history").Select(node => new InterchangeHistoryEntry(Id(node, "interchange", ids),
            Required(node, "format"), Required(node, "direction"), ReadReport(node["compatibility"]), node.DeepClone().AsObject())).ToImmutableArray();
        var layouts = ImmutableArray.CreateBuilder<AudioLayoutDescriptor>();
        foreach (JsonObject node in Objects(post, "audio_layouts"))
        {
            string id = Id(node, "audio layout", ids);
            AudioChannelLayout layout = ParseLayout(Required(node, "layout"));
            int channels = Integer(node, "channels");
            int expected = layout switch { AudioChannelLayout.Mono => 1, AudioChannelLayout.Stereo => 2, AudioChannelLayout.Surround51 => 6, AudioChannelLayout.Surround71 => 8, _ => channels };
            if (channels < 1 || channels > 128 || layout != AudioChannelLayout.Object && channels != expected)
                throw new InvalidDataException($"Audio layout '{id}' has an invalid channel count.");
            var objects = Objects(node, "objects").Select(value => new ObjectAudioDescriptor(Id(value, "audio object", ids),
                Optional(value, "media_asset_id"), Finite(value, "azimuth"), Finite(value, "elevation"), Finite(value, "gain"), value.DeepClone().AsObject())).ToImmutableArray();
            if (layout != AudioChannelLayout.Object && !objects.IsEmpty) throw new InvalidDataException("Only object layouts may contain audio objects.");
            layouts.Add(new(id, layout, channels, Optional(node, "media_asset_id"), objects, node.DeepClone().AsObject()));
        }
        return new(version, anchors, cues.ToImmutable(), reconforms, interchange, layouts.ToImmutable(), post.DeepClone().AsObject());
    }

    public static JsonObject Write(JsonObject timeline, PostProductionDocument document)
    {
        ArgumentNullException.ThrowIfNull(timeline); ArgumentNullException.ThrowIfNull(document);
        if (document.SchemaVersion != SchemaVersion) throw new InvalidDataException($"Unsupported post schema version '{document.SchemaVersion}'.");
        JsonObject result = timeline.DeepClone().AsObject();
        JsonObject post = document.Metadata.DeepClone().AsObject();
        post["schema_version"] = SchemaVersion;
        post["sync_anchors"] = Array(document.SyncAnchors.Select(WriteAnchor));
        post["adr_cues"] = Array(document.AdrCues.Select(WriteCue));
        post["reconform_history"] = Array(document.ReconformHistory.Select(WriteReconform));
        post["interchange_history"] = Array(document.InterchangeHistory.Select(WriteInterchange));
        post["audio_layouts"] = Array(document.AudioLayouts.Select(WriteLayout));
        result["post"] = post;
        _ = Read(result);
        return result;
    }

    public static void ValidateAgainstProject(CanonicalProject project, PostProductionDocument document)
    {
        ArgumentNullException.ThrowIfNull(project); ArgumentNullException.ThrowIfNull(document);
        var clips = project.Tracks.SelectMany(track => track.Events).ToDictionary(clip => clip.Id, StringComparer.Ordinal);
        var assets = project.MediaAssets.Select(asset => asset.Id).ToHashSet(StringComparer.Ordinal);
        var ids = project.Tracks.Select(track => track.Id).Concat(clips.Keys).Concat(assets).Concat(project.Markers.Select(marker => marker.Id)).ToHashSet(StringComparer.Ordinal);
        IEnumerable<string> postIds = document.SyncAnchors.Select(value => value.Id)
            .Concat(document.AdrCues.SelectMany(cue => cue.Takes.Select(take => take.Id).Prepend(cue.Id)))
            .Concat(document.ReconformHistory.Select(value => value.Id)).Concat(document.InterchangeHistory.Select(value => value.Id))
            .Concat(document.AudioLayouts.SelectMany(layout => layout.Objects.Select(value => value.Id).Prepend(layout.Id)));
        foreach (string id in postIds) if (!ids.Add(id)) throw new InvalidDataException($"Post ID '{id}' collides with another project identifier.");
        foreach (SyncAnchor anchor in document.SyncAnchors)
        {
            if (anchor.ClipId is not null && !clips.ContainsKey(anchor.ClipId) || anchor.MediaAssetId is not null && !assets.Contains(anchor.MediaAssetId))
                throw new InvalidDataException($"Sync anchor '{anchor.Id}' has an invalid clip or media reference.");
            if (anchor.ClipId is null && anchor.MediaAssetId is null) throw new InvalidDataException($"Sync anchor '{anchor.Id}' needs a clip or media reference.");
        }
        foreach (AdrCue cue in document.AdrCues)
        {
            if (cue.ClipId is not null && (!clips.TryGetValue(cue.ClipId, out TimelineEvent? clip) || cue.StartSample < clip.Start.Samples || cue.EndSample > clip.End.Samples))
                throw new InvalidDataException($"ADR cue '{cue.Id}' is outside its clip.");
            foreach (AdrTake take in cue.Takes) if (!assets.Contains(take.MediaAssetId)) throw new InvalidDataException($"ADR take '{take.Id}' references missing media.");
        }
        foreach (AudioLayoutDescriptor layout in document.AudioLayouts)
        {
            if (layout.MediaAssetId is not null && !assets.Contains(layout.MediaAssetId)) throw new InvalidDataException($"Audio layout '{layout.Id}' references missing media.");
            foreach (ObjectAudioDescriptor value in layout.Objects) if (value.MediaAssetId is not null && !assets.Contains(value.MediaAssetId)) throw new InvalidDataException($"Audio object '{value.Id}' references missing media.");
        }
    }

    public static PostProductionDocument Empty() => new(SchemaVersion, [], [], [], [], [], new JsonObject());
    internal static string SampleText(long value) => value.ToString(CultureInfo.InvariantCulture);

    private static JsonObject WriteAnchor(SyncAnchor value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; n["method"] = SyncText(value.Method); SetOptional(n, "clip_id", value.ClipId); SetOptional(n, "media_asset_id", value.MediaAssetId); n["offset_samples"] = SampleText(value.OffsetSamples); n["confidence"] = value.Confidence; return n; }
    private static JsonObject WriteCue(AdrCue value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; SetOptional(n, "clip_id", value.ClipId); n["start_sample"] = SampleText(value.StartSample); n["end_sample"] = SampleText(value.EndSample); n["text"] = value.Text; SetOptional(n, "performer", value.Performer); n["takes"] = Array(value.Takes.Select(WriteTake)); return n; }
    private static JsonObject WriteTake(AdrTake value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; n["cue_id"] = value.CueId; n["media_asset_id"] = value.MediaAssetId; n["review_status"] = ReviewText(value.ReviewStatus); n["preferred"] = value.Preferred; JsonObject r = value.Recording.Metadata.DeepClone().AsObject(); SetOptional(r, "performer", value.Recording.Performer); SetOptional(r, "microphone", value.Recording.Microphone); SetOptional(r, "input", value.Recording.Input); SetOptional(r, "recorded_at", value.Recording.RecordedAt); r["sample_rate"] = value.Recording.SampleRate; r["channels"] = value.Recording.Channels; n["recording"] = r; return n; }
    private static JsonObject WriteReconform(ReconformHistoryEntry value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; n["applied_at"] = value.AppliedAt; n["edits"] = Array(value.Edits.Select(WriteEdit)); return n; }
    private static JsonObject WriteInterchange(InterchangeHistoryEntry value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; n["format"] = value.Format; n["direction"] = value.Direction; n["compatibility"] = WriteReport(value.Compatibility); return n; }
    private static JsonObject WriteLayout(AudioLayoutDescriptor value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; n["layout"] = LayoutText(value.Layout); n["channels"] = value.Channels; SetOptional(n, "media_asset_id", value.MediaAssetId); n["objects"] = Array(value.Objects.Select(WriteObject)); return n; }
    private static JsonObject WriteObject(ObjectAudioDescriptor value) { JsonObject n = value.Metadata.DeepClone().AsObject(); n["id"] = value.Id; SetOptional(n, "media_asset_id", value.MediaAssetId); n["azimuth"] = value.Azimuth; n["elevation"] = value.Elevation; n["gain"] = value.Gain; return n; }
    internal static JsonObject WriteEdit(ReconformEdit value) { JsonObject n = value.Metadata?.DeepClone().AsObject() ?? new JsonObject(); n["kind"] = EditText(value.Kind); n["old_start_sample"] = SampleText(value.OldStartSample); n["old_end_sample"] = SampleText(value.OldEndSample); n["new_start_sample"] = SampleText(value.NewStartSample); n["new_end_sample"] = SampleText(value.NewEndSample); return n; }
    private static ImmutableArray<ReconformEdit> ReadEdits(JsonObject owner)
    {
        ImmutableArray<ReconformEdit> edits = Objects(owner, "edits").Select(n => new ReconformEdit(ParseEdit(Required(n, "kind")), Sample(n, "old_start_sample"), Sample(n, "old_end_sample"), Sample(n, "new_start_sample"), Sample(n, "new_end_sample"), n.DeepClone().AsObject())).ToImmutableArray();
        ReconformPlan plan = ReconformService.Plan(edits);
        if (!plan.CanApply) throw new InvalidDataException("Reconform history contains invalid or conflicting edits.");
        return edits;
    }
    private static CompatibilityReport ReadReport(JsonNode? node) { if (node is null) return CompatibilityReport.Compatible; if (node is not JsonObject report) throw new InvalidDataException("Compatibility report must be an object."); return new(Objects(report, "issues").Select(i => new CompatibilityIssue(Required(i, "code"), Enum.Parse<CompatibilitySeverity>(Required(i, "severity"), true), Required(i, "message"))).ToImmutableArray()); }
    private static JsonObject WriteReport(CompatibilityReport report) => new() { ["issues"] = Array(report.Issues.Select(i => new JsonObject { ["code"] = i.Code, ["severity"] = i.Severity.ToString().ToLowerInvariant(), ["message"] = i.Message })) };
    private static JsonArray Array(IEnumerable<JsonObject> values) => new(values.Select(value => (JsonNode?)value).ToArray());
    private static IEnumerable<JsonObject> Objects(JsonObject owner, string name) { if (owner[name] is null) yield break; if (owner[name] is not JsonArray a || a.Count > MaximumItems) throw new InvalidDataException($"'{name}' must be a bounded array."); foreach (JsonNode? n in a) yield return n as JsonObject ?? throw new InvalidDataException($"'{name}' entries must be objects."); }
    private static string Id(JsonObject n, string kind, HashSet<string> ids) { string id = Required(n, "id"); if (!ids.Add(id)) throw new InvalidDataException($"Duplicate {kind} ID '{id}'."); return id; }
    private static string Required(JsonObject n, string name) => Optional(n, name) is { Length: > 0 } text ? text : throw new InvalidDataException($"'{name}' is required.");
    private static string? Optional(JsonObject n, string name) => n[name] is null ? null : n[name] is JsonValue v && v.TryGetValue<string>(out string? text) ? text : throw new InvalidDataException($"'{name}' must be a string.");
    private static int Integer(JsonObject n, string name) => n[name] is JsonValue v && v.TryGetValue<int>(out int value) ? value : throw new InvalidDataException($"'{name}' must be an integer.");
    private static bool Boolean(JsonObject n, string name) => n[name] is JsonValue v && v.TryGetValue<bool>(out bool value) && value;
    private static long Sample(JsonObject n, string name) { string text = Required(n, name); if (!long.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out long value) || value < 0 || SampleText(value) != text) throw new InvalidDataException($"'{name}' must be a canonical nonnegative int64 sample string."); return value; }
    private static long SignedSample(JsonObject n, string name) { string text = Required(n, name); if (!long.TryParse(text, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long value) || SampleText(value) != text) throw new InvalidDataException($"'{name}' must be a canonical int64 sample string."); return value; }
    private static double Finite(JsonObject n, string name) => n[name] is JsonValue v && v.TryGetValue<double>(out double value) && double.IsFinite(value) ? value : throw new InvalidDataException($"'{name}' must be finite.");
    private static double Confidence(JsonObject n) { double value = Finite(n, "confidence"); if (value is < 0 or > 1) throw new InvalidDataException("Confidence must be between zero and one."); return value; }
    private static void SetOptional(JsonObject n, string name, string? value) { if (value is null) n.Remove(name); else n[name] = value; }
    internal static string SyncText(SyncMethod value) => value switch { SyncMethod.Timecode => "timecode", SyncMethod.Clap => "clap", SyncMethod.Transient => "transient", SyncMethod.WaveformCorrelation => "waveform_correlation", _ => throw new ArgumentOutOfRangeException(nameof(value)) };
    public static SyncMethod ParseSyncSelection(string value) => value switch { "timecode" => SyncMethod.Timecode, "clap" => SyncMethod.Clap, "transient" => SyncMethod.Transient, "waveform_correlation" => SyncMethod.WaveformCorrelation, _ => throw new InvalidDataException("Unknown sync method.") };
    private static SyncMethod ParseSync(string value) => ParseSyncSelection(value);
    private static AdrReviewStatus ParseReview(string value) => value switch { "unreviewed" => AdrReviewStatus.Unreviewed, "approved" => AdrReviewStatus.Approved, "rejected" => AdrReviewStatus.Rejected, _ => throw new InvalidDataException("Unknown ADR review status.") };
    private static string ReviewText(AdrReviewStatus value) => value.ToString().ToLowerInvariant();
    private static AudioChannelLayout ParseLayout(string value) => value switch { "mono" => AudioChannelLayout.Mono, "stereo" => AudioChannelLayout.Stereo, "5.1" => AudioChannelLayout.Surround51, "7.1" => AudioChannelLayout.Surround71, "object" => AudioChannelLayout.Object, _ => throw new InvalidDataException("Unsupported audio channel layout.") };
    internal static string LayoutText(AudioChannelLayout value) => value switch { AudioChannelLayout.Mono => "mono", AudioChannelLayout.Stereo => "stereo", AudioChannelLayout.Surround51 => "5.1", AudioChannelLayout.Surround71 => "7.1", AudioChannelLayout.Object => "object", _ => throw new ArgumentOutOfRangeException(nameof(value)) };
    private static ReconformEditKind ParseEdit(string value) => value switch { "insert" => ReconformEditKind.Insert, "delete" => ReconformEditKind.Delete, "move" => ReconformEditKind.Move, _ => throw new InvalidDataException("Unknown reconform edit kind.") };
    internal static string EditText(ReconformEditKind value) => value.ToString().ToLowerInvariant();
}

public sealed record AlignmentResult(long OffsetSamples, double Confidence, int OverlapSamples, bool Acceptable,
    bool Ambiguous, string Diagnostics);

public static class PostAlignment
{
    public static AlignmentResult FromTimecode(Timecode reference, Timecode candidate, ProjectTimebase timebase, double threshold = .8)
    {
        if (reference.Rate != candidate.Rate || reference.DropFrame != candidate.DropFrame) throw new ArgumentException("Timecodes must use the same rate and mode.");
        long offset = timebase.FromFrame(candidate.FrameNumber - reference.FrameNumber).Samples;
        return new(offset, 1, 1, true, false, "Exact timecode alignment.");
    }

    public static AlignmentResult StrongestOnset(ReadOnlySpan<float> reference, ReadOnlySpan<float> candidate,
        SyncMethod method = SyncMethod.Clap, double threshold = .6, CancellationToken cancellationToken = default)
    {
        if (method is not (SyncMethod.Clap or SyncMethod.Transient)) throw new ArgumentException("Onset alignment requires clap or transient method.");
        if (reference.Length < 2 || candidate.Length < 2) return Insufficient("At least two samples are required.");
        (int ri, double rv, double rs) = Peak(reference, cancellationToken); (int ci, double cv, double cs) = Peak(candidate, cancellationToken);
        double confidence = Math.Min(rv / Math.Max(rs, 1e-12), cv / Math.Max(cs, 1e-12));
        confidence = Math.Clamp((confidence - 1) / 4, 0, 1);
        bool ambiguous = confidence < threshold;
        return new(ci - ri, confidence, Math.Min(reference.Length, candidate.Length), !ambiguous, ambiguous,
            ambiguous ? "Onset peak is ambiguous or below threshold." : $"Strongest {PostProductionContracts.SyncText(method)} onset aligned.");
    }

    public static AlignmentResult WaveformCorrelation(ReadOnlySpan<float> reference, ReadOnlySpan<float> candidate,
        int maximumShiftSamples, double threshold = .8, CancellationToken cancellationToken = default,
        long maximumOperations = long.MaxValue)
    {
        if (maximumShiftSamples < 0) throw new ArgumentOutOfRangeException(nameof(maximumShiftSamples));
        if (maximumOperations <= 0) throw new ArgumentOutOfRangeException(nameof(maximumOperations));
        if (reference.Length < 3 || candidate.Length < 3) return Insufficient("At least three samples are required.");
        long estimatedOperations = EstimateCorrelationOperations(reference.Length, candidate.Length, maximumShiftSamples);
        if (estimatedOperations > maximumOperations)
            throw new InvalidOperationException($"Correlation requires {estimatedOperations} sample operations, exceeding the configured limit of {maximumOperations}.");
        double best = double.NegativeInfinity, second = double.NegativeInfinity; int bestShift = 0, overlap = 0;
        for (int shift = -maximumShiftSamples; shift <= maximumShiftSamples; shift++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            int r0 = Math.Max(0, -shift), c0 = Math.Max(0, shift), count = Math.Min(reference.Length - r0, candidate.Length - c0);
            if (count < 3) continue;
            double rMean = 0, cMean = 0;
            for (int i = 0; i < count; i++) { if ((i & 0x3fff) == 0) cancellationToken.ThrowIfCancellationRequested(); rMean += reference[r0 + i]; cMean += candidate[c0 + i]; }
            rMean /= count; cMean /= count;
            double numerator = 0, rd = 0, cd = 0;
            for (int i = 0; i < count; i++) { if ((i & 0x3fff) == 0) cancellationToken.ThrowIfCancellationRequested(); double r = reference[r0 + i] - rMean, c = candidate[c0 + i] - cMean; numerator += r * c; rd += r * r; cd += c * c; }
            double score = rd > 0 && cd > 0 ? numerator / Math.Sqrt(rd * cd) : 0;
            if (score > best) { second = best; best = score; bestShift = shift; overlap = count; } else if (score > second) second = score;
        }
        double confidence = Math.Clamp(best, 0, 1); bool ambiguous = second > best - .01;
        bool acceptable = confidence >= threshold && !ambiguous;
        return new(bestShift, confidence, overlap, acceptable, ambiguous, acceptable ? "Normalized cross-correlation aligned." : ambiguous ? "Correlation peak is ambiguous." : "Correlation is below threshold.");
    }

    private static long EstimateCorrelationOperations(int referenceLength, int candidateLength, int maximumShiftSamples)
    {
        try { return checked((2L * maximumShiftSamples + 1) * Math.Min(referenceLength, candidateLength) * 2); }
        catch (OverflowException) { return long.MaxValue; }
    }

    private static (int Index, double Peak, double Second) Peak(ReadOnlySpan<float> data, CancellationToken cancellationToken)
    {
        int index = 1; double best = 0, second = 0;
        for (int i = 1; i < data.Length; i++)
        {
            if ((i & 0x3fff) == 0) cancellationToken.ThrowIfCancellationRequested();
            double value = Math.Abs(data[i] - data[i - 1]);
            if (value > best) { second = best; best = value; index = i; } else if (value > second) second = value;
        }
        return (index, best, second);
    }
    private static AlignmentResult Insufficient(string text) => new(0, 0, 0, false, true, text);
}

public static class AdrOperations
{
    public static PostProductionDocument AddCue(PostProductionDocument document, AdrCue cue)
    {
        if (document.AdrCues.Any(value => value.Id == cue.Id)) throw new InvalidOperationException("ADR cue ID already exists.");
        if (cue.StartSample < 0 || cue.EndSample <= cue.StartSample || string.IsNullOrWhiteSpace(cue.Id) || string.IsNullOrWhiteSpace(cue.Text)) throw new ArgumentException("ADR cue is invalid.", nameof(cue));
        return document with { AdrCues = document.AdrCues.Add(cue) };
    }
    public static PostProductionDocument RegisterTake(PostProductionDocument document, string cueId, AdrTake take)
    {
        int index = IndexOf(document.AdrCues, cue => cue.Id == cueId); if (index < 0) throw new KeyNotFoundException("ADR cue was not found.");
        if (take.CueId != cueId || document.AdrCues.SelectMany(c => c.Takes).Any(value => value.Id == take.Id)) throw new InvalidOperationException("ADR take owner or ID is invalid.");
        AdrCue cue = document.AdrCues[index]; if (take.Preferred && cue.Takes.Any(value => value.Preferred)) throw new InvalidOperationException("The cue already has a preferred take.");
        return document with { AdrCues = document.AdrCues.SetItem(index, cue with { Takes = cue.Takes.Add(take) }) };
    }
    public static PostProductionDocument ReviewTake(PostProductionDocument document, string cueId, string takeId, AdrReviewStatus status, bool preferred = false)
    {
        int cueIndex = IndexOf(document.AdrCues, cue => cue.Id == cueId); if (cueIndex < 0) throw new KeyNotFoundException("ADR cue was not found.");
        AdrCue cue = document.AdrCues[cueIndex]; int takeIndex = IndexOf(cue.Takes, take => take.Id == takeId); if (takeIndex < 0) throw new KeyNotFoundException("ADR take was not found.");
        if (preferred && status != AdrReviewStatus.Approved) throw new InvalidOperationException("Only an approved take can be preferred.");
        ImmutableArray<AdrTake> takes = cue.Takes.Select((take, index) => index == takeIndex ? take with { ReviewStatus = status, Preferred = preferred } : preferred ? take with { Preferred = false } : take).ToImmutableArray();
        return document with { AdrCues = document.AdrCues.SetItem(cueIndex, cue with { Takes = takes }) };
    }
    private static int IndexOf<T>(ImmutableArray<T> values, Func<T, bool> predicate)
    {
        for (int index = 0; index < values.Length; index++) if (predicate(values[index])) return index;
        return -1;
    }
}

public sealed record ReconformEdit(ReconformEditKind Kind, long OldStartSample, long OldEndSample, long NewStartSample,
    long NewEndSample, JsonObject? Metadata = null);
public sealed record ReconformConflict(string Code, string Message, string? ItemId);
public sealed record ReconformPlan(ImmutableArray<ReconformEdit> Edits, ImmutableArray<ReconformConflict> Conflicts)
{ public bool CanApply => Conflicts.IsEmpty; }
public sealed record ReconformResult(CanonicalProject Project, PostProductionDocument Post);

public static class ReconformService
{
    public static ReconformPlan Plan(IEnumerable<ReconformEdit> edits)
    {
        ImmutableArray<ReconformEdit> ordered = edits.OrderBy(value => value.OldStartSample).ThenBy(value => value.NewStartSample).ToImmutableArray();
        var conflicts = ImmutableArray.CreateBuilder<ReconformConflict>(); long oldEnd = -1, newEnd = -1, cumulativeDelta = 0;
        foreach (ReconformEdit edit in ordered)
        {
            if (edit.OldStartSample < 0 || edit.NewStartSample < 0 || edit.OldEndSample < edit.OldStartSample || edit.NewEndSample < edit.NewStartSample)
                conflicts.Add(new("invalid_range", "Reconform ranges must be ordered and nonnegative.", null));
            if (edit.OldStartSample < oldEnd || edit.NewStartSample < newEnd) conflicts.Add(new("overlap", "Reconform edits overlap.", null));
            if (edit.Kind == ReconformEditKind.Insert && edit.OldStartSample != edit.OldEndSample || edit.Kind == ReconformEditKind.Delete && edit.NewStartSample != edit.NewEndSample || edit.Kind == ReconformEditKind.Move && edit.OldEndSample - edit.OldStartSample != edit.NewEndSample - edit.NewStartSample)
                conflicts.Add(new("kind_range_mismatch", "Reconform edit ranges do not match their kind.", null));
            if (edit.Kind is ReconformEditKind.Insert or ReconformEditKind.Delete)
            {
                long expected = checked(edit.OldStartSample + cumulativeDelta);
                if (edit.NewStartSample != expected)
                    conflicts.Add(new("coordinate_mismatch", "Reconform new coordinates do not match preceding edit deltas.", null));
                cumulativeDelta = checked(cumulativeDelta + (edit.NewEndSample - edit.NewStartSample) -
                    (edit.OldEndSample - edit.OldStartSample));
            }
            oldEnd = Math.Max(oldEnd, edit.OldEndSample); newEnd = Math.Max(newEnd, edit.NewEndSample);
        }
        return new(ordered, conflicts.ToImmutable());
    }

    public static ReconformResult Apply(CanonicalProject project, PostProductionDocument post, ReconformPlan plan)
    {
        if (!plan.CanApply) throw new InvalidOperationException("A reconform plan with conflicts cannot be applied.");
        foreach (Track track in project.Tracks.Where(value => value.Locked))
            if (track.Events.Any(clip => plan.Edits.Any(edit => Affects(clip.Start.Samples, clip.End.Samples, edit))))
                throw new InvalidOperationException($"Locked track '{track.Id}' is affected by reconform.");
        long Map(long sample) => MapSample(sample, plan.Edits, startBoundary: true);
        var allocatedIds = ProjectAndPostIds(project, post).ToHashSet(StringComparer.Ordinal);
        var clipMappings = new List<ClipSegmentMapping>();
        IReadOnlyList<Track> tracks = project.Tracks.Select(track =>
        {
            ClipEditResult transformed = ApplyClipEdits(track.Events, plan.Edits, project.Timebase.SampleRate, allocatedIds);
            clipMappings.AddRange(transformed.Mappings);
            return track with { Events = transformed.Clips };
        }).ToArray();
        IReadOnlyList<TimelineMarker> markers = project.Markers.Select(marker => marker with { Position = new(Map(marker.Position.Samples)) }).ToArray();
        ImmutableArray<AdrCue> cues = post.AdrCues.Select(cue => (Cue: cue, Start: Map(cue.StartSample), End: Map(cue.EndSample)))
            .Where(value => value.End > value.Start)
            .Select(value => value.Cue with
            {
                StartSample = value.Start,
                EndSample = value.End,
                ClipId = RemapCueClip(value.Cue, clipMappings)
            })
            .ToImmutableArray();
        var history = new ReconformHistoryEntry(Guid.NewGuid().ToString("N"), DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture), plan.Edits, new JsonObject());
        PostProductionDocument updated = post with
        {
            SyncAnchors = post.SyncAnchors.Select(anchor => anchor with
                {
                    OffsetSamples = anchor.OffsetSamples < 0 ? anchor.OffsetSamples : Map(anchor.OffsetSamples),
                    ClipId = anchor.OffsetSamples < 0
                        ? RemapRelativeClip(anchor.ClipId, clipMappings)
                        : RemapPointClip(anchor.ClipId, anchor.OffsetSamples, clipMappings)
                })
                .Where(anchor => anchor.ClipId is not null || anchor.MediaAssetId is not null)
                .ToImmutableArray(),
            AdrCues = cues,
            ReconformHistory = post.ReconformHistory.Add(history)
        };
        CanonicalProject result = project with { Tracks = tracks, Markers = markers }; result = result with { Timeline = PostProductionContracts.Write(ProjectTimelineContracts.RebuildTimeline(result), updated) };
        return new(result, updated);
    }
    private static bool Affects(long start, long end, ReconformEdit edit) => edit.Kind == ReconformEditKind.Insert ? end >= edit.OldStartSample : start < edit.OldEndSample && end > edit.OldStartSample;

    private sealed record ClipSegmentMapping(string OriginalId, long OriginalStart, long OriginalEnd, string ResultId);
    private sealed record ClipEditResult(IReadOnlyList<TimelineEvent> Clips, IReadOnlyList<ClipSegmentMapping> Mappings);

    private static ClipEditResult ApplyClipEdits(
        IReadOnlyList<TimelineEvent> clips,
        ImmutableArray<ReconformEdit> edits,
        int timelineSampleRate,
        HashSet<string> allocatedIds)
    {
        var results = new List<TimelineEvent>();
        var mappings = new List<ClipSegmentMapping>();
        foreach (TimelineEvent clip in clips)
        {
            List<(long Start, long End)> retained = [(clip.Start.Samples, clip.End.Samples)];
            foreach (ReconformEdit edit in edits.Where(edit => edit.Kind == ReconformEditKind.Delete))
            {
                retained = retained.SelectMany(segment => Subtract(segment, edit.OldStartSample, edit.OldEndSample)).ToList();
            }
            foreach (long split in edits.Where(edit => edit.Kind == ReconformEditKind.Insert)
                         .Select(edit => edit.OldStartSample).Distinct().Order())
            {
                retained = retained.SelectMany(segment => Split(segment, split)).ToList();
            }

            int segmentIndex = 0;
            foreach ((long sourceStart, long sourceEnd) in retained)
            {
                ReconformEdit? move = edits.FirstOrDefault(edit => edit.Kind == ReconformEditKind.Move &&
                    sourceStart >= edit.OldStartSample && sourceEnd <= edit.OldEndSample);
                if (edits.Any(edit => edit.Kind == ReconformEditKind.Move &&
                                      sourceStart < edit.OldEndSample && sourceEnd > edit.OldStartSample) && move is null)
                    throw new InvalidOperationException($"Move reconform crosses clip '{clip.Id}'. Split the clip at the move boundaries before applying.");

                long resultStart = move is null
                    ? MapSample(sourceStart, edits, startBoundary: true)
                    : checked(move.NewStartSample + sourceStart - move.OldStartSample);
                long resultEnd = move is null
                    ? MapSample(sourceEnd, edits, startBoundary: false)
                    : checked(move.NewStartSample + sourceEnd - move.OldStartSample);
                if (resultEnd <= resultStart) continue;
                string id = segmentIndex++ == 0 ? clip.Id : AllocateSplitId(clip.Id, sourceStart, allocatedIds);
                results.Add(Segment(clip, sourceStart, sourceEnd, resultStart, resultEnd, timelineSampleRate, id));
                mappings.Add(new(clip.Id, sourceStart, sourceEnd, id));
            }
        }
        return new(results, mappings);
    }

    private static IEnumerable<(long Start, long End)> Subtract((long Start, long End) segment, long deleteStart, long deleteEnd)
    {
        if (segment.End <= deleteStart || segment.Start >= deleteEnd) return [segment];
        if (segment.Start >= deleteStart && segment.End <= deleteEnd) return [];
        if (segment.Start < deleteStart && segment.End > deleteEnd)
            return [(segment.Start, deleteStart), (deleteEnd, segment.End)];
        return segment.Start < deleteStart ? [(segment.Start, deleteStart)] : [(deleteEnd, segment.End)];
    }

    private static IEnumerable<(long Start, long End)> Split((long Start, long End) segment, long position)
    {
        if (position <= segment.Start || position >= segment.End) return [segment];
        return [(segment.Start, position), (position, segment.End)];
    }

    private static long MapSample(long sample, ImmutableArray<ReconformEdit> edits, bool startBoundary)
    {
        long delta = 0;
        foreach (ReconformEdit edit in edits)
        {
            bool insideMove = startBoundary
                ? sample >= edit.OldStartSample && sample < edit.OldEndSample
                : sample > edit.OldStartSample && sample <= edit.OldEndSample;
            if (edit.Kind == ReconformEditKind.Move && insideMove)
                return checked(edit.NewStartSample + sample - edit.OldStartSample);
            if (edit.Kind == ReconformEditKind.Insert &&
                (sample > edit.OldStartSample || startBoundary && sample == edit.OldStartSample))
                delta = checked(delta + edit.NewEndSample - edit.NewStartSample);
            else if (edit.Kind == ReconformEditKind.Delete)
            {
                if (sample > edit.OldStartSample && sample < edit.OldEndSample)
                    return checked(edit.OldStartSample + delta);
                if (sample >= edit.OldEndSample)
                    delta = checked(delta - (edit.OldEndSample - edit.OldStartSample));
            }
        }
        return checked(sample + delta);
    }

    private static TimelineEvent Segment(TimelineEvent clip, long sourceTimelineStart, long sourceTimelineEnd,
        long resultStart, long resultEnd, int timelineSampleRate, string id)
    {
        SourceRange? source = clip.Source;
        if (source is not null)
        {
            SourcePosition sourceStart = OffsetSource(source.Start, sourceTimelineStart - clip.Start.Samples, timelineSampleRate);
            SourcePosition sourceEnd = sourceTimelineEnd == clip.End.Samples && source.End is not null
                ? source.End
                : OffsetSource(source.Start, sourceTimelineEnd - clip.Start.Samples, timelineSampleRate);
            source = new SourceRange(sourceStart, sourceEnd);
        }
        return clip with { Id = id, Start = new(resultStart), End = new(resultEnd), Source = source };
    }

    private static SourcePosition OffsetSource(SourcePosition start, long timelineSamples, int timelineSampleRate)
    {
        (BigInteger remainderNumerator, BigInteger remainderDenominator) = ParseFraction(start.Remainder);
        BigInteger timelineRate = timelineSampleRate;
        BigInteger denominator = remainderDenominator / BigInteger.GreatestCommonDivisor(remainderDenominator, timelineRate) * timelineRate;
        BigInteger numerator = (new BigInteger(start.Samples) * remainderDenominator + remainderNumerator) * (denominator / remainderDenominator) +
                               new BigInteger(timelineSamples) * start.SampleRate * (denominator / timelineSampleRate);
        BigInteger samples = BigInteger.DivRem(numerator, denominator, out BigInteger remainder);
        if (samples > long.MaxValue) throw new OverflowException("Reconform source position exceeds the supported range.");
        if (remainder.IsZero) return new(start.SampleRate, (long)samples);
        BigInteger divisor = BigInteger.GreatestCommonDivisor(remainder, denominator);
        return new(start.SampleRate, (long)samples,
            $"{remainder / divisor}/{denominator / divisor}");
    }

    private static (BigInteger Numerator, BigInteger Denominator) ParseFraction(string value)
    {
        if (value == "0") return (BigInteger.Zero, BigInteger.One);
        string[] parts = value.Split('/');
        return (BigInteger.Parse(parts[0], CultureInfo.InvariantCulture), BigInteger.Parse(parts[1], CultureInfo.InvariantCulture));
    }

    private static string? RemapCueClip(AdrCue cue, IReadOnlyList<ClipSegmentMapping> mappings)
    {
        if (cue.ClipId is null) return null;
        ClipSegmentMapping? segment = mappings.FirstOrDefault(value => value.OriginalId == cue.ClipId &&
            cue.StartSample >= value.OriginalStart && cue.EndSample <= value.OriginalEnd);
        return segment?.ResultId;
    }

    private static string? RemapPointClip(string? clipId, long position, IReadOnlyList<ClipSegmentMapping> mappings)
    {
        if (clipId is null) return null;
        ClipSegmentMapping? segment = mappings.FirstOrDefault(value => value.OriginalId == clipId &&
            position >= value.OriginalStart && position < value.OriginalEnd);
        return segment?.ResultId;
    }

    private static string? RemapRelativeClip(string? clipId, IReadOnlyList<ClipSegmentMapping> mappings)
    {
        if (clipId is null) return null;
        return mappings.FirstOrDefault(value => value.OriginalId == clipId)?.ResultId;
    }

    private static string AllocateSplitId(string clipId, long sourceStart, HashSet<string> allocatedIds)
    {
        string prefix = $"{clipId}-reconform-{sourceStart}-right";
        string candidate = prefix;
        for (int suffix = 2; !allocatedIds.Add(candidate); suffix++) candidate = $"{prefix}-{suffix}";
        return candidate;
    }

    private static IEnumerable<string> ProjectAndPostIds(CanonicalProject project, PostProductionDocument post) =>
        project.Tracks.Select(track => track.Id)
            .Concat(project.Tracks.SelectMany(track => track.Events).Select(clip => clip.Id))
            .Concat(project.MediaAssets.Select(asset => asset.Id))
            .Concat(project.Markers.Select(marker => marker.Id))
            .Concat(post.SyncAnchors.Select(anchor => anchor.Id))
            .Concat(post.AdrCues.SelectMany(cue => cue.Takes.Select(take => take.Id).Prepend(cue.Id)))
            .Concat(post.ReconformHistory.Select(entry => entry.Id))
            .Concat(post.InterchangeHistory.Select(entry => entry.Id))
            .Concat(post.AudioLayouts.SelectMany(layout => layout.Objects.Select(item => item.Id).Prepend(layout.Id)));
}

public sealed record AudioLayoutCapability(AudioChannelLayout Layout, bool Preview, bool Render, bool Export, string Detail);
public enum PostProductionOperation { Preview, Render, Export }
public sealed record PostProductionOperationGate(bool Allowed, string Explanation, CompatibilityReport Compatibility);
public static class PostProductionCapabilities
{
    public static ImmutableArray<AudioLayoutCapability> Native { get; } =
    [
        new(AudioChannelLayout.Mono, false, false, false, "Native engine currently supports stereo only."),
        new(AudioChannelLayout.Stereo, true, true, true, "Native stereo preview, render, and export are supported."),
        new(AudioChannelLayout.Surround51, false, false, false, "5.1 metadata is preserved; native DSP is unsupported."),
        new(AudioChannelLayout.Surround71, false, false, false, "7.1 metadata is preserved; native DSP is unsupported."),
        new(AudioChannelLayout.Object, false, false, false, "Object metadata is preserved; native object DSP is unsupported.")
    ];
    public static CompatibilityReport Report(PostProductionDocument document) => new(document.AudioLayouts
        .Where(layout => layout.Layout != AudioChannelLayout.Stereo)
        .Select(layout => new CompatibilityIssue("unsupported_audio_layout", CompatibilitySeverity.Warning, $"Native preview/render/export does not support {PostProductionContracts.LayoutText(layout.Layout)}.")).ToImmutableArray());

    public static PostProductionOperationGate Gate(PostProductionDocument document, PostProductionOperation operation)
    {
        CompatibilityReport report = Report(document);
        AudioLayoutDescriptor? unsupported = document.AudioLayouts.FirstOrDefault(layout =>
        {
            AudioLayoutCapability capability = Native.Single(item => item.Layout == layout.Layout);
            return operation switch
            {
                PostProductionOperation.Preview => !capability.Preview,
                PostProductionOperation.Render => !capability.Render,
                PostProductionOperation.Export => !capability.Export,
                _ => true
            };
        });
        return unsupported is null
            ? new(true, string.Empty, report)
            : new(false,
                $"Native {operation.ToString().ToLowerInvariant()} is blocked because layout '{unsupported.Id}' is {PostProductionContracts.LayoutText(unsupported.Layout)}. Change it to stereo or use metadata-only canonical JSON interchange.",
                report);
    }
}

public static class PostProductionInterchange
{
    public static InterchangeResult<string> ExportCanonical(PostProductionDocument document)
    {
        JsonObject timeline = PostProductionContracts.Write(new JsonObject(), document);
        return new(timeline["post"]!.ToJsonString(), CompatibilityReport.Compatible);
    }
    public static InterchangeResult<PostProductionDocument> ImportCanonical(string json)
    {
        JsonObject post = JsonNode.Parse(json)?.AsObject() ?? throw new InvalidDataException("Canonical post JSON must be an object.");
        return new(PostProductionContracts.Read(new JsonObject { ["post"] = post }), CompatibilityReport.Compatible);
    }
    public static InterchangeResult<string> ExportCmx3600(CanonicalProject project, PostProductionDocument document, bool allowOmissions = false)
    {
        var issues = ImmutableArray.CreateBuilder<CompatibilityIssue>();
        if (!document.AdrCues.IsEmpty || !document.SyncAnchors.IsEmpty || !document.AudioLayouts.IsEmpty)
            issues.Add(new("cmx_omits_post_metadata", CompatibilitySeverity.Warning, "CMX3600 omits ADR, sync, channel-layout, and object metadata."));
        if (document.AudioLayouts.Any(layout => layout.Layout != AudioChannelLayout.Stereo))
            issues.Add(new("cmx_unsupported_audio_layout", CompatibilitySeverity.Warning, "CMX3600 cannot represent surround or object audio."));
        IReadOnlyDictionary<string, MediaAsset> assets = project.MediaAssets.ToDictionary(asset => asset.Id, StringComparer.Ordinal);
        foreach (TimelineEvent clip in project.Tracks.SelectMany(track => track.Events))
        {
            if (clip.MediaAssetId is null || !assets.TryGetValue(clip.MediaAssetId, out MediaAsset? asset) || OptionalText(asset.Metadata["reel_id"]) is null)
                issues.Add(new("cmx_missing_reel_id", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' has no CMX reel ID and will use AX."));
            if (clip.Data["transition"] is not null || clip.Data["effects"] is JsonArray { Count: > 0 })
                issues.Add(new("cmx_unsupported_clip_metadata", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' has transition or effect metadata that CMX3600 cannot preserve."));
            if (clip.Source is null)
                issues.Add(new("cmx_missing_source_range", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' has no source range; CMX source timecode will start at zero."));
            else if (clip.Source.End is null)
                issues.Add(new("cmx_missing_source_end", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' has no source end; CMX source out will be derived from timeline duration."));
            if (clip.Data["speed"] is JsonValue)
                issues.Add(new("cmx_speed_not_represented", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' has speed metadata that this CMX3600 export cannot represent."));
            if (!IsFrameBoundary(project.Timebase, clip.Start) || !IsFrameBoundary(project.Timebase, clip.End))
                issues.Add(new("cmx_frame_rounding", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' requires frame-boundary rounding."));
            if (clip.Source is not null && (!IsSourceFrameBoundary(project.Timebase, clip.Source.Start) ||
                                             clip.Source.End is not null && !IsSourceFrameBoundary(project.Timebase, clip.Source.End)))
                issues.Add(new("cmx_source_frame_rounding", CompatibilitySeverity.Warning, $"Clip '{clip.Id}' source range requires project-frame rounding."));
        }
        if (issues.Count > 0 && !allowOmissions) throw new InvalidOperationException("CMX3600 export would be lossy; pass allowOmissions=true to continue.");
        var text = new StringBuilder("TITLE: ").AppendLine(project.Name).AppendLine("FCM: " + (project.Timebase.DropFrame ? "DROP FRAME" : "NON-DROP FRAME")); int number = 1;
        foreach (TimelineEvent clip in project.Tracks.SelectMany(track => track.Events).OrderBy(value => value.Start.Samples))
        {
            string reel = clip.MediaAssetId is not null && assets.TryGetValue(clip.MediaAssetId, out MediaAsset? asset)
                ? OptionalText(asset.Metadata["reel_id"]) ?? "AX"
                : "AX";
            reel = reel[..Math.Min(8, reel.Length)].ToUpperInvariant();
            TimelinePosition sourceIn = clip.Source is null ? new(0) : SourcePositionToTimeline(project.Timebase, clip.Source.Start);
            TimelinePosition sourceOut = clip.Source?.End is not null
                ? SourcePositionToTimeline(project.Timebase, clip.Source.End)
                : new(checked(sourceIn.Samples + clip.End.Samples - clip.Start.Samples));
            text.Append(number++.ToString("000", CultureInfo.InvariantCulture)).Append("  ").Append(reel.PadRight(8)).Append(" V     C        ")
                .Append(SourceTimecode(project.Timebase, sourceIn)).Append(' ').Append(SourceTimecode(project.Timebase, sourceOut)).Append(' ')
                .Append(project.Timebase.ToTimecode(clip.Start)).Append(' ').AppendLine(project.Timebase.ToTimecode(clip.End).ToString());
            text.AppendLine("* FROM CLIP NAME: " + clip.Id);
        }
        return new(text.ToString(), new(issues.ToImmutable()));
    }
    public static InterchangeResult<ImmutableArray<ReconformEdit>> ImportCmx3600(string text, ProjectTimebase timebase)
    {
        var edits = ImmutableArray.CreateBuilder<ReconformEdit>(); var issues = ImmutableArray.CreateBuilder<CompatibilityIssue>();
        foreach (string line in text.Replace("\r", string.Empty).Split('\n').Where(line => line.Length >= 3 && char.IsDigit(line[0])))
        {
            string[] parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries); if (parts.Length < 8) { issues.Add(new("cmx_unparsed_event", CompatibilitySeverity.Warning, "A CMX event line was not understood.")); continue; }
            try { long oldStart = SourceTimecodeToPosition(parts[^4], timebase).Samples, oldEnd = SourceTimecodeToPosition(parts[^3], timebase).Samples, newStart = timebase.FromTimecode(parts[^2]).Samples, newEnd = timebase.FromTimecode(parts[^1]).Samples; edits.Add(new(ReconformEditKind.Move, oldStart, oldEnd, newStart, newEnd)); }
            catch (Exception e) when (e is FormatException or ArgumentException) { issues.Add(new("cmx_invalid_timecode", CompatibilitySeverity.Error, e.Message)); }
        }
        return new(edits.ToImmutable(), new(issues.ToImmutable()));
    }
    public static InterchangeResult<string> ExportAdrCsv(PostProductionDocument document)
    {
        var text = new StringBuilder("cue_id,start_sample,end_sample,text,performer,preferred_take,review_status\r\n");
        foreach (AdrCue cue in document.AdrCues) { AdrTake? take = cue.Takes.FirstOrDefault(value => value.Preferred); text.Append(Csv(cue.Id)).Append(',').Append(cue.StartSample).Append(',').Append(cue.EndSample).Append(',').Append(Csv(cue.Text)).Append(',').Append(Csv(cue.Performer ?? string.Empty)).Append(',').Append(Csv(take?.Id ?? string.Empty)).Append(',').AppendLine(Csv(take?.ReviewStatus.ToString().ToLowerInvariant() ?? string.Empty)); }
        var issues = ImmutableArray.CreateBuilder<CompatibilityIssue>();
        if (!document.AudioLayouts.IsEmpty || !document.SyncAnchors.IsEmpty || !document.ReconformHistory.IsEmpty || !document.InterchangeHistory.IsEmpty)
            issues.Add(new("adr_csv_omits_post_metadata", CompatibilitySeverity.Warning, "ADR CSV omits sync, reconform, interchange, and audio-layout metadata."));
        if (document.AdrCues.Any(cue => cue.ClipId is not null || cue.Metadata.Count > 0))
            issues.Add(new("adr_csv_omits_cue_metadata", CompatibilitySeverity.Warning, "ADR CSV omits cue clip associations and extension metadata."));
        if (document.AdrCues.Any(cue => !cue.Takes.IsEmpty))
            issues.Add(new("adr_csv_omits_take_metadata", CompatibilitySeverity.Warning, "ADR CSV cannot round-trip ADR takes, media references, recording metadata, or review state."));
        return new(text.ToString(), new(issues.ToImmutable()));
    }
    public static InterchangeResult<ImmutableArray<AdrCue>> ImportAdrCsv(string csv)
    {
        string[][] rows = ParseCsvRows(csv).Where(row => row.Any(value => value.Length > 0)).ToArray(); var cues = ImmutableArray.CreateBuilder<AdrCue>(); var issues = ImmutableArray.CreateBuilder<CompatibilityIssue>();
        if (rows.Length == 0 || rows[0].Length < 5 || !string.Equals(rows[0][0], "cue_id", StringComparison.OrdinalIgnoreCase))
            return new([], new([new("adr_csv_missing_header", CompatibilitySeverity.Error, "ADR CSV header is missing or invalid.")]));
        foreach (string[] fields in rows.Skip(1)) { if (fields.Length < 5 || string.IsNullOrWhiteSpace(fields[0]) || !long.TryParse(fields[1], NumberStyles.None, CultureInfo.InvariantCulture, out long start) || !long.TryParse(fields[2], NumberStyles.None, CultureInfo.InvariantCulture, out long end) || end <= start) { issues.Add(new("adr_csv_invalid_row", CompatibilitySeverity.Error, "An ADR CSV row is invalid.")); continue; } if (fields.Length > 5 && fields.Skip(5).Any(value => value.Length > 0)) issues.Add(new("adr_csv_take_reference", CompatibilitySeverity.Warning, "Take references require media metadata and were not imported.")); cues.Add(new(fields[0], null, start, end, fields[3], fields[4], [], new JsonObject())); }
        return new(cues.ToImmutable(), new(issues.ToImmutable()));
    }
    private static string Csv(string value) => value.IndexOfAny([',', '"', '\r', '\n']) < 0 ? value : '"' + value.Replace("\"", "\"\"") + '"';
    private static IEnumerable<string[]> ParseCsvRows(string csv) { var row = new List<string>(); var value = new StringBuilder(); bool quoted = false; for (int i = 0; i < csv.Length; i++) { char c = csv[i]; if (c == '"' && quoted && i + 1 < csv.Length && csv[i + 1] == '"') { value.Append('"'); i++; } else if (c == '"') quoted = !quoted; else if (c == ',' && !quoted) { row.Add(value.ToString()); value.Clear(); } else if (c is '\r' or '\n' && !quoted) { if (c == '\r' && i + 1 < csv.Length && csv[i + 1] == '\n') i++; row.Add(value.ToString()); value.Clear(); yield return row.ToArray(); row.Clear(); } else value.Append(c); } if (quoted) throw new InvalidDataException("ADR CSV contains an unterminated quoted field."); if (value.Length > 0 || row.Count > 0) { row.Add(value.ToString()); yield return row.ToArray(); } }
    private static string? OptionalText(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out string? text) && !string.IsNullOrWhiteSpace(text) ? text.Trim() : null;
    private static bool IsFrameBoundary(ProjectTimebase timebase, TimelinePosition position) => timebase.FromFrame(timebase.ToFrame(position)) == position;
    private static bool IsSourceFrameBoundary(ProjectTimebase timebase, SourcePosition position) =>
        IsFrameBoundary(timebase, SourcePositionToTimeline(timebase, position));
    private static Timecode SourceTimecode(ProjectTimebase timebase, TimelinePosition position) =>
        Timecode.FromFrameNumber(timebase.ToFrame(position), timebase.FrameRate, timebase.DropFrame);
    private static TimelinePosition SourceTimecodeToPosition(string value, ProjectTimebase timebase) =>
        timebase.FromFrame(Timecode.Parse(value, timebase.FrameRate, timebase.DropFrame).FrameNumber);
    private static TimelinePosition SourcePositionToTimeline(ProjectTimebase timebase, SourcePosition position)
    {
        string[] fraction = position.Remainder == "0" ? ["0", "1"] : position.Remainder.Split('/');
        decimal samples = position.Samples + decimal.Parse(fraction[0], CultureInfo.InvariantCulture) /
            decimal.Parse(fraction[1], CultureInfo.InvariantCulture);
        return new(checked((long)Math.Round(samples * timebase.SampleRate / position.SampleRate, MidpointRounding.AwayFromZero)));
    }
}
