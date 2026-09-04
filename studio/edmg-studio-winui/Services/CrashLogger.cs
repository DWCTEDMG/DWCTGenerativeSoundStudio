namespace EdmgStudio.WinUI.Services;

internal static class CrashLogger
{
    private static readonly object Sync = new();

    public static string LogDirectory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DWCT",
        "EDMG Studio",
        "Logs");

    public static string LogPath => Path.Combine(LogDirectory, "winui-crash.log");

    public static void Write(string message, Exception? exception = null)
    {
        try
        {
            lock (Sync)
            {
                Directory.CreateDirectory(LogDirectory);
                using var writer = new StreamWriter(LogPath, append: true);
                writer.WriteLine("============================================================");
                writer.WriteLine($"UTC: {DateTimeOffset.UtcNow:O}");
                writer.WriteLine($"Local: {DateTimeOffset.Now:O}");
                writer.WriteLine($"Process: {Environment.ProcessPath}");
                writer.WriteLine($"Runtime: {Environment.Version}");
                writer.WriteLine($"OS: {Environment.OSVersion}");
                writer.WriteLine(message);
                if (exception is not null)
                {
                    writer.WriteLine(exception.ToString());
                }
            }
        }
        catch
        {
            // Diagnostics must never become another startup failure.
        }
    }
}
