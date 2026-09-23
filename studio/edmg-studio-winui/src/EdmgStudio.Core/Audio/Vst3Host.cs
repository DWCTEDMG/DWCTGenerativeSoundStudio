using System.Collections.Immutable;

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

    public static Vst3HostCapabilities NativeWorker(string diagnostic) =>
        new(Vst3CapabilityState.HostReady, true, true, true, true, true, true, diagnostic);
}

public enum Vst3WorkerHealth { Starting, Ready, Failed, TimedOut, Exited, Disposed }
public sealed record Vst3ParameterDescriptor(
    uint Id,
    string Name,
    double NormalizedValue,
    double DefaultNormalizedValue = 0,
    bool IsReadOnly = false,
    string Units = "",
    string DisplayValue = "");
public sealed record Vst3InstanceRequest(string InstanceId, string ModulePath, string PluginId, int SampleRate, int MaximumFrames);
public enum Vst3MidiEventKind { NoteOn, NoteOff }
public sealed record Vst3MidiEvent(Vst3MidiEventKind Kind, int Channel, int Note, double Velocity, int SampleOffset);
public sealed record Vst3InstanceStatus(
    string InstanceId, bool Active, int ReportedLatencySamples, string? Diagnostic,
    int AudioInputs = 0, int AudioOutputs = 0,
    ImmutableArray<Vst3ParameterDescriptor> Parameters = default,
    Vst3WorkerHealth Health = Vst3WorkerHealth.Starting);

public interface IVst3InsertProcessor : IDisposable
{
    string InstanceId { get; }
    string ModulePath { get; }
    string PluginId { get; }
    int SampleRate { get; }
    int MaximumFrames { get; }
    int ReportedLatencySamples { get; }
    Vst3WorkerHealth Health { get; }
    string? Diagnostic { get; }
    bool TryProcessInPlace(Span<float> interleavedStereo, int frames);
    void Reset();
}

public interface IVst3HostSession : IAsyncDisposable
{
    Vst3HostCapabilities Capabilities { get; }
    ValueTask<Vst3InstanceStatus> CreateInstanceAsync(Vst3InstanceRequest request, CancellationToken cancellationToken = default);
    ValueTask<Vst3InstanceStatus> SetStateAsync(string instanceId, ReadOnlyMemory<byte> state, CancellationToken cancellationToken = default);
    ValueTask<ReadOnlyMemory<byte>> GetStateAsync(string instanceId, CancellationToken cancellationToken = default);
    ValueTask<Vst3InstanceStatus> SetParameterAsync(string instanceId, uint parameterId, double normalizedValue, CancellationToken cancellationToken = default);
    ValueTask QueueMidiEventsAsync(string instanceId, IReadOnlyList<Vst3MidiEvent> events, CancellationToken cancellationToken = default);
    bool TryGetProcessor(string instanceId, out IVst3InsertProcessor? processor);
    ValueTask RemoveInstanceAsync(string instanceId, CancellationToken cancellationToken = default);
}

public sealed class UnavailableVst3HostSession : IVst3HostSession
{
    public Vst3HostCapabilities Capabilities { get; } = Vst3HostCapabilities.Unavailable(
        "No native VST3 SDK host is installed. Discovery and audio processing are disabled.");

    public ValueTask<Vst3InstanceStatus> CreateInstanceAsync(Vst3InstanceRequest request, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(new Vst3InstanceStatus(request.InstanceId, false, 0, Capabilities.Diagnostic));
    public ValueTask<Vst3InstanceStatus> SetStateAsync(string instanceId, ReadOnlyMemory<byte> state, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(new Vst3InstanceStatus(instanceId, false, 0, Capabilities.Diagnostic, Health: Vst3WorkerHealth.Failed));
    public ValueTask<ReadOnlyMemory<byte>> GetStateAsync(string instanceId, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(ReadOnlyMemory<byte>.Empty);
    public ValueTask<Vst3InstanceStatus> SetParameterAsync(string instanceId, uint parameterId, double normalizedValue, CancellationToken cancellationToken = default) =>
        ValueTask.FromResult(new Vst3InstanceStatus(instanceId, false, 0, Capabilities.Diagnostic, Health: Vst3WorkerHealth.Failed));
    public ValueTask QueueMidiEventsAsync(string instanceId, IReadOnlyList<Vst3MidiEvent> events, CancellationToken cancellationToken = default) =>
        ValueTask.FromException(new InvalidOperationException(Capabilities.Diagnostic));
    public bool TryGetProcessor(string instanceId, out IVst3InsertProcessor? processor) { processor = null; return false; }
    public ValueTask RemoveInstanceAsync(string instanceId, CancellationToken cancellationToken = default) => ValueTask.CompletedTask;
    public ValueTask DisposeAsync() => ValueTask.CompletedTask;
}
