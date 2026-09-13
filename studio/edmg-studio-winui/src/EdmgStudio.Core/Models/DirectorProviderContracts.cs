using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public sealed record StoryBible(
    int Revision,
    string ProjectTheme,
    string NarrativeSummary,
    string VisualStyle,
    IReadOnlyDictionary<string, string> Characters,
    IReadOnlyDictionary<string, string> Locations,
    IReadOnlyList<string> ContinuityRules,
    IReadOnlyList<string> ForbiddenChanges,
    JsonObject Metadata);

public sealed record DirectorSubject(
    string Id,
    string Role,
    bool AppearanceLock,
    IReadOnlyList<string> AppearanceNotes,
    string Expression,
    JsonObject Metadata);

public sealed record SceneSpec(
    string Id,
    TimelinePosition Start,
    TimelinePosition End,
    string Intent,
    string ContinuityMode,
    IReadOnlyList<DirectorSubject> Subjects,
    IReadOnlyList<string> Actions,
    JsonObject Camera,
    JsonObject Environment,
    JsonObject Lighting,
    JsonObject RendererHints,
    JsonObject Metadata);

public sealed record SharedDirectorDocument(
    int OperationalVersion,
    StoryBible StoryBible,
    IReadOnlyList<SceneSpec> Scenes,
    long? AnalysisRevision,
    JsonObject Metadata);

public sealed record ProviderCapability(
    string SchemaVersion,
    string Id,
    string ProviderId,
    string Media,
    string Operation,
    IReadOnlyList<string> Controls,
    double? MaxDurationSeconds,
    IReadOnlyList<string> Resolutions,
    bool Deterministic,
    bool SupportsCancel,
    string Locality,
    JsonObject Metadata);

public sealed record RendererReadiness(
    string State, bool Installed, bool AdapterReady, bool? HardwareCompatible, int ValidationLevel,
    string? ValidationReceiptId, DateTimeOffset? ValidatedAt, IReadOnlyList<string> Blockers);

public sealed record RendererDescriptor(
    string SchemaVersion, string Id, string ProviderId, string Engine, string? ModelId, string? Family,
    string Media, IReadOnlyList<string> Operations, IReadOnlyList<string> Controls,
    IReadOnlyList<string> RenderModes, IReadOnlyList<string> HardwareBackends, double? MinimumVramGb,
    RendererReadiness Readiness, JsonObject Metadata);

public sealed record HardwareProfile(
    string SchemaVersion,
    string Id,
    string Backend,
    string Device,
    string DeviceName,
    IReadOnlyList<string> AvailableBackends,
    double VramGb,
    double RamGb,
    int CpuThreads,
    int? PhysicalCoreCount,
    int? LogicalCoreCount,
    string Platform,
    string Machine,
    bool IntegratedAcceleration,
    string? GpuVendor,
    bool SupportsDirectMl,
    bool DirectMlRuntimeReady,
    string? DirectMlDeviceName,
    IReadOnlyList<HardwareGpu> Gpus,
    IReadOnlyList<HardwareDisk> Disks,
    IReadOnlyList<HardwareAudioDevice> AudioDevices,
    string RecommendedTier,
    string? RecommendedDirector,
    string? RecommendedRenderer,
    IReadOnlyList<string> Warnings,
    JsonObject Metadata);

public sealed record HardwareGpu(
    string Id, string? Vendor, string Name, string? Architecture, double DedicatedVramGb,
    string? Driver, bool CudaAvailable, bool RocmAvailable, bool DirectMlAvailable, JsonObject Metadata);

public sealed record HardwareDisk(string Id, string Path, double FreeGb, double? TotalGb);

public sealed record HardwareAudioDevice(
    string Id, string Name, string Backend, int InputChannels, int OutputChannels, bool IsDefault, JsonObject Metadata);

public static class DirectorProviderContracts
{
    public const string SchemaVersion = "1.0";

    public static SharedDirectorDocument ParseDirectorDocument(JsonElement document) =>
        ParseDirectorDocument(JsonNode.Parse(document.GetRawText())?.AsObject() ?? throw new InvalidDataException("Director document must be an object."));

