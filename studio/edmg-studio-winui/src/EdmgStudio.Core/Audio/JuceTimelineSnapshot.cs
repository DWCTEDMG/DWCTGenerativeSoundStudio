using EdmgStudio.Core.Models;
using System.Collections.Immutable;

namespace EdmgStudio.Core.Audio;

public interface IJuceTimelineSourceReader
{
  ValueTask<JuceTimelineSource> ReadAsync(string authorizedPath, CancellationToken cancellationToken = default);
}

public sealed class JuceTimelineSource
{
  private readonly float[] _samples;
  private readonly long _frameCount;

  public JuceTimelineSource(string path, int sampleRate, int channels, float[] interleavedSamples)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(path);
    ArgumentOutOfRangeException.ThrowIfNegativeOrZero(sampleRate);
    if (channels is < 1 or > 2)
    {
      throw new InvalidDataException("JUCE Timeline preview currently supports mono and stereo sources only.");
    }
    ArgumentNullException.ThrowIfNull(interleavedSamples);
    if (interleavedSamples.Length % channels != 0 || interleavedSamples.Any(sample => !float.IsFinite(sample)))
    {
      throw new InvalidDataException("Timeline source samples must contain complete, finite frames.");
    }

    Path = path.Trim();
    SampleRate = sampleRate;
    Channels = channels;
    _samples = (float[])interleavedSamples.Clone();
    _frameCount = _samples.LongLength / Channels;
  }

  private JuceTimelineSource(string path, int sampleRate, int channels, long frameCount)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(path);
    ArgumentOutOfRangeException.ThrowIfNegativeOrZero(sampleRate);
    if (channels is < 1 or > 2 || frameCount <= 0)
    {
      throw new InvalidDataException("File-backed JUCE Timeline sources require mono/stereo metadata and a positive frame count.");
    }
    Path = System.IO.Path.GetFullPath(path);
    SampleRate = sampleRate;
    Channels = channels;
    _frameCount = frameCount;
    _samples = [];
  }

  public static JuceTimelineSource CreateFileBacked(string path, int sampleRate, int channels, long frameCount) =>
      new(path, sampleRate, channels, frameCount);

  public string Path { get; }
  public int SampleRate { get; }
  public int Channels { get; }
  public long FrameCount => _frameCount;
  public bool IsFileBacked => _samples.Length == 0;

  internal ImmutableArray<float> ToImmutableSamples() => ImmutableArray.CreateRange(_samples);

  internal void ReadLinear(double sourceFrame, out float left, out float right)
  {
    if (IsFileBacked)
    {
      throw new InvalidOperationException("File-backed Timeline media is rendered by the native JUCE host.");
    }
    long first = (long)Math.Floor(sourceFrame);
    if (first < 0 || first >= FrameCount)
    {
      left = right = 0;
      return;
    }

    long second = Math.Min(first + 1, FrameCount - 1);
    float fraction = (float)(sourceFrame - first);
    int firstOffset = checked((int)(first * Channels));
    int secondOffset = checked((int)(second * Channels));
    left = Lerp(_samples[firstOffset], _samples[secondOffset], fraction);
    right = Channels == 1
        ? left
        : Lerp(_samples[firstOffset + 1], _samples[secondOffset + 1], fraction);
  }

  private static float Lerp(float first, float second, float amount) => first + ((second - first) * amount);
}

public sealed class FileBackedWaveTimelineSourceReader : IJuceTimelineSourceReader
{
  private readonly WavePcmExtractor _extractor = new();

  public async ValueTask<JuceTimelineSource> ReadAsync(
      string authorizedPath,
      CancellationToken cancellationToken = default)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(authorizedPath);
    string path = Path.GetFullPath(authorizedPath.Trim());
    await using FileStream stream = new(path, FileMode.Open, FileAccess.Read, FileShare.Read,
        bufferSize: 64 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
    WaveAudioMetadata metadata = await _extractor.ReadMetadataAsync(stream, cancellationToken).ConfigureAwait(false);
    return JuceTimelineSource.CreateFileBacked(path, metadata.SampleRate, metadata.Channels, metadata.FrameCount);
  }
}

