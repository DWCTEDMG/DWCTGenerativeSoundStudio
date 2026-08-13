using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

public sealed class StudioSessionService
{
    private const string ProjectKey = "StudioSession.ActiveProjectId";
    private const string VariantKey = "StudioSession.SelectedVariant";
    private readonly ApplicationDataContainer? _settings;
    private string _fallbackProjectId = string.Empty;
    private int _fallbackVariant;

    public StudioSessionService()
    {
        try
        {
            _settings = ApplicationData.Current.LocalSettings;
        }
        catch
        {
            _settings = null;
        }
    }

    public event EventHandler? Changed;

    public string ActiveProjectId
    {
        get => _settings?.Values[ProjectKey] as string ?? _fallbackProjectId;
        set
        {
            var normalized = value?.Trim() ?? string.Empty;
            if (normalized == ActiveProjectId)
            {
                return;
            }

            if (_settings is not null)
            {
                _settings.Values[ProjectKey] = normalized;
                _settings.Values[VariantKey] = 0;
            }
            else
            {
                _fallbackProjectId = normalized;
                _fallbackVariant = 0;
            }

            Changed?.Invoke(this, EventArgs.Empty);
        }
    }

    public int SelectedVariantIndex
    {
        get
        {
            if (_settings?.Values[VariantKey] is int value)
            {
                return Math.Max(0, value);
            }

            return Math.Max(0, _fallbackVariant);
        }
        set
        {
            var normalized = Math.Max(0, value);
            if (normalized == SelectedVariantIndex)
            {
                return;
            }

            if (_settings is not null)
            {
                _settings.Values[VariantKey] = normalized;
            }
            else
            {
                _fallbackVariant = normalized;
            }

            Changed?.Invoke(this, EventArgs.Empty);
        }
    }
}
