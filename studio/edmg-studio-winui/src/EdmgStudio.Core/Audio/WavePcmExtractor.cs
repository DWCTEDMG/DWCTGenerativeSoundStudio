using System.Buffers.Binary;

namespace EdmgStudio.Core.Audio;

public sealed record ExtractedWaveAudio(int SampleRate, int Channels, float[] InterleavedSamples)
{
    public int FrameCount => InterleavedSamples.Length / Channels;

    public float[] DownmixToMono()
    {
        var mono = new float[FrameCount];
        for (int frame = 0; frame < mono.Length; frame++)
        {
            double sum = 0;
            for (int channel = 0; channel < Channels; channel++)
                sum += InterleavedSamples[frame * Channels + channel];
            mono[frame] = (float)(sum / Channels);
        }
        return mono;
    }
}

public sealed class WavePcmExtractor
{
    public const long DefaultMaximumDataBytes = 256L * 1024 * 1024;

    public async Task<ExtractedWaveAudio> ExtractAsync(Stream source, long maximumDataBytes = DefaultMaximumDataBytes,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (!source.CanRead) throw new ArgumentException("The WAVE source must be readable.", nameof(source));
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(maximumDataBytes);

        byte[] header = new byte[12];
        await ReadExactlyAsync(source, header, cancellationToken).ConfigureAwait(false);
        if (!header.AsSpan(0, 4).SequenceEqual("RIFF"u8) || !header.AsSpan(8, 4).SequenceEqual("WAVE"u8))
            throw new InvalidDataException("Only little-endian RIFF/WAVE files are supported.");

        WaveFormat? format = null;
        byte[]? data = null;
        var chunkHeader = new byte[8];
        while (data is null)
        {
            await ReadExactlyAsync(source, chunkHeader, cancellationToken).ConfigureAwait(false);
            uint chunkLength = BinaryPrimitives.ReadUInt32LittleEndian(chunkHeader.AsSpan(4));
            if (chunkHeader.AsSpan(0, 4).SequenceEqual("fmt "u8))
            {
                if (chunkLength < 16 || chunkLength > 64 * 1024) throw new InvalidDataException("The WAVE format chunk is invalid.");
                byte[] bytes = new byte[chunkLength];
                await ReadExactlyAsync(source, bytes, cancellationToken).ConfigureAwait(false);
                format = ParseFormat(bytes);
            }
            else if (chunkHeader.AsSpan(0, 4).SequenceEqual("data"u8))
            {
                if (format is null) throw new InvalidDataException("The WAVE format chunk must precede audio data.");
                if (chunkLength > maximumDataBytes || chunkLength > int.MaxValue)
                    throw new InvalidDataException("The WAVE data chunk exceeds the configured extraction limit.");
                data = new byte[chunkLength];
                await ReadExactlyAsync(source, data, cancellationToken).ConfigureAwait(false);
            }
            else
            {
                await SkipExactlyAsync(source, chunkLength, cancellationToken).ConfigureAwait(false);
            }
            if ((chunkLength & 1) != 0) await SkipExactlyAsync(source, 1, cancellationToken).ConfigureAwait(false);
        }

        WaveFormat value = format!;
        if (data.Length % value.BlockAlign != 0) throw new InvalidDataException("The WAVE data chunk ends with a partial sample frame.");
        int sampleCount = data.Length / value.BytesPerSample;
        var samples = new float[sampleCount];
        for (int index = 0, offset = 0; index < samples.Length; index++, offset += value.BytesPerSample)
        {
            cancellationToken.ThrowIfCancellationRequested();
            samples[index] = value.FormatTag switch
            {
                1 when value.BitsPerSample == 16 => BinaryPrimitives.ReadInt16LittleEndian(data.AsSpan(offset, 2)) / 32768f,
                1 when value.BitsPerSample == 24 => ReadInt24(data, offset) / 8388608f,
                1 when value.BitsPerSample == 32 => BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(offset, 4)) / 2147483648f,
                3 when value.BitsPerSample == 32 => BitConverter.Int32BitsToSingle(BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(offset, 4))),
                _ => throw new InvalidDataException("Unsupported WAVE sample encoding.")
            };
            if (!float.IsFinite(samples[index])) throw new InvalidDataException("IEEE float WAVE samples must be finite.");
        }
        return new(value.SampleRate, value.Channels, samples);
    }

    private static WaveFormat ParseFormat(ReadOnlySpan<byte> bytes)
    {
        ushort tag = BinaryPrimitives.ReadUInt16LittleEndian(bytes);
        ushort channels = BinaryPrimitives.ReadUInt16LittleEndian(bytes[2..]);
        int sampleRate = BinaryPrimitives.ReadInt32LittleEndian(bytes[4..]);
        ushort blockAlign = BinaryPrimitives.ReadUInt16LittleEndian(bytes[12..]);
        ushort bits = BinaryPrimitives.ReadUInt16LittleEndian(bytes[14..]);
        if (tag is not (1 or 3) || channels == 0 || sampleRate <= 0 ||
            tag == 1 && bits is not (16 or 24 or 32) || tag == 3 && bits != 32)
            throw new InvalidDataException("Only PCM16/24/32 and IEEE float32 WAVE audio is supported.");
        int bytesPerSample = bits / 8;
        if (blockAlign != channels * bytesPerSample) throw new InvalidDataException("The WAVE block alignment is inconsistent with its format.");
        return new(tag, channels, sampleRate, blockAlign, bits, bytesPerSample);
    }

    private static int ReadInt24(byte[] bytes, int offset)
    {
        int value = bytes[offset] | bytes[offset + 1] << 8 | bytes[offset + 2] << 16;
        return (value & 0x800000) == 0 ? value : value | unchecked((int)0xff000000);
    }

    private static async Task ReadExactlyAsync(Stream source, Memory<byte> destination, CancellationToken cancellationToken)
    {
        int read = 0;
        while (read < destination.Length)
        {
            int count = await source.ReadAsync(destination[read..], cancellationToken).ConfigureAwait(false);
            if (count == 0) throw new EndOfStreamException("The RIFF/WAVE file is truncated.");
            read += count;
        }
    }

    private static async Task SkipExactlyAsync(Stream source, long count, CancellationToken cancellationToken)
    {
        byte[] buffer = new byte[8192];
        while (count > 0)
        {
            int requested = (int)Math.Min(count, buffer.Length);
            await ReadExactlyAsync(source, buffer.AsMemory(0, requested), cancellationToken).ConfigureAwait(false);
            count -= requested;
        }
    }

    private sealed record WaveFormat(ushort FormatTag, int Channels, int SampleRate, int BlockAlign, int BitsPerSample, int BytesPerSample);
}