    public static SharedDirectorDocument ParseDirectorDocument(JsonObject document)
    {
        int version = ReadInt32(document["version"], 1);
        if (version != 1) throw new InvalidDataException($"Unsupported Director document version '{version}'.");
        JsonObject bible = document["story_bible"] as JsonObject ?? [];
        var storyBible = new StoryBible(
            ReadInt32(bible["revision"], 1), ReadString(bible["project_theme"]) ?? string.Empty,
            ReadString(bible["narrative_summary"]) ?? string.Empty, ReadString(bible["visual_style"]) ?? string.Empty,
            ReadStringMap(bible["characters"]), ReadStringMap(bible["locations"]),
            ReadStrings(bible["continuity_rules"]), ReadStrings(bible["forbidden_changes"]), bible.DeepClone().AsObject());
        var scenes = new List<SceneSpec>();
        var sceneIds = new HashSet<string>(StringComparer.Ordinal);
        if (document["scenes"] is JsonArray sourceScenes)
        {
            foreach (JsonNode? sceneNode in sourceScenes)
            {
                JsonObject scene = sceneNode as JsonObject ?? throw new InvalidDataException("Director scenes must be objects.");
                string id = ReadString(scene["scene_id"]) ?? throw new InvalidDataException("Director scene ID is required.");
                if (!sceneIds.Add(id)) throw new InvalidDataException($"Director scene ID '{id}' must be unique.");
                var start = new TimelinePosition(ReadExactSample(scene["start_sample"], "start_sample"));
                var end = new TimelinePosition(ReadExactSample(scene["end_sample"], "end_sample"));
                if (start.Samples < 0 || end.Samples <= start.Samples) throw new InvalidDataException($"Director scene '{id}' has an invalid sample range.");
                var subjects = new List<DirectorSubject>();
                var subjectIds = new HashSet<string>(StringComparer.Ordinal);
                if (scene["subjects"] is JsonArray sourceSubjects)
                {
                    foreach (JsonNode? subjectNode in sourceSubjects)
                    {
                        JsonObject subject = subjectNode as JsonObject ?? throw new InvalidDataException("Director subjects must be objects.");
                        string subjectId = ReadString(subject["id"]) ?? throw new InvalidDataException("Director subject ID is required.");
                        if (!subjectIds.Add(subjectId)) throw new InvalidDataException($"Director subject ID '{subjectId}' must be unique within scene '{id}'.");
                        subjects.Add(new DirectorSubject(subjectId, ReadString(subject["role"]) ?? "primary",
                            ReadBoolean(subject["appearance_lock"], true), ReadStrings(subject["appearance_notes"]),
                            ReadString(subject["expression"]) ?? string.Empty, subject.DeepClone().AsObject()));
                    }
                }
                scenes.Add(new SceneSpec(id, start, end,
                    ReadString(scene["intent"]) ?? throw new InvalidDataException($"Director scene '{id}' requires intent."),
                    ReadChoice(scene["continuity_mode"], "continuous", "continuous", "cut", "independent"), subjects,
                    ReadStrings(scene["actions"]), CloneObject(scene["camera"]), CloneObject(scene["environment"]),
                    CloneObject(scene["lighting"]), CloneObject(scene["renderer_hints"]), scene.DeepClone().AsObject()));
            }
        }
        return new SharedDirectorDocument(version, storyBible, scenes, ReadNullableInt64(document["analysis_revision"]), document.DeepClone().AsObject());
    }

