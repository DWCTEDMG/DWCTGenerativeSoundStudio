namespace EdmgStudio.Core.Audio;

public sealed record AudioCallbackSnapshot(
    long Revision,
    MixerGraphPlan Mixer,
    AudioAutomationSnapshot Automation,
    int MaximumFrames);

public readonly record struct AudioCallbackResult(
    long Revision,
    long StartSample,
    int Frames,
    bool StateReset,
    int MeterCount);

/// <summary>Deterministic callback boundary for offline qualification; it does not open or qualify an audio device.</summary>
public sealed class DeterministicAudioCallbackHarness
{
    private PublishedState _published;
    private PublishedState? _active;
    private long _expectedSample = -1;

    public DeterministicAudioCallbackHarness(AudioCallbackSnapshot initialSnapshot)
    {
        Validate(initialSnapshot);
        _published = new PublishedState(initialSnapshot);
    }

    public AudioCallbackSnapshot Published => Volatile.Read(ref _published).Snapshot;

    public void Publish(AudioCallbackSnapshot snapshot)
    {
        Validate(snapshot);
        var replacement = new PublishedState(snapshot);
        while (true)
        {
            PublishedState current = Volatile.Read(ref _published);
            if (snapshot.Revision <= current.Snapshot.Revision)
                throw new ArgumentException("Audio callback snapshot revisions must increase.", nameof(snapshot));
            if (ReferenceEquals(Interlocked.CompareExchange(ref _published, replacement, current), current)) return;
        }
    }

    public AudioCallbackResult ProcessBlock(ReadOnlySpan<MixerInputBlock> inputs, Span<float> output,
        long startSample, int frames, bool transportDiscontinuity = false)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(startSample);
        PublishedState published = Volatile.Read(ref _published);
        bool graphChanged = !ReferenceEquals(_active, published);
        if (graphChanged) _active = published;

        bool reset = graphChanged || transportDiscontinuity || (_expectedSample >= 0 && startSample != _expectedSample);
        if (reset) published.Processor.Reset();
        published.Processor.ProcessBlock(inputs, output, frames, startSample, published.Snapshot.Automation);
        _expectedSample = checked(startSample + frames);
        int meterCount = published.Processor.CopyMeterSnapshots(published.Meters);
        return new(published.Snapshot.Revision, startSample, frames, reset, meterCount);
    }

    public int CopyMeterSnapshots(Span<MixerMeterSnapshot> destination)
    {
        PublishedState? active = _active;
        int count = Math.Min(destination.Length, active?.Snapshot.Mixer.ProcessingOrder.Length ?? 0);
        if (active is not null) active.Meters.AsSpan(0, count).CopyTo(destination);
        return count;
    }

    private sealed class PublishedState
    {
        public PublishedState(AudioCallbackSnapshot snapshot)
        {
            Snapshot = snapshot;
            Processor = new MixerProcessor(snapshot.Mixer, snapshot.MaximumFrames);
            Meters = new MixerMeterSnapshot[snapshot.Mixer.ProcessingOrder.Length];
        }

        public AudioCallbackSnapshot Snapshot { get; }
        public MixerProcessor Processor { get; }
        public MixerMeterSnapshot[] Meters { get; }
    }

    private static void Validate(AudioCallbackSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ArgumentNullException.ThrowIfNull(snapshot.Mixer);
        ArgumentNullException.ThrowIfNull(snapshot.Automation);
        ArgumentOutOfRangeException.ThrowIfNegative(snapshot.Revision);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(snapshot.MaximumFrames);
    }
}
