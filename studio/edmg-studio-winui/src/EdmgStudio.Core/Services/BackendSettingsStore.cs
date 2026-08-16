using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Services;

public static class BackendSettingsStore
{
    public static string GetDefaultBootstrapPath() =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "EDMG Studio",
            "bootstrap.json");

    public static void ResetToManaged(string? bootstrapPath = null, string host = "127.0.0.1", int port = 7863)
    {
        if (string.IsNullOrWhiteSpace(host))
        {
            throw new ArgumentException("Managed backend host is required.", nameof(host));
        }

        if (port is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(port), "Managed backend port must be between 1 and 65535.");
        }

        var path = Path.GetFullPath(bootstrapPath ?? GetDefaultBootstrapPath());
        JsonObject root;
        if (File.Exists(path))
        {
            try
            {
                root = JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                    ?? throw new InvalidDataException("The Studio bootstrap file must contain a JSON object.");
            }
            catch (JsonException exception)
            {
                throw new InvalidDataException(
                    "The Studio bootstrap file is malformed. It was not changed so the existing configuration can be recovered safely.",
                    exception);
            }
        }
        else
        {
            root = new JsonObject();
        }

        root["backendSettings"] = new JsonObject
        {
            ["mode"] = "managed",
            ["host"] = host.Trim(),
            ["port"] = port.ToString(),
            ["url"] = string.Empty
        };
        root["updatedAt"] = DateTimeOffset.UtcNow.ToString("O");

        WriteAtomically(path, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);
    }

    private static void WriteAtomically(string path, string content)
    {
        var directory = Path.GetDirectoryName(path)
            ?? throw new InvalidOperationException("The bootstrap path has no parent directory.");
        Directory.CreateDirectory(directory);
        var temporaryPath = Path.Combine(directory, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var stream = new FileStream(
                       temporaryPath,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None,
                       4096,
                       FileOptions.WriteThrough))
            using (var writer = new StreamWriter(stream, new System.Text.UTF8Encoding(encoderShouldEmitUTF8Identifier: false)))
            {
                writer.Write(content);
                writer.Flush();
                stream.Flush(flushToDisk: true);
            }

            File.Move(temporaryPath, path, overwrite: true);
        }
        finally
        {
            if (File.Exists(temporaryPath))
            {
                File.Delete(temporaryPath);
            }
        }
    }
}
