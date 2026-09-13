using System.Collections.Immutable;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public enum AudioDeviceBackend
{
    Asio,
    WasapiExclusive,
    WasapiShared
}

public sealed record AudioDeviceDescriptor(
    string Id,
    string Name,
    AudioDeviceBackend Backend,
    bool IsDefault,
    ImmutableArray<int> SupportedSampleRates);

public sealed record AudioClipSource(
    string EventId,
    string MediaAssetId,
    string SourcePath,
    long TimelineStartSample,
    long TimelineEndSample,
    long SourceStartSample,
    int SourceSampleRate);

public sealed record AudioTrackRoute(
    string TrackId,
    string OutputBusId,
    float Gain,
    float Pan,
    bool Muted,
    bool Solo,
    ImmutableArray<AudioClipSource> Clips);

public sealed record AudioMeterSnapshot(
    string ChannelId,
    float PeakLeft,
    float PeakRight,
    float RmsLeft,
    float RmsRight,
    long SamplePosition);

public sealed record AudioEngineConfiguration(
    string ProjectId,
    string DeviceId,
    int SampleRate,
    int BufferFrames,
    ImmutableArray<AudioTrackRoute> Tracks);

public sealed class AudioRenderGraph
{
    private readonly ImmutableArray<AudioTrackRoute> _tracks;
    private readonly bool _hasSolo;

    public AudioRenderGraph(AudioEngineConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(configuration);
        ArgumentException.ThrowIfNullOrWhiteSpace(configuration.ProjectId);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(configuration.SampleRate);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(configuration.BufferFrames);
        if (configuration.Tracks.Any(track => string.IsNullOrWhiteSpace(track.TrackId) ||
                                              string.IsNullOrWhiteSpace(track.OutputBusId) ||
                                              !float.IsFinite(track.Gain) ||
                                              !float.IsFinite(track.Pan) ||
                                              track.Pan is < -1 or > 1 ||
                                              track.Clips.Any(clip => string.IsNullOrWhiteSpace(clip.EventId) ||
                                                                      string.IsNullOrWhiteSpace(clip.MediaAssetId) ||
                                                                      string.IsNullOrWhiteSpace(clip.SourcePath) ||
                                                                      clip.TimelineStartSample < 0 ||
                                                                      clip.TimelineEndSample <= clip.TimelineStartSample ||
                                                                      clip.SourceStartSample < 0 ||
                                                                      clip.SourceSampleRate <= 0)))
        {
            throw new ArgumentException("Audio routes require stable IDs, finite gain, and pan between -1 and 1.", nameof(configuration));
        }

        if (configuration.Tracks.Select(track => track.TrackId).Distinct(StringComparer.Ordinal).Count() !=
            configuration.Tracks.Length)
        {
            throw new ArgumentException("Audio route track IDs must be unique.", nameof(configuration));
        }

        Configuration = configuration;
        _tracks = configuration.Tracks;
        _hasSolo = _tracks.Any(track => track.Solo);
    }

    public AudioEngineConfiguration Configuration { get; }

    public int TrackCount => _tracks.Length;

    public bool TryGetAudibleRoute(string trackId, out AudioTrackRoute? route)
    {
        route = _tracks.FirstOrDefault(candidate => string.Equals(candidate.TrackId, trackId, StringComparison.Ordinal));
        if (route is null || route.Muted || _hasSolo && !route.Solo)
        {
            route = null;
            return false;
        }
        return true;
    }
}

public static class AudioRenderGraphBuilder
{
    public static AudioRenderGraph Build(
        CanonicalProject project,
        string deviceId,
        int bufferFrames,
        Func<MediaAsset, string?> resolveSourcePath)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentException.ThrowIfNullOrWhiteSpace(deviceId);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(bufferFrames);
        ArgumentNullException.ThrowIfNull(resolveSourcePath);

