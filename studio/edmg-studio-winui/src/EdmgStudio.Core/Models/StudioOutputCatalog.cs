using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Models;

public enum StudioOutputSort
{
    Newest,
    Name,
    SizeDescending,
}

public enum StudioOutputKind
{
    File,
    Image,
    Video,
    DeforumExport,
    UnrealBundle,
    UnrealReturnedImage,
    UnrealReturnedVideo,
}

public sealed record StudioOutputItem
{
    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".bmp",
        ".gif",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    };

    private static readonly HashSet<string> VideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".webm",
    };

    public StudioOutputItem(
        string group,
        string name,
        string path,
        long? sizeBytes,
        double? modifiedAt,
        JsonNode? metadata)
    {
        Group = group;
        Name = name;
        Path = path;
        SizeBytes = sizeBytes;
        ModifiedAt = modifiedAt;
        Metadata = metadata;
        Kind = InferKind(group, path);
    }

    public string Group { get; set; }

    public string Name { get; set; }

    public string Path { get; set; }

    public long? SizeBytes { get; set; }

    public double? ModifiedAt { get; set; }

    public JsonNode? Metadata { get; set; }

    public StudioOutputKind Kind { get; set; }

    public string? MetadataPath { get; set; }

    public string? BundleDirectory { get; set; }

    public string? ManifestPath { get; set; }

    public string? ImportPlanPath { get; set; }

    public string? ZipPath { get; set; }

    public string? SourceDirectory { get; set; }

    public string? SourcePath { get; set; }

    public string? ParentReturnManifestPath { get; set; }

    public string? ReturnContractPath { get; set; }

    public string? SequenceName { get; set; }

    public int? VariantIndex { get; set; }

    public double? CreatedAt { get; set; }

    public JsonNode? UnrealManifest { get; set; }

    public JsonNode? UnrealImportPlan { get; set; }

    public JsonNode? ParentUnrealReturn { get; set; }

    public string StableIdentity =>
        $"{(Kind == StudioOutputKind.UnrealBundle ? "bundle" : "file")}:{StudioOutputCatalog.NormalizePath(Path)}";

    public string Extension => System.IO.Path.GetExtension(Path);

    public bool IsImage =>
        Kind is StudioOutputKind.Image or StudioOutputKind.UnrealReturnedImage ||
        ImageExtensions.Contains(Extension);

    public bool IsVideo =>
        Kind is StudioOutputKind.Video or StudioOutputKind.UnrealReturnedVideo ||
        VideoExtensions.Contains(Extension);

    public bool IsMedia => IsImage || IsVideo;

    public bool IsPreviewable => SupportsMediaWorkflow;

    public bool IsDownloadable => Kind != StudioOutputKind.UnrealBundle && !string.IsNullOrWhiteSpace(Path);

    public bool SupportsMediaWorkflow => Kind != StudioOutputKind.UnrealBundle && IsMedia;

    public bool SupportsBundleWorkflow =>
        Kind == StudioOutputKind.UnrealBundle &&
        !string.IsNullOrWhiteSpace(BundleDirectory);

    public string Summary
    {
        get
        {
            List<string> parts = [FormatGroup(Group)];
            if (Kind == StudioOutputKind.UnrealBundle)
            {
                if (VariantIndex is int variantIndex)
                {
                    parts.Add($"variant {variantIndex}");
                }

                if (!string.IsNullOrWhiteSpace(ZipPath))
                {
                    parts.Add("ZIP");
                }
            }
            else if (SizeBytes is long bytes)
            {
                parts.Add(FormatSize(bytes));
            }

            double? timestamp = ModifiedAt ?? CreatedAt;
            if (timestamp is double unixSeconds)
            {
                parts.Add(DateTimeOffset.FromUnixTimeSeconds((long)unixSeconds)
                    .ToLocalTime()
                    .ToString("g", CultureInfo.CurrentCulture));
            }

            return string.Join(" · ", parts);
        }
    }

    private static StudioOutputKind InferKind(string group, string path)
    {
        if (group.Equals("unreal_exports", StringComparison.OrdinalIgnoreCase))
        {
            return StudioOutputKind.UnrealBundle;
        }

        if (group.Equals("deforum_exports", StringComparison.OrdinalIgnoreCase))
        {
            return StudioOutputKind.DeforumExport;
        }

        string extension = System.IO.Path.GetExtension(path);
        if (ImageExtensions.Contains(extension))
        {
            return StudioOutputKind.Image;
        }

        if (VideoExtensions.Contains(extension))
        {
            return StudioOutputKind.Video;
        }

        return StudioOutputKind.File;
    }

    private static string FormatGroup(string group) =>
        group.Replace('_', ' ').Trim() switch
        {
            { Length: 0 } => "Output",
            var value => CultureInfo.CurrentCulture.TextInfo.ToTitleCase(value),
        };

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB"];
        double value = bytes;
        var suffixIndex = 0;
        while (value >= 1024 && suffixIndex < suffixes.Length - 1)
        {
            value /= 1024;
            suffixIndex++;
        }

        return $"{value:0.#} {suffixes[suffixIndex]}";
    }
}

