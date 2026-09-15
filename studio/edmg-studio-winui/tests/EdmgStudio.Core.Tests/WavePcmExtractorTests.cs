using System.Buffers.Binary;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class WavePcmExtractorTests
{
    [DataTestMethod]
    [DataRow((ushort)1, (ushort)16)]
    [DataRow((ushort)1, (ushort)24)]
    [DataRow((ushort)1, (ushort)32)]
    [DataRow((ushort)3, (ushort)32)]
    public async Task ExtractsSupportedSamplesAndDownmixes(ushort format, ushort bits)
    {
        byte[] wave = Wave(format, bits, 2, [-1f, .5f, 1f, -.5f]);
        ExtractedWaveAudio audio = await new WavePcmExtractor().ExtractAsync(new MemoryStream(wave));
        Assert.AreEqual(48_000, audio.SampleRate);
        Assert.AreEqual(2, audio.Channels);
        Assert.AreEqual(2, audio.FrameCount);
        Assert.AreEqual(-.25f, audio.DownmixToMono()[0], bits == 16 ? 1e-4 : 1e-6);
        Assert.AreEqual(.25f, audio.DownmixToMono()[1], bits == 16 ? 1e-4 : 1e-6);
    }

    [TestMethod]
    public async Task RejectsUnsupportedMalformedTruncatedAndBoundedData()
    {
        byte[] unsupported = Wave(1, 16, 1, [0]);
        BinaryPrimitives.WriteUInt16LittleEndian(unsupported.AsSpan(34, 2), 8);
        await Assert.ThrowsExactlyAsync<InvalidDataException>(() => new WavePcmExtractor().ExtractAsync(new MemoryStream(unsupported)));
        byte[] partialFrame = Wave(1, 16, 2, [0, 0]);
        BinaryPrimitives.WriteUInt32LittleEndian(partialFrame.AsSpan(40, 4), 3);
        Array.Resize(ref partialFrame, 48);
        await Assert.ThrowsExactlyAsync<InvalidDataException>(() => new WavePcmExtractor().ExtractAsync(new MemoryStream(partialFrame)));
        byte[] truncated = Wave(1, 24, 1, [0, 1]);
        Array.Resize(ref truncated, truncated.Length - 1);
        await Assert.ThrowsExactlyAsync<EndOfStreamException>(() => new WavePcmExtractor().ExtractAsync(new MemoryStream(truncated)));
        await Assert.ThrowsExactlyAsync<InvalidDataException>(() => new WavePcmExtractor().ExtractAsync(new MemoryStream(Wave(1, 16, 1, [0, 1])), 2));
    }

    [TestMethod]
    public async Task HonorsCancellationAndAlignmentUsesDownmixedSamples()
    {
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        await Assert.ThrowsAsync<OperationCanceledException>(() => new WavePcmExtractor().ExtractAsync(new MemoryStream(Wave(1, 16, 1, [0])), cancellationToken: cancelled.Token));

        float[] reference = [0, 0, 0, 0, 1, 1, .2f, .2f, -.4f, -.4f, .8f, .8f, -.2f, -.2f, 0, 0];
        float[] candidate = [0, 0, 0, 0, 0, 0, 1, 1, .2f, .2f, -.4f, -.4f, .8f, .8f, -.2f, -.2f];
        AlignmentResult result = await new WaveAlignmentService().AlignAsync(
            new MemoryStream(Wave(3, 32, 2, reference)), new MemoryStream(Wave(3, 32, 2, candidate)),
            SyncMethod.WaveformCorrelation, 3, .8);
        Assert.AreEqual(1L, result.OffsetSamples);
        Assert.IsTrue(result.Acceptable);
    }

    [TestMethod]
    public async Task AlignmentRejectsSampleRateMismatch()
    {
        byte[] first = Wave(1, 16, 1, [0, 1, 0]);
        byte[] second = Wave(1, 16, 1, [0, 1, 0]);
        BinaryPrimitives.WriteInt32LittleEndian(second.AsSpan(24, 4), 44_100);
        await Assert.ThrowsExactlyAsync<InvalidDataException>(() => new WaveAlignmentService().AlignAsync(
            new MemoryStream(first), new MemoryStream(second), SyncMethod.Clap));
    }

    internal static byte[] Wave(ushort format, ushort bits, ushort channels, IReadOnlyList<float> samples)
    {
        int bytesPerSample = bits / 8;
        int dataLength = samples.Count * bytesPerSample;
        byte[] bytes = new byte[44 + dataLength];
        "RIFF"u8.CopyTo(bytes); BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4), (uint)(bytes.Length - 8));
        "WAVEfmt "u8.CopyTo(bytes.AsSpan(8)); BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(16), 16);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(20), format); BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(22), channels);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(24), 48_000);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(28), 48_000 * channels * bytesPerSample);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(32), (ushort)(channels * bytesPerSample)); BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(34), bits);
        "data"u8.CopyTo(bytes.AsSpan(36)); BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(40), (uint)dataLength);
        for (int index = 0, offset = 44; index < samples.Count; index++, offset += bytesPerSample)
        {
            float value = samples[index];
            if (format == 3) BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(offset), BitConverter.SingleToInt32Bits(value));
            else if (bits == 16) BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(offset), (short)Math.Clamp(Math.Round(value * 32768), short.MinValue, short.MaxValue));
            else if (bits == 24) { int sample = (int)Math.Clamp(Math.Round(value * 8388608), -8388608, 8388607); bytes[offset] = (byte)sample; bytes[offset + 1] = (byte)(sample >> 8); bytes[offset + 2] = (byte)(sample >> 16); }
            else BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(offset), (int)Math.Clamp(Math.Round(value * 2147483648d), int.MinValue, int.MaxValue));
        }
        return bytes;
    }
}