    public static JsonObject RebuildDirectorDocument(SharedDirectorDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        JsonObject result = document.Metadata.DeepClone().AsObject();
        result["version"] = document.OperationalVersion;
        JsonObject bible = document.StoryBible.Metadata.DeepClone().AsObject();
        bible["revision"] = document.StoryBible.Revision;
        bible["project_theme"] = document.StoryBible.ProjectTheme;
        bible["narrative_summary"] = document.StoryBible.NarrativeSummary;
        bible["visual_style"] = document.StoryBible.VisualStyle;
        bible["characters"] = BuildStringMap(document.StoryBible.Characters);
        bible["locations"] = BuildStringMap(document.StoryBible.Locations);
        bible["continuity_rules"] = BuildStringArray(document.StoryBible.ContinuityRules);
        bible["forbidden_changes"] = BuildStringArray(document.StoryBible.ForbiddenChanges);
        result["story_bible"] = bible;
        var scenes = new JsonArray();
        foreach (SceneSpec scene in document.Scenes)
        {
            JsonObject item = scene.Metadata.DeepClone().AsObject();
            item["scene_id"] = scene.Id;
            item["start_sample"] = scene.Start.Samples.ToString(CultureInfo.InvariantCulture);
            item["end_sample"] = scene.End.Samples.ToString(CultureInfo.InvariantCulture);
            item["intent"] = scene.Intent;
            item["continuity_mode"] = scene.ContinuityMode;
            item["actions"] = BuildStringArray(scene.Actions);
            item["camera"] = scene.Camera.DeepClone();
            item["environment"] = scene.Environment.DeepClone();
            item["lighting"] = scene.Lighting.DeepClone();
            item["renderer_hints"] = scene.RendererHints.DeepClone();
            var subjects = new JsonArray();
            foreach (DirectorSubject subject in scene.Subjects)
            {
                JsonObject value = subject.Metadata.DeepClone().AsObject();
                value["id"] = subject.Id;
                value["role"] = subject.Role;
                value["appearance_lock"] = subject.AppearanceLock;
                value["appearance_notes"] = BuildStringArray(subject.AppearanceNotes);
                value["expression"] = subject.Expression;
                subjects.Add(value);
            }
            item["subjects"] = subjects;
            scenes.Add(item);
        }
        result["scenes"] = scenes;
        if (document.AnalysisRevision is long revision) result["analysis_revision"] = revision;
        else result.Remove("analysis_revision");
        return result;
    }

    public static ProviderCapability ParseCapability(JsonElement capability) =>
        ParseCapability(JsonNode.Parse(capability.GetRawText())?.AsObject() ?? throw new InvalidDataException("Capability must be an object."));

    public static ProviderCapability ParseCapability(JsonObject capability)
    {
        string schemaVersion = ReadString(capability["schema_version"]) ?? SchemaVersion;
        if (schemaVersion != SchemaVersion) throw new InvalidDataException($"Unsupported capability schema version '{schemaVersion}'.");
        double? duration = ReadNullableDouble(capability["max_duration_seconds"]);
        if (duration is <= 0) throw new InvalidDataException("Capability maximum duration must be positive.");
        return new ProviderCapability(schemaVersion,
            RequiredString(capability, "id"), RequiredString(capability, "provider_id"),
            ReadChoice(capability["media"], null, "image", "video", "audio", "mask", "depth", "scene"),
            ReadChoice(capability["operation"], null, "generate", "transform", "extend", "upscale", "interpolate", "assemble"),
            ReadStrings(capability["controls"]), duration, ReadStrings(capability["resolutions"]),
            ReadBoolean(capability["deterministic"]), ReadBoolean(capability["supports_cancel"]),
            ReadChoice(capability["locality"], null, "in_process", "local_service", "remote"), capability.DeepClone().AsObject());
    }

    public static RendererDescriptor ParseRenderer(JsonElement renderer) =>
        ParseRenderer(JsonNode.Parse(renderer.GetRawText())?.AsObject() ?? throw new InvalidDataException("Renderer must be an object."));

