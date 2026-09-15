using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace EdmgStudio.Core.Audio;

public enum AudioQualificationLevel { Unavailable, DeterministicSimulation, NativeDevice }
public enum AudioQualificationStatus { Passed, Failed }

public sealed record AudioDeviceQualificationRequest(
    string DeviceId,
    AudioDeviceBackend Backend,
    int SampleRate,
    int BufferFrames,
    string DriverIdentity,
    string RuntimeIdentity);

public sealed record AudioDeviceQualificationFingerprint(string Sha256);

public sealed record AudioDeviceQualificationReceipt(
    int SchemaVersion,
    AudioDeviceQualificationFingerprint Fingerprint,
    AudioQualificationLevel Level,
    AudioQualificationStatus Status,
    DateTimeOffset QualifiedAtUtc,
    ImmutableArray<string> Checks,
    string Diagnostic)
{
    public bool IsValidFor(AudioDeviceQualificationRequest request) =>
        SchemaVersion == 1 && Fingerprint == AudioDeviceQualificationFingerprinting.Create(request);

    public bool EstablishesNativeReadiness =>
        IsSuccessful && Level == AudioQualificationLevel.NativeDevice;

    public bool IsSuccessful => Status == AudioQualificationStatus.Passed;
}

public interface IAudioDeviceQualificationProbe
{
    AudioQualificationLevel Level { get; }
    AudioDeviceQualificationReceipt Qualify(AudioDeviceQualificationRequest request);
}

public static class AudioDeviceQualificationFingerprinting
{
    public static AudioDeviceQualificationFingerprint Create(AudioDeviceQualificationRequest request)
    {
        Validate(request);
        byte[] canonical = JsonSerializer.SerializeToUtf8Bytes(new
        {
            schemaVersion = 1,
            deviceId = request.DeviceId,
            backend = request.Backend.ToString(),
            sampleRate = request.SampleRate,
            bufferFrames = request.BufferFrames,
            driverIdentity = request.DriverIdentity,
            runtimeIdentity = request.RuntimeIdentity
        });
        return new(Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant());
    }

    internal static void Validate(AudioDeviceQualificationRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.DeviceId);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.DriverIdentity);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.RuntimeIdentity);
        if (!Enum.IsDefined(request.Backend)) throw new ArgumentOutOfRangeException(nameof(request));
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(request.SampleRate);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(request.BufferFrames);
    }
}

/// <summary>A repository-controlled simulation probe. Passing it never establishes native-device readiness.</summary>
public sealed class DeterministicAudioQualificationProbe : IAudioDeviceQualificationProbe
{
    private static readonly DateTimeOffset DeterministicTimestamp = DateTimeOffset.UnixEpoch;

    public AudioQualificationLevel Level => AudioQualificationLevel.DeterministicSimulation;

    public AudioDeviceQualificationReceipt Qualify(AudioDeviceQualificationRequest request)
    {
        AudioDeviceQualificationFingerprint fingerprint = AudioDeviceQualificationFingerprinting.Create(request);
        MixerGraphPlan plan = MixerGraphBuilder.Build([
            new MixerChannel("probe", "Probe", MixerChannelKind.Track, "master", [], [], Pan: -1),
            new MixerChannel("master", "Master", MixerChannelKind.Master, null, [], [], Pan: -1)]);
        var harness = new DeterministicAudioCallbackHarness(new AudioCallbackSnapshot(1, plan, AudioAutomationSnapshot.Empty, 4));
        float[] output = new float[8];
        harness.ProcessBlock([new MixerInputBlock("probe", [1, 0, 0, 0, 0, 0, 0, 0])], output, 0, 4);
        bool impulse = output[0] == 1 && output.AsSpan(1).IndexOfAnyExcept(0) < 0;
        return new(1, fingerprint, Level,
            impulse ? AudioQualificationStatus.Passed : AudioQualificationStatus.Failed,
            DeterministicTimestamp,
            ["graph-build", "callback-block", "meter-publication", "discontinuity-reset"],
            impulse
                ? "Deterministic Core simulation passed; no native device or live callback was exercised."
                : "Deterministic Core simulation produced unexpected samples.");
    }
}