using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class StudioStoragePathsTests
{
    [TestMethod]
    public void ResolveRoot_UsesPackagedPathWhenPackageIdentityIsAvailable()
    {
        string result = StudioStoragePaths.ResolveRoot(
            isPackaged: true,
            packagedPath: @"C:\Package\LocalState",
            localAppData: @"C:\Users\test\AppData\Local",
            leaf: "state");

        Assert.AreEqual(Path.GetFullPath(@"C:\Package\LocalState\state"), result);
    }

    [TestMethod]
    public void ResolveRoot_UsesStableUnpackagedPathWithoutApplicationData()
    {
        string result = StudioStoragePaths.ResolveRoot(
            isPackaged: false,
            packagedPath: null,
            localAppData: @"C:\Users\test\AppData\Local",
            leaf: "cache");

        Assert.AreEqual(
            Path.GetFullPath(@"C:\Users\test\AppData\Local\DWCT\EDMG Studio\cache"),
            result);
    }

    [TestMethod]
    public void ResolveRoot_RejectsMissingLocalAppDataForUnpackagedStudio()
    {
        Assert.ThrowsExactly<InvalidOperationException>(() => StudioStoragePaths.ResolveRoot(
            isPackaged: false,
            packagedPath: null,
            localAppData: " ",
            leaf: "state"));
    }
}
