using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioOutputCatalogTests
{
    [TestMethod]
    public void CountArtifacts_CountsArtifactGroupsButNotJobOrLatestMetadata()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "images": [{"path":"a.png"}],
              "videos": [{"path":"a.mp4"}, {"path":"b.mp4"}],
              "deforum_exports": [],
              "unreal_exports": [{"path":"scene.zip"}],
              "unreal_returns": [{"path":"return.mp4"}],
              "internal_render_history": [{"path":"history.mp4"}],
              "active_internal_jobs": [{"id":"job-1"}],
              "latest_internal_render": {"path":"history.mp4"}
            }
            """);

        Assert.AreEqual(6, StudioOutputCatalog.CountArtifacts(document.RootElement));
    }

    [TestMethod]
    public void CountArtifacts_ReturnsZeroForNonObjectPayload()
    {
        using var document = JsonDocument.Parse("[]");

        Assert.AreEqual(0, StudioOutputCatalog.CountArtifacts(document.RootElement));
    }

    [TestMethod]
    public void FilterAndSort_FiltersAcrossNamePathAndGroup()
    {
        StudioOutputItem[] items =
        [
            Item("images", "cover.png", "outputs/images/cover.png", 10, 1),
            Item("videos", "final.mp4", "outputs/videos/final.mp4", 20, 2),
            Item("deforum_exports", "settings.json", "outputs/deforum/settings.json", 30, 3),
        ];

        var result = StudioOutputCatalog.FilterAndSort(items, "deforum", "All", StudioOutputSort.Newest);

        Assert.HasCount(1, result);
        Assert.AreEqual("settings.json", result[0].Name);
    }

    [TestMethod]
    public void FilterAndSort_AppliesMediaKindAndStableNewestOrder()
    {
        StudioOutputItem[] items =
        [
            Item("images", "z.png", "z.png", 10, 5),
            Item("images", "a.jpg", "a.jpg", 20, 5),
            Item("videos", "clip.mp4", "clip.mp4", 30, 9),
        ];

        var result = StudioOutputCatalog.FilterAndSort(items, null, "Images", StudioOutputSort.Newest);

        CollectionAssert.AreEqual(new[] { "a.jpg", "z.png" }, result.Select(item => item.Name).ToArray());
    }

    [TestMethod]
    public void FilterAndSort_SortsByDescendingSize()
    {
        StudioOutputItem[] items =
        [
            Item("other", "small.json", "small.json", 10, null),
            Item("other", "large.json", "large.json", 50, null),
        ];

        var result = StudioOutputCatalog.FilterAndSort(items, null, "Other", StudioOutputSort.SizeDescending);

        CollectionAssert.AreEqual(new[] { "large.json", "small.json" }, result.Select(item => item.Name).ToArray());
    }

    [TestMethod]
    public void Project_ProjectsUnrealBundleWithoutTreatingItAsMedia()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "unreal_exports": [{
                "name": "hero-sequence",
                "bundle_dir": "outputs\\unreal\\hero-sequence",
                "manifest_path": "outputs/unreal/hero-sequence/unreal_manifest.json",
                "import_plan_path": "outputs/unreal/hero-sequence/unreal_import_plan.json",
                "zip_path": "outputs/unreal/hero-sequence.zip",
                "variant_index": 3,
                "created_at": 1700000000,
                "manifest": {"schema_version": 1},
                "future_field": {"retained": true}
              }]
            }
            """);

        var projected = StudioOutputCatalog.Project(document.RootElement);
        Assert.HasCount(1, projected);
        StudioOutputItem item = projected[0];

        Assert.AreEqual(StudioOutputKind.UnrealBundle, item.Kind);
        Assert.AreEqual("outputs/unreal/hero-sequence", item.Path);
        Assert.AreEqual("outputs/unreal/hero-sequence", item.BundleDirectory);
        Assert.AreEqual("outputs/unreal/hero-sequence.zip", item.ZipPath);
        Assert.AreEqual(3, item.VariantIndex);
        Assert.IsTrue(item.SupportsBundleWorkflow);
        Assert.IsFalse(item.SupportsMediaWorkflow);
        Assert.IsFalse(item.IsPreviewable);
        Assert.IsFalse(item.IsDownloadable);
        Assert.IsNotNull(item.Metadata?["future_field"]);
    }

    [TestMethod]
    public void Project_FlattensReturnedMediaAndEnrichesMatchingOrdinaryOutput()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "videos": [{
                "name": "shot.mp4",
                "path": "outputs\\videos\\shot.mp4",
                "size_bytes": 2048,
                "modified_at": 1700000001
              }],
              "unreal_returns": [{
                "source_dir": "incoming\\unreal",
                "return_manifest_path": "outputs/unreal/returns/return.json",
                "contract_path": "outputs/unreal/returns/contract.json",
                "variant_index": 4,
                "unknown_parent": "retained",
                "media": [{
                  "path": "outputs/videos/./shot.mp4",
                  "source_path": "incoming/unreal/shot.mp4",
                  "sequence_name": "MainSequence"
                }]
              }]
            }
            """);

        var projected = StudioOutputCatalog.Project(document.RootElement);
        Assert.HasCount(1, projected);
        StudioOutputItem item = projected[0];

        Assert.AreEqual(StudioOutputKind.UnrealReturnedVideo, item.Kind);
        Assert.AreEqual("videos", item.Group);
        Assert.AreEqual("outputs/videos/shot.mp4", item.Path);
        Assert.AreEqual(2048, item.SizeBytes);
        Assert.AreEqual("incoming/unreal", item.SourceDirectory);
        Assert.AreEqual("incoming/unreal/shot.mp4", item.SourcePath);
        Assert.AreEqual("MainSequence", item.SequenceName);
        Assert.AreEqual(4, item.VariantIndex);
        Assert.AreEqual(
            "retained",
            item.ParentUnrealReturn?["unknown_parent"]?.GetValue<string>());
        Assert.IsTrue(item.IsPreviewable);
        Assert.IsTrue(item.IsDownloadable);
        Assert.IsTrue(item.SupportsMediaWorkflow);
        Assert.IsFalse(item.SupportsBundleWorkflow);
    }

    [TestMethod]
    public void Project_PreservesFileIdentityWhenUnrealReturnEnrichesMedia()
    {
        using var ordinaryDocument = JsonDocument.Parse(
            """
            {
              "videos": [{"path": "outputs\\videos\\shot.mp4"}]
            }
            """);
        using var enrichedDocument = JsonDocument.Parse(
            """
            {
              "videos": [{"path": "outputs/videos/shot.mp4"}],
              "unreal_returns": [{
                "media": [{"path": "outputs/videos/./shot.mp4"}]
              }]
            }
            """);

        StudioOutputItem ordinary = StudioOutputCatalog.Project(ordinaryDocument.RootElement).Single();
        StudioOutputItem enriched = StudioOutputCatalog.Project(enrichedDocument.RootElement).Single();

        Assert.AreEqual("file:outputs/videos/shot.mp4", ordinary.StableIdentity);
        Assert.AreEqual(ordinary.StableIdentity, enriched.StableIdentity);
        Assert.AreEqual(StudioOutputKind.UnrealReturnedVideo, enriched.Kind);
    }

    [TestMethod]
    public void Project_UsesDistinctBundleIdentityForMatchingPath()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "videos": [{"path": "outputs/unreal/hero"}],
              "unreal_exports": [{"bundle_dir": "outputs\\unreal\\hero"}]
            }
            """);

        var projected = StudioOutputCatalog.Project(document.RootElement);

        CollectionAssert.AreEquivalent(
            new[] { "file:outputs/unreal/hero", "bundle:outputs/unreal/hero" },
            projected.Select(item => item.StableIdentity).ToArray());
    }

    [TestMethod]
    public void Project_IncludesInternalRenderHistory()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "internal_render_history": [{
                "name": "preview.mp4",
                "path": "outputs/internal/preview.mp4",
                "size_bytes": 4096,
                "modified_at": 1700000002
              }]
            }
            """);

        StudioOutputItem item = StudioOutputCatalog.Project(document.RootElement).Single();

        Assert.AreEqual("internal_render_history", item.Group);
        Assert.AreEqual("outputs/internal/preview.mp4", item.Path);
        Assert.IsTrue(item.IsVideo);
        Assert.IsTrue(item.SupportsMediaWorkflow);
    }

    [TestMethod]
    public void Project_AddsReturnedMediaThatIsAbsentFromOrdinaryGroups()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "unreal_returns": [{
                "media": [{
                  "name": "frame.png",
                  "path": "outputs/images/frame.png"
                }]
              }]
            }
            """);

        var projected = StudioOutputCatalog.Project(document.RootElement);
        Assert.HasCount(1, projected);
        StudioOutputItem item = projected[0];

        Assert.AreEqual(StudioOutputKind.UnrealReturnedImage, item.Kind);
        Assert.AreEqual("unreal_returns", item.Group);
        Assert.IsTrue(item.IsImage);
    }

    [TestMethod]
    public void FilterAndSort_FiltersUnrealBundlesAndReturnedMedia()
    {
        using var document = JsonDocument.Parse(
            """
            {
              "images": [{"path": "outputs/images/ordinary.png"}],
              "unreal_exports": [{"bundle_dir": "outputs/unreal/bundle"}],
              "unreal_returns": [{
                "media": [{"path": "outputs/videos/returned.mp4"}]
              }]
            }
            """);

        var result = StudioOutputCatalog.FilterAndSort(
            StudioOutputCatalog.Project(document.RootElement),
            null,
            "Unreal",
            StudioOutputSort.Name);

        CollectionAssert.AreEqual(
            new[] { "bundle", "returned.mp4" },
            result.Select(item => item.Name).ToArray());
    }

    private static StudioOutputItem Item(
        string group,
        string name,
        string path,
        long size,
        double? modifiedAt) =>
        new(group, name, path, size, modifiedAt, new JsonObject());
}
