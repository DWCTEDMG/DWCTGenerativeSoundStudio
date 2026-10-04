using System.Collections.Immutable;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Audio;

public enum JuceAudioEngineLifecycleState
{
  Unavailable,
  Incompatible,
  Starting,
  ReadyWithoutDevice,
  Failed,
  Restarting,
  ShuttingDown,
  Stopped
}

public sealed record JuceAudioEngineStatus(
    JuceAudioEngineLifecycleState State,
    string Message,
    DateTimeOffset ChangedAt,
    string? BuildIdentity = null,
    string? FailureCode = null,
    bool FallbackSafe = true,
    int RestartCount = 0,
    int DroppedStaleMessages = 0);

public sealed record JuceProtocolEnvelope(
    int ProtocolVersion,
    long Sequence,
    string CorrelationId,
    string Kind,
    JsonElement Payload);

public sealed record JuceHandshakeRequest(
    int MinimumProtocolVersion,
    int MaximumProtocolVersion,
    string ClientBuildIdentity,
    string SessionToken);

public sealed record JuceHandshakeResponse(
    int ProtocolVersion,
    string HostBuildIdentity,
    string Architecture,
    ImmutableArray<string> FeatureFlags,
    string EngineState,
    bool Compatible,
    string? Diagnostic = null);

public sealed record JuceAudioDeviceDescriptor(
    string Id,
    string Name,
    string Api,
    int InputChannels,
    int OutputChannels,
    ImmutableArray<int> SampleRates,
    ImmutableArray<int> BufferSizes,
    bool SupportsSharedMode,
    bool SupportsExclusiveMode,
    bool IsDefaultOutput);

public sealed record JuceAudioDeviceConfiguration(
    string DeviceId,
    int SampleRate,
    int BufferFrames,
    int OutputChannels,
    bool ExclusiveMode);

public sealed record JuceAudioDeviceConfigurationResult(
    bool Configured,
    string? Diagnostic,
    string? DeviceId = null,
    int SampleRate = 0,
    int BufferFrames = 0,
    int OutputChannels = 0);

public sealed record JuceProtocolError(string Code, string Message);

public sealed record JuceTransportConfiguration(
    long ProjectRevision,
    int SampleRate,
    long DurationSamples,
    double ToneFrequencyHz = 440.0);

public sealed record JuceTransportCommand(
    string Action,
    long? PositionSamples = null,
    bool? LoopEnabled = null,
    long? LoopStartSample = null,
    long? LoopEndSample = null,
    long SeekSequence = 0);

public sealed record JuceTransportPosition(
    long ProjectRevision,
    long PositionSamples,
    int SampleRate,
    string State,
    bool LoopEnabled,
    long LoopStartSample,
    long LoopEndSample,
    long SeekSequence);

public sealed record JucePreparedTimelineSource(
    string SourceId,
    int SampleRate,
    int Channels,
    ImmutableArray<float> InterleavedSamples,
    string? AuthorizedPath = null,
    long FrameCount = 0,
    string? ContentHash = null);

public sealed record JucePreparedTimelineClip(
    string EventId,
    long TimelineStartSample,
    long TimelineEndSample,
    long SourceStartSample,
    double PlaybackRate,
    long FadeInSamples,
    long FadeOutSamples,
    string FadeCurve,
    string SourceId);

public sealed record JucePreparedTimelineTrack(
    string TrackId,
    float LeftGain,
    float RightGain,
    ImmutableArray<JucePreparedTimelineClip> Clips);

public sealed record JucePreparedTimelineSnapshot(
    long Revision,
    int SampleRate,
    long DurationSamples,
    ImmutableArray<JucePreparedTimelineSource> Sources,
    ImmutableArray<JucePreparedTimelineTrack> Tracks);

public sealed record JucePreparedTimelineResult(
    bool Prepared,
    long Revision,
    int SampleRate,
    long DurationSamples,
    int SourceCount,
    int TrackCount,
    int ClipCount);

public sealed record JuceNativeTimelineRenderRequest(long StartSample, int Frames);

public sealed record JuceNativeTimelineRenderResult(
    long Revision,
    long StartSample,
    int Frames,
    ImmutableArray<float> InterleavedSamples);

