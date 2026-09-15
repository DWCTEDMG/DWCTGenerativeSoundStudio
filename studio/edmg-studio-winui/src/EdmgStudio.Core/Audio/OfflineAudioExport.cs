using System.Buffers.Binary;
using System.Collections.Immutable;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public sealed record OfflineAudioLayout(AudioChannelLayout Layout, ImmutableArray<string> ChannelIds)
{
    public static OfflineAudioLayout Create(AudioChannelLayout layout) => layout switch
    {
        AudioChannelLayout.Mono => new(layout, ["M"]),
        AudioChannelLayout.Stereo => new(layout, ["L", "R"]),
        AudioChannelLayout.Surround51 => new(layout, ["L", "R", "C", "LFE", "Ls", "Rs"]),
        AudioChannelLayout.Surround71 => new(layout, ["L", "R", "C", "LFE", "Lss", "Rss", "Lrs", "Rrs"]),
        _ => throw new NotSupportedException("Object audio requires a renderer and is not supported by channel-bed export.")
    };
}

public sealed class AudioRouteMatrix
{
    private readonly float[] _gains;

    public AudioRouteMatrix(int inputChannels, int outputChannels, IReadOnlyList<float> gains)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(inputChannels);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(outputChannels);
        ArgumentNullException.ThrowIfNull(gains);
        if (gains.Count != checked(inputChannels * outputChannels) || gains.Any(value => !float.IsFinite(value)))
            throw new ArgumentException("Route gains must be a finite output-major matrix.", nameof(gains));
        InputChannels = inputChannels;
        OutputChannels = outputChannels;
        _gains = gains.ToArray();
    }

    public int InputChannels { get; }
    public int OutputChannels { get; }

    public float[] Apply(ReadOnlySpan<float> interleavedInput)
    {
        if (interleavedInput.Length % InputChannels != 0) throw new ArgumentException("Input ends with a partial frame.", nameof(interleavedInput));
        int frames = interleavedInput.Length / InputChannels;
        var output = new float[checked(frames * OutputChannels)];
        for (int frame = 0; frame < frames; frame++)
            for (int destination = 0; destination < OutputChannels; destination++)
            {
                double sum = 0;
                for (int source = 0; source < InputChannels; source++)
                    sum += interleavedInput[frame * InputChannels + source] * _gains[destination * InputChannels + source];
                output[frame * OutputChannels + destination] = (float)sum;
            }
        return output;
    }
}

public static class OfflineWaveExporter
{
    public static byte[] ExportPcm24(int sampleRate, OfflineAudioLayout layout, ReadOnlySpan<float> interleavedSamples)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(sampleRate);
        ArgumentNullException.ThrowIfNull(layout);
        int channels = layout.ChannelIds.Length;
        if (channels == 0 || interleavedSamples.Length % channels != 0) throw new ArgumentException("Audio must contain complete channel frames.", nameof(interleavedSamples));
        int dataLength = checked(interleavedSamples.Length * 3);
        var output = new byte[checked(44 + dataLength)];
        "RIFF"u8.CopyTo(output); BinaryPrimitives.WriteUInt32LittleEndian(output.AsSpan(4), (uint)(output.Length - 8));
        "WAVEfmt "u8.CopyTo(output.AsSpan(8)); BinaryPrimitives.WriteUInt32LittleEndian(output.AsSpan(16), 16);
        BinaryPrimitives.WriteUInt16LittleEndian(output.AsSpan(20), 1); BinaryPrimitives.WriteUInt16LittleEndian(output.AsSpan(22), checked((ushort)channels));
        BinaryPrimitives.WriteInt32LittleEndian(output.AsSpan(24), sampleRate); BinaryPrimitives.WriteInt32LittleEndian(output.AsSpan(28), checked(sampleRate * channels * 3));
        BinaryPrimitives.WriteUInt16LittleEndian(output.AsSpan(32), checked((ushort)(channels * 3))); BinaryPrimitives.WriteUInt16LittleEndian(output.AsSpan(34), 24);
        "data"u8.CopyTo(output.AsSpan(36)); BinaryPrimitives.WriteUInt32LittleEndian(output.AsSpan(40), (uint)dataLength);
        for (int index = 0, offset = 44; index < interleavedSamples.Length; index++, offset += 3)
        {
            float finite = float.IsFinite(interleavedSamples[index]) ? interleavedSamples[index] : throw new InvalidDataException("Audio samples must be finite.");
            int sample = (int)Math.Round(Math.Clamp(finite, -1, 1) * (finite < 0 ? 8388608d : 8388607d), MidpointRounding.AwayFromZero);
            output[offset] = (byte)sample; output[offset + 1] = (byte)(sample >> 8); output[offset + 2] = (byte)(sample >> 16);
        }
        return output;
    }
}

public static class OfflineAudioCapabilities
{
    public static bool CanPreview(AudioChannelLayout layout) => layout == AudioChannelLayout.Stereo;
    public static bool CanExportChannelBed(AudioChannelLayout layout) => layout != AudioChannelLayout.Object;
}