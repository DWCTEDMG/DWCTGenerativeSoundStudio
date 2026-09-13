using System.Diagnostics;

namespace EdmgStudio.Core.Audio;

public enum TransportMode
{
    Stopped,
    Playing,
    Recording
}

public sealed record TransportLoop(bool Enabled, long StartSample, long EndSample);

public sealed record TransportState(
    string ProjectId,
    int SampleRate,
    long DurationSamples,
    long PositionSamples,
    TransportMode Mode,
    TransportLoop Loop)
{
    public double PositionSeconds => PositionSamples / (double)SampleRate;
}

public interface ITransportService
{
    event EventHandler<TransportState>? StateChanged;

    TransportState State { get; }
    void Configure(string projectId, int sampleRate, long durationSamples, long positionSamples = 0);
    void Play();
    void Record();
    void Pause();
    void Stop();
    void Seek(long positionSamples);
    void SetLoop(bool enabled, long startSample, long endSample);
}

public interface IMonotonicClock
{
    long Timestamp { get; }
    TimeSpan Elapsed(long startTimestamp, long endTimestamp);
}

public sealed class StopwatchMonotonicClock : IMonotonicClock
{
    public long Timestamp => Stopwatch.GetTimestamp();

    public TimeSpan Elapsed(long startTimestamp, long endTimestamp) =>
        Stopwatch.GetElapsedTime(startTimestamp, endTimestamp);
}

public sealed class TransportService : ITransportService
{
    public const int DefaultSampleRate = 48_000;

    private readonly object _sync = new();
    private readonly IMonotonicClock _clock;
    private TransportState _state = EmptyState;
    private long _anchorSample;
    private long _anchorTimestamp;

    public TransportService(IMonotonicClock? clock = null)
    {
        _clock = clock ?? new StopwatchMonotonicClock();
    }

    public event EventHandler<TransportState>? StateChanged;

    public TransportState State
    {
        get
        {
            TransportState snapshot;
            bool stoppedAtEnd;
            lock (_sync)
            {
                TransportMode previousMode = _state.Mode;
                snapshot = SnapshotLocked(_clock.Timestamp);
                stoppedAtEnd = previousMode != TransportMode.Stopped && snapshot.Mode == TransportMode.Stopped;
            }
            if (stoppedAtEnd)
            {
                StateChanged?.Invoke(this, snapshot);
            }
            return snapshot;
        }
    }

    public void Configure(string projectId, int sampleRate, long durationSamples, long positionSamples = 0)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(projectId);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(sampleRate);
        ArgumentOutOfRangeException.ThrowIfNegative(durationSamples);
        TransportState changed;
        lock (_sync)
        {
            long position = Math.Clamp(positionSamples, 0, durationSamples);
            changed = new TransportState(projectId.Trim(), sampleRate, durationSamples, position,
                TransportMode.Stopped, new TransportLoop(false, 0, durationSamples));
            SetStateLocked(changed);
        }
        StateChanged?.Invoke(this, changed);
    }

    public void Play() => Start(TransportMode.Playing);

    public void Record() => Start(TransportMode.Recording);

    public void Pause()
    {
        TransportState changed;
        lock (_sync)
        {
            TransportState current = SnapshotLocked(_clock.Timestamp);
            changed = current with { Mode = TransportMode.Stopped };
            SetStateLocked(changed);
        }
        StateChanged?.Invoke(this, changed);
    }

    public void Stop()
    {
        TransportState changed;
        lock (_sync)
        {
            changed = _state with { PositionSamples = 0, Mode = TransportMode.Stopped };
            SetStateLocked(changed);
        }
        StateChanged?.Invoke(this, changed);
    }

    public void Seek(long positionSamples)
    {
        TransportState changed;
        lock (_sync)
        {
            TransportState current = SnapshotLocked(_clock.Timestamp);
            changed = current with { PositionSamples = Math.Clamp(positionSamples, 0, current.DurationSamples) };
            SetStateLocked(changed);
        }
        StateChanged?.Invoke(this, changed);
    }

    public void SetLoop(bool enabled, long startSample, long endSample)
    {
        TransportState changed;
        lock (_sync)
        {
            TransportState current = SnapshotLocked(_clock.Timestamp);
            long start = Math.Clamp(startSample, 0, current.DurationSamples);
            long end = Math.Clamp(endSample, 0, current.DurationSamples);
            if (enabled && end <= start)
            {
                throw new ArgumentException("The loop end must be after the loop start.", nameof(endSample));
            }
            changed = current with { Loop = new TransportLoop(enabled, start, end) };
            SetStateLocked(changed);
        }
        StateChanged?.Invoke(this, changed);
    }

    private void Start(TransportMode mode)
    {
        TransportState changed;
        lock (_sync)
        {
            TransportState current = SnapshotLocked(_clock.Timestamp);
            long position = current.PositionSamples >= current.DurationSamples
                ? current.Loop.Enabled ? current.Loop.StartSample : 0
                : current.PositionSamples;
            changed = current with { PositionSamples = position, Mode = mode };
            SetStateLocked(changed);
        }
        StateChanged?.Invoke(this, changed);
    }

    private TransportState SnapshotLocked(long timestamp)
    {
        if (_state.Mode == TransportMode.Stopped || _state.DurationSamples == 0)
        {
            return _state;
        }

        double elapsedSamples = _clock.Elapsed(_anchorTimestamp, timestamp).TotalSeconds * _state.SampleRate;
        long position = _anchorSample + Math.Max(0, (long)Math.Floor(elapsedSamples));
        if (_state.Loop.Enabled && position >= _state.Loop.EndSample)
        {
            long loopLength = _state.Loop.EndSample - _state.Loop.StartSample;
            position = _state.Loop.StartSample + ((position - _state.Loop.StartSample) % loopLength);
        }
        else if (position >= _state.DurationSamples)
        {
            TransportState stopped = _state with
            {
                PositionSamples = _state.DurationSamples,
                Mode = TransportMode.Stopped
            };
            SetStateLocked(stopped);
            return stopped;
        }

        return _state with { PositionSamples = position };
    }

    private void SetStateLocked(TransportState state)
    {
        _state = state;
        _anchorSample = state.PositionSamples;
        _anchorTimestamp = _clock.Timestamp;
    }

    private static TransportState EmptyState { get; } = new(
        string.Empty, DefaultSampleRate, 0, 0, TransportMode.Stopped, new TransportLoop(false, 0, 0));
}
