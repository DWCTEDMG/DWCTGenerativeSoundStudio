namespace EdmgStudio.Core.Audio;

public sealed record Vst3HostCapabilities(
    Vst3CapabilityState State,
    bool CanInstantiate,
    bool CanNegotiateAudioBuses,
    bool CanProcessAudio,
    bool CanRestoreState,
    bool CanReportLatency,
    bool IsCrashIsolated,
    string Diagnostic)
{
    public static Vst3HostCapabilities Unavailable(string diagnostic) =>
        new(Vst3CapabilityState.Unavailable, false, false, false, false, false, false, diagnostic);

    public static Vst3HostCapabilities ScannerOnly(string diagnostic) =>
        new(Vst3CapabilityState.ScannerReady, false, false, false, false, false, true, diagnostic);
}

public sealed record Vst3InstanceRequest(string InstanceId, string ModulePath, string PluginId, int SampleRate, int MaximumFrames);
public sealed record Vst3InstanceStatus(string InstanceId, bool Active, int ReportedLatencySamples, string? Diagnostic);

public interface IVst3HostSession : IAsyncDisposable
{
    Vst3HostCapabilities Capabilities { get; }
    ValueTask<Vst3InstanceStatus> CreateInstanceAsync(Vst3InstanceRequest request, CancellationToken cancellationToken = default);
    ValueTask<Vst3InstanceStatus> SetStateAsync(string instanceId, ReadOnlyMemory<byte> state, CancellationToken cancellationToken = default);
    ValueTask RemoveInstanceAsync(string instanceId, CancellationToken cancellationToken = default);
}

public sealed class UnavailableVst3HostSession : IVst3HostSession
{
    public Vst3HostCapabilities Capabilities { get; } = Vst3HostCapabilities.Unavailable(
        "No native VST3 SDK host is installed. Discovery and audio processing are disabled.");

    public ValueTask<Vst3InstanceStatus> CreateInstanceAsync(Vst3InstanceRequest request, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(new Vst3InstanceStatus(request.InstanceId, false, 0, Capabilities.Diagnostic));
    public ValueTask<Vst3InstanceStatus> SetStateAsync(string instanceId, ReadOnlyMemory<byte> state, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(new Vst3InstanceStatus(instanceId, false, 0, Capabilities.Diagnostic));
    public ValueTask RemoveInstanceAsync(string instanceId, CancellationToken cancellationToken = default) => ValueTask.CompletedTask;
    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
