namespace EdmgStudio.Core.Services;

public static class StudioStoragePaths
{
    public static string ResolveRoot(
        bool isPackaged,
        string? packagedPath,
        string? localAppData,
        string leaf)
    {
        if (string.IsNullOrWhiteSpace(leaf))
        {
            throw new ArgumentException("A storage leaf name is required.", nameof(leaf));
        }

        string root;
        if (isPackaged)
        {
            root = !string.IsNullOrWhiteSpace(packagedPath)
                ? packagedPath
                : throw new InvalidOperationException("The packaged Studio storage path is unavailable.");
        }
        else
        {
            root = !string.IsNullOrWhiteSpace(localAppData)
                ? Path.Combine(localAppData, "DWCT", "EDMG Studio")
                : throw new InvalidOperationException("The local application-data directory is unavailable.");
        }

        return Path.GetFullPath(Path.Combine(root, leaf));
    }
}