    public static RendererDescriptor ParseRenderer(JsonObject renderer)
    {
        string schemaVersion = ReadString(renderer["schema_version"]) ?? SchemaVersion;
        if (schemaVersion != SchemaVersion) throw new InvalidDataException($"Unsupported renderer schema version '{schemaVersion}'.");
        JsonObject readiness = renderer["readiness"] as JsonObject ?? throw new InvalidDataException("Renderer readiness is required.");
        string state = ReadChoice(readiness["state"], null, "unavailable", "installable", "installed", "adapter_ready", "validated");
        bool installed = ReadBoolean(readiness["installed"]);
        bool adapterReady = ReadBoolean(readiness["adapter_ready"]);
        int validationLevel = ReadInt32(readiness["validation_level"], 0);
        string? receiptId = ReadString(readiness["validation_receipt_id"]);
        DateTimeOffset? validatedAt = ReadNullableDateTimeOffset(readiness["validated_at"]);
        bool installedState = state is "installed" or "adapter_ready" or "validated";
        bool adapterState = state is "adapter_ready" or "validated";
        if (installedState && !installed) throw new InvalidDataException("Installed renderer states require an installed package.");
        if (adapterState && !adapterReady) throw new InvalidDataException("Adapter-ready renderer states require a ready adapter.");
        if (state == "validated" && (validationLevel < 3 || receiptId is null || validatedAt is null))
            throw new InvalidDataException("Validated renderer state requires level-3 inference evidence.");
        double? minimumVram = ReadNullableDouble(renderer["minimum_vram_gb"]);
        if (minimumVram < 0) throw new InvalidDataException("Renderer minimum VRAM cannot be negative.");
        return new RendererDescriptor(schemaVersion, RequiredString(renderer, "id"), RequiredString(renderer, "provider_id"),
            RequiredString(renderer, "engine"), ReadString(renderer["model_id"]), ReadString(renderer["family"]),
            ReadChoice(renderer["media"], null, "image", "video", "audio"),
            ReadChoices(renderer["operations"], "generate", "transform", "extend", "upscale", "interpolate", "assemble"),
            ReadChoices(renderer["controls"], "text", "image", "first_frame", "last_frame", "audio", "pose", "depth", "mask"),
            ReadStrings(renderer["render_modes"]), ReadChoices(renderer["hardware_backends"], "cpu", "cuda", "directml", "mps", "remote"),
            minimumVram, new RendererReadiness(state, installed, adapterReady, ReadNullableBoolean(readiness["hardware_compatible"]),
                validationLevel, receiptId, validatedAt, ReadStrings(readiness["blockers"])), renderer.DeepClone().AsObject());
    }

    public static HardwareProfile ParseHardwareProfile(JsonElement profile) =>
        ParseHardwareProfile(JsonNode.Parse(profile.GetRawText())?.AsObject() ?? throw new InvalidDataException("Hardware profile must be an object."));

