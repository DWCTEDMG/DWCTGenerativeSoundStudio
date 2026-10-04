using EdmgStudio.Core.Audio;
using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

internal sealed class WindowsAudioPreviewEnginePreferenceStore : IAudioPreviewEnginePreferenceStore
{
  private const string SettingKey = "Audio.PreviewEngine";
  private readonly ApplicationDataContainer? _settings;

  public WindowsAudioPreviewEnginePreferenceStore()
  {
    if (!WindowsPackageIdentity.IsPackaged)
    {
      return;
    }

    try
    {
      _settings = ApplicationData.Current.LocalSettings;
    }
    catch (Exception exception)
    {
      CrashLogger.Write("Unable to open packaged audio-preview settings; using AudioGraph for this session.", exception);
    }
  }

  public AudioPreviewEngine Load()
  {
    string? saved = _settings?.Values[SettingKey] as string;
    return Enum.TryParse(saved, ignoreCase: true, out AudioPreviewEngine engine) && Enum.IsDefined(engine)
        ? engine
        : AudioPreviewEngine.AudioGraph;
  }

  public void Save(AudioPreviewEngine engine)
  {
    if (_settings is null)
    {
      return;
    }

    try
    {
      _settings.Values[SettingKey] = engine.ToString();
    }
    catch (Exception exception)
    {
      CrashLogger.Write("Unable to persist the audio-preview engine; continuing for this session.", exception);
    }
  }
}
