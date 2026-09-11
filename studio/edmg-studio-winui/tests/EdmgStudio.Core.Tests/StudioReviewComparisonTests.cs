using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioReviewComparisonTests
{
    [TestMethod]
    public void KeepReference_PreservesAvailableReferenceOrUsesFirstSlot()
    {
        Assert.AreEqual("b.mp4", StudioReviewComparison.KeepReference(" B.MP4 ", ["a.mp4", "b.mp4"]));
        Assert.AreEqual("a.mp4", StudioReviewComparison.KeepReference("missing.mp4", ["a.mp4", "b.mp4"]));
        Assert.IsNull(StudioReviewComparison.KeepReference("missing.mp4", []));
    }

    [TestMethod]
    public void MoveActive_WrapsAcrossOrderedSlots()
    {
        Assert.AreEqual("a.mp4", StudioReviewComparison.MoveActive(["a.mp4", "b.mp4"], "b.mp4", 1));
        Assert.AreEqual("b.mp4", StudioReviewComparison.MoveActive(["a.mp4", "b.mp4"], "a.mp4", -1));
    }

    [TestMethod]
    public void CompareMetadata_FlagsOnlyChangedRows()
    {
        ReviewComparisonArtifact[] artifacts =
        [
            new("a.mp4", "A", "video", "Warm", "approved", "comfy", "model-a", "10", 2048),
            new("b.mp4", "B", "video", "Cool", "approved", "comfy", "model-b", "10", 2048)
        ];

        IReadOnlyList<ReviewMetadataDifference> differences = StudioReviewComparison.CompareMetadata(artifacts);

        Assert.IsTrue(differences.Single(item => item.Label == "Variant").IsDifferent);
        Assert.IsTrue(differences.Single(item => item.Label == "Model").IsDifferent);
        Assert.IsFalse(differences.Single(item => item.Label == "Engine").IsDifferent);
    }

    [TestMethod]
    public void AnnotationNormalize_ClampsPositionAndTrimsNote()
    {
        Assert.AreEqual(new ReviewAnnotation(1, "Cut here"), new ReviewAnnotation(2.5, " Cut here ").Normalize());
        Assert.AreEqual(0, new ReviewAnnotation(double.NaN, "note").Normalize().Position);
    }
}