        IReadOnlyDictionary<string, MediaAsset> assets = project.MediaAssets.ToDictionary(asset => asset.Id, StringComparer.Ordinal);
        var routes = ImmutableArray.CreateBuilder<AudioTrackRoute>();
        foreach (Track track in project.Tracks.Where(IsAudioTrack).OrderBy(track => track.Order))
        {
            var clips = ImmutableArray.CreateBuilder<AudioClipSource>();
            foreach (TimelineEvent timelineEvent in track.Events.OrderBy(item => item.Start.Samples))
            {
                if (string.IsNullOrWhiteSpace(timelineEvent.MediaAssetId))
                {
                    continue;
                }
                if (!assets.TryGetValue(timelineEvent.MediaAssetId, out MediaAsset? asset))
                {
                    throw new InvalidDataException($"Audio event '{timelineEvent.Id}' references missing media asset '{timelineEvent.MediaAssetId}'.");
                }
                string sourcePath = resolveSourcePath(asset)?.Trim() ?? string.Empty;
                if (sourcePath.Length == 0)
                {
                    throw new InvalidDataException($"Audio media asset '{asset.Id}' could not be resolved to a local source path.");
                }
                clips.Add(new AudioClipSource(
                    timelineEvent.Id,
                    asset.Id,
                    sourcePath,
                    timelineEvent.Start.Samples,
                    timelineEvent.End.Samples,
                    timelineEvent.Source?.Start.Samples ?? 0,
                    timelineEvent.Source?.Start.SampleRate ?? project.Timebase.SampleRate));
            }

            JsonObject? routing = track.Metadata["routing"] as JsonObject;
            routes.Add(new AudioTrackRoute(
                track.Id,
                ReadString(routing?["bus"]) ?? "master",
                ReadSingle(track.Metadata["gain"], 1),
                Math.Clamp(ReadSingle(track.Metadata["pan"], 0), -1, 1),
                track.Muted,
                track.Solo,
                clips.ToImmutable()));
        }

        return new AudioRenderGraph(new AudioEngineConfiguration(
            project.Id,
            deviceId.Trim(),
            project.Timebase.SampleRate,
            bufferFrames,
            routes.ToImmutable()));
    }

    private static bool IsAudioTrack(Track track) =>
        string.Equals(track.Type, "audio", StringComparison.OrdinalIgnoreCase) ||
        track.Events.Any(item => string.Equals(item.Type, "audio", StringComparison.OrdinalIgnoreCase));

    private static string? ReadString(JsonNode? node) =>
        node is JsonValue value && value.TryGetValue(out string? result) && !string.IsNullOrWhiteSpace(result)
            ? result.Trim()
            : null;

    private static float ReadSingle(JsonNode? node, float fallback) =>
        node is JsonValue value && value.TryGetValue(out float result) && float.IsFinite(result)
            ? result
            : fallback;
}

public enum AudioEngineCommandKind
{
    ReplaceGraph,
    Transport,
    Shutdown
}

public readonly record struct AudioEngineCommand(
    AudioEngineCommandKind Kind,
    AudioRenderGraph? Graph,
    TransportState? Transport);

public sealed class AudioEngineCommandQueue
{
    private readonly AudioEngineCommand[] _buffer;
    private int _readIndex;
    private int _writeIndex;

    public AudioEngineCommandQueue(int capacity = 256)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(capacity);
        _buffer = new AudioEngineCommand[checked(capacity + 1)];
    }

    public int Capacity => _buffer.Length - 1;

    public bool TryEnqueue(AudioEngineCommand command)
    {
        int write = _writeIndex;
        int next = Increment(write);
        if (next == Volatile.Read(ref _readIndex))
        {
            return false;
        }
        _buffer[write] = command;
        Volatile.Write(ref _writeIndex, next);
        return true;
    }

    public bool TryDequeue(out AudioEngineCommand command)
    {
        int read = _readIndex;
        if (read == Volatile.Read(ref _writeIndex))
        {
            command = default;
            return false;
        }
        command = _buffer[read];
        _buffer[read] = default;
        Volatile.Write(ref _readIndex, Increment(read));
        return true;
    }

    private int Increment(int index) => index + 1 == _buffer.Length ? 0 : index + 1;
}

public interface IAudioEngine : IAsyncDisposable
{
    event EventHandler<IReadOnlyList<AudioMeterSnapshot>>? MetersAvailable;

    IReadOnlyList<AudioDeviceDescriptor> Devices { get; }
    AudioEngineConfiguration? Configuration { get; }
    Task RefreshDevicesAsync(CancellationToken cancellationToken = default);
    Task ConfigureAsync(AudioEngineConfiguration configuration, CancellationToken cancellationToken = default);
    ValueTask EnqueueTransportStateAsync(TransportState state, CancellationToken cancellationToken = default);
}
