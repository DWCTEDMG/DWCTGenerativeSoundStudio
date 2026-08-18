using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.Storage;
using Windows.UI;
using Windows.UI.ViewManagement;

namespace EdmgStudio.WinUI.Services;

internal static class StudioAppearanceService
{
    private const string ThemeSettingKey = "edmg_studio_theme_v1";
    private static readonly IReadOnlyDictionary<string, StudioPalette> Palettes =
        new Dictionary<string, StudioPalette>(StringComparer.OrdinalIgnoreCase)
        {
            ["studio"] = new("#041417", "#E6091719", "#E6061214", "#472CD6E0", "#EEF5F4", "#AEBAA8", "#35D8DF", "#94B7D8", "#FF7A66", "#6FF0BA"),
            ["ember"] = new("#140D0C", "#D61F100E", "#EB180C0B", "#47EC835E", "#F8EDE8", "#D3BBB0", "#FF8B61", "#FFBF9A", "#FF8676", "#FFD17A"),
            ["aurora"] = new("#07111B", "#D60A1623", "#EB08121D", "#425EB8FF", "#EEF7FF", "#B4C7DA", "#57C9FF", "#8EDCFF", "#FF8D88", "#74F1D0"),
            ["atlas"] = new("#0A1410", "#D60C1812", "#EB0A130F", "#3D76C38C", "#EFF7F1", "#B7C9BA", "#7DE0A1", "#A9DFBA", "#FF8C7D", "#B8F08D"),
        };

    public static IReadOnlyList<string> ThemeIds { get; } = ["studio", "ember", "aurora", "atlas"];

    public static string CurrentThemeId
    {
        get
        {
            string? value = ApplicationData.Current.LocalSettings.Values[ThemeSettingKey] as string;
            return value is not null && Palettes.ContainsKey(value) ? value.ToLowerInvariant() : "studio";
        }
    }

    public static void ApplySavedTheme(FrameworkElement root) => ApplyTheme(CurrentThemeId, root, persist: false);

    public static void ApplyTheme(string themeId, FrameworkElement root, bool persist = true)
    {
        if (!Palettes.TryGetValue(themeId, out StudioPalette? palette))
        {
            throw new ArgumentException($"Unsupported Studio appearance '{themeId}'.", nameof(themeId));
        }

        if (persist)
        {
            ApplicationData.Current.LocalSettings.Values[ThemeSettingKey] = themeId.ToLowerInvariant();
        }

        ResourceDictionary? studioResources = Application.Current.Resources.MergedDictionaries
            .FirstOrDefault(dictionary =>
                dictionary.Source?.OriginalString.EndsWith("StudioTheme.xaml", StringComparison.OrdinalIgnoreCase) == true);
        if (studioResources?.ThemeDictionaries["Dark"] is not ResourceDictionary darkResources)
        {
            return;
        }

        SetBrush(darkResources, "StudioBackgroundBrush", palette.Background);
        SetBrush(darkResources, "AppCanvasBrush", palette.Background);
        SetBrush(darkResources, "StudioCardBrush", palette.Panel);
        SetBrush(darkResources, "CardBackgroundBrush", palette.Panel);
        SetBrush(darkResources, "StudioBorderBrush", palette.Border);
        SetBrush(darkResources, "CardStrokeBrush", palette.Border);
        SetBrush(darkResources, "StudioTextBrush", palette.Text);
        SetBrush(darkResources, "StudioMutedTextBrush", palette.Muted);
        SetBrush(darkResources, "SecondaryTextBrush", palette.Muted);
        SetBrush(darkResources, "StudioAccentBrush", palette.Accent);
        SetBrush(darkResources, "StudioAccentForegroundBrush", Color.FromArgb(0xFF, 0x03, 0x14, 0x17));
        SetBrush(darkResources, "StudioAccentSoftBrush", palette.AccentSoft);
        SetBrush(darkResources, "StudioDangerBrush", palette.Danger);
        SetBrush(darkResources, "StudioSuccessBrush", palette.Success);
        SetBrush(darkResources, "StudioNavigationPaneBrush", palette.PanelSecondary);
        SetBrush(darkResources, "StudioLogoPanelBrush", palette.PanelSecondary);
        SetBrush(darkResources, "StudioTitleBarBrush", palette.PanelSecondary);
        SetBrush(darkResources, "AccentButtonBackground", palette.Accent);
        SetBrush(darkResources, "AccentButtonForeground", Color.FromArgb(0xFF, 0x03, 0x14, 0x17));
        SetBrush(darkResources, "NavigationViewSelectionIndicatorForeground", palette.Accent);

        SetGradient(darkResources, "StudioContentScrimBrush", palette.Background);
        SetGradient(darkResources, "StudioWorkspaceScrimBrush", palette.Background);

        // All four canonical Studio palettes are dark. High Contrast remains authoritative and
        // uses the separate HighContrast resource dictionary without any palette overrides.
        if (!new AccessibilitySettings().HighContrast)
        {
            root.RequestedTheme = ElementTheme.Dark;
        }
    }

    private static void SetBrush(ResourceDictionary dictionary, string key, Color color)
    {
        if (dictionary.ContainsKey(key) && dictionary[key] is SolidColorBrush brush)
        {
            brush.Color = color;
        }
    }

    private static void SetGradient(ResourceDictionary dictionary, string key, Color color)
    {
        if (!dictionary.ContainsKey(key) || dictionary[key] is not LinearGradientBrush gradient)
        {
            return;
        }

        foreach (GradientStop stop in gradient.GradientStops)
        {
            stop.Color = Color.FromArgb(stop.Color.A, color.R, color.G, color.B);
        }
    }

    private sealed record StudioPalette(
        Color Background,
        Color Panel,
        Color PanelSecondary,
        Color Border,
        Color Text,
        Color Muted,
        Color Accent,
        Color AccentSoft,
        Color Danger,
        Color Success)
    {
        public StudioPalette(
            string background,
            string panel,
            string panelSecondary,
            string border,
            string text,
            string muted,
            string accent,
            string accentSoft,
            string danger,
            string success)
            : this(
                ParseColor(background),
                ParseColor(panel),
                ParseColor(panelSecondary),
                ParseColor(border),
                ParseColor(text),
                ParseColor(muted),
                ParseColor(accent),
                ParseColor(accentSoft),
                ParseColor(danger),
                ParseColor(success))
        {
        }

        private static Color ParseColor(string value)
        {
            string hex = value.TrimStart('#');
            uint parsed = Convert.ToUInt32(hex, 16);
            return hex.Length == 8
                ? Color.FromArgb((byte)(parsed >> 24), (byte)(parsed >> 16), (byte)(parsed >> 8), (byte)parsed)
                : Color.FromArgb(0xFF, (byte)(parsed >> 16), (byte)(parsed >> 8), (byte)parsed);
        }
    }
}
