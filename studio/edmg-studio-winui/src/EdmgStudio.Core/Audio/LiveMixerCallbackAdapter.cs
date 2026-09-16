namespace EdmgStudio.Core.Audio;

public enum LiveMixerCallbackState
{
    Ready,
    Failed
}

public readonly record struct LiveMixerQuantumResult(
    AudioCallbackResult Callback,
    LiveMixerCallbackState State,
    bool MeterSnapshotPublished);

/// <summary>
/// Allocation-free adapter between a native audio callback and the deterministic Core mixer.
/// Native hosts must supply decoded, preallocated stereo track buffers and consume the output
/// synchronously. Meter records are copied on the control/UI thread through TryCopyMeters.
/// </summary>
public sealed class LiveMixerCallbackAdapter
{
    private DeterministicAudioCallbackHarness _harness;
    private readonly MeterSlot[] _meterSlots;
    private readonly int _meterIntervalSamples;
    private long _nextMeterSample;
    private long _publishedSequence;
    private int _writeSlot;
    private Exception? _failure;

    public LiveMixerCallbackAdapter(AudioCallbackSnapshot snapshot, int meterIntervalSamples)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(meterIntervalSamples);
        _harness = new(snapshot);
        _meterIntervalSamples = meterIntervalSamples;
        int meterCount = snapshot.Mixer.ProcessingOrder.Length;
        _meterSlots = [new(meterCount), new(meterCount), new(meterCount)];
    }

    public LiveMixerCallbackState State => Volatile.Read(ref _failure) is null
        ? LiveMixerCallbackState.Ready
        : LiveMixerCallbackState.Failed;

    public Exception? Failure => Volatile.Read(ref _failure);

    public void Publish(AudioCallbackSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        if (snapshot.Mixer.ProcessingOrder.Length > _meterSlots[0].Meters.Length)
        {
            throw new ArgumentException("A published snapshot cannot exceed the adapter's preallocated meter capacity.", nameof(snapshot));
        }
        Volatile.Read(ref _harness).Publish(snapshot);
    }

    public LiveMixerQuantumResult ProcessQuantum(
        ReadOnlySpan<MixerInputBlock> inputs,
        Span<float> interleavedStereoOutput,
        long startSample,
        int frames,
        bool transportDiscontinuity = false)
    {
        if (Volatile.Read(ref _failure) is not null)
        {
            Silence(interleavedStereoOutput, frames);
            return new(default, LiveMixerCallbackState.Failed, false);
        }

        try
        {
            DeterministicAudioCallbackHarness harness = Volatile.Read(ref _harness);
            AudioCallbackResult result = harness.ProcessBlock(
                inputs, interleavedStereoOutput, startSample, frames, transportDiscontinuity);
            bool publishMeters = checked(startSample + frames) >= _nextMeterSample;
            if (publishMeters)
            {
                PublishMeters(harness, result);
                _nextMeterSample = checked(startSample + _meterIntervalSamples);
            }
            return new(result, LiveMixerCallbackState.Ready, publishMeters);
        }
        catch (Exception exception)
        {
            Silence(interleavedStereoOutput, frames);
            Volatile.Write(ref _failure, exception);
            return new(default, LiveMixerCallbackState.Failed, false);
        }
    }

    public bool TryCopyMeters(
        Span<MixerMeterSnapshot> destination,
        out int count,
        out long samplePosition,
        ref long lastSequence)
    {
        for (int attempt = 0; attempt < _meterSlots.Length; attempt++)
        {
            long sequence = Volatile.Read(ref _publishedSequence);
            if (sequence == 0 || sequence == lastSequence)
            {
                count = 0;
                samplePosition = 0;
                return false;
            }

            MeterSlot slot = _meterSlots[(int)((sequence - 1) % _meterSlots.Length)];
            long before = Volatile.Read(ref slot.Version);
            if ((before & 1) != 0)
            {
                continue;
            }
            int copied = Math.Min(destination.Length, slot.Count);
            slot.Meters.AsSpan(0, copied).CopyTo(destination);
            long position = slot.SamplePosition;
            long after = Volatile.Read(ref slot.Version);
            if (before != after || (after & 1) != 0 || sequence != Volatile.Read(ref _publishedSequence))
            {
                continue;
            }

            count = copied;
            samplePosition = position;
            lastSequence = sequence;
            return true;
        }

        count = 0;
        samplePosition = 0;
        return false;
    }

    public void Recover(AudioCallbackSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        if (snapshot.Mixer.ProcessingOrder.Length > _meterSlots[0].Meters.Length)
        {
            throw new ArgumentException("Recovery cannot exceed the adapter's preallocated meter capacity.", nameof(snapshot));
        }
        var replacement = new DeterministicAudioCallbackHarness(snapshot);
        Volatile.Write(ref _harness, replacement);
        _nextMeterSample = 0;
        Volatile.Write(ref _failure, null);
    }

    private void PublishMeters(DeterministicAudioCallbackHarness harness, AudioCallbackResult result)
    {
        MeterSlot slot = _meterSlots[_writeSlot];
        Interlocked.Increment(ref slot.Version);
        slot.Count = harness.CopyMeterSnapshots(slot.Meters);
        slot.SamplePosition = result.StartSample;
        Interlocked.Increment(ref slot.Version);
        long sequence = Interlocked.Increment(ref _publishedSequence);
        _writeSlot = (int)(sequence % _meterSlots.Length);
    }

    private static void Silence(Span<float> output, int frames)
    {
        if (frames <= 0)
        {
            return;
        }
        int samples = Math.Min(output.Length, checked(frames * 2));
        output[..samples].Clear();
    }

    private sealed class MeterSlot(int capacity)
    {
        public readonly MixerMeterSnapshot[] Meters = new MixerMeterSnapshot[capacity];
        public long Version;
        public long SamplePosition;
        public int Count;
    }
}
