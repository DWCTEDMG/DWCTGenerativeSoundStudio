using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioShellActivityTests
{
    [TestMethod]
    public void Create_ProjectsJobBadgesFeaturedRenderAndModelAttention()
    {
        StudioJob running = Job("running", "internal_video", "active", "2026-09-11T08:00:00Z");
        StudioJob failed = Job("failed", "timeline_render", "failed", "2026-09-11T07:00:00Z");
        StudioJob review = Job("succeeded", "timeline_render", "review", "2026-09-11T06:00:00Z");
        var catalogue = new ModelCatalogueResponse
        {
            Catalog =
            [
                new ModelCatalogueEntry
                {
                    Id = "blocked",
                    Installed = true,
                    PackageStatus = new ModelRuntimeStatus("blocked", "blocked", true, false, 1, false, true, true, true, null, ["Missing runtime"]),
                },
                new ModelCatalogueEntry
                {
                    Id = "ready",
                    Installed = true,
                    PackageStatus = new ModelRuntimeStatus("ready", "ready", true, true, 1, true, true, true, true, null, []),
                },
            ],
        };

        StudioShellActivity result = StudioShellActivity.Create([failed, review, running], catalogue);

        Assert.AreEqual("active", result.FeaturedJob?.Id);
        Assert.AreEqual(1, result.ActiveJobCount);
        Assert.AreEqual(1, result.FailedJobCount);
        Assert.AreEqual(1, result.ReviewItemCount);
        Assert.AreEqual(1, result.ModelAttentionCount);
    }

    [TestMethod]
    public void Create_ExcludesReviewedAndNonRenderSuccesses()
    {
        StudioJob reviewed = Job("succeeded", "internal_video", "reviewed", "2026-09-11T08:00:00Z");
        StudioJob analysis = Job("succeeded", "analysis", "analysis", "2026-09-11T07:00:00Z");

        StudioShellActivity result = StudioShellActivity.Create(
            [reviewed, analysis],
            null,
            new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "reviewed" });

        Assert.AreEqual(0, result.ReviewItemCount);
        Assert.IsNull(result.FeaturedJob);
    }

    private static StudioJob Job(string status, string type, string id, string updatedAt) =>
        new(id, "project", type, status, updatedAt, updatedAt, updatedAt, null, null, new StudioJobProgress(25, "render", "Rendering", 1, 4), null, null);
}
