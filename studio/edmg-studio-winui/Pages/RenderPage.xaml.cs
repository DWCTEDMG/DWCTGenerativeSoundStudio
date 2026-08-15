using System;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class RenderPage : Page
{
    private string? _projectId;
    private bool _isBusy;

    public RenderPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _projectId = App.Services.Session.ActiveProjectId;
        ProjectText.Text = _projectId is null ? "No active project" : $"Project {StudioPageHelpers.ShortId(_projectId)}";
        SetEnabledState();
        if (_projectId is null)
        {
            ShowStatus("Choose a project before configuring a render.", InfoBarSeverity.Warning);
        }
    }

    private JsonElement BuildRequest()
    {
        var prompt = PromptBox.Text.Trim();
        var seed = Number(SeedBox, -1);
        var request = new JsonObject
        {
            ["variant_index"] = Math.Max(0, App.Services.Session.SelectedVariantIndex),
            ["fps_output"] = Number(FpsBox, 24),
            ["fps_render"] = Math.Min(Number(FpsBox, 24), 30),
            ["width"] = Number(WidthBox, 1280),
            ["height"] = Number(HeightBox, 720),
            ["steps"] = Number(StepsBox, 28),
            ["cfg"] = CfgBox.Value,
            ["sampler"] = Selected(SamplerBox, "euler"),
            ["seed"] = seed < 0 ? null : seed,
            ["keyframe_interval_s"] = KeyframeBox.Value,
            ["interpolation_engine"] = NormalizeInterpolation(InterpolationBox.Text),
            ["model_id"] = EmptyToNull(ModelBox.Text) ?? "auto",
            ["render_mode"] = HostedBox.IsOn ? "hosted" : Selected(ModeBox, "auto"),
            ["render_tier"] = Selected(TierBox, "balanced"),
            ["device_preference"] = Selected(DeviceBox, "auto"),
            ["allow_hosted_fallback"] = HostedFallbackBox.IsOn,
            ["hosted_service"] = NormalizeHostedService(ProviderBox),
            ["hosted_model"] = EmptyToNull(HostedModelBox.Text),
            ["negative_prompt"] = NegativePromptBox.Text.Trim(),
            ["loras"] = ParseLoras(LoraBox.Text),
            ["vae"] = EmptyToNull(VaeBox.Text),
            ["refiner"] = BuildRefiner(),
            ["temporal_mode"] = "keyframes",
            ["temporal_strength"] = TemporalBox.Value,
            ["motion_strategy"] = MotionBox.Value > 1.0 ? "storyboard_full_motion" : "manual",
            ["parseq_enabled"] = !string.IsNullOrWhiteSpace(DeforumBox.Text),
            ["parseq_manifest"] = ParseOptionalObject(DeforumBox.Text, "Parseq manifest"),
            ["source_asset"] = EmptyToNull(VideoAssetBox.Text),
            ["source_strength"] = Math.Clamp(MotionBox.Value / 5.0, 0.05, 0.95),
            ["deforum_prompts"] = string.IsNullOrWhiteSpace(prompt)
                ? null
                : new JsonObject { ["0"] = prompt },
        };

        return StudioPageHelpers.ToElement(request);
    }

    private static string NormalizeInterpolation(string value)
        => value.Trim().ToLowerInvariant() switch
        {
            "minterpolate" => "minterpolate",
            "fps" => "fps",
            "rife" => "rife",
            _ => "auto",
        };

    private static string NormalizeHostedService(ComboBox comboBox)
        => Selected(comboBox, "default").ToLowerInvariant() switch
        {
            "core" => "core",
            "ultra" => "ultra",
            "sd3" => "sd3",
            _ => "default",
        };

    private static JsonArray ParseLoras(string value)
    {
        var result = new JsonArray();
        foreach (var entry in value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var parts = entry.Split('@', 2, StringSplitOptions.TrimEntries);
            if (string.IsNullOrWhiteSpace(parts[0]))
            {
                continue;
            }

            var weight = parts.Length == 2 &&
                double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed)
                    ? Math.Clamp(parsed, -4.0, 4.0)
                    : 1.0;
            result.Add((JsonNode)new JsonObject { ["name"] = parts[0], ["weight"] = weight });
        }

        return result;
    }

    private static JsonObject? ParseOptionalObject(string value, string label)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        try
        {
            return JsonNode.Parse(value) as JsonObject
                ?? throw new InvalidOperationException($"{label} must be a JSON object.");
        }
        catch (JsonException exception)
        {
            throw new InvalidOperationException($"{label} contains invalid JSON.", exception);
        }
    }

    private JsonObject? BuildRefiner()
    {
        var model = EmptyToNull(RefinerBox.Text);
        return model is null ? null : new JsonObject { ["model"] = model, ["switch_at"] = 0.8 };
    }

    private async void PreflightButton_Click(object sender, RoutedEventArgs e)
    {
        if (_projectId is null)
        {
            return;
        }

        await RunBusyAsync(async () =>
        {
            JsonElement request = BuildRequest();
            JsonElement result = await App.Services.ApiClient.PreflightInternalRenderAsync(_projectId, request);
            PreflightResultBox.Text = StudioPageHelpers.PrettyJson(result);
            ShowStatus("Preflight completed. Review the checks before rendering.", InfoBarSeverity.Success);
        });
    }

    private async void RenderButton_Click(object sender, RoutedEventArgs e)
    {
        if (_projectId is null)
        {
            return;
        }

        await RunBusyAsync(async () =>
        {
            JsonElement request = BuildRequest();
            JsonElement result = await App.Services.ApiClient.StartInternalRenderAsync(_projectId, request);
            string jobId = result.TryGetProperty("job_id", out JsonElement id)
                ? id.GetString() ?? "queued"
                : result.TryGetProperty("job", out JsonElement job) && job.TryGetProperty("id", out JsonElement nestedId)
                    ? nestedId.GetString() ?? "queued"
                    : "queued";
            PreflightResultBox.Text = StudioPageHelpers.PrettyJson(result);
            ShowStatus($"Render {StudioPageHelpers.ShortId(jobId)} queued. Track it in Queue.", InfoBarSeverity.Success);
        });
    }

    private async Task RunBusyAsync(Func<Task> operation)
    {
        if (_isBusy)
        {
            return;
        }

        _isBusy = true;
        SetEnabledState();
        try
        {
            await operation();
        }
        catch (JsonException exception)
        {
            ShowStatus($"Advanced schedule JSON is invalid: {exception.Message}", InfoBarSeverity.Error);
        }
        catch (Exception exception)
        {
            ShowStatus(StudioPageHelpers.UserMessage(exception), InfoBarSeverity.Error);
        }
        finally
        {
            _isBusy = false;
            SetEnabledState();
        }
    }

    private void SetEnabledState()
    {
        bool enabled = !_isBusy && _projectId is not null;
        PreflightButton.IsEnabled = enabled;
        RenderButton.IsEnabled = enabled;
        BusyRing.IsActive = _isBusy;
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusBar.Message = message;
        StatusBar.Severity = severity;
        StatusBar.IsOpen = true;
    }

    private static int Number(NumberBox numberBox, int fallback)
        => double.IsNaN(numberBox.Value) ? fallback : Convert.ToInt32(numberBox.Value);

    private static string Selected(ComboBox comboBox, string fallback)
        => comboBox.SelectedItem as string ?? comboBox.SelectedValue as string ?? fallback;

    private static string? EmptyToNull(string value)
        => string.IsNullOrWhiteSpace(value) ? null : value.Trim();
}
