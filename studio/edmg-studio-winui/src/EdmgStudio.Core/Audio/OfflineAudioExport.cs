using EdmgStudio.Core.Models;
using System.Buffers;
using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Security.Cryptography;

namespace EdmgStudio.Core.Audio;

public sealed record OfflineAudioLayout(AudioChannelLayout Layout, ImmutableArray<string> ChannelIds)
{
  public static OfflineAudioLayout Create(AudioChannelLayout layout)
  {
    return layout switch
    {
      AudioChannelLayout.Mono => new(layout, ["M"]),
      AudioChannelLayout.Stereo => new(layout, ["L", "R"]),
      AudioChannelLayout.Surround51 => new(layout, ["L", "R", "C", "LFE", "Ls", "Rs"]),
      AudioChannelLayout.Surround71 => new(layout, ["L", "R", "C", "LFE", "Lss", "Rss", "Lrs", "Rrs"]),
      _ => throw new NotSupportedException("Object audio requires a renderer and is not supported by channel-bed export.")
    };
  }
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
    {
      throw new ArgumentException("Route gains must be a finite output-major matrix.", nameof(gains));
    }

    InputChannels = inputChannels;
    OutputChannels = outputChannels;
    _gains = gains.ToArray();
  }

  public int InputChannels { get; }
  public int OutputChannels { get; }

  public float[] Apply(ReadOnlySpan<float> interleavedInput)
  {
    if (interleavedInput.Length % InputChannels != 0)
    {
      throw new ArgumentException("Input ends with a partial frame.", nameof(interleavedInput));
    }

    int frames = interleavedInput.Length / InputChannels;
    float[] output = new float[checked(frames * OutputChannels)];
    for (int frame = 0; frame < frames; frame++)
    {
      for (int destination = 0; destination < OutputChannels; destination++)
      {
        double sum = 0;
        for (int source = 0; source < InputChannels; source++)
        {
          sum += interleavedInput[(frame * InputChannels) + source] * _gains[(destination * InputChannels) + source];
        }

        output[(frame * OutputChannels) + destination] = (float)sum;
      }
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
    if (channels == 0 || interleavedSamples.Length % channels != 0)
    {
      throw new ArgumentException("Audio must contain complete channel frames.", nameof(interleavedSamples));
    }

    int dataLength = checked(interleavedSamples.Length * 3);
    byte[] output = new byte[checked(44 + dataLength)];
    WritePcm24Header(output, sampleRate, channels, dataLength);
    EncodePcm24(interleavedSamples, output.AsSpan(44));
    return output;
  }

  internal static void WritePcm24Header(Span<byte> output, int sampleRate, int channels, long dataLength)
  {
    if (output.Length < 44 || dataLength is < 0 or > uint.MaxValue - 36)
    {
      throw new ArgumentOutOfRangeException(nameof(dataLength), "PCM WAV output must fit the RIFF 32-bit length fields.");
    }

    output[..44].Clear();
    "RIFF"u8.CopyTo(output); BinaryPrimitives.WriteUInt32LittleEndian(output[4..], checked((uint)(36 + dataLength)));
    "WAVEfmt "u8.CopyTo(output[8..]); BinaryPrimitives.WriteUInt32LittleEndian(output[16..], 16);
    BinaryPrimitives.WriteUInt16LittleEndian(output[20..], 1); BinaryPrimitives.WriteUInt16LittleEndian(output[22..], checked((ushort)channels));
    BinaryPrimitives.WriteInt32LittleEndian(output[24..], sampleRate); BinaryPrimitives.WriteInt32LittleEndian(output[28..], checked(sampleRate * channels * 3));
    BinaryPrimitives.WriteUInt16LittleEndian(output[32..], checked((ushort)(channels * 3))); BinaryPrimitives.WriteUInt16LittleEndian(output[34..], 24);
    "data"u8.CopyTo(output[36..]); BinaryPrimitives.WriteUInt32LittleEndian(output[40..], checked((uint)dataLength));
  }

  internal static void EncodePcm24(ReadOnlySpan<float> samples, Span<byte> output)
  {
    if (output.Length != checked(samples.Length * 3))
    {
      throw new ArgumentException("PCM24 output length does not match the sample count.", nameof(output));
    }

    for (int index = 0, offset = 0; index < samples.Length; index++, offset += 3)
    {
      float finite = float.IsFinite(samples[index]) ? samples[index] : throw new InvalidDataException("Audio samples must be finite.");
      int sample = (int)Math.Round(Math.Clamp(finite, -1, 1) * (finite < 0 ? 8388608d : 8388607d), MidpointRounding.AwayFromZero);
      output[offset] = (byte)sample; output[offset + 1] = (byte)(sample >> 8); output[offset + 2] = (byte)(sample >> 16);
    }
  }
}

public sealed record OfflineBounceRequest(
    string OutputPath,
    long StartSample,
    long EndSample,
    int SampleRate,
    OfflineAudioLayout Layout,
    int BitDepth = 24,
    int ChunkFrames = 4096,
    bool Deterministic = true,
    ImmutableArray<string> NondeterministicComponents = default);