public static class JuceAudioEngineProtocol
{
  public const int Version = 1;
  public const int MaximumMessageBytes = 1024 * 1024;
  public const string LifecycleFeature = "lifecycle";
  public const string DeviceEnumerationFeature = "device_enumeration";
  public const string GeneratedToneTransportFeature = "generated_tone_transport";
  public const string PreparedTimelineFeature = "prepared_timeline_v1";
  public const string FileBackedPreparedMediaFeature = "file_backed_prepared_media_v1";
  public const string ListDevicesCommand = "list_devices";
  public const string DeviceListEvent = "device_list";
  public const string ConfigureDeviceCommand = "configure_device";
  public const string DeviceConfiguredEvent = "device_configured";
  public const string CloseDeviceCommand = "close_device";
  public const string DeviceClosedEvent = "device_closed";
  public const string ConfigureTransportCommand = "configure_transport";
  public const string TransportConfiguredEvent = "transport_configured";
  public const string PrepareTimelineCommand = "prepare_timeline";
  public const string TimelinePreparedEvent = "timeline_prepared";
  public const string RenderTimelineCommand = "render_timeline";
  public const string TimelineRenderedEvent = "timeline_rendered";
  public const string TransportCommand = "transport";
  public const string TransportPositionEvent = "transport_position";
  public const string ErrorEvent = "error";

  private static readonly JsonSerializerOptions Options = new()
  {
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
  };

  public static string Serialize<T>(T value)
  {
    ArgumentNullException.ThrowIfNull(value);
    string json = JsonSerializer.Serialize(value, Options);
    return Encoding.UTF8.GetByteCount(json) <= MaximumMessageBytes
        ? json
        : throw new InvalidDataException("JUCE audio-engine message exceeds the protocol limit.");
  }

  public static T Parse<T>(string json)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(json);
    if (Encoding.UTF8.GetByteCount(json) > MaximumMessageBytes)
    {
      throw new InvalidDataException("JUCE audio-engine message exceeds the protocol limit.");
    }

    try
    {
      return JsonSerializer.Deserialize<T>(json, Options)
          ?? throw new JsonException("The message body was empty.");
    }
    catch (JsonException exception)
    {
      throw new InvalidDataException("Malformed JUCE audio-engine protocol message.", exception);
    }
  }

  public static JuceProtocolEnvelope CreateEnvelope<T>(long sequence, string correlationId, string kind, T payload)
  {
    ArgumentOutOfRangeException.ThrowIfNegativeOrZero(sequence);
    ArgumentException.ThrowIfNullOrWhiteSpace(correlationId);
    ArgumentException.ThrowIfNullOrWhiteSpace(kind);
    ArgumentNullException.ThrowIfNull(payload);
    return new JuceProtocolEnvelope(
        Version,
        sequence,
        correlationId.Trim(),
        kind.Trim(),
        JsonSerializer.SerializeToElement(payload, Options));
  }

  public static T ParsePayload<T>(JuceProtocolEnvelope envelope)
  {
    ValidateEnvelope(envelope);
    try
    {
      return envelope.Payload.Deserialize<T>(Options)
          ?? throw new JsonException("The payload was empty.");
    }
    catch (JsonException exception)
    {
      throw new InvalidDataException("Malformed JUCE audio-engine payload.", exception);
    }
  }

  public static void ValidateEnvelope(JuceProtocolEnvelope envelope)
  {
    ArgumentNullException.ThrowIfNull(envelope);
    if (envelope.ProtocolVersion != Version || envelope.Sequence <= 0 ||
        string.IsNullOrWhiteSpace(envelope.CorrelationId) || string.IsNullOrWhiteSpace(envelope.Kind) ||
        envelope.Payload.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
    {
      throw new InvalidDataException("JUCE audio-engine envelope violates the protocol contract.");
    }
  }

  public static void ValidateHandshakeResponse(JuceHandshakeResponse response)
  {
    ArgumentNullException.ThrowIfNull(response);
    if (string.IsNullOrWhiteSpace(response.HostBuildIdentity) ||
        string.IsNullOrWhiteSpace(response.Architecture) ||
        response.FeatureFlags.IsDefault ||
        response.FeatureFlags.Any(string.IsNullOrWhiteSpace) ||
        string.IsNullOrWhiteSpace(response.EngineState))
    {
      throw new InvalidDataException("JUCE host handshake violates the protocol contract.");
    }
  }
}