public sealed class AuthorizedWaveTimelineSourceReader : IJuceTimelineSourceReader
{
  private readonly Func<string, CancellationToken, ValueTask<Stream>> _openAuthorizedSource;
  private readonly WavePcmExtractor _extractor = new();

  public AuthorizedWaveTimelineSourceReader(Func<string, CancellationToken, ValueTask<Stream>> openAuthorizedSource)
  {
    ArgumentNullException.ThrowIfNull(openAuthorizedSource);
    _openAuthorizedSource = openAuthorizedSource;
  }

  public async ValueTask<JuceTimelineSource> ReadAsync(string authorizedPath, CancellationToken cancellationToken = default)
  {
    ArgumentException.ThrowIfNullOrWhiteSpace(authorizedPath);
    await using Stream stream = await _openAuthorizedSource(authorizedPath.Trim(), cancellationToken).ConfigureAwait(false);
    ExtractedWaveAudio audio = await _extractor.ExtractAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
    return new JuceTimelineSource(authorizedPath, audio.SampleRate, audio.Channels, audio.InterleavedSamples);
  }
}

public sealed record JuceTimelineClipSnapshot(
    string EventId,
    long TimelineStartSample,
    long TimelineEndSample,
    long SourceStartSample,
    double PlaybackRate,
    long FadeInSamples,
    long FadeOutSamples,
    FadeCurve FadeCurve,
    JuceTimelineSource Source);

public sealed record JuceTimelineTrackSnapshot(
    string TrackId,
    float Gain,
    float Pan,
    ImmutableArray<JuceTimelineClipSnapshot> Clips)
{
  public float LeftGain { get; } = Gain * (Pan <= 0 ? 1 : MathF.Sqrt(1 - Pan));
  public float RightGain { get; } = Gain * (Pan >= 0 ? 1 : MathF.Sqrt(1 + Pan));
}

public sealed record JuceTimelineSnapshot(
    long Revision,
    int SampleRate,
    long DurationSamples,
    ImmutableArray<JuceTimelineTrackSnapshot> Tracks);

