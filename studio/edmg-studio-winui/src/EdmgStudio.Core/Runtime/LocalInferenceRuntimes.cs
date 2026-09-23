using System.Collections.Immutable;
using System.Globalization;

namespace EdmgStudio.Core.Runtime;

public abstract class WslInferenceRuntime : ILocalInferenceRuntime
{
    private readonly IWslCommandRunner _runner;
    private readonly string _executable;
    private readonly string _logDirectory;

    protected WslInferenceRuntime(IWslCommandRunner runner, string executable, string logDirectory)
    {
        _runner = runner;
        _executable = executable;
        _logDirectory = logDirectory;
    }

    public abstract LocalRuntimeType RuntimeType { get; }

    public async Task<bool> IsInstalledAsync(CancellationToken cancellationToken = default)
    {
        CommandResult result = await _runner.RunAsync(
            $"test -x {QuoteExecutable(_executable)} || command -v -- {WslCommandRunner.ShellQuote(_executable)} >/dev/null 2>&1",
            TimeSpan.FromSeconds(10),
            cancellationToken).ConfigureAwait(false);
        return result.Succeeded;
    }

    public async Task<RuntimeLaunchResult> StartAsync(ResolvedRuntimeProfile profile, CancellationToken cancellationToken = default)
    {
        if (profile.RuntimeType != RuntimeType) throw new ArgumentException($"Profile runtime {profile.RuntimeType} cannot be launched by {RuntimeType}.", nameof(profile));
        string logPath = $"{_logDirectory.TrimEnd('/')}/{GetLogPrefix()}-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}.log";
        DetachedCommandResult launched = await _runner.StartDetachedAsync(BuildCommand(_executable, profile), logPath, TimeSpan.FromSeconds(15), cancellationToken).ConfigureAwait(false);
        return new RuntimeLaunchResult(
            RuntimeType,
            profile.Model,
            new Uri($"http://127.0.0.1:{profile.Port}/"),
            new RuntimeOwnership(true, null, launched.WslProcessId, DateTimeOffset.UtcNow),
            launched.LogPath);
    }

    public async Task StopAsync(RuntimeOwnership ownership, CancellationToken cancellationToken = default)
    {
        if (!ownership.StartedByStudio || ownership.WslProcessId is not > 0) return;
        int pid = ownership.WslProcessId.Value;
        CommandResult result = await _runner.RunAsync(
            $"if kill -0 {pid.ToString(CultureInfo.InvariantCulture)} 2>/dev/null; then kill -TERM {pid.ToString(CultureInfo.InvariantCulture)}; for i in $(seq 1 30); do kill -0 {pid.ToString(CultureInfo.InvariantCulture)} 2>/dev/null || exit 0; sleep 0.1; done; kill -KILL {pid.ToString(CultureInfo.InvariantCulture)}; fi",
            TimeSpan.FromSeconds(8),
            cancellationToken).ConfigureAwait(false);
        if (!result.Succeeded) throw new InvalidOperationException($"Unable to stop owned {RuntimeType} process {pid}: {result.StandardError.Trim()}");
    }

    protected abstract string BuildCommand(string executable, ResolvedRuntimeProfile profile);
    protected abstract string GetLogPrefix();

    protected static string QuoteExecutable(string executable)
    {
        if (executable.StartsWith("~/", StringComparison.Ordinal))
        {
            return $"\"$HOME/{executable[2..].Replace("\"", "\\\"", StringComparison.Ordinal)}\"";
        }
        return WslCommandRunner.ShellQuote(executable);
    }

    protected static string BuildCudaPrefix(ResolvedRuntimeProfile profile)
    {
        if (!profile.Cuda || profile.GpuDevices.IsDefaultOrEmpty) return string.Empty;
        return $"env CUDA_VISIBLE_DEVICES={WslCommandRunner.ShellQuote(string.Join(',', profile.GpuDevices))} ";
    }

    protected static string JoinArguments(IEnumerable<string> arguments) => string.Join(' ', arguments.Select(WslCommandRunner.ShellQuote));
}

public sealed class LlamaCppRuntime : WslInferenceRuntime
{
    public LlamaCppRuntime(IWslCommandRunner runner, string executable, string logDirectory = "/tmp/edmg-studio/runtime")
        : base(runner, executable, logDirectory)
    {
    }

    public override LocalRuntimeType RuntimeType => LocalRuntimeType.LlamaCpp;

    public static string CreateCommand(string executable, ResolvedRuntimeProfile profile)
    {
        var arguments = new List<string>
        {
            "serve", "-hf", profile.Model, "-ngl", profile.Cuda ? profile.GpuLayers : "0",
            "--split-mode", profile.MultiGpu ? profile.SplitMode : "none",
            "--fit", profile.Fit ? "on" : "off", "-c", profile.ContextSize.ToString(CultureInfo.InvariantCulture),
            "--host", "127.0.0.1", "--port", profile.Port.ToString(CultureInfo.InvariantCulture)
        };
        if (profile.MultiGpu && !string.IsNullOrWhiteSpace(profile.TensorSplit))
        {
            arguments.Add("--tensor-split");
            arguments.Add(profile.TensorSplit);
        }
        arguments.AddRange(profile.AdditionalArguments);
        return $"{BuildCudaPrefix(profile)}{QuoteExecutable(executable)} {JoinArguments(arguments)}";
    }

    protected override string BuildCommand(string executable, ResolvedRuntimeProfile profile) => CreateCommand(executable, profile);
    protected override string GetLogPrefix() => "llama-cpp";
}

public sealed class TensorRtLlmRuntime : WslInferenceRuntime
{
    public TensorRtLlmRuntime(IWslCommandRunner runner, string executable, string logDirectory = "/tmp/edmg-studio/runtime")
        : base(runner, executable, logDirectory)
    {
    }

    public override LocalRuntimeType RuntimeType => LocalRuntimeType.TensorRtLlm;

    public static string CreateCommand(string executable, ResolvedRuntimeProfile profile)
    {
        if (profile.ModelFormat.Equals("gguf", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("GGUF models cannot be launched by TensorRT-LLM.");
        var arguments = new List<string>
        {
            profile.Model,
            "--tp_size", profile.TensorParallelSize.ToString(CultureInfo.InvariantCulture),
            "--host", "127.0.0.1", "--port", profile.Port.ToString(CultureInfo.InvariantCulture)
        };
        arguments.AddRange(profile.AdditionalArguments);
        return $"{BuildCudaPrefix(profile)}{QuoteExecutable(executable)} {JoinArguments(arguments)}";
    }

    protected override string BuildCommand(string executable, ResolvedRuntimeProfile profile) => CreateCommand(executable, profile);
    protected override string GetLogPrefix() => "tensorrt-llm";
}
