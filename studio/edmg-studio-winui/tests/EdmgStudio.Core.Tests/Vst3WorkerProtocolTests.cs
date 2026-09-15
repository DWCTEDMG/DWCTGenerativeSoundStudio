using EdmgStudio.Core.Audio;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class Vst3WorkerProtocolTests
{
    [TestMethod]
    public void ProtocolRejectsVersionMismatchUnknownFieldsAndOversizedMessages()
    {
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3WorkerProtocol.Serialize(new(2, "id", "process", null, [0])));
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3WorkerProtocol.ParseResponse("{\"protocolVersion\":1,\"requestId\":\"id\",\"success\":true,\"samples\":[],\"diagnostic\":null,\"extra\":1}", "id"));
        string oversized = "{\"protocolVersion\":1,\"requestId\":\"id\",\"success\":false,\"samples\":null,\"diagnostic\":\"" + new string('x', Vst3WorkerProtocol.MaximumMessageBytes) + "\"}";
        Assert.ThrowsExactly<InvalidDataException>(() => Vst3WorkerProtocol.ParseResponse(oversized, "id"));
    }

    [TestMethod]
    public async Task RealChildProcessRoundTripsVersionedFakeWorker()
    {
        const string script = "$r=[Console]::ReadLine()|ConvertFrom-Json;$o=[ordered]@{protocolVersion=1;requestId=$r.requestId;success=$true;samples=@($r.samples|%{[double]$_*0.5});diagnostic='deterministic fake; no native VST3 processing'};$o|ConvertTo-Json -Compress -Depth 4";
        var client = new Vst3WorkerProcessClient("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script]);
        Vst3WorkerResponse response = await client.SendAsync(new(1, "request-1", "process", "fake", [1, -.5f]), TimeSpan.FromSeconds(10));
        Assert.IsTrue(response.Success);
        CollectionAssert.AreEqual(new[] { .5f, -.25f }, response.Samples!);
        StringAssert.Contains(response.Diagnostic, "no native VST3 processing");
        Assert.IsFalse(new UnavailableVst3HostSession().Capabilities.CanProcessAudio);
    }

    [TestMethod]
    public async Task RealChildProcessFailureIsReported()
    {
        var client = new Vst3WorkerProcessClient("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", "[Console]::Error.Write('boom');exit 7"]);
        InvalidOperationException error = await Assert.ThrowsExactlyAsync<InvalidOperationException>(() =>
            client.SendAsync(new(1, "request-2", "ping", null, null), TimeSpan.FromSeconds(10)));
        StringAssert.Contains(error.Message, "code 7");
    }
}