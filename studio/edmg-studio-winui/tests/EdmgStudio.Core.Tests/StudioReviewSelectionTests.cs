using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioReviewSelectionTests
{
    [TestMethod]
    public void AddRecent_NormalizesDeduplicatesAndKeepsTheMostRecentFour()
    {
        var result = StudioReviewSelection.AddRecent(
            ["a.png", "b.png", "c.png", "A.PNG", "d.png"],
            " e.png ");

        CollectionAssert.AreEqual(
            new[] { "b.png", "c.png", "d.png", "e.png" },
            result.ToArray());
    }

    [TestMethod]
    public void AddRecent_ReSelectingArtifactMovesItToTheEnd()
    {
        var result = StudioReviewSelection.AddRecent(
            ["a.png", "b.png", "c.png"],
            "B.PNG");

        CollectionAssert.AreEqual(
            new[] { "a.png", "c.png", "B.PNG" },
            result.ToArray());
    }

    [TestMethod]
    public void KeepAvailable_RemovesMissingArtifactsAndPreservesOrder()
    {
        var result = StudioReviewSelection.KeepAvailable(
            ["missing.png", "B.PNG", "a.png", "b.png"],
            ["a.png", "b.png", "c.png"]);

        CollectionAssert.AreEqual(
            new[] { "B.PNG", "a.png" },
            result.ToArray());
    }
}
