using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

/// <summary>
/// Lossless editable projection of one entry in <c>timeline.camera.keyframes</c>.
/// Known camera values are written back to their existing aliases while unknown
/// metadata remains in the source object.
/// </summary>
public sealed class TimelineCameraKeyframeDocument
{
    private static readonly string[] TimeAliases = ["t", "time_s", "time"];
    private static readonly string[] TranslationXAliases = ["translation_x", "pan_x"];
    private static readonly string[] TranslationYAliases = ["translation_y", "pan_y"];
    private static readonly string[] TranslationZAliases = ["translation_z", "pan_z"];
    private static readonly string[] RotationXAliases = ["rotation_x"];
    private static readonly string[] RotationYAliases = ["rotation_y"];
    private static readonly string[] RotationZAliases = ["rotation_z", "rotation_deg", "angle"];
    private static readonly string[] ZoomAliases = ["zoom"];
    private static readonly string[] FovAliases = ["fov", "field_of_view"];

    private readonly JsonObject _source;
    private readonly bool _persistStableId;
    private double? _translationX;
    private double? _translationY;
    private double? _translationZ;
    private double? _rotationX;
    private double? _rotationY;
    private double? _rotationZ;
    private double? _zoom;
    private double? _fov;
    private bool _translationXTouched;
    private bool _translationYTouched;
    private bool _translationZTouched;
    private bool _rotationXTouched;
    private bool _rotationYTouched;
    private bool _rotationZTouched;
    private bool _zoomTouched;
    private bool _fovTouched;

    internal TimelineCameraKeyframeDocument(
        string stableId,
        bool persistStableId,
        double timeSeconds,
        JsonObject source)
    {
        StableId = stableId;
        _persistStableId = persistStableId;
        TimeSeconds = timeSeconds;
        _source = source.DeepClone().AsObject();
        _translationX = ReadVectorValue(_source, TranslationXAliases, "translation", "position", "x");
        _translationY = ReadVectorValue(_source, TranslationYAliases, "translation", "position", "y");
        _translationZ = ReadVectorValue(_source, TranslationZAliases, "translation", "position", "z");
        _rotationX = ReadVectorValue(_source, RotationXAliases, "rotation", null, "x");
        _rotationY = ReadVectorValue(_source, RotationYAliases, "rotation", null, "y");
        _rotationZ = ReadVectorValue(_source, RotationZAliases, "rotation", null, "z");
        _zoom = ReadNumber(_source, ZoomAliases);
        _fov = ReadNumber(_source, FovAliases);
    }

    public string StableId { get; }

    public double TimeSeconds { get; set; }

    public double? TranslationX
    {
        get => _translationX;
        set => SetOptional(value, out _translationX, out _translationXTouched);
    }

    public double? TranslationY
    {
        get => _translationY;
        set => SetOptional(value, out _translationY, out _translationYTouched);
    }

    public double? TranslationZ
    {
        get => _translationZ;
        set => SetOptional(value, out _translationZ, out _translationZTouched);
    }

    public double? RotationX
    {
        get => _rotationX;
        set => SetOptional(value, out _rotationX, out _rotationXTouched);
    }

    public double? RotationY
    {
        get => _rotationY;
        set => SetOptional(value, out _rotationY, out _rotationYTouched);
    }

    public double? RotationZ
    {
        get => _rotationZ;
        set => SetOptional(value, out _rotationZ, out _rotationZTouched);
    }

    public double? Zoom
    {
        get => _zoom;
        set => SetOptional(value, out _zoom, out _zoomTouched);
    }

    public double? Fov
    {
        get => _fov;
        set => SetOptional(value, out _fov, out _fovTouched);
    }

    public void MoveTo(double timeSeconds, double? durationSeconds = null) =>
        TimeSeconds = TimelineCameraProjection.NormalizeTime(timeSeconds, durationSeconds);

    public void Quantize(double gridSeconds, double? durationSeconds = null)
    {
        if (!double.IsFinite(gridSeconds) || gridSeconds <= 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(gridSeconds),
                gridSeconds,
                "Grid seconds must be finite and greater than zero.");
        }

