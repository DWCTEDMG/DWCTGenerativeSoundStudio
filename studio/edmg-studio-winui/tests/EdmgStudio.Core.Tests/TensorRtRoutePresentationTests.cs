using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class TensorRtRoutePresentationTests
{
    [TestMethod]
    public void HuggingFaceRouteDoesNotClaimAccelerationWithoutExecutionEvidence()
    {
        var status = new RuntimeComponentStatus
        {
            SourceKind = "huggingface",
            SelectedRoute = "huggingface_torch_tensorrt",
            RouteSupported = true,
            Validated = true,
            Accelerating = false,
        };

        TensorRtRoutePresentation view = TensorRtRoutePresentation.From(status);

        Assert.AreEqual("Hugging Face via Torch-TensorRT", view.RouteLabel);
        Assert.AreEqual("Validated, not active", view.State);
    }

    [TestMethod]
    public void UnsupportedRouteShowsBackendReason()
    {
        var status = new RuntimeComponentStatus
        {
            SourceKind = "pytorch_checkpoint",
            SelectedRoute = "existing_runtime",
            RouteSupported = false,
            RouteReason = "Architecture FixtureModel has no registered loader",
        };

        TensorRtRoutePresentation view = TensorRtRoutePresentation.From(status);

        Assert.AreEqual("Existing model runtime", view.RouteLabel);
        StringAssert.Contains(view.Detail, "FixtureModel");
    }

    [TestMethod]
    public void OldPayloadDefaultsRemainNeutral()
    {
        TensorRtRoutePresentation view = TensorRtRoutePresentation.From(new RuntimeComponentStatus());
        Assert.AreEqual("Existing model runtime", view.RouteLabel);
        Assert.AreEqual("Unsupported", view.State);
    }
}
