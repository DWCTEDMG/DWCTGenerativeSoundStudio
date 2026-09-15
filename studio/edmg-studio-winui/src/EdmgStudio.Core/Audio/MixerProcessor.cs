using System.Collections.Immutable;

namespace EdmgStudio.Core.Audio;

public readonly record struct MixerInputBlock(string ChannelId, float[] InterleavedStereo);
public readonly record struct MixerMeterSnapshot(string ChannelId, float PeakLeft, float PeakRight, float RmsLeft, float RmsRight);

/// <summary>A preallocated stereo DSP boundary. Construct and replace instances on the control thread.</summary>
public sealed class MixerProcessor
{
    private readonly MixerGraphPlan _plan;
    private readonly int _maximumFrames;
    private readonly Dictionary<string, int> _channelIndexes;
    private readonly float[][] _buffers;
    private readonly DelayState[] _insertDelays;
    private readonly RouteState[][] _outgoing;
    private readonly MixerMeterSnapshot[] _meters;
    private readonly bool[] _audible;
    private readonly int _masterIndex;

    public MixerProcessor(MixerGraphPlan plan, int maximumFrames)
    {
        ArgumentNullException.ThrowIfNull(plan);
        if (maximumFrames <= 0) throw new ArgumentOutOfRangeException(nameof(maximumFrames));
        _plan = plan;
        _maximumFrames = maximumFrames;
        _channelIndexes = plan.ProcessingOrder.Select((channel, index) => (channel.Id, index))
            .ToDictionary(item => item.Id, item => item.index, StringComparer.Ordinal);
        _buffers = plan.ProcessingOrder.Select(_ => new float[checked(maximumFrames * 2)]).ToArray();
        _insertDelays = plan.ProcessingOrder.Select(channel =>
            new DelayState(channel.Inserts.Where(insert => insert.Enabled).Sum(insert => insert.LatencySamples))).ToArray();
        _meters = new MixerMeterSnapshot[plan.ProcessingOrder.Length];
        _audible = plan.ProcessingOrder.Select(channel => plan.AudibleChannelIds.Contains(channel.Id)).ToArray();
        _masterIndex = Array.FindIndex(plan.ProcessingOrder.ToArray(), channel => channel.Kind == MixerChannelKind.Master);
        _outgoing = new RouteState[plan.ProcessingOrder.Length][];
        for (int index = 0; index < _outgoing.Length; index++)
        {
            string sourceId = plan.ProcessingOrder[index].Id;
            _outgoing[index] = plan.Routes.Where(route => route.SourceId == sourceId)
                .Select(route => new RouteState(route, _channelIndexes[route.DestinationId]))
                .ToArray();
        }
    }

    public int MaximumFrames => _maximumFrames;
    public long TotalLatencySamples => _plan.TotalLatencySamples;
    public ImmutableArray<string> ChannelIds => _plan.ProcessingOrder.Select(channel => channel.Id).ToImmutableArray();

    public void Reset()
    {
        foreach (float[] buffer in _buffers) Array.Clear(buffer);
        foreach (DelayState delay in _insertDelays) delay.Reset();
        foreach (RouteState[] routes in _outgoing)
            foreach (RouteState route in routes) route.Reset();
        Array.Clear(_meters);
    }

    public void ProcessBlock(ReadOnlySpan<MixerInputBlock> inputs, Span<float> interleavedStereoOutput, int frames) =>
        ProcessBlock(inputs, interleavedStereoOutput, frames, 0, AudioAutomationSnapshot.Empty);

    public void ProcessBlock(ReadOnlySpan<MixerInputBlock> inputs, Span<float> interleavedStereoOutput, int frames,
        long startSample, AudioAutomationSnapshot automation)
    {
        ArgumentNullException.ThrowIfNull(automation);
        if (frames < 0 || frames > _maximumFrames) throw new ArgumentOutOfRangeException(nameof(frames));
        ArgumentOutOfRangeException.ThrowIfNegative(startSample);
        int samples = checked(frames * 2);
        if (interleavedStereoOutput.Length < samples) throw new ArgumentException("The output buffer is too small.", nameof(interleavedStereoOutput));
        for (int index = 0; index < _buffers.Length; index++)
            Array.Clear(_buffers[index], 0, samples);

        foreach (MixerInputBlock input in inputs)
        {
            if (!_channelIndexes.TryGetValue(input.ChannelId, out int index))
                throw new ArgumentException($"Input channel '{input.ChannelId}' is not in the mixer graph.", nameof(inputs));
            if (_plan.ProcessingOrder[index].Kind != MixerChannelKind.Track)
                throw new ArgumentException($"Input channel '{input.ChannelId}' is not a track.", nameof(inputs));
            if (input.InterleavedStereo is null || input.InterleavedStereo.Length < samples)
                throw new ArgumentException($"Input channel '{input.ChannelId}' has an undersized stereo buffer.", nameof(inputs));
            input.InterleavedStereo.AsSpan(0, samples).CopyTo(_buffers[index]);
        }

        for (int index = 0; index < _buffers.Length; index++) ProcessChannel(index, frames, startSample, automation);
        _buffers[_masterIndex].AsSpan(0, samples).CopyTo(interleavedStereoOutput);
    }

    public int CopyMeterSnapshots(Span<MixerMeterSnapshot> destination)
    {
        int count = Math.Min(destination.Length, _meters.Length);
        _meters.AsSpan(0, count).CopyTo(destination);
        return count;
    }