public static class JuceTimelineSnapshotBuilder
{
  public static async Task<JuceTimelineSnapshot> BuildAsync(
      long revision,
      AudioRenderGraph graph,
      ProfessionalEditingDocument editing,
      IJuceTimelineSourceReader sourceReader,
      CancellationToken cancellationToken = default)
  {
    ArgumentOutOfRangeException.ThrowIfNegative(revision);
    ArgumentNullException.ThrowIfNull(graph);
    ArgumentNullException.ThrowIfNull(editing);
    ArgumentNullException.ThrowIfNull(sourceReader);

    Dictionary<string, ClipEditingDescriptor> descriptors = editing.Clips.ToDictionary(item => item.ClipId, StringComparer.Ordinal);
    Dictionary<string, JuceTimelineSource> sources = new(StringComparer.OrdinalIgnoreCase);
    ImmutableArray<JuceTimelineTrackSnapshot>.Builder tracks = ImmutableArray.CreateBuilder<JuceTimelineTrackSnapshot>();
    long duration = 0;
    foreach (AudioTrackRoute route in graph.Configuration.Tracks)
    {
      cancellationToken.ThrowIfCancellationRequested();
      if (!graph.TryGetAudibleRoute(route.TrackId, out AudioTrackRoute? audibleRoute) || audibleRoute is null)
      {
        continue;
      }

      ImmutableArray<JuceTimelineClipSnapshot>.Builder clips = ImmutableArray.CreateBuilder<JuceTimelineClipSnapshot>();
      foreach (AudioClipSource clip in audibleRoute.Clips)
      {
        if (!sources.TryGetValue(clip.SourcePath, out JuceTimelineSource? source))
        {
          source = await sourceReader.ReadAsync(clip.SourcePath, cancellationToken).ConfigureAwait(false);
          sources.Add(clip.SourcePath, source);
        }
        if (source.SampleRate != clip.SourceSampleRate)
        {
          throw new InvalidDataException($"Audio clip '{clip.EventId}' declares {clip.SourceSampleRate} Hz but its source is {source.SampleRate} Hz.");
        }

        descriptors.TryGetValue(clip.EventId, out ClipEditingDescriptor? descriptor);
        ProcessDescriptor? process = descriptor?.Process;
        if (process?.Algorithm == ProcessAlgorithm.PhaseVocoder)
        {
          throw new NotSupportedException($"Audio clip '{clip.EventId}' requires phase-vocoder processing, which is not available in JUCE Timeline preview.");
        }
        double playbackRate = process?.PlaybackRate ?? 1;
        if (!double.IsFinite(playbackRate) || playbackRate is < .25 or > 4)
        {
          throw new InvalidDataException($"Audio clip '{clip.EventId}' has an invalid playback rate.");
        }

        FadeDescriptor? fades = descriptor?.Fades;
        long fadeIn = fades?.InSamples ?? 0;
        long fadeOut = fades?.OutSamples ?? 0;
        long clipDuration = clip.TimelineEndSample - clip.TimelineStartSample;
        if (fadeIn < 0 || fadeOut < 0 || fadeIn > clipDuration - fadeOut)
        {
          throw new InvalidDataException($"Fades on audio clip '{clip.EventId}' exceed its duration.");
        }

        JuceTimelineClipSnapshot preparedClip = new(
            clip.EventId, clip.TimelineStartSample, clip.TimelineEndSample, clip.SourceStartSample,
            playbackRate, fadeIn, fadeOut, fades?.Curve ?? FadeCurve.EqualPower, source);
        JuceTimelineRenderer.ValidateClip(preparedClip, graph.Configuration.SampleRate, clip.TimelineEndSample);
        clips.Add(preparedClip);
        duration = Math.Max(duration, clip.TimelineEndSample);
      }
      tracks.Add(new JuceTimelineTrackSnapshot(audibleRoute.TrackId, audibleRoute.Gain, audibleRoute.Pan, clips.ToImmutable()));
    }

    return new JuceTimelineSnapshot(revision, graph.Configuration.SampleRate, duration, tracks.ToImmutable());
  }
}

public static class JucePreparedTimelineProjection
{
  public static JucePreparedTimelineSnapshot Create(JuceTimelineSnapshot snapshot, bool preferFileBackedMedia = false)
  {
    ArgumentNullException.ThrowIfNull(snapshot);
    _ = new JuceTimelineRenderer(snapshot);
    Dictionary<JuceTimelineSource, string> sourceIds = new(ReferenceEqualityComparer.Instance);
    ImmutableArray<JucePreparedTimelineSource>.Builder sources = ImmutableArray.CreateBuilder<JucePreparedTimelineSource>();
    ImmutableArray<JucePreparedTimelineTrack>.Builder tracks = ImmutableArray.CreateBuilder<JucePreparedTimelineTrack>(snapshot.Tracks.Length);
    foreach (JuceTimelineTrackSnapshot track in snapshot.Tracks)
    {
      ImmutableArray<JucePreparedTimelineClip>.Builder clips = ImmutableArray.CreateBuilder<JucePreparedTimelineClip>(track.Clips.Length);
      foreach (JuceTimelineClipSnapshot clip in track.Clips)
      {
        if (!sourceIds.TryGetValue(clip.Source, out string? sourceId))
        {
          sourceId = $"source-{sourceIds.Count + 1}";
          sourceIds.Add(clip.Source, sourceId);
          bool useFile = (preferFileBackedMedia || clip.Source.IsFileBacked) &&
              Path.IsPathFullyQualified(clip.Source.Path) && File.Exists(clip.Source.Path);
          sources.Add(useFile
              ? new(sourceId, clip.Source.SampleRate, clip.Source.Channels, [],
                  Path.GetFullPath(clip.Source.Path), clip.Source.FrameCount)
              : new(sourceId, clip.Source.SampleRate, clip.Source.Channels, clip.Source.ToImmutableSamples()));
        }
        clips.Add(new(clip.EventId, clip.TimelineStartSample, clip.TimelineEndSample, clip.SourceStartSample,
            clip.PlaybackRate, clip.FadeInSamples, clip.FadeOutSamples, clip.FadeCurve switch
            {
              FadeCurve.Linear => "linear",
              FadeCurve.EqualPower => "equal_power",
              FadeCurve.SCurve => "s_curve",
              _ => throw new ArgumentOutOfRangeException(nameof(clip.FadeCurve))
            }, sourceId));
      }
      tracks.Add(new(track.TrackId, track.LeftGain, track.RightGain, clips.ToImmutable()));
    }

    JucePreparedTimelineSnapshot prepared = new(snapshot.Revision, snapshot.SampleRate, snapshot.DurationSamples,
        sources.ToImmutable(), tracks.ToImmutable());
    _ = JuceAudioEngineProtocol.Serialize(prepared);
    return prepared;
  }
}

