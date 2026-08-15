using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI.Pages;

public sealed class TimelineLane
{
    internal JsonObject Source { get; init; } = [];
    public string AutomationKey { get; set; } = Guid.NewGuid().ToString("N");
    public string Name { get; set; } = "Untitled clip";
    public string Type { get; set; } = "clip";
    public double StartSeconds { get; set; }
    public double EndSeconds { get; set; } = 5;
    public string NameAutomationId => $"Timeline.Lane.{AutomationKey}.Name";
    public string StartAutomationId => $"Timeline.Lane.{AutomationKey}.Start";
    public string EndAutomationId => $"Timeline.Lane.{AutomationKey}.End";
    public string RemoveAutomationId => $"Timeline.Lane.{AutomationKey}.Remove";
}

public sealed partial class TimelinePage : Page
{
    private readonly Stack<string> _undo = new();
    private readonly Stack<string> _redo = new();
    private JsonObject _timeline = new() { ["layers"] = new JsonArray() };
    private string? _projectId;
    private bool _isBusy;
    private bool _isRecoveryAvailable;
    private CancellationTokenSource? _previewCancellation;
    private int _previewGeneration;

    public ObservableCollection<TimelineLane> Lanes { get; } = [];

    public TimelinePage()
    {
        InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _projectId = App.Services.Session.ActiveProjectId;
        await LoadTimelineAsync();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        CancelPreview();
        base.OnNavigatedFrom(e);
    }

    private async Task LoadTimelineAsync()
    {
        if (string.IsNullOrWhiteSpace(_projectId))
        {
            SetEnabledState(false);
            ShowStatus("Choose a project before editing its timeline.", InfoBarSeverity.Warning);
            return;
        }

        await RunBusyAsync(async () =>
        {
            JsonElement response = await App.Services.ApiClient.GetTimelineAsync(_projectId);
            JsonElement timeline = response.TryGetProperty("timeline", out JsonElement value) ? value : response;
            _timeline = JsonNode.Parse(timeline.GetRawText()) as JsonObject ?? new JsonObject();
            if (_timeline["layers"] is not JsonArray)
            {
                _timeline["layers"] = new JsonArray();
            }

            _undo.Clear();
            _redo.Clear();
            PopulateLanes();
            ProjectText.Text = $"Project {_projectId}";
            SetEnabledState(true);
            ShowStatus("Timeline loaded from the backend.", InfoBarSeverity.Success);
        });
    }

    private void PopulateLanes()
    {
        Lanes.Clear();
        foreach (JsonNode? node in _timeline["layers"]?.AsArray() ?? [])
        {
            if (node is not JsonObject item)
            {
                continue;
            }

            Lanes.Add(new TimelineLane
            {
                Source = item,
                AutomationKey = AutomationKey(item["id"]?.GetValue<string>()),
                Name = item["name"]?.GetValue<string>() ?? item["id"]?.GetValue<string>() ?? "Untitled clip",
                Type = item["type"]?.GetValue<string>() ?? item["kind"]?.GetValue<string>() ?? "clip",
                StartSeconds = ReadDouble(item["start_s"]),
                EndSeconds = ReadDouble(item["end_s"], 5),
            });
        }

        RawTimelineBox.Text = StudioPageHelpers.FormatJson(_timeline);
        UpdateHistoryButtons();
    }

    private void CaptureUndo()
    {
        _undo.Push(_timeline.ToJsonString());
        _redo.Clear();
        UpdateHistoryButtons();
    }

    private void RebuildTimelineFromLanes()
    {
        var layers = new JsonArray();
        foreach (TimelineLane lane in Lanes)
        {
            JsonObject item = lane.Source.DeepClone() as JsonObject ?? new JsonObject();
            item["name"] = lane.Name;
            item["type"] = lane.Type;
            item["start_s"] = Math.Max(0, lane.StartSeconds);
            item["end_s"] = Math.Max(lane.StartSeconds + 0.05, lane.EndSeconds);
            layers.Add((JsonNode)item);
        }

        _timeline["layers"] = layers;
        RawTimelineBox.Text = StudioPageHelpers.FormatJson(_timeline);
    }