        MoveTo(Math.Round(TimeSeconds / gridSeconds, MidpointRounding.AwayFromZero) * gridSeconds, durationSeconds);
    }

    internal JsonObject ToJsonObject(double? durationSeconds)
    {
        var result = _source.DeepClone().AsObject();
        WriteNumber(result, TimeAliases, "t", TimelineCameraProjection.NormalizeTime(TimeSeconds, durationSeconds));
        if (_persistStableId)
        {
            result["id"] = StableId;
        }

        WriteVectorValue(
            result,
            TranslationXAliases,
            "translation_x",
            "translation",
            "position",
            "x",
            _translationX,
            _translationXTouched);
        WriteVectorValue(
            result,
            TranslationYAliases,
            "translation_y",
            "translation",
            "position",
            "y",
            _translationY,
            _translationYTouched);
        WriteVectorValue(
            result,
            TranslationZAliases,
            "translation_z",
            "translation",
            "position",
            "z",
            _translationZ,
            _translationZTouched);
        WriteVectorValue(
            result,
            RotationXAliases,
            "rotation_x",
            "rotation",
            null,
            "x",
            _rotationX,
            _rotationXTouched);
        WriteVectorValue(
            result,
            RotationYAliases,
            "rotation_y",
            "rotation",
            null,
            "y",
            _rotationY,
            _rotationYTouched);
        WriteVectorValue(
            result,
            RotationZAliases,
            "rotation_z",
            "rotation",
            null,
            "z",
            _rotationZ,
            _rotationZTouched);
        WriteOptionalNumber(result, ZoomAliases, "zoom", _zoom, _zoomTouched);
        WriteOptionalNumber(result, FovAliases, "fov", _fov, _fovTouched);
        return result;
    }

    internal TimelineCameraKeyframeDocument Duplicate(double? durationSeconds)
    {
        var source = ToJsonObject(durationSeconds);
        var stableId = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
        source["id"] = stableId;
        return new TimelineCameraKeyframeDocument(
            stableId,
            persistStableId: false,
            TimelineCameraProjection.NormalizeTime(TimeSeconds, durationSeconds),
            source);
    }

    private static void SetOptional(double? value, out double? target, out bool touched)
    {
        target = value is { } number && double.IsFinite(number) ? number : null;
        touched = true;
    }

    private static double? ReadVectorValue(
        JsonObject source,
        IReadOnlyList<string> directAliases,
        string primaryContainer,
        string? secondaryContainer,
        string component)
    {
        var direct = ReadNumber(source, directAliases);
        if (direct.HasValue)
        {
            return direct;
        }

        if (ReadNestedNumber(source, primaryContainer, component) is { } primary)
        {
            return primary;
        }

        return secondaryContainer is null
            ? null
            : ReadNestedNumber(source, secondaryContainer, component);
    }

    private static double? ReadNumber(JsonObject source, IReadOnlyList<string> aliases)
    {
        foreach (var alias in aliases)
        {
            if (TryReadFiniteNumber(source[alias], out var value))
            {
                return value;
            }
        }

        return null;
    }

    private static double? ReadNestedNumber(JsonObject source, string container, string component) =>
        source[container] is JsonObject nested && TryReadFiniteNumber(nested[component], out var value)
            ? value
            : null;

    internal static bool TryReadFiniteNumber(JsonNode? node, out double value)
    {
        value = 0;
        if (node is not JsonValue jsonValue)
        {
            return false;
        }

        if (jsonValue.TryGetValue<double>(out value))
        {
            return double.IsFinite(value);
        }

        if (jsonValue.TryGetValue<int>(out var intValue))
        {
            value = intValue;
            return true;
        }

        if (jsonValue.TryGetValue<long>(out var longValue))
        {
            value = longValue;
            return true;
        }

        if (jsonValue.TryGetValue<decimal>(out var decimalValue))
        {
            value = decimal.ToDouble(decimalValue);
            return double.IsFinite(value);
        }

        if (jsonValue.TryGetValue<string>(out var text) &&
            double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out value))
        {
            return double.IsFinite(value);
        }

        return false;
    }

    private static void WriteVectorValue(
        JsonObject result,
        IReadOnlyList<string> directAliases,
        string fallbackAlias,
        string primaryContainer,
        string? secondaryContainer,
        string component,
        double? value,
        bool touched)
    {
        if (!touched)
        {
            return;
        }

        if (!value.HasValue)
        {
            RemoveVectorValue(result, directAliases, primaryContainer, secondaryContainer, component);
            return;
        }

        foreach (var alias in directAliases)
        {
            if (result.ContainsKey(alias))
            {
                result[alias] = value.Value;
                return;
            }
        }

        if (TryWriteNested(result, primaryContainer, component, value.Value) ||
            secondaryContainer is not null && TryWriteNested(result, secondaryContainer, component, value.Value))
        {
            return;
        }

        result[fallbackAlias] = value.Value;
    }

    private static bool TryWriteNested(JsonObject result, string container, string component, double value)
    {
        if (result[container] is not JsonObject nested || !nested.ContainsKey(component))
        {
            return false;
        }

        nested[component] = value;
        return true;
    }

    private static void RemoveVectorValue(
        JsonObject result,
        IReadOnlyList<string> directAliases,
        string primaryContainer,
        string? secondaryContainer,
        string component)
    {
        foreach (var alias in directAliases)
        {
            result.Remove(alias);
        }

        if (result[primaryContainer] is JsonObject primary)
        {
            primary.Remove(component);
        }

        if (secondaryContainer is not null && result[secondaryContainer] is JsonObject secondary)
        {
            secondary.Remove(component);
        }
    }

    private static void WriteOptionalNumber(
        JsonObject result,
        IReadOnlyList<string> aliases,
        string fallbackAlias,
        double? value,
        bool touched)
    {
        if (!touched)
        {
            return;
        }

        if (!value.HasValue)
        {
            foreach (var alias in aliases)
            {
                result.Remove(alias);
            }

            return;
        }

        WriteNumber(result, aliases, fallbackAlias, value.Value);
    }

    private static void WriteNumber(
        JsonObject result,
        IReadOnlyList<string> aliases,
        string fallbackAlias,
        double value)
    {
        foreach (var alias in aliases)
        {
            if (result.ContainsKey(alias))
            {
                result[alias] = value;
                return;
            }
        }

        result[fallbackAlias] = value;
    }
}