public readonly record struct JuceTimelineRenderResult(long Revision, long StartSample, int Frames, bool SnapshotChanged);

public sealed class JuceTimelineRenderer
{
  private JuceTimelineSnapshot _published;
  private JuceTimelineSnapshot? _active;

  public JuceTimelineRenderer(JuceTimelineSnapshot initialSnapshot)
  {
    Validate(initialSnapshot);
    _published = initialSnapshot;
  }

  public JuceTimelineSnapshot Published => Volatile.Read(ref _published);

  public void Publish(JuceTimelineSnapshot snapshot)
  {
    Validate(snapshot);
    while (true)
    {
      JuceTimelineSnapshot current = Volatile.Read(ref _published);
      if (snapshot.Revision <= current.Revision)
      {
        throw new ArgumentException("JUCE Timeline snapshot revisions must increase.", nameof(snapshot));
      }
      if (ReferenceEquals(Interlocked.CompareExchange(ref _published, snapshot, current), current))
      {
        return;
      }
    }
  }

  public JuceTimelineRenderResult ProcessBlock(Span<float> interleavedStereoOutput, long startSample, int frames)
  {
    ArgumentOutOfRangeException.ThrowIfNegative(startSample);
    ArgumentOutOfRangeException.ThrowIfNegative(frames);
    if (interleavedStereoOutput.Length < checked(frames * 2))
    {
      throw new ArgumentException("The output buffer is too small.", nameof(interleavedStereoOutput));
    }

    if (frames > 0 && startSample > long.MaxValue - (frames - 1L))
    {
      throw new ArgumentOutOfRangeException(nameof(frames), "The requested block exceeds the Timeline sample range.");
    }

    JuceTimelineSnapshot snapshot = Volatile.Read(ref _published);
    bool changed = !ReferenceEquals(snapshot, _active);
    _active = snapshot;
    interleavedStereoOutput[..(frames * 2)].Clear();
    for (int frame = 0; frame < frames; frame++)
    {
      long timelineSample = startSample + frame;
      float mixedLeft = 0;
      float mixedRight = 0;
      foreach (JuceTimelineTrackSnapshot track in snapshot.Tracks)
      {
        foreach (JuceTimelineClipSnapshot clip in track.Clips)
        {
          if (timelineSample < clip.TimelineStartSample || timelineSample >= clip.TimelineEndSample)
          {
            continue;
          }
          long relative = timelineSample - clip.TimelineStartSample;
          double sourceFrame = clip.SourceStartSample +
              (relative * ((double)clip.Source.SampleRate / snapshot.SampleRate) * clip.PlaybackRate);
          clip.Source.ReadLinear(sourceFrame, out float left, out float right);
          float fade = FadeGain(clip, relative);
          mixedLeft += left * fade * track.LeftGain;
          mixedRight += right * fade * track.RightGain;
        }
      }
      interleavedStereoOutput[frame * 2] = mixedLeft;
      interleavedStereoOutput[(frame * 2) + 1] = mixedRight;
    }
    return new(snapshot.Revision, startSample, frames, changed);
  }

