using EdmgStudio.Core.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class ManagedProjectPathResolverTests
{
    [TestMethod]
    public void Resolve_ReturnsManagedProjectPath()
    {
        string dataDirectory = CreateDataDirectory();

        ManagedProjectPathResolution result = ManagedProjectPathResolver.Resolve(
            RequestedBackendMode.Managed,
            dataDirectory,
            "project-123",
            @"outputs\unreal\sequence-1");

        Assert.IsTrue(result.IsAvailable);
        Assert.AreEqual(
            Path.GetFullPath(Path.Combine(dataDirectory, "projects", "project-123", "outputs", "unreal", "sequence-1")),
            result.FullPath);
        Assert.AreEqual(string.Empty, result.ErrorMessage);
    }

    [TestMethod]
    public void Resolve_RejectsExternalBackend()
    {
        ManagedProjectPathResolution result = ManagedProjectPathResolver.Resolve(
            RequestedBackendMode.External,
            CreateDataDirectory(),
            "project-123",
            @"outputs\unreal\sequence-1");

        Assert.IsFalse(result.IsAvailable);
        Assert.IsNull(result.FullPath);
        StringAssert.Contains(result.ErrorMessage, "external backend");
    }

    [DataTestMethod]
    [DataRow("")]
    [DataRow(" ")]
    [DataRow(".")]
    [DataRow("..")]
    [DataRow(@"..\other-project")]
    [DataRow(@"nested\project")]
    [DataRow(@"C:\projects\project-123")]
    public void Resolve_RejectsInvalidProjectIds(string projectId)
    {
        ManagedProjectPathResolution result = ManagedProjectPathResolver.Resolve(
            RequestedBackendMode.Managed,
            CreateDataDirectory(),
            projectId,
            @"outputs\unreal\sequence-1");

        Assert.IsFalse(result.IsAvailable);
        StringAssert.Contains(result.ErrorMessage, "project ID");
    }

    [DataTestMethod]
    [DataRow("")]
    [DataRow(" ")]
    [DataRow(@"..\outside")]
    [DataRow(@"outputs\unreal\..\..\..\outside")]
    [DataRow(@"C:\outside")]
    public void Resolve_RejectsUnsafePaths(string relativePath)
    {
        ManagedProjectPathResolution result = ManagedProjectPathResolver.Resolve(
            RequestedBackendMode.Managed,
            CreateDataDirectory(),
            "project-123",
            relativePath);

        Assert.IsFalse(result.IsAvailable);
        Assert.IsNull(result.FullPath);
    }

    [TestMethod]
    public void Resolve_RejectsMalformedPath()
    {
        ManagedProjectPathResolution result = ManagedProjectPathResolver.Resolve(
            RequestedBackendMode.Managed,
            CreateDataDirectory(),
            "project-123",
            "outputs\0unreal");

        Assert.IsFalse(result.IsAvailable);
        StringAssert.Contains(result.ErrorMessage, "malformed");
    }

    private static string CreateDataDirectory() =>
        Path.Combine(Path.GetTempPath(), "edmg-path-tests", Guid.NewGuid().ToString("N"));
}