    public static HardwareProfile ParseHardwareProfile(JsonObject profile)
    {
        string schemaVersion = ReadString(profile["schema_version"]) ?? SchemaVersion;
        if (schemaVersion != SchemaVersion) throw new InvalidDataException($"Unsupported hardware profile schema version '{schemaVersion}'.");
        string backend = ReadChoice(profile["backend"], null, "cpu", "cuda", "directml", "mps");
        string[] availableBackends = ReadStrings(profile["available_backends"]);
        if (!availableBackends.Contains(backend, StringComparer.Ordinal)) throw new InvalidDataException("Selected hardware backend must be available.");
        if (!availableBackends.Contains("cpu", StringComparer.Ordinal)) throw new InvalidDataException("CPU must remain an available hardware backend.");
        double vramGb = ReadNullableDouble(profile["vram_gb"]) ?? 0;
        double ramGb = ReadNullableDouble(profile["ram_gb"]) ?? 0;
        int cpuThreads = ReadInt32(profile["cpu_threads"], 0);
        int? physicalCoreCount = ReadNullableInt32(profile["physical_core_count"]);
        int? logicalCoreCount = ReadNullableInt32(profile["logical_core_count"]);
        if (vramGb < 0 || ramGb < 0) throw new InvalidDataException("Hardware memory values cannot be negative.");
        if (cpuThreads < 1) throw new InvalidDataException("Hardware CPU thread count must be positive.");
        if (physicalCoreCount is < 1 || logicalCoreCount is < 1) throw new InvalidDataException("Hardware core counts must be positive.");
        if (physicalCoreCount > (logicalCoreCount ?? cpuThreads)) throw new InvalidDataException("Physical core count cannot exceed logical core count.");
        HardwareGpu[] gpus = ReadObjects(profile["gpus"], "GPU").Select(value => new HardwareGpu(
            RequiredString(value, "id"), ReadString(value["vendor"]), RequiredString(value, "name"),
            ReadString(value["architecture"]), ReadNonNegativeDouble(value["dedicated_vram_gb"], "GPU VRAM"),
            ReadString(value["driver"]), ReadBoolean(value["cuda_available"]), ReadBoolean(value["rocm_available"]),
            ReadBoolean(value["directml_available"]), value.DeepClone().AsObject())).ToArray();
        HardwareDisk[] disks = ReadObjects(profile["disks"], "disk").Select(value =>
        {
            double free = ReadNonNegativeDouble(value["free_gb"], "disk free capacity");
            double? total = ReadNullableDouble(value["total_gb"]);
            if (total < 0 || total is not null && free > total) throw new InvalidDataException("Disk capacity is invalid.");
            return new HardwareDisk(RequiredString(value, "id"), RequiredString(value, "path"), free, total);
        }).ToArray();
        HardwareAudioDevice[] audioDevices = ReadObjects(profile["audio_devices"], "audio device").Select(value => new HardwareAudioDevice(
            RequiredString(value, "id"), RequiredString(value, "name"), RequiredString(value, "backend"),
            ReadNonNegativeInt32(value["input_channels"], "input channels"), ReadNonNegativeInt32(value["output_channels"], "output channels"),
            ReadBoolean(value["is_default"]), value.DeepClone().AsObject())).ToArray();
        EnsureUniqueIds(gpus.Select(value => value.Id), "GPU");
        EnsureUniqueIds(disks.Select(value => value.Id), "disk");
        EnsureUniqueIds(audioDevices.Select(value => value.Id), "audio device");
        return new HardwareProfile(schemaVersion, RequiredString(profile, "id"), backend,
            RequiredString(profile, "device"), RequiredString(profile, "device_name"), availableBackends,
            vramGb, ramGb, cpuThreads, physicalCoreCount, logicalCoreCount,
            RequiredString(profile, "platform"), RequiredString(profile, "machine"),
            ReadBoolean(profile["integrated_acceleration"]), ReadString(profile["gpu_vendor"]),
            ReadBoolean(profile["supports_directml"]), ReadBoolean(profile["directml_runtime_ready"]),
            ReadString(profile["directml_device_name"]), gpus, disks, audioDevices,
            ReadChoice(profile["recommended_tier"], "draft", "draft", "balanced", "quality"),
            ReadString(profile["recommended_director"]), ReadString(profile["recommended_renderer"]),
            ReadStrings(profile["warnings"]), profile.DeepClone().AsObject());
    }