/// <summary>
/// Projects and rebuilds camera automation without replacing any unrelated
/// timeline, camera, or keyframe metadata.
/// </summary>
public static class TimelineCameraProjection
{
    public static IReadOnlyList<TimelineCameraKeyframeDocument> Project(JsonObject timeline)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        if (timeline["camera"] is not JsonObject camera ||
            camera["keyframes"] is not JsonArray keyframes)
        {
            return [];
        }

        var durationSeconds = GetDurationSeconds(timeline);
        var identities = new Dictionary<string, int>(StringComparer.Ordinal);
        var projected = new List<TimelineCameraKeyframeDocument>();
        for (var index = 0; index < keyframes.Count; index++)
        {
            if (keyframes[index] is not JsonObject keyframe)
            {
                continue;
            }

            string? persistedId = null;
            bool hasPersistedId = keyframe["id"] is JsonValue idValue &&
                idValue.TryGetValue<string>(out persistedId) &&
                !string.IsNullOrWhiteSpace(persistedId);
            var baseIdentity = hasPersistedId
                ? persistedId!
                : CreateDeterministicIdentity(keyframe, index);
            identities.TryGetValue(baseIdentity, out var occurrence);
            identities[baseIdentity] = ++occurrence;
            var stableIdentity = occurrence == 1
                ? baseIdentity
                : string.Create(
                    CultureInfo.InvariantCulture,
                    $"{baseIdentity}~{occurrence}");
            var time = ReadTime(keyframe);
            projected.Add(
                new TimelineCameraKeyframeDocument(
                    stableIdentity,
                    persistStableId: !hasPersistedId || occurrence > 1,
                    NormalizeTime(time, durationSeconds),
                    keyframe));
        }

