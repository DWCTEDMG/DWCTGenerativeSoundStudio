namespace EdmgStudio.Core.Audio;

public sealed class JuceGeneratedTransport
{
  private JuceTransportConfiguration? _configuration;
  private long _positionSamples;
  private long _seekSequence;
  private bool _playing;
  private bool _loopEnabled;
  private long _loopStartSample;
  private long _loopEndSample;

  public JuceTransportPosition Position => CreatePosition();

  public JuceTransportPosition Configure(JuceTransportConfiguration configuration)
  {
    ArgumentNullException.ThrowIfNull(configuration);
    ArgumentOutOfRangeException.ThrowIfNegative(configuration.ProjectRevision);
    ArgumentOutOfRangeException.ThrowIfNegativeOrZero(configuration.SampleRate);
    ArgumentOutOfRangeException.ThrowIfNegative(configuration.DurationSamples);
    if (!double.IsFinite(configuration.ToneFrequencyHz) || configuration.ToneFrequencyHz <= 0 ||
        configuration.ToneFrequencyHz >= configuration.SampleRate / 2.0)
    {
      throw new ArgumentOutOfRangeException(nameof(configuration));
    }

    _configuration = configuration;
    _positionSamples = 0;
    _seekSequence = 0;
    _playing = false;
    _loopEnabled = false;
    _loopStartSample = 0;
    _loopEndSample = configuration.DurationSamples;
    return CreatePosition();
  }

  public JuceTransportPosition Apply(JuceTransportCommand command)
  {
    ArgumentNullException.ThrowIfNull(command);
    JuceTransportConfiguration configuration = RequireConfiguration();
    string action = command.Action?.Trim().ToLowerInvariant() ?? string.Empty;
    switch (action)
    {
      case "play":
        if (_positionSamples >= configuration.DurationSamples)
        {
          _positionSamples = _loopEnabled ? _loopStartSample : 0;
        }
        _playing = true;
        break;
      case "pause":
        _playing = false;
        break;
      case "stop":
        _playing = false;
        _positionSamples = 0;
        break;
      case "seek":
        if (command.PositionSamples is null || command.SeekSequence <= _seekSequence)
        {
          throw new ArgumentException("Seek requires a position and an increasing seek sequence.", nameof(command));
        }
        _positionSamples = Math.Clamp(command.PositionSamples.Value, 0, configuration.DurationSamples);
        _seekSequence = command.SeekSequence;
        break;
      case "loop":
        ApplyLoop(command, configuration.DurationSamples);
        break;
      default:
        throw new ArgumentException("Unsupported JUCE transport action.", nameof(command));
    }

    return CreatePosition();
  }

  public JuceTransportPosition Advance(int frames)
  {
    ArgumentOutOfRangeException.ThrowIfNegative(frames);
    JuceTransportConfiguration configuration = RequireConfiguration();
    if (!_playing || frames == 0)
    {
      return CreatePosition();
    }

    long advanced = checked(_positionSamples + frames);
    if (_loopEnabled && advanced >= _loopEndSample)
    {
      long loopLength = _loopEndSample - _loopStartSample;
      _positionSamples = _loopStartSample + ((advanced - _loopStartSample) % loopLength);
    }
    else if (advanced >= configuration.DurationSamples)
    {
      _positionSamples = configuration.DurationSamples;
      _playing = false;
    }
    else
    {
      _positionSamples = advanced;
    }

    return CreatePosition();
  }

  private void ApplyLoop(JuceTransportCommand command, long durationSamples)
  {
    bool enabled = command.LoopEnabled ?? throw new ArgumentException("Loop requires an enabled value.", nameof(command));
    long start = Math.Clamp(command.LoopStartSample ?? 0, 0, durationSamples);
    long end = Math.Clamp(command.LoopEndSample ?? durationSamples, 0, durationSamples);
    if (enabled && end <= start)
    {
      throw new ArgumentException("Loop end must be after loop start.", nameof(command));
    }

    _loopEnabled = enabled;
    _loopStartSample = start;
    _loopEndSample = end;
  }

  private JuceTransportConfiguration RequireConfiguration() =>
      _configuration ?? throw new InvalidOperationException("Generated transport is not configured.");

  private JuceTransportPosition CreatePosition()
  {
    JuceTransportConfiguration configuration = RequireConfiguration();
    return new(configuration.ProjectRevision, _positionSamples, configuration.SampleRate,
        _playing ? "playing" : "stopped", _loopEnabled, _loopStartSample, _loopEndSample, _seekSequence);
  }
}
