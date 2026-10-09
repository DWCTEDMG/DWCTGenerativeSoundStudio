using EdmgStudio.Core.Audio;
using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

internal sealed class WindowsAudioPreviewEnginePreferenceStore : IAudioPreviewEnginePreferenceStore
{
  private static readonly string PreferencePath = Path.Combine(
      Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "EDMGStudio", "audio-preview.json");
  internal sealed record Preferences(AudioPreviewEngine Engine = AudioPreviewEngine.AudioGraph,
      string? DeviceId = null, int SampleRate = 48000, int BufferFrames = 512);

  internal static Preferences ReadPreferences(string? path = null)
  {
    try
    {
      return File.Exists(path ?? PreferencePath)
          ? System.Text.Json.JsonSerializer.Deserialize<Preferences>(File.ReadAllText(path ?? PreferencePath)) ?? new()
          : new();
    }
    catch (Exception exception)
    {
      CrashLogger.Write("Unable to read local audio preferences; using defaults.", exception);
      return new();
    }
  }

  internal static void WritePreferences(Preferences preferences, string? path = null)
  {
    path ??= PreferencePath;
    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
    string temporary = path + ".tmp";
    File.WriteAllText(temporary, System.Text.Json.JsonSerializer.Serialize(preferences));
    File.Move(temporary, path, overwrite: true);
  }

  private const string SettingKey = "Audio.PreviewEngine";
  private readonly ApplicationDataContainer? _settings;
  private readonly string? _path;

  public WindowsAudioPreviewEnginePreferenceStore(string? path = null)
  {
    _path = path;
    if (path is not null || !WindowsPackageIdentity.IsPackaged)
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
    string? saved = _settings?.Values[SettingKey] as string ?? ReadPreferences(_path).Engine.ToString();
    return Enum.TryParse(saved, ignoreCase: true, out AudioPreviewEngine engine) && Enum.IsDefined(engine)
        ? engine
        : AudioPreviewEngine.AudioGraph;
  }

  public void Save(AudioPreviewEngine engine)
  {
    try
    {
      WritePreferences(ReadPreferences(_path) with { Engine = engine }, _path);
      if (_settings is not null)
      {
        _settings.Values[SettingKey] = engine.ToString();
      }
    }
    catch (Exception exception)
    {
      CrashLogger.Write("Unable to persist the audio-preview engine; continuing for this session.", exception);
    }
  }
}