    private static long ReadExactSample(JsonNode? node, string name)
    {
        string? value = ReadString(node);
        if (value is null || !long.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out long samples) ||
            samples.ToString(CultureInfo.InvariantCulture) != value) throw new InvalidDataException($"'{name}' must be a canonical decimal int64 string.");
        return samples;
    }

    private static string RequiredString(JsonObject source, string name) =>
        ReadString(source[name]) is string value && !string.IsNullOrWhiteSpace(value) ? value : throw new InvalidDataException($"'{name}' is required.");
    private static string ReadChoice(JsonNode? node, string? fallback, params string[] choices)
    {
        string? value = ReadString(node) ?? fallback;
        return value is not null && choices.Contains(value, StringComparer.Ordinal) ? value : throw new InvalidDataException($"Unsupported contract value '{value}'.");
    }
    private static JsonObject CloneObject(JsonNode? node) => node switch
    {
        null => [],
        JsonObject value => value.DeepClone().AsObject(),
        _ => throw new InvalidDataException("Contract object field must be an object."),
    };
    private static string? ReadString(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out string? result) ? result : null;
    private static int ReadInt32(JsonNode? node, int fallback) => node is null ? fallback
        : node is JsonValue value && value.TryGetValue<int>(out int result) ? result
        : throw new InvalidDataException("Contract integer field must be an integer.");
    private static long? ReadNullableInt64(JsonNode? node) => node is null ? null
        : node is JsonValue value && value.TryGetValue<long>(out long result) ? result
        : throw new InvalidDataException("Contract integer field must be an integer.");
    private static int? ReadNullableInt32(JsonNode? node) => node is null ? null
        : node is JsonValue value && value.TryGetValue<int>(out int result) ? result
        : throw new InvalidDataException("Contract integer field must be an integer.");
    private static int ReadNonNegativeInt32(JsonNode? node, string name)
    {
        int result = ReadInt32(node, 0);
        return result >= 0 ? result : throw new InvalidDataException($"Hardware {name} cannot be negative.");
    }
    private static double ReadNonNegativeDouble(JsonNode? node, string name)
    {
        double result = ReadNullableDouble(node) ?? 0;
        return result >= 0 ? result : throw new InvalidDataException($"Hardware {name} cannot be negative.");
    }
    private static double? ReadNullableDouble(JsonNode? node) => node is null ? null
        : node is JsonValue value && value.TryGetValue<double>(out double result) ? result
        : throw new InvalidDataException("Contract numeric field must be numeric.");
    private static bool? ReadNullableBoolean(JsonNode? node) => node is null ? null
        : node is JsonValue value && value.TryGetValue<bool>(out bool result) ? result
        : throw new InvalidDataException("Contract Boolean field must be a Boolean.");
    private static DateTimeOffset? ReadNullableDateTimeOffset(JsonNode? node)
    {
        string? value = ReadString(node);
        return value is null ? null
            : DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out DateTimeOffset result)
                ? result : throw new InvalidDataException("Contract timestamp field must be ISO 8601.");
    }
    private static bool ReadBoolean(JsonNode? node, bool fallback = false) => node is null ? fallback
        : node is JsonValue value && value.TryGetValue<bool>(out bool result) ? result
        : throw new InvalidDataException("Contract Boolean field must be a Boolean.");
    private static string[] ReadStrings(JsonNode? node)
    {
        if (node is null) return [];
        if (node is not JsonArray values) throw new InvalidDataException("Contract string-list field must be an array.");
        return values.Select(value => ReadString(value) ?? throw new InvalidDataException("Contract string-list entries must be strings.")).ToArray();
    }
    private static string[] ReadChoices(JsonNode? node, params string[] choices)
    {
        string[] values = ReadStrings(node);
        if (values.Any(value => !choices.Contains(value, StringComparer.Ordinal)))
            throw new InvalidDataException("Contract list contains an unsupported value.");
        return values;
    }
    private static JsonObject[] ReadObjects(JsonNode? node, string name)
    {
        if (node is null) return [];
        if (node is not JsonArray values) throw new InvalidDataException($"Hardware {name} list must be an array.");
        return values.Select(value => value as JsonObject ?? throw new InvalidDataException($"Hardware {name} entries must be objects.")).ToArray();
    }
    private static void EnsureUniqueIds(IEnumerable<string> ids, string name)
    {
        if (ids.Distinct(StringComparer.Ordinal).Count() != ids.Count()) throw new InvalidDataException($"Hardware {name} IDs must be unique.");
    }
    private static IReadOnlyDictionary<string, string> ReadStringMap(JsonNode? node)
    {
        if (node is null) return new Dictionary<string, string>();
        if (node is not JsonObject values) throw new InvalidDataException("Contract string-map field must be an object.");
        return values.ToDictionary(item => item.Key,
            item => ReadString(item.Value) ?? throw new InvalidDataException("Contract string-map values must be strings."), StringComparer.Ordinal);
    }
    private static JsonArray BuildStringArray(IEnumerable<string> values) => new(values.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray());
    private static JsonObject BuildStringMap(IReadOnlyDictionary<string, string> values) => new(values.Select(item => KeyValuePair.Create<string, JsonNode?>(item.Key, JsonValue.Create(item.Value))));
}
