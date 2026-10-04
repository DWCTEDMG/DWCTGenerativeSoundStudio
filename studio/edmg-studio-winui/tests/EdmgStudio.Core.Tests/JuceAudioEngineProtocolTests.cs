using EdmgStudio.Core.Audio;
using System.Collections.Immutable;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class JuceAudioEngineProtocolTests
{
  [TestMethod]
  public void HandshakeRoundTripsAndRejectsUnknownRequiredFields()
  {
    JuceHandshakeResponse expected = new(
        JuceAudioEngineProtocol.Version,
        "host-build",
        "x64",
        ImmutableArray.Create("lifecycle"),
        "ready_without_device",
        true);

    JuceHandshakeResponse actual = JuceAudioEngineProtocol.Parse<JuceHandshakeResponse>(
        JuceAudioEngineProtocol.Serialize(expected));

    Assert.AreEqual(expected.ProtocolVersion, actual.ProtocolVersion);
    Assert.AreEqual(expected.HostBuildIdentity, actual.HostBuildIdentity);
    Assert.AreEqual(expected.Architecture, actual.Architecture);
    CollectionAssert.AreEqual(expected.FeatureFlags.ToArray(), actual.FeatureFlags.ToArray());
    Assert.AreEqual(expected.EngineState, actual.EngineState);
    Assert.AreEqual(expected.Compatible, actual.Compatible);
    Assert.AreEqual(expected.Diagnostic, actual.Diagnostic);
    Assert.ThrowsExactly<InvalidDataException>(() =>
        JuceAudioEngineProtocol.Parse<JuceHandshakeResponse>(
            "{\"protocolVersion\":1,\"hostBuildIdentity\":\"host\",\"architecture\":\"x64\",\"featureFlags\":[],\"engineState\":\"ready_without_device\",\"compatible\":true,\"requiredFutureField\":1}"));
  }

  [TestMethod]
  public async Task ClientReportsReadyWithoutClaimingDeviceReadiness()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");

    JuceAudioEngineStatus status = await client.StartAsync();

    Assert.AreEqual(JuceAudioEngineLifecycleState.ReadyWithoutDevice, status.State);
    Assert.IsTrue(status.FallbackSafe);
    Assert.AreEqual("deterministic-host", status.BuildIdentity);
  }

  [TestMethod]
  public async Task ClientRejectsIncompatibleHost()
  {
    DeterministicJuceAudioEngineHost host = new(new JuceHandshakeResponse(
        2, "future-host", "x64", [], "ready_without_device", false, "Protocol mismatch."));
    await using JuceAudioEngineClient client = new(() => host, "test-client");

    JuceAudioEngineStatus status = await client.StartAsync();

    Assert.AreEqual(JuceAudioEngineLifecycleState.Incompatible, status.State);
    Assert.AreEqual("JUCE_PROTOCOL_INCOMPATIBLE", status.FailureCode);
  }

  [TestMethod]
  public async Task ClientRejectsHostWithoutRequiredLifecycleFeature()
  {
    DeterministicJuceAudioEngineHost host = new(new JuceHandshakeResponse(
        JuceAudioEngineProtocol.Version,
        "incomplete-host",
        Environment.Is64BitProcess ? "x64" : "x86",
        [],
        "ready_without_device",
        true));
    await using JuceAudioEngineClient client = new(() => host, "test-client");

    JuceAudioEngineStatus status = await client.StartAsync();

    Assert.AreEqual(JuceAudioEngineLifecycleState.Incompatible, status.State);
    Assert.AreEqual("JUCE_PROTOCOL_INCOMPATIBLE", status.FailureCode);
  }

  [TestMethod]
  public async Task ClientReportsMissingHostAsUnavailable()
  {
    string missingHost = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"), "missing-host.exe");
    await using JuceAudioEngineClient client = new(
        () => new ProcessJuceAudioEngineHostConnection(missingHost),
        "test-client");

    JuceAudioEngineStatus status = await client.StartAsync();

    Assert.AreEqual(JuceAudioEngineLifecycleState.Unavailable, status.State);
    Assert.AreEqual("JUCE_HOST_UNAVAILABLE", status.FailureCode);
  }

  [TestMethod]
  public async Task StopIsIdempotent()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    _ = await client.StartAsync();

    await client.StopAsync();
    await client.StopAsync();

    Assert.AreEqual(JuceAudioEngineLifecycleState.Stopped, client.Status.State);
  }

  [TestMethod]
  public async Task ClientDropsStaleHostMessages()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    List<long> received = [];
    client.MessageReceived += (_, envelope) => received.Add(envelope.Sequence);
    _ = await client.StartAsync();

    host.Emit(JuceAudioEngineProtocol.CreateEnvelope(2, "new", "diagnostic", new { callbackLoad = 0.1 }));
    host.Emit(JuceAudioEngineProtocol.CreateEnvelope(1, "stale", "diagnostic", new { callbackLoad = 0.2 }));

    CollectionAssert.AreEqual(new long[] { 2 }, received);
    Assert.AreEqual(1, client.Status.DroppedStaleMessages);
  }

  [TestMethod]
  public async Task OutboundCommandsDoNotMakeIndependentHostEventsStale()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    List<long> received = [];
    client.MessageReceived += (_, envelope) => received.Add(envelope.Sequence);
    _ = await client.StartAsync();

    await client.SendAsync("configure", new { sampleRate = 48000 });
    host.Emit(JuceAudioEngineProtocol.CreateEnvelope(1, "host-event", "diagnostic", new { callbackLoad = 0.1 }));

    Assert.HasCount(1, host.Commands);
    CollectionAssert.AreEqual(new long[] { 1 }, received);
    Assert.AreEqual(0, client.Status.DroppedStaleMessages);
  }

  [TestMethod]
  public async Task ClientSurfacesMalformedHostOutputAsProtocolFailure()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    _ = await client.StartAsync();

    host.FailProtocol(new InvalidDataException("Malformed host event."));

    Assert.AreEqual(JuceAudioEngineLifecycleState.Failed, client.Status.State);
    Assert.AreEqual("JUCE_PROTOCOL_ERROR", client.Status.FailureCode);
  }

  [TestMethod]
  public async Task CorrelatedRequestReturnsTypedPayload()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    _ = await client.StartAsync();

    Task<JuceAudioDeviceDescriptor[]> request = client.RequestAsync<JuceAudioDeviceDescriptor[]>(
        JuceAudioEngineProtocol.ListDevicesCommand, new { }, JuceAudioEngineProtocol.DeviceListEvent);
    await WaitForCommandAsync(host);
    JuceProtocolEnvelope command = host.Commands[0];
    host.Emit(JuceAudioEngineProtocol.CreateEnvelope(1, command.CorrelationId, JuceAudioEngineProtocol.DeviceListEvent,
        new[] { new JuceAudioDeviceDescriptor("api:id", "Device", "api", 0, 2, [48_000], [512], true, false, true) }));

    JuceAudioDeviceDescriptor[] devices = await request;

    Assert.HasCount(1, devices);
    Assert.AreEqual("api:id", devices[0].Id);
  }

  [TestMethod]
  public async Task PreparedTimelineRequestReturnsTypedAcknowledgement()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    _ = await client.StartAsync();
    JucePreparedTimelineSnapshot snapshot = new(4, 48_000, 1,
        [new JucePreparedTimelineSource("source-1", 48_000, 1, [1])],
        [new JucePreparedTimelineTrack("track", 1, 1,
          [new JucePreparedTimelineClip("clip", 0, 1, 0, 1, 0, 0, "linear", "source-1")])]);

    Task<JucePreparedTimelineResult> request = client.RequestAsync<JucePreparedTimelineResult>(
        JuceAudioEngineProtocol.PrepareTimelineCommand, snapshot, JuceAudioEngineProtocol.TimelinePreparedEvent);
    await WaitForCommandAsync(host);
    JuceProtocolEnvelope command = host.Commands[0];
    host.Emit(JuceAudioEngineProtocol.CreateEnvelope(1, command.CorrelationId,
        JuceAudioEngineProtocol.TimelinePreparedEvent, new JucePreparedTimelineResult(true, 4, 48_000, 1, 1, 1, 1)));

    JucePreparedTimelineResult result = await request;

    Assert.IsTrue(result.Prepared);
    Assert.AreEqual(4, result.Revision);
    Assert.AreEqual(1, result.ClipCount);
  }

  [TestMethod]
  public void TimelineRenderResultRoundTripsStrictly()
  {
    JuceNativeTimelineRenderResult expected = new(3, 10, 2, [.25f, .5f, .75f, 1]);

    JuceNativeTimelineRenderResult actual = JuceAudioEngineProtocol.Parse<JuceNativeTimelineRenderResult>(
        JuceAudioEngineProtocol.Serialize(expected));

    Assert.AreEqual(expected.Revision, actual.Revision);
    CollectionAssert.AreEqual(expected.InterleavedSamples.ToArray(), actual.InterleavedSamples.ToArray());
  }

  [TestMethod]
  public async Task CorrelatedRequestSurfacesStructuredHostError()
  {
    DeterministicJuceAudioEngineHost host = new();
    await using JuceAudioEngineClient client = new(() => host, "test-client");
    _ = await client.StartAsync();

    Task<JuceAudioDeviceConfigurationResult> request = client.RequestAsync<JuceAudioDeviceConfigurationResult>(
        JuceAudioEngineProtocol.ConfigureDeviceCommand,
        new JuceAudioDeviceConfiguration("missing", 48_000, 512, 2, false),
        JuceAudioEngineProtocol.DeviceConfiguredEvent);
    await WaitForCommandAsync(host);
    JuceProtocolEnvelope command = host.Commands[0];
    host.Emit(JuceAudioEngineProtocol.CreateEnvelope(1, command.CorrelationId, JuceAudioEngineProtocol.ErrorEvent,
        new JuceProtocolError("JUCE_DEVICE_OPEN_FAILED", "Device unavailable.")));

    InvalidOperationException exception = await Assert.ThrowsAsync<InvalidOperationException>(async () => await request);
    StringAssert.Contains(exception.Message, "JUCE_DEVICE_OPEN_FAILED");
  }

  [TestMethod]
  public async Task ClientRestartsOnceThenFailsClosed()
  {
    DeterministicJuceAudioEngineHost first = new();
    DeterministicJuceAudioEngineHost second = new();
    Queue<DeterministicJuceAudioEngineHost> hosts = new([first, second]);
    await using JuceAudioEngineClient client = new(() => hosts.Dequeue(), "test-client", maximumRestarts: 1);
    _ = await client.StartAsync();

    first.Crash(10);
    await WaitForStatusAsync(client, status =>
        status.State == JuceAudioEngineLifecycleState.ReadyWithoutDevice && status.RestartCount == 1);
    Assert.AreEqual(1, client.Status.RestartCount);

    second.Crash(11);
    await WaitForStatusAsync(client, status => status.State == JuceAudioEngineLifecycleState.Failed);
    Assert.AreEqual("JUCE_HOST_EXITED", client.Status.FailureCode);
    Assert.IsTrue(client.Status.FallbackSafe);
  }

  private static async Task WaitForCommandAsync(DeterministicJuceAudioEngineHost host)
  {
    using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(2));
    while (host.Commands.Count == 0)
    {
      await Task.Delay(10, timeout.Token);
    }
  }

  private static async Task WaitForStatusAsync(
      JuceAudioEngineClient client,
      Func<JuceAudioEngineStatus, bool> predicate)
  {
    using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(2));
    while (!predicate(client.Status))
    {
      await Task.Delay(10, timeout.Token);
    }
  }
}
