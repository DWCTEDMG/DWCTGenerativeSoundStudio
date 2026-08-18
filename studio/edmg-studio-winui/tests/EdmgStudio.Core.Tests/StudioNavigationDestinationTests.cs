using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioNavigationDestinationTests
{
    [TestMethod]
    [DataRow(" outputs ", "outputs")]
    [DataRow("DIRECTORLAB", "directorLab")]
    [DataRow("migration", "migration")]
    [DataRow("unknown", "dashboard")]
    [DataRow(null, "dashboard")]
    public void NormalizeOrDefault_ReturnsCanonicalKnownDestination(string? value, string expected)
    {
        Assert.AreEqual(expected, StudioNavigationDestination.NormalizeOrDefault(value));
    }

    [TestMethod]
    public void NormalizeRestorableOrDefault_DoesNotRestoreSetupOrUnknownText()
    {
        Assert.AreEqual("dashboard", StudioNavigationDestination.NormalizeRestorableOrDefault("setup"));
        Assert.AreEqual("dashboard", StudioNavigationDestination.NormalizeRestorableOrDefault("old-route"));
        Assert.AreEqual("review", StudioNavigationDestination.NormalizeRestorableOrDefault("review"));
    }
}
