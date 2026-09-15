using System.Security.Cryptography;
using EdmgStudio.Core.Audio;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class OfflineAudioExportTests
{
    [TestMethod]
    public void RouteMatrixMapsStereoIntoSurroundBedDeterministically()
    {
        var matrix = new AudioRouteMatrix(2, 6, [1, 0, 0, 1, .5f, .5f, 0, 0, 0, 0, 0, 0]);
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
        Assert.AreEqual(62, first.Length);
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
        Assert.ThrowsExactly<NotSupportedException>(() => OfflineAudioLayout.Create(AudioChannelLayout.Object));
    }
}
