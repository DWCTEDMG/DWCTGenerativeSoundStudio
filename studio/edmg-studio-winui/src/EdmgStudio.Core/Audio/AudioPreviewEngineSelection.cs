namespace EdmgStudio.Core.Audio;

public enum AudioPreviewEngine
{
  AudioGraph,
  Juce
}

public interface IAudioPreviewEnginePreferenceStore
{
  AudioPreviewEngine Load();
  void Save(AudioPreviewEngine engine);
}

public sealed record AudioPreviewEngineSelectionResult(
    bool Changed,
    AudioPreviewEngine SelectedEngine,
    string Message);

public sealed class AudioPreviewEngineSelection
{
  private readonly IAudioPreviewEnginePreferenceStore _store;
  private readonly Func<bool> _juceAvailable;
  private readonly object _sync = new();
  private AudioPreviewEngine _selectedEngine;

  public AudioPreviewEngineSelection(
      IAudioPreviewEnginePreferenceStore store,
      Func<bool> juceAvailable)
  {
    _store = store ?? throw new ArgumentNullException(nameof(store));
    _juceAvailable = juceAvailable ?? throw new ArgumentNullException(nameof(juceAvailable));
    AudioPreviewEngine saved = store.Load();
    _selectedEngine = saved == AudioPreviewEngine.Juce && !juceAvailable()
        ? AudioPreviewEngine.AudioGraph
        : saved;
    if (_selectedEngine != saved)
    {
      store.Save(_selectedEngine);
    }
  }

  public event EventHandler<AudioPreviewEngine>? SelectionChanged;

  public AudioPreviewEngine SelectedEngine
  {
    get
    {
      lock (_sync)
      {
        return _selectedEngine;
      }
    }
  }

  public AudioPreviewEngineSelectionResult Select(AudioPreviewEngine engine, TransportMode transportMode)
  {
    if (!Enum.IsDefined(engine))
    {
      throw new ArgumentOutOfRangeException(nameof(engine));
    }
    if (transportMode != TransportMode.Stopped)
    {
      return new(false, SelectedEngine, "Stop playback or recording before switching preview engines.");
    }
    if (engine == AudioPreviewEngine.Juce && !_juceAvailable())
    {
      return new(false, SelectedEngine, "The optional JUCE host executable is not installed. AudioGraph remains selected.");
    }

    bool changed;
    lock (_sync)
    {
      changed = _selectedEngine != engine;
      if (changed)
      {
        _selectedEngine = engine;
        _store.Save(engine);
      }
    }
    if (changed)
    {
      SelectionChanged?.Invoke(this, engine);
    }

    string message = engine == AudioPreviewEngine.AudioGraph
        ? "AudioGraph is selected as the default and rollback preview engine."
        : "JUCE is selected for Timeline output. Timeline starts the host and configures the saved device when preparing playback.";
    return new(changed, engine, message);
  }
}