public static class StudioOutputCatalog
{
    private static readonly string[] ArtifactGroups =
    [
        "images",
        "videos",
        "deforum_exports",
        "unreal_exports",
        "unreal_returns",
        "internal_render_history",
    ];

    public static int CountArtifacts(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return 0;
        }

        var count = 0;
        foreach (string group in ArtifactGroups)
        {
            if (root.TryGetProperty(group, out JsonElement values) &&
                values.ValueKind == JsonValueKind.Array)
            {
                count += values.GetArrayLength();
            }
        }

        return count;
    }

    public static IReadOnlyList<StudioOutputItem> Project(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return [];
        }

        var projected = new List<StudioOutputItem>();
        var itemIndexByPath = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        ProjectFiles(root, "images", StudioOutputKind.Image, projected, itemIndexByPath);
        ProjectFiles(root, "videos", StudioOutputKind.Video, projected, itemIndexByPath);
        ProjectFiles(root, "internal_render_history", StudioOutputKind.File, projected, itemIndexByPath);
        ProjectFiles(root, "deforum_exports", StudioOutputKind.DeforumExport, projected, itemIndexByPath);
        ProjectUnrealBundles(root, projected);
        ProjectUnrealReturns(root, projected, itemIndexByPath);

        return projected;
    }

    public static IReadOnlyList<StudioOutputItem> FilterAndSort(
        IEnumerable<StudioOutputItem> items,
        string? searchText,
        string? mediaKind,
        StudioOutputSort sort)
    {
        string search = searchText?.Trim() ?? string.Empty;
        IEnumerable<StudioOutputItem> query = items;

        if (search.Length > 0)
        {
            query = query.Where(item =>
                item.Name.Contains(search, StringComparison.OrdinalIgnoreCase) ||
                item.Path.Contains(search, StringComparison.OrdinalIgnoreCase) ||
                item.Group.Contains(search, StringComparison.OrdinalIgnoreCase) ||
                item.SequenceName?.Contains(search, StringComparison.OrdinalIgnoreCase) == true);
        }

        query = mediaKind?.Trim().ToUpperInvariant() switch
        {
            "IMAGES" => query.Where(item => item.IsImage),
            "VIDEOS" => query.Where(item => item.IsVideo),
            "OTHER" => query.Where(item => !item.IsMedia),
            "UNREAL" => query.Where(item =>
                item.Kind is StudioOutputKind.UnrealBundle or
                    StudioOutputKind.UnrealReturnedImage or
                    StudioOutputKind.UnrealReturnedVideo),
            _ => query,
        };

        return sort switch
        {
            StudioOutputSort.Name => query
                .OrderBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
                .ThenBy(item => item.Path, StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            StudioOutputSort.SizeDescending => query
                .OrderByDescending(item => item.SizeBytes ?? -1)
                .ThenBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            _ => query
                .OrderByDescending(item => item.ModifiedAt ?? item.CreatedAt ?? double.MinValue)
                .ThenBy(item => item.Name, StringComparer.OrdinalIgnoreCase)
                .ThenBy(item => item.Path, StringComparer.OrdinalIgnoreCase)
                .ToArray(),
        };
    }

    public static string NormalizePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return string.Empty;
        }

        var segments = new List<string>();
        foreach (string segment in path.Trim().Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries))
        {
            if (segment == ".")
            {
                continue;
            }

            if (segment == "..")
            {
                if (segments.Count > 0 && segments[^1] != "..")
                {
                    segments.RemoveAt(segments.Count - 1);
                }
                else
                {
                    segments.Add(segment);
                }

                continue;
            }

            segments.Add(segment);
        }

        string prefix = path.TrimStart().StartsWith('/') ? "/" : string.Empty;
        return prefix + string.Join('/', segments);
    }

    private static void ProjectFiles(
        JsonElement root,
        string group,
        StudioOutputKind kind,
        List<StudioOutputItem> projected,
        Dictionary<string, int> itemIndexByPath)
    {
        if (!root.TryGetProperty(group, out JsonElement values) ||
            values.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        foreach (JsonElement value in values.EnumerateArray())
        {
            if (!TryCreateFileItem(value, group, kind, out StudioOutputItem item))
            {
                continue;
            }

            string key = NormalizePath(item.Path);
            if (key.Length > 0 && !itemIndexByPath.ContainsKey(key))
            {
                itemIndexByPath[key] = projected.Count;
            }

            projected.Add(item);
        }
    }

    private static bool TryCreateFileItem(
        JsonElement value,
        string group,
        StudioOutputKind kind,
        out StudioOutputItem item)
    {
        item = null!;
        if (value.ValueKind != JsonValueKind.Object ||
            !TryGetString(value, "path", out string path) ||
            string.IsNullOrWhiteSpace(path))
        {
            return false;
        }

        string normalizedPath = NormalizePath(path);
        string name = TryGetString(value, "name", out string explicitName) &&
                      !string.IsNullOrWhiteSpace(explicitName)
            ? explicitName
            : GetFileName(normalizedPath);

        item = new StudioOutputItem(
            group,
            name,
            normalizedPath,
            TryGetInt64(value, "size_bytes"),
            TryGetDouble(value, "modified_at"),
            CloneNode(value))
        {
            Kind = kind,
            MetadataPath = GetOptionalPath(value, "metadata_path"),
        };

        return true;
    }

    private static void ProjectUnrealBundles(JsonElement root, List<StudioOutputItem> projected)
    {
        if (!root.TryGetProperty("unreal_exports", out JsonElement values) ||
            values.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        foreach (JsonElement value in values.EnumerateArray())
        {
            if (value.ValueKind != JsonValueKind.Object ||
                !TryGetString(value, "bundle_dir", out string bundleDirectory) ||
                string.IsNullOrWhiteSpace(bundleDirectory))
            {
                continue;
            }

            string normalizedBundleDirectory = NormalizePath(bundleDirectory);
            string name = TryGetString(value, "name", out string explicitName) &&
                          !string.IsNullOrWhiteSpace(explicitName)
                ? explicitName
                : GetFileName(normalizedBundleDirectory);

            projected.Add(new StudioOutputItem(
                "unreal_exports",
                name,
                normalizedBundleDirectory,
                null,
                TryGetDouble(value, "modified_at"),
                CloneNode(value))
            {
                Kind = StudioOutputKind.UnrealBundle,
                BundleDirectory = normalizedBundleDirectory,
                ManifestPath = GetOptionalPath(value, "manifest_path"),
                ImportPlanPath = GetOptionalPath(value, "import_plan_path"),
                ZipPath = GetOptionalPath(value, "zip_path"),
                VariantIndex = TryGetInt32(value, "variant_index"),
                CreatedAt = TryGetDouble(value, "created_at"),
                UnrealManifest = ClonePropertyNode(value, "manifest"),
                UnrealImportPlan = ClonePropertyNode(value, "import_plan"),
            });
        }
    }

    private static void ProjectUnrealReturns(
        JsonElement root,
        List<StudioOutputItem> projected,
        Dictionary<string, int> itemIndexByPath)
    {
        if (!root.TryGetProperty("unreal_returns", out JsonElement returns) ||
            returns.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        foreach (JsonElement unrealReturn in returns.EnumerateArray())
        {
            if (unrealReturn.ValueKind != JsonValueKind.Object ||
                !unrealReturn.TryGetProperty("media", out JsonElement media) ||
                media.ValueKind != JsonValueKind.Array)
            {
                continue;
            }

            JsonNode? parent = CloneNode(unrealReturn);
            foreach (JsonElement value in media.EnumerateArray())
            {
                if (!TryCreateFileItem(
                        value,
                        "unreal_returns",
                        StudioOutputKind.File,
                        out StudioOutputItem fileItem))
                {
                    continue;
                }

                StudioOutputKind kind = fileItem.IsImage
                    ? StudioOutputKind.UnrealReturnedImage
                    : fileItem.IsVideo
                        ? StudioOutputKind.UnrealReturnedVideo
                        : StudioOutputKind.File;

                StudioOutputItem returnedItem = fileItem with
                {
                    Kind = kind,
                    SourceDirectory = GetOptionalPath(unrealReturn, "source_dir"),
                    SourcePath = GetOptionalPath(value, "source_path"),
                    ParentReturnManifestPath = GetOptionalPath(unrealReturn, "return_manifest_path"),
                    ReturnContractPath = GetOptionalPath(unrealReturn, "contract_path"),
                    SequenceName = GetOptionalString(value, "sequence_name"),
                    VariantIndex = TryGetInt32(unrealReturn, "variant_index"),
                    ParentUnrealReturn = parent?.DeepClone(),
                };

                string key = NormalizePath(returnedItem.Path);
                if (key.Length > 0 && itemIndexByPath.TryGetValue(key, out int existingIndex))
                {
                    StudioOutputItem existing = projected[existingIndex];
                    projected[existingIndex] = returnedItem with
                    {
                        Group = existing.Group,
                        SizeBytes = existing.SizeBytes ?? returnedItem.SizeBytes,
                        ModifiedAt = existing.ModifiedAt ?? returnedItem.ModifiedAt,
                    };
                }
                else
                {
                    if (key.Length > 0)
                    {
                        itemIndexByPath[key] = projected.Count;
                    }

                    projected.Add(returnedItem);
                }
            }
        }
    }

    private static string GetFileName(string path)
    {
        int separatorIndex = path.LastIndexOf('/');
        return separatorIndex >= 0 ? path[(separatorIndex + 1)..] : path;
    }

    private static string? GetOptionalPath(JsonElement element, string propertyName) =>
        TryGetString(element, propertyName, out string value) && !string.IsNullOrWhiteSpace(value)
            ? NormalizePath(value)
            : null;

    private static string? GetOptionalString(JsonElement element, string propertyName) =>
        TryGetString(element, propertyName, out string value) && !string.IsNullOrWhiteSpace(value)
            ? value
            : null;

    private static bool TryGetString(JsonElement element, string propertyName, out string value)
    {
        value = string.Empty;
        return element.TryGetProperty(propertyName, out JsonElement property) &&
               property.ValueKind == JsonValueKind.String &&
               (value = property.GetString() ?? string.Empty).Length > 0;
    }

    private static long? TryGetInt64(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out JsonElement property) &&
        property.ValueKind == JsonValueKind.Number &&
        property.TryGetInt64(out long value)
            ? value
            : null;

    private static int? TryGetInt32(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out JsonElement property) &&
        property.ValueKind == JsonValueKind.Number &&
        property.TryGetInt32(out int value)
            ? value
            : null;

    private static double? TryGetDouble(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out JsonElement property) &&
        property.ValueKind == JsonValueKind.Number &&
        property.TryGetDouble(out double value)
            ? value
            : null;

    private static JsonNode? CloneNode(JsonElement element) =>
        JsonNode.Parse(element.GetRawText());

    private static JsonNode? ClonePropertyNode(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out JsonElement property)
            ? CloneNode(property)
            : null;
}