    private void ProcessChannel(int index, int frames, long startSample, AudioAutomationSnapshot automation)
    {
        MixerChannel channel = _plan.ProcessingOrder[index];
        float[] buffer = _buffers[index];
        if (!_audible[index])
        {
            Array.Clear(buffer, 0, frames * 2);
            _meters[index] = new(channel.Id, 0, 0, 0, 0);
            return;
        }

        _insertDelays[index].ProcessInPlace(buffer, frames * 2);
        foreach (RouteState route in _outgoing[index])
            if (route.Plan.Tap == MixerTap.PreFader)
                route.Add(buffer, _buffers[route.DestinationIndex], frames, startSample,
                    route.Plan.Id.StartsWith("send:", StringComparison.Ordinal)
                        ? automation.FindSendLane(channel.Id, route.Plan.DestinationId) : null);

        AutomationLaneSnapshot? volumeLane = automation.FindLane(channel.Id, "volume");
        AutomationLaneSnapshot? panLane = automation.FindLane(channel.Id, "pan");
        float peakLeft = 0, peakRight = 0;
        double squareLeft = 0, squareRight = 0;
        for (int frame = 0; frame < frames; frame++)
        {
            long timelineSample = checked(startSample + frame);
            float gain = volumeLane is null ? channel.Gain : (float)volumeLane.Evaluate(timelineSample);
            float pan = panLane is null ? channel.Pan : Math.Clamp((float)panLane.Evaluate(timelineSample), -1, 1);
            float leftGain = gain * (pan <= 0 ? 1 : MathF.Sqrt(1 - pan));
            float rightGain = gain * (pan >= 0 ? 1 : MathF.Sqrt(1 + pan));
            int sample = frame * 2;
            float left = buffer[sample] *= leftGain;
            float right = buffer[sample + 1] *= rightGain;
            peakLeft = Math.Max(peakLeft, Math.Abs(left));
            peakRight = Math.Max(peakRight, Math.Abs(right));
            squareLeft += left * left;
            squareRight += right * right;
        }
        _meters[index] = new(channel.Id, peakLeft, peakRight,
            frames == 0 ? 0 : (float)Math.Sqrt(squareLeft / frames),
            frames == 0 ? 0 : (float)Math.Sqrt(squareRight / frames));

        foreach (RouteState route in _outgoing[index])
            if (route.Plan.Tap == MixerTap.PostFader)
                route.Add(buffer, _buffers[route.DestinationIndex], frames, startSample,
                    route.Plan.Id.StartsWith("send:", StringComparison.Ordinal)
                        ? automation.FindSendLane(channel.Id, route.Plan.DestinationId) : null);
        if (index == _masterIndex)
        {
            peakLeft = peakRight = 0;
            squareLeft = squareRight = 0;
            for (int frame = 0; frame < frames; frame++)
            {
                int sample = frame * 2;
                float left = buffer[sample], right = buffer[sample + 1];
                peakLeft = Math.Max(peakLeft, Math.Abs(left)); peakRight = Math.Max(peakRight, Math.Abs(right));
                squareLeft += left * left; squareRight += right * right;
            }
            _meters[index] = new(channel.Id, peakLeft, peakRight,
                frames == 0 ? 0 : (float)Math.Sqrt(squareLeft / frames),
                frames == 0 ? 0 : (float)Math.Sqrt(squareRight / frames));
        }
    }

    private sealed class RouteState
    {
        private readonly DelayState _delay;

        public RouteState(MixerRouteDelay plan, int destinationIndex)
        {
            Plan = plan;
            DestinationIndex = destinationIndex;
            _delay = new DelayState(checked((int)plan.DelaySamples));
        }

        public MixerRouteDelay Plan { get; }
        public int DestinationIndex { get; }

        public void Add(float[] source, float[] destination, int frames, long startSample, AutomationLaneSnapshot? automation) =>
            _delay.AddDelayed(source, destination, frames, Plan.Gain, startSample, automation);
        public void Reset() => _delay.Reset();
    }

    private sealed class DelayState
    {
        private readonly float[] _samples;
        private int _position;

        public DelayState(int frames) => _samples = new float[checked(frames * 2)];

        public void ProcessInPlace(float[] buffer, int count)
        {
            if (_samples.Length == 0) return;
            for (int sample = 0; sample < count; sample++)
            {
                float delayed = _samples[_position];
                _samples[_position] = buffer[sample];
                buffer[sample] = delayed;
                if (++_position == _samples.Length) _position = 0;
            }
        }

        public void AddDelayed(float[] source, float[] destination, int frames, float gain,
            long startSample, AutomationLaneSnapshot? automation)
        {
            for (int frame = 0; frame < frames; frame++)
            {
                float frameGain = automation is null ? gain : (float)automation.Evaluate(checked(startSample + frame));
                for (int channel = 0; channel < 2; channel++)
                {
                    int sample = frame * 2 + channel;
                    if (_samples.Length == 0)
                    {
                        destination[sample] += source[sample] * frameGain;
                        continue;
                    }
                    float delayed = _samples[_position];
                    _samples[_position] = source[sample] * frameGain;
                    destination[sample] += delayed;
                    if (++_position == _samples.Length) _position = 0;
                }
            }
        }

        public void Reset()
        {
            Array.Clear(_samples);
            _position = 0;
        }
    }
}
