using EdmgStudio.Core.Audio;
using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

internal sealed class WindowsAudioPreviewEnginePreferenceStore : IAudioPreviewEnginePreferenceStore
{
  private const string SettingKey = "Audio.PreviewEngine";

  public AudioPreviewEngine Load()
  {
    string? saved = ApplicationData.Current.LocalSettings.Values[SettingKey] as string;
    return Enum.TryParse(saved, ignoreCase: true, out AudioPreviewEngine engine) && Enum.IsDefined(engine)
        ? engine
        : AudioPreviewEngine.AudioGraph;
  }

  public void Save(AudioPreviewEngine engine)
  {
    ApplicationData.Current.LocalSettings.Values[SettingKey] = engine.ToString();
  }
}
