using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace EdmgStudio.Core.Runtime;

public sealed class LocalRuntimeSettingsStore
{
    private readonly string _path;

    public LocalRuntimeSettingsStore(string? path = null)
    {
        _path = Path.GetFullPath(path ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "EDMG Studio",
            "bootstrap.json"));
    }

    public LocalRuntimeSettings Load()
    {
        JsonObject root = ReadRoot();
        if (root["localRuntime"] is not JsonObject value)
        {
            return new LocalRuntimeSettings();
        }

        return new LocalRuntimeSettings
        {
            Enabled = ReadBool(value, "enabled", true),
            AutoStart = ReadBool(value, "autoStart", true),
            StopOnExit = ReadBool(value, "stopOnExit", true),
            PreferredRuntime = ReadRuntime(value, "preferredRuntime"),
            CudaEnabled = ReadBool(value, "cudaEnabled", true),
            MultiGpuEnabled = ReadBool(value, "multiGpuEnabled", true),
            WslDistro = ReadString(value, "wslDistro"),
            LlamaExecutable = ReadString(value, "llamaExecutable") ?? "~/.llama-app/llama",
            LlamaModel = ReadString(value, "llamaModel") ?? "Qwen/Qwen3-4B-GGUF:Q4_K_M",
            LlamaPort = ReadPort(value, "llamaPort", 8080),
            GpuLayers = ReadString(value, "gpuLayers") ?? "all",
            SplitMode = ReadSplitMode(value),
            TensorSplit = ReadString(value, "tensorSplit"),
            Fit = ReadBool(value, "fit", true),
            ContextSize = ReadPositive(value, "contextSize", 8192),
            TensorRtExecutable = ReadString(value, "tensorRtExecutable") ?? "trtllm-serve",
            TensorRtModel = ReadString(value, "tensorRtModel"),
            TensorRtModelFormat = ReadString(value, "tensorRtModelFormat") ?? "engine",
            TensorRtPort = ReadPort(value, "tensorRtPort", 8081),
            TensorParallelSize = ReadNullablePositive(value, "tensorParallelSize"),
            DeviceList = ReadDeviceList(value),
            AdditionalArguments = ReadStringArray(value, "additionalArguments"),
            StartupTimeout = TimeSpan.FromSeconds(ReadPositive(value, "startupTimeoutSeconds", 180))
        };
    }

    public void Save(LocalRuntimeSettings settings)
    {
        ArgumentNullException.ThrowIfNull(settings);
        Validate(settings);
        JsonObject root = ReadRoot();
        root["localRuntime"] = new JsonObject
        {
            ["enabled"] = settings.Enabled,
            ["autoStart"] = settings.AutoStart,
            ["stopOnExit"] = settings.StopOnExit,
            ["preferredRuntime"] = settings.PreferredRuntime.ToString(),
            ["cudaEnabled"] = settings.CudaEnabled,
            ["multiGpuEnabled"] = settings.MultiGpuEnabled,
            ["wslDistro"] = settings.WslDistro,
            ["llamaExecutable"] = settings.LlamaExecutable,
            ["llamaModel"] = settings.LlamaModel,
            ["llamaPort"] = settings.LlamaPort,
            ["gpuLayers"] = settings.GpuLayers,
            ["splitMode"] = settings.SplitMode,
            ["tensorSplit"] = settings.TensorSplit,
            ["fit"] = settings.Fit,
            ["contextSize"] = settings.ContextSize,
            ["tensorRtExecutable"] = settings.TensorRtExecutable,
            ["tensorRtModel"] = settings.TensorRtModel,
            ["tensorRtModelFormat"] = settings.TensorRtModelFormat,
            ["tensorRtPort"] = settings.TensorRtPort,
            ["tensorParallelSize"] = settings.TensorParallelSize,
            ["deviceList"] = new JsonArray(settings.DeviceList.Select(index => JsonValue.Create(index)).ToArray()),
            ["additionalArguments"] = new JsonArray(settings.AdditionalArguments.Select(argument => JsonValue.Create(argument)).ToArray()),
            ["startupTimeoutSeconds"] = checked((int)Math.Ceiling(settings.StartupTimeout.TotalSeconds))
        };
        root["updatedAt"] = DateTimeOffset.UtcNow.ToString("O");
        WriteAtomically(root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine);
    }

    private JsonObject ReadRoot()
    {
        if (!File.Exists(_path)) return new JsonObject();
        try
        {
            return JsonNode.Parse(File.ReadAllText(_path)) as JsonObject
                ?? throw new InvalidDataException("The Studio bootstrap file must contain a JSON object.");
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("The Studio bootstrap file is malformed and was not changed.", exception);
        }
    }

    private void WriteAtomically(string content)
    {
        string directory = Path.GetDirectoryName(_path)
            ?? throw new InvalidOperationException("The runtime settings path has no parent directory.");
        Directory.CreateDirectory(directory);
        string temporaryPath = Path.Combine(directory, $".{Path.GetFileName(_path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            File.WriteAllText(temporaryPath, content, new System.Text.UTF8Encoding(false));
            File.Move(temporaryPath, _path, true);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }

    private static void Validate(LocalRuntimeSettings settings)
    {
        if (string.IsNullOrWhiteSpace(settings.LlamaExecutable)) throw new ArgumentException("llama.cpp executable is required.");
        if (string.IsNullOrWhiteSpace(settings.LlamaModel)) throw new ArgumentException("llama.cpp model is required.");
        if (settings.LlamaPort is < 1 or > 65535 || settings.TensorRtPort is < 1 or > 65535) throw new ArgumentOutOfRangeException(nameof(settings), "Runtime ports must be between 1 and 65535.");
        if (settings.ContextSize <= 0) throw new ArgumentOutOfRangeException(nameof(settings), "Context size must be positive.");
        if (settings.StartupTimeout <= TimeSpan.Zero || settings.StartupTimeout.TotalSeconds > int.MaxValue) throw new ArgumentOutOfRangeException(nameof(settings), "Startup timeout must be positive and representable in seconds.");
        if (settings.SplitMode is not ("layer" or "tensor" or "none")) throw new ArgumentException("Split mode must be layer, tensor, or none.");
        if (settings.DeviceList.Any(index => index < 0) || settings.DeviceList.Distinct().Count() != settings.DeviceList.Length) throw new ArgumentException("GPU device indexes must be unique and non-negative.");
    }

    private static string? ReadString(JsonObject value, string name) => value[name]?.GetValue<string?>()?.Trim() is { Length: > 0 } text ? text : null;
    private static bool ReadBool(JsonObject value, string name, bool fallback) => value[name]?.GetValue<bool?>() ?? fallback;
    private static int ReadPositive(JsonObject value, string name, int fallback) => value[name]?.GetValue<int?>() is > 0 and var number ? number : fallback;
    private static int? ReadNullablePositive(JsonObject value, string name) => value[name]?.GetValue<int?>() is > 0 and var number ? number : null;
    private static int ReadPort(JsonObject value, string name, int fallback) => value[name]?.GetValue<int?>() is >= 1 and <= 65535 and var port ? port : fallback;
    private static string ReadSplitMode(JsonObject value)
    {
        string? mode = ReadString(value, "splitMode");
        return mode is "layer" or "tensor" or "none" ? mode : "layer";
    }
    private static LocalRuntimeType ReadRuntime(JsonObject value, string name) => Enum.TryParse(ReadString(value, name), true, out LocalRuntimeType runtime) ? runtime : LocalRuntimeType.Auto;
    private static ImmutableArray<int> ReadDeviceList(JsonObject value) => value["deviceList"] is JsonArray array ? [.. array.Select(node => node?.GetValue<int>() ?? -1).Where(index => index >= 0).Distinct()] : [];
    private static ImmutableArray<string> ReadStringArray(JsonObject value, string name) => value[name] is JsonArray array ? [.. array.Select(node => node?.GetValue<string>()?.Trim()).Where(text => !string.IsNullOrWhiteSpace(text)).Select(text => text!)] : [];
}