    private JsonElement TimelineElement()
    {
        using JsonDocument document = JsonDocument.Parse(_timeline.ToJsonString());
        return document.RootElement.Clone();
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await LoadTimelineAsync();

    private async void LaneList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        await LoadSelectedFrameAsync(force: false);
        SetEnabledState(!_isBusy && !string.IsNullOrWhiteSpace(_projectId));
    }

    private async void PreviewFrameButton_Click(object sender, RoutedEventArgs e)
        => await LoadSelectedFrameAsync(force: true);

    private async Task LoadSelectedFrameAsync(bool force)
    {
        CancelPreview();
        int generation = Interlocked.Increment(ref _previewGeneration);
        if (LaneList.SelectedItem is not TimelineLane lane || string.IsNullOrWhiteSpace(_projectId))
        {
            PreviewFrameText.Text = "Select a lane to preview its start frame.";
            TimelinePreview.ShowEmpty("Select a lane to preview its start frame.");
            return;
        }

        double timeSeconds = Math.Max(0, lane.StartSeconds);
        PreviewFrameText.Text = $"{lane.Name} at {timeSeconds:N2} seconds";
        _previewCancellation = new CancellationTokenSource();
        CancellationToken cancellationToken = _previewCancellation.Token;
        try
        {
            await App.Services.ApiClient.StreamTimelineFrameAsync(
                _projectId,
                timeSeconds,
                640,
                360,
                force,
                async (file, callbackToken) =>
                {
                    if (generation != Volatile.Read(ref _previewGeneration))
                    {
                        return false;
                    }

                    await TimelinePreview.LoadStreamAsync(
                        file.Stream,
                        file.ContentHeaders.ContentType?.MediaType,
                        callbackToken);
                    return true;
                },
                cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            if (generation == Volatile.Read(ref _previewGeneration))
            {
                TimelinePreview.ShowError("Timeline frame could not be loaded.");
                ShowStatus(StudioPageHelpers.UserMessage(exception), InfoBarSeverity.Error);
            }
        }
    }

    private void CancelPreview()
    {
        Interlocked.Increment(ref _previewGeneration);
        CancellationTokenSource? cancellation = Interlocked.Exchange(ref _previewCancellation, null);
        cancellation?.Cancel();
        cancellation?.Dispose();
    }

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        if (_projectId is null)
        {
            return;
        }

        await RunBusyAsync(async () =>
        {
            RebuildTimelineFromLanes();
            await App.Services.ApiClient.SaveTimelineAsync(_projectId, TimelineElement());
            ShowStatus("Timeline saved and snapshotted.", InfoBarSeverity.Success);
        });
    }

    private async void AutosaveButton_Click(object sender, RoutedEventArgs e)
    {
        if (_projectId is null)
        {
            return;
        }

        await RunBusyAsync(async () =>
        {
            RebuildTimelineFromLanes();
            using JsonDocument emptyMeta = JsonDocument.Parse("{}");
            await App.Services.ApiClient.AutosaveTimelineAsync(
                _projectId,
                TimelineElement(),
                emptyMeta.RootElement.Clone(),
                "winui_timeline_autosave");
            ShowStatus("Autosave journal updated.", InfoBarSeverity.Success);
        });
    }

    private void AddLaneButton_Click(object sender, RoutedEventArgs e)
    {
        RebuildTimelineFromLanes();
        CaptureUndo();
        Lanes.Add(new TimelineLane
        {
            Source = new JsonObject { ["id"] = Guid.NewGuid().ToString("N") },
            AutomationKey = Guid.NewGuid().ToString("N"),
            Name = $"Clip {Lanes.Count + 1}",
            Type = "clip",
            EndSeconds = 5,
        });
        RebuildTimelineFromLanes();
    }

