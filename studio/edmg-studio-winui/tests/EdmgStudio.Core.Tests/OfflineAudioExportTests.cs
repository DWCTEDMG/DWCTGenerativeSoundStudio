using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;
using System.Security.Cryptography;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class OfflineAudioExportTests
{
  [TestMethod]
  public void RouteMatrixMapsStereoIntoSurroundBedDeterministically()
  {
    AudioRouteMatrix matrix = new(2, 6, [1, 0, 0, 1, .5f, .5f, 0, 0, 0, 0, 0, 0]);
    float[] output = matrix.Apply([1, -.5f]);
    CollectionAssert.AreEqual(new[] { 1f, -.5f, .25f, 0f, 0f, 0f }, output);
  }

  [TestMethod]
  public void Pcm24WaveHasStableGoldenHashAndLayoutHeader()
  {
    OfflineAudioLayout layout = OfflineAudioLayout.Create(AudioChannelLayout.Surround51);
    byte[] first = OfflineWaveExporter.ExportPcm24(48_000, layout, [-1, -.5f, 0, .5f, 1, .25f]);
    byte[] second = OfflineWaveExporter.ExportPcm24(48_000, layout, [-1, -.5f, 0, .5f, 1, .25f]);
    CollectionAssert.AreEqual(first, second);
    Assert.HasCount(62, first);
    Assert.AreEqual(6, BitConverter.ToUInt16(first, 22));
    Assert.AreEqual("dda7306a1e4e02d7b7243014626fe88ba1610471a3a39079cea6fab2691d610f", Convert.ToHexString(SHA256.HashData(first)).ToLowerInvariant());
  }

  [TestMethod]
  public void MultichannelIsOfflineOnlyAndObjectsRemainUnsupported()
  {
    Assert.IsTrue(OfflineAudioCapabilities.CanPreview(AudioChannelLayout.Stereo));
    Assert.IsFalse(OfflineAudioCapabilities.CanPreview(AudioChannelLayout.Surround51));
    Assert.IsTrue(OfflineAudioCapabilities.CanExportChannelBed(AudioChannelLayout.Surround71));
    Assert.IsFalse(OfflineAudioCapabilities.CanExportChannelBed(AudioChannelLayout.Object));
    _ = Assert.ThrowsExactly<NotSupportedException>(() => OfflineAudioLayout.Create(AudioChannelLayout.Object));
  }

  [TestMethod]
  public async Task StreamingBouncePublishesExactDeterministicRangeAndReceipt()
  {
    string directory = TemporaryDirectory();
    string output = Path.Combine(directory, "bounce.wav");
    try
    {
      OfflineBounceRequest request = new(output, 10, 15, 48_000, OfflineAudioLayout.Create(AudioChannelLayout.Stereo), ChunkFrames: 2);
      OfflineBounceReceipt first = await OfflineBounceExporter.ExportPcm24Async(request, RenderRamp);
      OfflineBounceReceipt second = await OfflineBounceExporter.ExportPcm24Async(request, RenderRamp);

      Assert.AreEqual(Path.GetFullPath(output), first.OutputPath);
      Assert.AreEqual(5L, first.FrameCount);
      Assert.AreEqual(74L, first.FileBytes);
      Assert.AreEqual(first.Sha256, second.Sha256);
      Assert.IsTrue(first.Deterministic);
      Assert.IsEmpty(first.NondeterministicComponents);
      byte[] bytes = await File.ReadAllBytesAsync(output);
      Assert.AreEqual(first.FileBytes, bytes.LongLength);
      Assert.AreEqual(first.Sha256, Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
      Assert.AreEqual(30u, BitConverter.ToUInt32(bytes, 40));
      Assert.IsEmpty(Directory.GetFiles(directory, "*.tmp", SearchOption.TopDirectoryOnly));
    }
    finally
    {
      Directory.Delete(directory, recursive: true);
    }

    static ValueTask<int> RenderRamp(long startSample, Memory<float> destination, CancellationToken _)
    {
      Span<float> samples = destination.Span;
      for (int frame = 0; frame < samples.Length / 2; frame++)
      {
        samples[frame * 2] = (startSample + frame) / 100f;
        samples[(frame * 2) + 1] = -(startSample + frame) / 100f;
      }
      return ValueTask.FromResult(samples.Length / 2);
    }
  }

  [TestMethod]
  public async Task CancellationLeavesExistingOutputUntouchedAndNoTemporaryArtifact()
  {
    string directory = TemporaryDirectory();
    string output = Path.Combine(directory, "existing.wav");
    byte[] original = [1, 2, 3, 4];
    await File.WriteAllBytesAsync(output, original);
    using CancellationTokenSource cancellation = new();
    int calls = 0;
    try
    {
      OfflineBounceRequest request = new(output, 0, 8, 48_000, OfflineAudioLayout.Create(AudioChannelLayout.Stereo), ChunkFrames: 2);
      await Assert.ThrowsExactlyAsync<OperationCanceledException>(async () =>
          await OfflineBounceExporter.ExportPcm24Async(request, (start, destination, token) =>
          {
            destination.Span.Clear();
            if (++calls == 2)
            {
              cancellation.Cancel();
            }
            token.ThrowIfCancellationRequested();
            return ValueTask.FromResult(destination.Length / 2);
          }, cancellation.Token));

      CollectionAssert.AreEqual(original, await File.ReadAllBytesAsync(output));
      Assert.IsEmpty(Directory.GetFiles(directory, "*.tmp", SearchOption.TopDirectoryOnly));
    }
    finally
    {
      Directory.Delete(directory, recursive: true);
    }
  }

  [TestMethod]
  public async Task RendererFailureDoesNotPublishOrLeakTemporaryArtifact()
  {
    string directory = TemporaryDirectory();
    string output = Path.Combine(directory, "failed.wav");
    try
    {
      OfflineBounceRequest request = new(output, 0, 4, 48_000, OfflineAudioLayout.Create(AudioChannelLayout.Mono), ChunkFrames: 2);
      await Assert.ThrowsExactlyAsync<InvalidDataException>(async () =>
          await OfflineBounceExporter.ExportPcm24Async(request, (_, destination, _) =>
          {
            destination.Span.Clear();
            return ValueTask.FromResult(0);
          }));

      Assert.IsFalse(File.Exists(output));
      Assert.IsEmpty(Directory.GetFiles(directory, "*.tmp", SearchOption.TopDirectoryOnly));
    }
    finally
    {
      Directory.Delete(directory, recursive: true);
    }
  }

  [TestMethod]
  public async Task ReceiptDisclosesNondeterministicComponents()
  {
    string directory = TemporaryDirectory();
    string output = Path.Combine(directory, "plugin.wav");
    try
    {
      OfflineBounceRequest request = new(output, 0, 1, 48_000, OfflineAudioLayout.Create(AudioChannelLayout.Mono),
          Deterministic: true, NondeterministicComponents: ["plugin:randomizer"]);
      OfflineBounceReceipt receipt = await OfflineBounceExporter.ExportPcm24Async(request, (_, destination, _) =>
      {
        destination.Span.Clear();
        return ValueTask.FromResult(1);
      });

      Assert.IsFalse(receipt.Deterministic);
      CollectionAssert.AreEqual(new[] { "plugin:randomizer" }, receipt.NondeterministicComponents.ToArray());
    }
    finally
    {
      Directory.Delete(directory, recursive: true);
    }
  }

  private static string TemporaryDirectory()
  {
    string directory = Path.Combine(Path.GetTempPath(), "edmg-offline-bounce-tests", Guid.NewGuid().ToString("N"));
    Directory.CreateDirectory(directory);
    return directory;
  }
}