public sealed record OfflineBounceReceipt(
    string OutputPath,
    long StartSample,
    long EndSample,
    int SampleRate,
    int BitDepth,
    ImmutableArray<string> ChannelIds,
    long FrameCount,
    long FileBytes,
    string Sha256,
    bool Deterministic,
    ImmutableArray<string> NondeterministicComponents);

public delegate ValueTask<int> OfflineAudioRenderCallback(
    long startSample,
    Memory<float> interleavedOutput,
    CancellationToken cancellationToken);

public static class OfflineBounceExporter
{
  public static async Task<OfflineBounceReceipt> ExportPcm24Async(
      OfflineBounceRequest request,
      OfflineAudioRenderCallback render,
      CancellationToken cancellationToken = default)
  {
    ArgumentNullException.ThrowIfNull(request);
    ArgumentNullException.ThrowIfNull(render);
    ArgumentException.ThrowIfNullOrWhiteSpace(request.OutputPath);
    ArgumentOutOfRangeException.ThrowIfNegative(request.StartSample);
    if (request.EndSample <= request.StartSample)
    {
      throw new ArgumentException("The bounce end sample must be after its start sample.", nameof(request));
    }
    ArgumentOutOfRangeException.ThrowIfNegativeOrZero(request.SampleRate);
    ArgumentNullException.ThrowIfNull(request.Layout);
    if (request.BitDepth != 24)
    {
      throw new NotSupportedException("Only PCM24 offline bounce is currently supported.");
    }
    if (request.ChunkFrames is < 1 or > 65_536)
    {
      throw new ArgumentOutOfRangeException(nameof(request), "Chunk frames must be between 1 and 65,536.");
    }

    int channels = request.Layout.ChannelIds.Length;
    if (channels == 0)
    {
      throw new ArgumentException("The bounce layout must contain at least one channel.", nameof(request));
    }

    long frameCount = checked(request.EndSample - request.StartSample);
    long dataLength = checked(frameCount * channels * 3L);
    byte[] header = new byte[44];
    OfflineWaveExporter.WritePcm24Header(header, request.SampleRate, channels, dataLength);
    string outputPath = Path.GetFullPath(request.OutputPath);
    string directory = Path.GetDirectoryName(outputPath) ?? throw new ArgumentException("The output path has no directory.", nameof(request));
    Directory.CreateDirectory(directory);
    string temporaryPath = Path.Combine(directory, $".{Path.GetFileName(outputPath)}.{Guid.NewGuid():N}.tmp");
    int maximumSamples = checked(request.ChunkFrames * channels);
    float[] samples = ArrayPool<float>.Shared.Rent(maximumSamples);
    byte[] encoded = ArrayPool<byte>.Shared.Rent(checked(maximumSamples * 3));
    using IncrementalHash hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    try
    {
      await using (FileStream stream = new(temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None,
          bufferSize: 65_536, FileOptions.Asynchronous | FileOptions.SequentialScan))
      {
        await stream.WriteAsync(header, cancellationToken).ConfigureAwait(false);
        hash.AppendData(header);
        long position = request.StartSample;
        while (position < request.EndSample)
        {
          cancellationToken.ThrowIfCancellationRequested();
          int frames = checked((int)Math.Min(request.ChunkFrames, request.EndSample - position));
          int sampleCount = checked(frames * channels);
          Memory<float> destination = samples.AsMemory(0, sampleCount);
          int renderedFrames = await render(position, destination, cancellationToken).ConfigureAwait(false);
          if (renderedFrames != frames)
          {
            throw new InvalidDataException($"Offline renderer returned {renderedFrames} frames when {frames} were required.");
          }

          int encodedCount = checked(sampleCount * 3);
          OfflineWaveExporter.EncodePcm24(destination.Span, encoded.AsSpan(0, encodedCount));
          await stream.WriteAsync(encoded.AsMemory(0, encodedCount), cancellationToken).ConfigureAwait(false);
          hash.AppendData(encoded.AsSpan(0, encodedCount));
          position = checked(position + frames);
        }
        await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        stream.Flush(flushToDisk: true);
        if (stream.Length != checked(44 + dataLength))
        {
          throw new InvalidDataException("Offline WAV length did not match its declared render range.");
        }
      }

      cancellationToken.ThrowIfCancellationRequested();
      File.Move(temporaryPath, outputPath, overwrite: true);
      ImmutableArray<string> nondeterministic = request.NondeterministicComponents.IsDefault
          ? []
          : request.NondeterministicComponents;
      bool deterministic = request.Deterministic && nondeterministic.Length == 0;
      return new(outputPath, request.StartSample, request.EndSample, request.SampleRate, request.BitDepth,
          request.Layout.ChannelIds, frameCount, checked(44 + dataLength), Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant(),
          deterministic, nondeterministic);
    }
    finally
    {
      ArrayPool<float>.Shared.Return(samples);
      ArrayPool<byte>.Shared.Return(encoded);
      if (File.Exists(temporaryPath))
      {
        File.Delete(temporaryPath);
      }
    }
  }
}

public static class OfflineAudioCapabilities
{
  public static bool CanPreview(AudioChannelLayout layout)
  {
    return layout == AudioChannelLayout.Stereo;
  }

  public static bool CanExportChannelBed(AudioChannelLayout layout)
  {
    return layout != AudioChannelLayout.Object;
  }
}