        return OrderKeyframes(projected);
    }

    public static TimelineCameraKeyframeDocument CreateAt(
        double timeSeconds,
        double? durationSeconds = null)
    {
        var stableId = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture);
        var normalizedTime = NormalizeTime(timeSeconds, durationSeconds);
        return new TimelineCameraKeyframeDocument(
            stableId,
            persistStableId: false,
            normalizedTime,
            new JsonObject
            {
                ["id"] = stableId,
                ["t"] = normalizedTime,
                ["translation_x"] = 0,
                ["translation_y"] = 0,
                ["translation_z"] = 0,
                ["rotation_x"] = 0,
                ["rotation_y"] = 0,
                ["rotation_z"] = 0,
                ["zoom"] = 1,
                ["fov"] = 60
            });
    }

    public static TimelineCameraKeyframeDocument Duplicate(
        TimelineCameraKeyframeDocument keyframe,
        double? durationSeconds = null)
    {
        ArgumentNullException.ThrowIfNull(keyframe);
        return keyframe.Duplicate(durationSeconds);
    }

    public static JsonObject Rebuild(
        JsonObject timeline,
        IEnumerable<TimelineCameraKeyframeDocument> keyframes)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        ArgumentNullException.ThrowIfNull(keyframes);
        var materializedKeyframes = keyframes.ToList();
        if (materializedKeyframes.Any(keyframe => keyframe is null))
        {
            throw new ArgumentException("Camera keyframe collection cannot contain null values.", nameof(keyframes));
        }

        var rebuilt = timeline.DeepClone().AsObject();
        var camera = rebuilt["camera"] as JsonObject;
        bool hadKeyframes = camera?["keyframes"] is JsonArray;
        if (camera is null)
        {
            if (materializedKeyframes.Count == 0)
            {
                return rebuilt;
            }

            camera = [];
            rebuilt["camera"] = camera;
        }

        if (!hadKeyframes && materializedKeyframes.Count == 0)
        {
            return rebuilt;
        }

        var opaqueEntries = camera["keyframes"] is JsonArray existing
            ? existing.Where(node => node is not JsonObject).Select(node => node?.DeepClone()).ToList()
            : [];
        var rebuiltKeyframes = new JsonArray();
        var durationSeconds = GetDurationSeconds(rebuilt);
        foreach (var keyframe in OrderKeyframes(materializedKeyframes))
        {
            rebuiltKeyframes.Add((JsonNode)keyframe.ToJsonObject(durationSeconds));
        }

        foreach (var opaqueEntry in opaqueEntries)
        {
            rebuiltKeyframes.Add(opaqueEntry);
        }

        camera["keyframes"] = rebuiltKeyframes;
        return rebuilt;
    }

    public static IReadOnlyList<TimelineCameraKeyframeDocument> OrderKeyframes(
        IEnumerable<TimelineCameraKeyframeDocument> keyframes)
    {
        ArgumentNullException.ThrowIfNull(keyframes);
        return keyframes
            .OrderBy(keyframe => keyframe.TimeSeconds)
            .ThenBy(keyframe => keyframe.StableId, StringComparer.Ordinal)
            .ToList();
    }

    public static double NormalizeTime(double timeSeconds, double? durationSeconds = null)
    {
        var normalized = double.IsFinite(timeSeconds) ? Math.Max(0, timeSeconds) : 0;
        if (durationSeconds is { } duration)
        {
            duration = double.IsFinite(duration) ? Math.Max(0, duration) : 0;
            normalized = Math.Min(normalized, duration);
        }

        return normalized;
    }

    public static double? GetDurationSeconds(JsonObject timeline)
    {
        ArgumentNullException.ThrowIfNull(timeline);
        if (!TimelineCameraKeyframeDocument.TryReadFiniteNumber(timeline["duration_s"], out var duration) &&
            !TimelineCameraKeyframeDocument.TryReadFiniteNumber(timeline["duration"], out duration))
        {
            return null;
        }

        return Math.Max(0, duration);
    }

    private static double ReadTime(JsonObject keyframe)
    {
        foreach (var alias in new[] { "t", "time_s", "time" })
        {
            if (TimelineCameraKeyframeDocument.TryReadFiniteNumber(keyframe[alias], out var time))
            {
                return time;
            }
        }

        return 0;
    }

    private static string CreateDeterministicIdentity(JsonObject keyframe, int sourceIndex)
    {
        var identitySource = string.Create(
            CultureInfo.InvariantCulture,
            $"{sourceIndex}:{keyframe.ToJsonString()}");
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(identitySource));
        return $"camera_{Convert.ToHexString(hash.AsSpan(0, 8)).ToLowerInvariant()}";
    }
}