  private static float FadeGain(JuceTimelineClipSnapshot clip, long relative)
  {
    long duration = clip.TimelineEndSample - clip.TimelineStartSample;
    double gain = 1;
    if (clip.FadeInSamples > 0 && relative < clip.FadeInSamples)
    {
      gain = Curve((double)relative / clip.FadeInSamples, clip.FadeCurve);
    }
    long remaining = duration - relative - 1;
    if (clip.FadeOutSamples > 0 && remaining < clip.FadeOutSamples)
    {
      gain = Math.Min(gain, Curve((double)remaining / clip.FadeOutSamples, clip.FadeCurve));
    }
    return (float)gain;
  }

  private static double Curve(double value, FadeCurve curve)
  {
    value = Math.Clamp(value, 0, 1);
    return curve switch
    {
      FadeCurve.Linear => value,
      FadeCurve.EqualPower => Math.Sin(value * Math.PI / 2),
      FadeCurve.SCurve => value * value * (3 - (2 * value)),
      _ => throw new ArgumentOutOfRangeException(nameof(curve))
    };
  }

  private static void Validate(JuceTimelineSnapshot snapshot)
  {
    ArgumentNullException.ThrowIfNull(snapshot);
    ArgumentOutOfRangeException.ThrowIfNegative(snapshot.Revision);
    ArgumentOutOfRangeException.ThrowIfNegativeOrZero(snapshot.SampleRate);
    ArgumentOutOfRangeException.ThrowIfNegative(snapshot.DurationSamples);
    if (snapshot.Tracks.IsDefault)
    {
      throw new ArgumentException("JUCE Timeline snapshot tracks are invalid.", nameof(snapshot));
    }

    HashSet<string> trackIds = new(StringComparer.Ordinal);
    HashSet<string> eventIds = new(StringComparer.Ordinal);
    foreach (JuceTimelineTrackSnapshot track in snapshot.Tracks)
    {
      if (string.IsNullOrWhiteSpace(track.TrackId) || !trackIds.Add(track.TrackId) ||
          track.Clips.IsDefault || !float.IsFinite(track.Gain) || !float.IsFinite(track.Pan) ||
          track.Pan is < -1 or > 1 || !float.IsFinite(track.LeftGain) || !float.IsFinite(track.RightGain))
      {
        throw new ArgumentException("JUCE Timeline snapshot tracks are invalid.", nameof(snapshot));
      }

      foreach (JuceTimelineClipSnapshot clip in track.Clips)
      {
        if (!eventIds.Add(clip.EventId))
        {
          throw new ArgumentException($"JUCE Timeline event ID '{clip.EventId}' is duplicated.", nameof(snapshot));
        }
        ValidateClip(clip, snapshot.SampleRate, snapshot.DurationSamples);
      }
    }
  }

  internal static void ValidateClip(JuceTimelineClipSnapshot clip, int timelineSampleRate, long durationSamples)
  {
    if (string.IsNullOrWhiteSpace(clip.EventId) || clip.Source is null ||
        clip.TimelineStartSample < 0 || clip.TimelineEndSample <= clip.TimelineStartSample ||
        clip.TimelineEndSample > durationSamples || clip.SourceStartSample < 0 ||
        !double.IsFinite(clip.PlaybackRate) || clip.PlaybackRate is < .25 or > 4 ||
        clip.FadeInSamples < 0 || clip.FadeOutSamples < 0 ||
        clip.FadeInSamples > (clip.TimelineEndSample - clip.TimelineStartSample) - clip.FadeOutSamples ||
        !Enum.IsDefined(clip.FadeCurve))
    {
      throw new ArgumentException($"JUCE Timeline clip '{clip.EventId}' is invalid.", nameof(clip));
    }

    long relativeLast = clip.TimelineEndSample - clip.TimelineStartSample - 1;
    double sourceLast = clip.SourceStartSample +
        (relativeLast * ((double)clip.Source.SampleRate / timelineSampleRate) * clip.PlaybackRate);
    if (!double.IsFinite(sourceLast) || clip.SourceStartSample >= clip.Source.FrameCount ||
        Math.Floor(sourceLast) >= clip.Source.FrameCount)
    {
      throw new InvalidDataException($"Audio clip '{clip.EventId}' extends beyond its prepared source media.");
    }
  }
}