    private void RemoveLaneButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: TimelineLane lane })
        {
            return;
        }

        RebuildTimelineFromLanes();
        CaptureUndo();
        Lanes.Remove(lane);
        RebuildTimelineFromLanes();
    }

    private void ApplyJsonButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            JsonObject parsed = JsonNode.Parse(RawTimelineBox.Text) as JsonObject
                ?? throw new JsonException("The timeline root must be a JSON object.");
            if (parsed["layers"] is not JsonArray)
            {
                throw new JsonException("The timeline must contain a layers array.");
            }

            RebuildTimelineFromLanes();
            CaptureUndo();
            _timeline = parsed;
            PopulateLanes();
            ShowStatus("JSON applied locally. Save to persist it.", InfoBarSeverity.Success);
        }
        catch (Exception exception)
        {
            ShowStatus(exception.Message, InfoBarSeverity.Error);
        }
    }

    private void UndoButton_Click(object sender, RoutedEventArgs e)
    {
        if (_undo.TryPop(out string? previous))
        {
            _redo.Push(_timeline.ToJsonString());
            _timeline = JsonNode.Parse(previous) as JsonObject ?? new JsonObject();
            PopulateLanes();
        }
    }

    private void RedoButton_Click(object sender, RoutedEventArgs e)
    {
        if (_redo.TryPop(out string? next))
        {
            _undo.Push(_timeline.ToJsonString());
            _timeline = JsonNode.Parse(next) as JsonObject ?? new JsonObject();
            PopulateLanes();
        }
    }

    private async void CheckRecoveryButton_Click(object sender, RoutedEventArgs e)
    {
        if (_projectId is null)
        {
            return;
        }

        await RunBusyAsync(async () =>
        {
            JsonElement state = await App.Services.ApiClient.GetRecoveryAsync(_projectId);
            RecoveryText.Text = StudioPageHelpers.PrettyJson(state);
            _isRecoveryAvailable = ReadBoolean(state, "needs_recovery")
                || ReadBoolean(state, "recoverable")
                || ReadBoolean(state, "has_journal");
        });
    }

    private async void RestoreRecoveryButton_Click(object sender, RoutedEventArgs e)
    {
        if (_projectId is null)
        {
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Restore autosave journal?",
            Content = "This replaces the current project state with the recoverable journal.",
            PrimaryButtonText = "Restore",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        var restored = false;
        await RunBusyAsync(async () =>
        {
            await App.Services.ApiClient.ApplyRecoveryAsync(_projectId, new RecoveryApplyRequest());
            restored = true;
        });

        if (restored)
        {
            await LoadTimelineAsync();
            ShowStatus("Autosave journal restored.", InfoBarSeverity.Success);
        }
    }

    private async Task RunBusyAsync(Func<Task> operation)
    {
        if (_isBusy)
        {
            return;
        }

        _isBusy = true;
        SetEnabledState(false);
        try
        {
            await operation();
        }
        catch (Exception exception)
        {
            ShowStatus(StudioPageHelpers.UserMessage(exception), InfoBarSeverity.Error);
        }
        finally
        {
            _isBusy = false;
            SetEnabledState(!string.IsNullOrWhiteSpace(_projectId));
        }
    }

    private void SetEnabledState(bool enabled)
    {
        RefreshButton.IsEnabled = !_isBusy && !string.IsNullOrWhiteSpace(_projectId);
        SaveButton.IsEnabled = enabled && !_isBusy;
        AutosaveButton.IsEnabled = enabled && !_isBusy;
        AddLaneButton.IsEnabled = enabled && !_isBusy;
        ApplyJsonButton.IsEnabled = enabled && !_isBusy;
        CheckRecoveryButton.IsEnabled = enabled && !_isBusy;
        RestoreRecoveryButton.IsEnabled = enabled && !_isBusy && _isRecoveryAvailable;
        PreviewFrameButton.IsEnabled =
            enabled && !_isBusy && LaneList.SelectedItem is TimelineLane;
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusBar.Message = message;
        StatusBar.Severity = severity;
        StatusBar.IsOpen = true;
    }

    private void UpdateHistoryButtons()
    {
        UndoButton.IsEnabled = _undo.Count > 0 && !_isBusy;
        RedoButton.IsEnabled = _redo.Count > 0 && !_isBusy;
    }

    private static double ReadDouble(JsonNode? value, double fallback = 0)
    {
        try
        {
            return value?.GetValue<double>() ?? fallback;
        }
        catch
        {
            return fallback;
        }
    }

    private static bool ReadBoolean(JsonElement value, string propertyName)
        => value.ValueKind == JsonValueKind.Object
            && value.TryGetProperty(propertyName, out var property)
            && property.ValueKind is JsonValueKind.True or JsonValueKind.False
            && property.GetBoolean();

    private static string AutomationKey(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return Guid.NewGuid().ToString("N");
        }

        return string.Concat(value.Where(character => char.IsLetterOrDigit(character) || character is '-' or '_'));
    }
}
