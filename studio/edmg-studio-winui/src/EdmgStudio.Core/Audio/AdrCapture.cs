using System.Collections.Immutable;

namespace EdmgStudio.Core.Audio;

public sealed record AdrCaptureRequest(string CueId, int SampleRate, int Channels, int MaximumFrames)
{
    public void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(CueId);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(SampleRate);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(Channels);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(MaximumFrames);
    }
}

public sealed record AdrCapturedAudio(int SampleRate, int Channels, ImmutableArray<float> InterleavedSamples, string Diagnostic)
{
    public int Frames => Channels > 0 ? InterleavedSamples.Length / Channels : 0;
}

public interface IAdrCaptureDevice
{
    bool IsHardwareAvailable { get; }
    string AvailabilityDiagnostic { get; }
    Task<AdrCapturedAudio> CaptureAsync(AdrCaptureRequest request, CancellationToken cancellationToken = default);
}

public sealed class UnavailableAdrCaptureDevice : IAdrCaptureDevice
{
    public bool IsHardwareAvailable => false;
    public string AvailabilityDiagnostic => "Production ADR hardware capture is not implemented by EdmgStudio.Core.";
    public Task<AdrCapturedAudio> CaptureAsync(AdrCaptureRequest request, CancellationToken cancellationToken = default) =>
        Task.FromException<AdrCapturedAudio>(new NotSupportedException(AvailabilityDiagnostic));
}

public sealed class DeterministicAdrCaptureDevice : IAdrCaptureDevice
{
    public bool IsHardwareAvailable => false;
    public string AvailabilityDiagnostic => "Deterministic test capture only; no production audio hardware was used.";

    public Task<AdrCapturedAudio> CaptureAsync(AdrCaptureRequest request, CancellationToken cancellationToken = default)
    {
        request.Validate();
        cancellationToken.ThrowIfCancellationRequested();
        int frames = Math.Min(request.MaximumFrames, 32);
        var samples = ImmutableArray.CreateBuilder<float>(checked(frames * request.Channels));
        for (int frame = 0; frame < frames; frame++)
            for (int channel = 0; channel < request.Channels; channel++)
                samples.Add(frame == 0 ? (channel + 1f) / request.Channels : 0);
        return Task.FromResult(new AdrCapturedAudio(request.SampleRate, request.Channels, samples.MoveToImmutable(), AvailabilityDiagnostic));
    }
}

public sealed class AdrCaptureCoordinator(IAdrCaptureDevice device)
{
    private readonly IAdrCaptureDevice _device = device ?? throw new ArgumentNullException(nameof(device));
    private int _capturing;

    public bool IsProductionHardwareAvailable => _device.IsHardwareAvailable;
    public string AvailabilityDiagnostic => _device.AvailabilityDiagnostic;

    public async Task<AdrCapturedAudio> CaptureAsync(AdrCaptureRequest request, CancellationToken cancellationToken = default)
    {
        request.Validate();
        if (Interlocked.CompareExchange(ref _capturing, 1, 0) != 0)
            throw new InvalidOperationException("An ADR capture is already active.");
        try
        {
            AdrCapturedAudio result = await _device.CaptureAsync(request, cancellationToken).ConfigureAwait(false);
            if (result.SampleRate != request.SampleRate || result.Channels != request.Channels ||
                result.InterleavedSamples.Length % request.Channels != 0 || result.Frames > request.MaximumFrames ||
                result.InterleavedSamples.Any(sample => !float.IsFinite(sample)))
                throw new InvalidDataException("The ADR capture device returned audio outside the requested contract.");
            return result;
        }
        finally { Volatile.Write(ref _capturing, 0); }
    }
}