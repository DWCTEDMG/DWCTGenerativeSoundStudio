using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class AudioDeviceQualificationTests
{
    private static AudioDeviceQualificationRequest Request => new(
        "fake-device", AudioDeviceBackend.WasapiShared, 48_000, 256, "fake-driver/1", ".NET 10/x64");

    [TestMethod]
    public void DeterministicProbeProducesStableNonNativeReceipt()
    {
        var probe = new DeterministicAudioQualificationProbe();

        AudioDeviceQualificationReceipt first = probe.Qualify(Request);
        AudioDeviceQualificationReceipt second = probe.Qualify(Request);

        Assert.AreEqual(AudioQualificationLevel.DeterministicSimulation, probe.Level);
        Assert.AreEqual(AudioQualificationStatus.Passed, first.Status);
        Assert.AreEqual(first.Fingerprint, second.Fingerprint);
        Assert.AreEqual(first.QualifiedAtUtc, second.QualifiedAtUtc);
        CollectionAssert.AreEqual(first.Checks.ToArray(), second.Checks.ToArray());
        Assert.IsTrue(first.IsValidFor(Request));
        Assert.IsFalse(first.EstablishesNativeReadiness);
        StringAssert.Contains(first.Diagnostic, "no native device");
    }

    [TestMethod]
    public void ReceiptInvalidatesForEveryRuntimeAndDeviceFingerprintInput()
    {
        AudioDeviceQualificationReceipt receipt = new DeterministicAudioQualificationProbe().Qualify(Request);

        Assert.IsFalse(receipt.IsValidFor(Request with { DeviceId = "replacement" }));
        Assert.IsFalse(receipt.IsValidFor(Request with { Backend = AudioDeviceBackend.WasapiExclusive }));
        Assert.IsFalse(receipt.IsValidFor(Request with { SampleRate = 96_000 }));
        Assert.IsFalse(receipt.IsValidFor(Request with { BufferFrames = 512 }));
        Assert.IsFalse(receipt.IsValidFor(Request with { DriverIdentity = "fake-driver/2" }));
        Assert.IsFalse(receipt.IsValidFor(Request with { RuntimeIdentity = ".NET 10/arm64" }));
    }

    [TestMethod]
    public void FingerprintingRejectsIncompleteRequests()
    {
        Assert.ThrowsExactly<ArgumentException>(() =>
            AudioDeviceQualificationFingerprinting.Create(Request with { DriverIdentity = " " }));
        Assert.ThrowsExactly<ArgumentOutOfRangeException>(() =>
            AudioDeviceQualificationFingerprinting.Create(Request with { BufferFrames = 0 }));
    }
}
