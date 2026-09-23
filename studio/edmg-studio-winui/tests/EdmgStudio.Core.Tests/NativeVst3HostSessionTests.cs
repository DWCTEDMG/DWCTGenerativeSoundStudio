using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class NativeVst3HostSessionTests
{
    private const string AgainPluginId = "84E8DE5F92554F5396FAE4133C935A18";

    [TestMethod]
    public async Task OfficialAgainSampleProcessesParametersAndStateThroughPersistentWorker()
    {
        string? hostPath = Environment.GetEnvironmentVariable("EDMG_VST3_HOST_TEST_PATH");
        string? modulePath = Environment.GetEnvironmentVariable("EDMG_VST3_MODULE_TEST_PATH");
        if (!OperatingSystem.IsWindows() || string.IsNullOrWhiteSpace(hostPath) || string.IsNullOrWhiteSpace(modulePath) ||
            !File.Exists(hostPath) || (!File.Exists(modulePath) && !Directory.Exists(modulePath)))
            Assert.Inconclusive("Set EDMG_VST3_HOST_TEST_PATH and EDMG_VST3_MODULE_TEST_PATH to run native VST3 integration evidence.");

        await using var session = new NativeVst3HostSession(hostPath, TimeSpan.FromSeconds(20), TimeSpan.FromSeconds(2));
        Vst3InstanceStatus status = await session.CreateInstanceAsync(new("again", modulePath, AgainPluginId, 48000, 256));
        Assert.IsTrue(status.Active, status.Diagnostic);
        Assert.AreEqual(Vst3WorkerHealth.Ready, status.Health);
        Assert.AreEqual(2, status.AudioInputs);
        Assert.AreEqual(2, status.AudioOutputs);
        Assert.IsGreaterThanOrEqualTo(3, status.Parameters.Length);
        Assert.IsTrue(session.TryGetProcessor("again", out IVst3InsertProcessor? processor));

        float[] audio = new float[512];
        audio[0] = 0.25f;
        audio[1] = -0.25f;
        Assert.IsTrue(processor!.TryProcessInPlace(audio, 256), processor.Diagnostic);
        Assert.IsTrue(audio.All(float.IsFinite));
        Assert.IsTrue(audio.Any(sample => sample != 0));

        Vst3ParameterDescriptor parameter = status.Parameters[0];
        double changed = parameter.NormalizedValue > 0.5 ? 0.25 : 0.75;
        status = await session.SetParameterAsync("again", parameter.Id, changed);
        Assert.AreEqual(changed, status.Parameters.Single(item => item.Id == parameter.Id).NormalizedValue, 0.000001);

        ReadOnlyMemory<byte> state = await session.GetStateAsync("again");
        Assert.IsGreaterThan(0, state.Length);
        status = await session.SetStateAsync("again", state);
        Assert.IsTrue(status.Active, status.Diagnostic);
        await session.RemoveInstanceAsync("again");
    }

    [TestMethod]
    [DataRow(false)]
    [DataRow(true)]
    public async Task WorkerCrashOrTimeoutTransitionsToDeterministicBypass(bool timeout)
    {
        string? hostPath = Environment.GetEnvironmentVariable("EDMG_VST3_HOST_TEST_PATH");
        string? modulePath = Environment.GetEnvironmentVariable("EDMG_VST3_MODULE_TEST_PATH");
        if (!OperatingSystem.IsWindows() || string.IsNullOrWhiteSpace(hostPath) || string.IsNullOrWhiteSpace(modulePath) ||
            !File.Exists(hostPath) || (!File.Exists(modulePath) && !Directory.Exists(modulePath)))
            Assert.Inconclusive("Set EDMG_VST3_HOST_TEST_PATH and EDMG_VST3_MODULE_TEST_PATH to run native VST3 integration evidence.");

        await using var session = new NativeVst3HostSession(hostPath, TimeSpan.FromSeconds(20), TimeSpan.FromMilliseconds(100));
        Vst3InstanceStatus status = await session.CreateInstanceAsync(new($"failure-{timeout}", modulePath, AgainPluginId, 48000, 64));
        Assert.IsTrue(session.TryGetProcessor(status.InstanceId, out IVst3InsertProcessor? processor));

        await session.SimulateWorkerFailureAsync(status.InstanceId, timeout);

        Assert.AreEqual(timeout ? Vst3WorkerHealth.TimedOut : Vst3WorkerHealth.Exited, processor!.Health);
        float[] audio = [0.25f, -0.25f];
        Assert.IsFalse(processor.TryProcessInPlace(audio, 1));
        CollectionAssert.AreEqual(new[] { 0.25f, -0.25f }, audio);
        await Assert.ThrowsAsync<IOException>(async () => await session.GetStateAsync(status.InstanceId));
    }
}
