using System.Text.Json;

namespace EdmgStudio.Core.Models;

public sealed record ModelRenderConfiguration(
    string ModelId,
    string VideoModelId,
    string RenderMode,
    string Device,
    string TemporalMode,
    string VideoModelEngine,
    string KeyframeRenderer,
    string KeyframeModelId);

public sealed record ModelRenderCandidate(
    string ModelId,
    string Name,
    string Kind,
    string Family,
    string Engine,
    string Lane,
    string Source,
    string LicenseId,
    bool IsInstalled,
    bool IsInstallable,
    bool IsHardwareCompatible,
    IReadOnlyList<string> Blockers);

public sealed record ModelRenderGuidance(
    ModelRenderCandidate? Primary,
    ModelRenderCandidate? Video,
    ModelRenderCandidate? Keyframe,
    IReadOnlyList<ModelRenderCandidate> PrimaryAlternatives,
    IReadOnlyList<ModelRenderCandidate> VideoAlternatives,
    IReadOnlyList<string> Blockers,
    bool IsReady)
{
    public string? RecommendedPrimaryModelId => PrimaryAlternatives.FirstOrDefault()?.ModelId;

    public string? RecommendedVideoModelId => VideoAlternatives.FirstOrDefault()?.ModelId;
}

public static class ModelRenderGuidanceEvaluator
{
    public const string CanonicalTensorRtModelId = "local_sd15_tensorrt_bundle";

