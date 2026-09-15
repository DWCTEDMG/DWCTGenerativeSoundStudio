namespace EdmgStudio.Core.Audio;

public readonly record struct AudioPlaybackPosition(long Samples, bool RequiresSeek);

/// <summary>Tracks loop crossings independently of the device's drift tolerance.</summary>
public sealed class AudioPlaybackCursor
{
    private long? _loopIteration;

    public AudioPlaybackPosition Advance(
        TransportState state, long anchorMilliseconds, long nowMilliseconds, bool transportChanged = false)
    {
        long elapsed = state.Mode == TransportMode.Stopped ? 0 : Math.Max(0, nowMilliseconds - anchorMilliseconds);
        // Int128 avoids overflow before clamping long-running transport positions.
        Int128 position = state.PositionSamples + (Int128)elapsed * state.SampleRate / 1000;
        long iteration = 0;
        if (state.Mode != TransportMode.Stopped && state.Loop.Enabled && position >= state.Loop.EndSample)
        {
            long length = state.Loop.EndSample - state.Loop.StartSample;
            if (length <= 0)
            {
                throw new ArgumentException("The loop end must be after its start.", nameof(state));
            }
            iteration = checked((long)((position - state.Loop.StartSample) / length));
            position = state.Loop.StartSample + (position - state.Loop.StartSample) % length;
        }

        bool seek = transportChanged || _loopIteration is null || _loopIteration != iteration;
        _loopIteration = iteration;
        return new AudioPlaybackPosition((long)Int128.Clamp(position, 0, state.DurationSamples), seek);
    }
}