    public static ModelRenderGuidance Evaluate(
        ModelCatalogueResponse catalogue,
        ModelRenderConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(catalogue);
        ArgumentNullException.ThrowIfNull(configuration);

        IReadOnlyList<ModelRenderCandidate> primaryCandidates = (catalogue.Catalog ?? [])
            .Where(entry => IsPrimaryCandidate(entry, configuration))
            .Select(entry => CreateCandidate(catalogue, entry, configuration.Device))
            .OrderBy(CandidateRank)
            .ThenBy(candidate => candidate.Name, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        IReadOnlyList<ModelRenderCandidate> videoCandidates = (catalogue.Catalog ?? [])
            .Where(IsVideoCandidate)
            .Where(entry => EngineMatches(entry, configuration.VideoModelEngine))
            .Select(entry => CreateCandidate(catalogue, entry, configuration.Device))
            .OrderBy(CandidateRank)
            .ThenBy(candidate => candidate.Name, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        ModelRenderCandidate? primary = ResolveSelection(
            primaryCandidates,
            configuration.RenderMode.Equals("tensorrt", StringComparison.OrdinalIgnoreCase)
                ? CanonicalTensorRtModelId
                : configuration.ModelId);
        ModelRenderCandidate? video = configuration.TemporalMode.Equals("video_model", StringComparison.OrdinalIgnoreCase)
            ? ResolveSelection(videoCandidates, configuration.VideoModelId)
            : null;

        IReadOnlyList<ModelRenderCandidate> keyframeCandidates = (catalogue.Catalog ?? [])
            .Where(entry => IsTensorRtCandidate(entry))
            .Select(entry => CreateCandidate(catalogue, entry, configuration.Device))
            .OrderBy(CandidateRank)
            .ToArray();
        ModelRenderCandidate? keyframe =
            configuration.KeyframeRenderer.Equals("tensorrt_sd15", StringComparison.OrdinalIgnoreCase)
            || configuration.RenderMode.Equals("tensorrt", StringComparison.OrdinalIgnoreCase)
                ? ResolveSelection(
                    keyframeCandidates,
                    string.IsNullOrWhiteSpace(configuration.KeyframeModelId)
                        ? CanonicalTensorRtModelId
                        : configuration.KeyframeModelId)
                : null;

        var blockers = new List<string>();
        AddSelectionBlockers(blockers, "Primary model", primary, primaryCandidates);
        if (video is not null)
        {
            AddSelectionBlockers(blockers, "Video model", video, videoCandidates);
            if (video.Engine.Equals("animatediff", StringComparison.OrdinalIgnoreCase)
                && primary is not null
                && !primary.Family.Equals("sd15", StringComparison.OrdinalIgnoreCase))
            {
                blockers.Add("AnimateDiff requires an SD 1.5 primary model. Choose SVD for SDXL or SD 3.5 keyframes.");
            }
        }
        else if (configuration.TemporalMode.Equals("video_model", StringComparison.OrdinalIgnoreCase))
        {
            blockers.Add("No compatible video model is selected or available.");
        }

        if (keyframe is not null)
        {
            AddSelectionBlockers(blockers, "TensorRT keyframe model", keyframe, keyframeCandidates);
            if (!keyframe.ModelId.Equals(CanonicalTensorRtModelId, StringComparison.OrdinalIgnoreCase))
            {
                blockers.Add("Only the local SD 1.5 TensorRT bundle is executable for internal-video keyframes.");
            }
        }
        else if (configuration.RenderMode.Equals("tensorrt", StringComparison.OrdinalIgnoreCase)
                 || configuration.KeyframeRenderer.Equals("tensorrt_sd15", StringComparison.OrdinalIgnoreCase))
        {
            blockers.Add("The local SD 1.5 TensorRT bundle is required for TensorRT keyframes.");
        }

        return new ModelRenderGuidance(
            primary,
            video,
            keyframe,
            primaryCandidates,
            videoCandidates,
            blockers.Distinct(StringComparer.OrdinalIgnoreCase).ToArray(),
            blockers.Count == 0);
    }

    private static bool IsPrimaryCandidate(ModelCatalogueEntry entry, ModelRenderConfiguration configuration)
    {
        if (configuration.RenderMode.Equals("tensorrt", StringComparison.OrdinalIgnoreCase))
        {
            return IsTensorRtCandidate(entry);
        }

        return string.Equals(entry.Kind, "diffusers", StringComparison.OrdinalIgnoreCase)
               && MetadataString(entry, "render", "engine").Equals("internal", StringComparison.OrdinalIgnoreCase)
               && MetadataStrings(entry, "render", "render_modes")
                   .Contains("internal_video", StringComparer.OrdinalIgnoreCase);
    }

    private static bool IsVideoCandidate(ModelCatalogueEntry entry) =>
        (string.Equals(entry.Kind, "video_diffusers", StringComparison.OrdinalIgnoreCase)
         || string.Equals(entry.Kind, "motion_adapter", StringComparison.OrdinalIgnoreCase))
        && MetadataString(entry, "render", "engine")
            .Equals("internal_video_model", StringComparison.OrdinalIgnoreCase)
        && MetadataStrings(entry, "render", "render_modes")
            .Contains("internal_video_model", StringComparer.OrdinalIgnoreCase);

    private static bool IsTensorRtCandidate(ModelCatalogueEntry entry) =>
        string.Equals(entry.Kind, "runtime_bundle", StringComparison.OrdinalIgnoreCase)
        && MetadataStrings(entry, "render", "render_modes")
            .Contains("internal_video_keyframes", StringComparer.OrdinalIgnoreCase);

    private static bool EngineMatches(ModelCatalogueEntry entry, string engine)
    {
        if (string.IsNullOrWhiteSpace(engine) || engine.Equals("auto", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return MetadataString(entry, "render", "video_model_engine")
            .Equals(engine, StringComparison.OrdinalIgnoreCase);
    }

    private static ModelRenderCandidate? ResolveSelection(
        IReadOnlyList<ModelRenderCandidate> candidates,
        string? selectedModelId)
    {
        if (string.IsNullOrWhiteSpace(selectedModelId)
            || selectedModelId.Equals("auto", StringComparison.OrdinalIgnoreCase))
        {
            return candidates.FirstOrDefault();
        }

        return candidates.FirstOrDefault(candidate =>
            candidate.ModelId.Equals(selectedModelId, StringComparison.OrdinalIgnoreCase));
    }

    private static ModelRenderCandidate CreateCandidate(
        ModelCatalogueResponse catalogue,
        ModelCatalogueEntry entry,
        string device)
    {
        string family = MetadataString(entry, "family");
        string engine = MetadataString(entry, "render", "video_model_engine");
        if (string.IsNullOrWhiteSpace(engine))
        {
            engine = MetadataString(entry, "render", "engine");
        }

        string lane = MetadataString(entry, "lane");
        if (string.IsNullOrWhiteSpace(lane))
        {
            lane = InferLane(entry);
        }

        bool installed = entry.Installed || InstalledMapValue(catalogue, entry.Id);
        bool installable = MetadataBoolean(entry, "installable", true);
        IReadOnlyList<string> hardwareTargets = MetadataStrings(entry, "hardware_targets");
        bool hardwareCompatible = HardwareCompatible(hardwareTargets, device);
        var blockers = new List<string>();
        if (!installed)
        {
            blockers.Add(installable ? "Not installed." : "Not installed and not installable from the catalogue.");
        }

        if (!hardwareCompatible)
        {
            blockers.Add($"not compatible with the selected {device} device.");
        }

        if (!installed
            && !string.IsNullOrWhiteSpace(entry.LicenseId)
            && !AcceptedLicense(catalogue, entry.LicenseId))
        {
            blockers.Add($"License '{entry.LicenseId}' must be accepted before installation.");
        }

        return new ModelRenderCandidate(
            entry.Id,
            entry.Name ?? entry.Id,
            entry.Kind ?? string.Empty,
            family,
            engine,
            lane,
            entry.Source ?? string.Empty,
            entry.LicenseId ?? string.Empty,
            installed,
            installable,
            hardwareCompatible,
            blockers);
    }

    private static void AddSelectionBlockers(
        ICollection<string> blockers,
        string label,
        ModelRenderCandidate? selected,
        IReadOnlyList<ModelRenderCandidate> candidates)
    {
        if (selected is null)
        {
            if (candidates.Count == 0)
            {
                blockers.Add($"{label}: no compatible catalogue entry is available.");
            }
            else
            {
                blockers.Add($"{label}: the entered model ID is not compatible with this render path.");
            }

            return;
        }

        foreach (string blocker in selected.Blockers)
        {
            blockers.Add($"{label} '{selected.Name}': {blocker}");
        }
    }

    private static int CandidateRank(ModelRenderCandidate candidate)
    {
        int rank = candidate.IsInstalled ? 0 : 100;
        rank += candidate.IsHardwareCompatible ? 0 : 40;
        rank += candidate.Lane.ToLowerInvariant() switch
        {
            "stable" => 0,
            "recommended" => 2,
            "experimental" => 8,
            "research" => 16,
            "legacy" => 24,
            _ => 12,
        };
        return rank;
    }

    private static bool InstalledMapValue(ModelCatalogueResponse catalogue, string modelId)
    {
        if (catalogue.Installed is null
            || !catalogue.Installed.TryGetValue(modelId, out JsonElement value))
        {
            return false;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.String => bool.TryParse(value.GetString(), out bool parsed) && parsed,
            JsonValueKind.Object when value.TryGetProperty("installed", out JsonElement installed) =>
                installed.ValueKind == JsonValueKind.True,
            _ => false,
        };
    }

    private static bool AcceptedLicense(ModelCatalogueResponse catalogue, string licenseId)
    {
        if (catalogue.Accepted is null
            || !catalogue.Accepted.TryGetValue(licenseId, out JsonElement value))
        {
            return false;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.String => !string.IsNullOrWhiteSpace(value.GetString()),
            JsonValueKind.Object => true,
            _ => false,
        };
    }

    private static bool HardwareCompatible(IReadOnlyList<string> targets, string device)
    {
        if (targets.Count == 0
            || string.IsNullOrWhiteSpace(device)
            || device.Equals("auto", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        string[] accepted = device.ToLowerInvariant() switch
        {
            "cpu" => ["cpu"],
            "cuda" => ["nvidia", "discrete_gpu"],
            "mps" => ["apple_silicon"],
            "directml" => ["integrated_gpu", "discrete_gpu"],
            _ => [],
        };
        return targets.Any(target => accepted.Contains(target, StringComparer.OrdinalIgnoreCase));
    }

    private static string InferLane(ModelCatalogueEntry entry)
    {
        string recommended = MetadataString(entry, "recommended").ToLowerInvariant();
        IReadOnlyList<string> tags = MetadataStrings(entry, "tags");
        if (recommended == "legacy" || tags.Contains("legacy", StringComparer.OrdinalIgnoreCase))
        {
            return "legacy";
        }

        return recommended switch
        {
            "default" or "production" => "recommended",
            "stable" => "stable",
            "research" or "browser" => "research",
            "advanced" or "optional" or "experimental" => "experimental",
            _ => MetadataBoolean(entry, "installable", true) ? "experimental" : "research",
        };
    }

    private static bool MetadataBoolean(ModelCatalogueEntry entry, string property, bool fallback)
    {
        if (entry.ExtensionData is null
            || !entry.ExtensionData.TryGetValue(property, out JsonElement value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.String when bool.TryParse(value.GetString(), out bool parsed) => parsed,
            _ => fallback,
        };
    }

    private static string MetadataString(ModelCatalogueEntry entry, params string[] path)
    {
        if (!TryMetadata(entry, path, out JsonElement value))
        {
            return string.Empty;
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() ?? string.Empty : string.Empty;
    }

    private static IReadOnlyList<string> MetadataStrings(ModelCatalogueEntry entry, params string[] path)
    {
        if (!TryMetadata(entry, path, out JsonElement value) || value.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        return value.EnumerateArray()
            .Where(item => item.ValueKind == JsonValueKind.String)
            .Select(item => item.GetString())
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .Cast<string>()
            .ToArray();
    }

    private static bool TryMetadata(
        ModelCatalogueEntry entry,
        IReadOnlyList<string> path,
        out JsonElement value)
    {
        value = default;
        if (path.Count == 0
            || entry.ExtensionData is null
            || !entry.ExtensionData.TryGetValue(path[0], out value))
        {
            return false;
        }

        for (int index = 1; index < path.Count; index++)
        {
            if (value.ValueKind != JsonValueKind.Object
                || !value.TryGetProperty(path[index], out value))
            {
                return false;
            }
        }

        return true;
    }
}
