using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.UI;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class TimelinePage : Page
{
    private const double DefaultDurationSeconds = 60;
    private const double DefaultFps = 30;
    private const double TrackHeight = 56;
    private const double ClipVerticalInset = 6;
    private const double MinimumPixelsPerSecond = 12;
    private const double MaximumPixelsPerSecond = 360;
    private const int HistoryLimit = 50;

    private readonly DispatcherTimer _transportTimer = new()
    {
        Interval = TimeSpan.FromMilliseconds(1000 / DefaultFps)
    };
    private readonly Stopwatch _transportWatch = new();
    private readonly List<JsonObject> _undoHistory = [];
    private readonly List<JsonObject> _redoHistory = [];

    private CancellationTokenSource? _pageCancellation;
    private CancellationTokenSource? _previewCancellation;
    private JsonObject? _timelineDocument;
    private JsonObject? _recoveryDocument;
    private IReadOnlyList<TimelineLaneDocument> _lanes = [];
    private ProjectDto? _project;
    private string? _loadedProjectId;
    private string? _selectedLaneId;
    private Border? _selectedClipBorder;
    private Line? _playheadLine;
    private TimelineLaneDocument? _dragOriginalLane;
    private TimelineLaneDocument? _dragProvisionalLane;
    private JsonObject? _dragBeforeSnapshot;
    private Border? _dragBorder;
    private uint _dragPointerId;
    private Point _dragStartPoint;
    private DragMode _dragMode;
    private double _durationSeconds = DefaultDurationSeconds;
    private double _positionSeconds;
    private double _transportAnchorSeconds;
    private double _pixelsPerSecond = 80;
    private long _previewGeneration;
    private bool _isLoaded;
    private bool _isBusy;
    private bool _isDirty;
    private bool _isPlaying;
    private bool _positionPointerActive;
    private bool _updatingPosition;
    private bool _syncingScroll;

    public TimelinePage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        _transportTimer.Tick += TransportTimer_Tick;
        UpdateTransportUi();
        UpdateCommandState();
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_isLoaded)
        {
            return;
        }

        _isLoaded = true;
        App.Services.Session.Changed += Session_Changed;
        await LoadActiveProjectAsync();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (!_isLoaded)
        {
            return;
        }

        _isLoaded = false;
        App.Services.Session.Changed -= Session_Changed;
        StopPlayback();
        CancelPreview();
        _pageCancellation?.Cancel();
        _pageCancellation?.Dispose();
        _pageCancellation = null;
    }

    private void Session_Changed(object? sender, EventArgs e)
    {
        if (!_isLoaded)
        {
            return;
        }

        DispatcherQueue.TryEnqueue(async () => await LoadActiveProjectAsync());
    }

    private async Task LoadActiveProjectAsync(bool forceReload = false)
    {
        string? projectId = App.Services.Session.ActiveProjectId;
        if (string.IsNullOrWhiteSpace(projectId))
        {
            ClearTimeline("Select a project in Projects to begin editing.");
            return;
        }

        if (!forceReload &&
            _isBusy &&
            string.Equals(_loadedProjectId, projectId, StringComparison.Ordinal))
        {
            return;
        }

        _pageCancellation?.Cancel();
        _pageCancellation?.Dispose();
        _pageCancellation = new CancellationTokenSource();
        CancellationToken cancellationToken = _pageCancellation.Token;

        SetBusy(true);
        StopPlayback();
        CancelPreview();
        PageInfoBar.IsOpen = false;
        StatusText.Text = "Loading timeline...";

        try
        {
            var projectTask = App.Services.ApiClient.GetProjectAsync(projectId, cancellationToken);
            var timelineTask = App.Services.ApiClient.GetTimelineAsync(projectId, cancellationToken);
            var recoveryTask = App.Services.ApiClient.GetRecoveryAsync(projectId, cancellationToken);
            await Task.WhenAll(projectTask, timelineTask, recoveryTask);

            _project = projectTask.Result.Project;
            _loadedProjectId = projectId;
            _timelineDocument = ExtractTimeline(timelineTask.Result);
            _recoveryDocument = JsonNode.Parse(recoveryTask.Result.GetRawText()) as JsonObject;
            _lanes = TimelineProjection.Project(_timelineDocument);
            _durationSeconds = ResolveDuration(_project, _lanes);
            _positionSeconds = 0;
            _selectedLaneId = null;
            _undoHistory.Clear();
            _redoHistory.Clear();
            _isDirty = false;

            RefreshEditor(updateRawText: true);
            RefreshRecoverySummary();
            StatusText.Text = "Timeline ready.";
            await RefreshPreviewAsync(force: false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            ClearTimeline("The timeline could not be loaded.");
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private static JsonObject ExtractTimeline(JsonElement response)
    {
        JsonElement timeline = response;
        if (response.ValueKind == JsonValueKind.Object &&
            response.TryGetProperty("timeline", out JsonElement wrappedTimeline))
        {
            timeline = wrappedTimeline;
        }

        return JsonNode.Parse(timeline.GetRawText()) as JsonObject
            ?? throw new JsonException("The backend returned an invalid timeline document.");
    }

    private static double ResolveDuration(
        ProjectDto? project,
        IReadOnlyList<TimelineLaneDocument> lanes)
    {
        if (project?.DurationSeconds is double projectDuration &&
            double.IsFinite(projectDuration) &&
            projectDuration > 0)
        {
            return projectDuration;
        }

        double laneDuration = lanes.Count == 0 ? 0 : lanes.Max(lane => lane.EndSeconds);
        return laneDuration > 0 ? laneDuration : DefaultDurationSeconds;
    }

    private void ClearTimeline(string message)
    {
        StopPlayback();
        CancelPreview();
        _loadedProjectId = null;
        _project = null;
        _timelineDocument = null;
        _recoveryDocument = null;
        _lanes = [];
        _selectedLaneId = null;
        _undoHistory.Clear();
        _redoHistory.Clear();
        _isDirty = false;
        _positionSeconds = 0;
        ProjectText.Text = "No active project";
        DurationSummaryText.Text = message;
        TimelineTextBox.Text = string.Empty;
        BackupSummaryText.Text = "No recovery information is available.";
        StatusText.Text = message;
        TrackHeadersPanel.Children.Clear();
        RulerCanvas.Children.Clear();
        TimelineCanvas.Children.Clear();
        SelectedClipTitle.Text = "No clip selected";
        SelectedClipSubtitle.Text = "Select a clip to inspect its timing and media properties.";
        PreviewSurface.ShowEmpty(message);
        PreviewHintText.Text = message;
        UpdateCommandState();
    }

    private void RefreshEditor(bool updateRawText)
    {
        if (_timelineDocument is null)
        {
            return;
        }

        _lanes = TimelineProjection.Project(_timelineDocument);
        _durationSeconds = Math.Max(
            TimelineProjection.MinimumDurationSeconds,
            ResolveDuration(_project, _lanes));
        _positionSeconds = Math.Clamp(_positionSeconds, 0, _durationSeconds);

        if (_selectedLaneId is not null &&
            !_lanes.Any(lane => lane.StableId == _selectedLaneId))
        {
            _selectedLaneId = null;
        }

        ProjectText.Text = _project?.Name ?? _loadedProjectId ?? "Timeline";
        DurationSummaryText.Text =
            $"{FormatClock(_durationSeconds)}  •  {_lanes.Count} clips  •  {TrackCount} tracks";
        PositionSlider.Maximum = _durationSeconds;
        LoopInNumberBox.Maximum = _durationSeconds;
        LoopOutNumberBox.Maximum = _durationSeconds;
        if (!double.IsFinite(LoopOutNumberBox.Value) ||
            LoopOutNumberBox.Value <= 0 ||
            LoopOutNumberBox.Value > _durationSeconds)
        {
            LoopOutNumberBox.Value = _durationSeconds;
        }

        if (updateRawText)
        {
            TimelineTextBox.Text = _timelineDocument.ToJsonString(new JsonSerializerOptions
            {
                WriteIndented = true
            });
        }

        RenderTrackHeaders();
        RenderRuler();
        RenderTimeline();
        PopulateInspector();
        UpdateTransportUi();
        UpdateCommandState();
    }

    private int TrackCount =>
        Math.Max(1, _lanes.Count == 0 ? 1 : _lanes.Max(lane => lane.TrackIndex) + 1);

    private double SurfaceWidth =>
        Math.Max(720, Math.Ceiling(_durationSeconds * _pixelsPerSecond));

    private void RenderTrackHeaders()
    {
        TrackHeadersPanel.Children.Clear();
        for (int trackIndex = 0; trackIndex < TrackCount; trackIndex++)
        {
            var panel = new Grid
            {
                Height = TrackHeight,
                Padding = new Thickness(12, 7, 10, 6),
                BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
                BorderThickness = new Thickness(0, 0, 0, 1)
            };
            panel.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            panel.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var title = new TextBlock
            {
                Text = $"Track {trackIndex + 1}",
                FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                TextTrimming = TextTrimming.CharacterEllipsis
            };
            var detail = new TextBlock
            {
                Text = $"{_lanes.Count(lane => lane.TrackIndex == trackIndex)} clips",
                Opacity = 0.62,
                FontSize = 11
            };
            Grid.SetRow(detail, 1);
            panel.Children.Add(title);
            panel.Children.Add(detail);
            TrackHeadersPanel.Children.Add(panel);
        }
    }

    private void RenderRuler()
    {
        RulerCanvas.Children.Clear();
        RulerCanvas.Width = SurfaceWidth;
        double labelStep = ResolveRulerStep();
        int tickCount = (int)Math.Ceiling(_durationSeconds / labelStep);
        for (int index = 0; index <= tickCount; index++)
        {
            double seconds = Math.Min(_durationSeconds, index * labelStep);
            double x = seconds * _pixelsPerSecond;
            var line = new Line
            {
                X1 = x,
                X2 = x,
                Y1 = 27,
                Y2 = 36,
                Stroke = (Brush)Application.Current.Resources["TextFillColorSecondaryBrush"],
                StrokeThickness = 1
            };
            var label = new TextBlock
            {
                Text = FormatRulerTime(seconds),
                FontSize = 10,
                Opacity = 0.68
            };
            Canvas.SetLeft(label, x + 4);
            Canvas.SetTop(label, 5);
            RulerCanvas.Children.Add(line);
            RulerCanvas.Children.Add(label);
        }
    }

    private double ResolveRulerStep()
    {
        ReadOnlySpan<double> candidates = [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
        foreach (double candidate in candidates)
        {
            if (candidate * _pixelsPerSecond >= 76)
            {
                return candidate;
            }
        }

        return 600;
    }

    private void RenderTimeline()
    {
        TimelineCanvas.Children.Clear();
        TimelineCanvas.Width = SurfaceWidth;
        TimelineCanvas.Height = TrackCount * TrackHeight;
        _selectedClipBorder = null;

        for (int trackIndex = 0; trackIndex < TrackCount; trackIndex++)
        {
            var separator = new Line
            {
                X1 = 0,
                X2 = SurfaceWidth,
                Y1 = (trackIndex + 1) * TrackHeight,
                Y2 = (trackIndex + 1) * TrackHeight,
                Stroke = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"],
                StrokeThickness = 1
            };
            TimelineCanvas.Children.Add(separator);
        }

        if (_lanes.Count == 0)
        {
            var empty = new TextBlock
            {
                Text = "This timeline has no clips. Add clips in Director or edit the raw JSON.",
                Opacity = 0.65,
                FontSize = 13
            };
            Canvas.SetLeft(empty, 24);
            Canvas.SetTop(empty, 20);
            TimelineCanvas.Children.Add(empty);
        }

        foreach (TimelineLaneDocument lane in TimelineProjection.OrderLanes(_lanes))
        {
            Border border = CreateClipVisual(lane);
            TimelineCanvas.Children.Add(border);
            if (lane.StableId == _selectedLaneId)
            {
                _selectedClipBorder = border;
            }
        }

        _playheadLine = new Line
        {
            X1 = _positionSeconds * _pixelsPerSecond,
            X2 = _positionSeconds * _pixelsPerSecond,
            Y1 = 0,
            Y2 = TimelineCanvas.Height,
            Stroke = new SolidColorBrush(Colors.White),
            StrokeThickness = 2,
            IsHitTestVisible = false
        };
        TimelineCanvas.Children.Add(_playheadLine);
    }

    private Border CreateClipVisual(TimelineLaneDocument lane)
    {
        bool isSelected = lane.StableId == _selectedLaneId;
        var border = new Border
        {
            Tag = lane.StableId,
            Width = Math.Max(8, (lane.EndSeconds - lane.StartSeconds) * _pixelsPerSecond),
            Height = TrackHeight - (ClipVerticalInset * 2),
            Background = ResolveClipBrush(lane.Type, isSelected),
            BorderBrush = isSelected
                ? new SolidColorBrush(Colors.White)
                : new SolidColorBrush(Color.FromArgb(150, 255, 255, 255)),
            BorderThickness = new Thickness(isSelected ? 2 : 1),
            CornerRadius = new CornerRadius(5),
            Padding = new Thickness(8, 4, 8, 4)
        };
        border.Child = new StackPanel
        {
            Spacing = 1,
            Children =
            {
                new TextBlock
                {
                    Text = lane.Name,
                    FontSize = 12,
                    FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                    TextTrimming = TextTrimming.CharacterEllipsis
                },
                new TextBlock
                {
                    Text = $"{FormatClock(lane.StartSeconds)} – {FormatClock(lane.EndSeconds)}",
                    FontSize = 10,
                    Opacity = 0.72,
                    TextTrimming = TextTrimming.CharacterEllipsis
                }
            }
        };
        Canvas.SetLeft(border, lane.StartSeconds * _pixelsPerSecond);
        Canvas.SetTop(border, (lane.TrackIndex * TrackHeight) + ClipVerticalInset);
        border.PointerPressed += Clip_PointerPressed;
        border.PointerMoved += Clip_PointerMoved;
        border.PointerReleased += Clip_PointerReleased;
        border.PointerCanceled += Clip_PointerCanceled;
        return border;
    }

    private static Brush ResolveClipBrush(string type, bool selected)
    {
        Color color = type.Contains("audio", StringComparison.OrdinalIgnoreCase)
            ? Color.FromArgb(255, 21, 128, 111)
            : type.Contains("image", StringComparison.OrdinalIgnoreCase)
                ? Color.FromArgb(255, 117, 76, 153)
                : Color.FromArgb(255, 22, 100, 166);
        if (selected)
        {
            color = Color.FromArgb(
                color.A,
                (byte)Math.Min(255, color.R + 25),
                (byte)Math.Min(255, color.G + 25),
                (byte)Math.Min(255, color.B + 25));
        }

        return new SolidColorBrush(color);
    }

    private void SelectLane(string? stableId)
    {
        _selectedLaneId = stableId;
        RenderTimeline();
        PopulateInspector();
        UpdateCommandState();
    }

    private TimelineLaneDocument? SelectedLane =>
        _selectedLaneId is null
            ? null
            : _lanes.FirstOrDefault(lane => lane.StableId == _selectedLaneId);

    private void PopulateInspector()
    {
        TimelineLaneDocument? lane = SelectedLane;
        bool enabled = lane is not null;
        SelectedClipTitle.Text = lane?.Name ?? "No clip selected";
        SelectedClipSubtitle.Text = lane is null
            ? "Select a clip to inspect its timing and media properties."
            : $"{lane.Type} clip • Track {lane.TrackIndex + 1}";

        StartNumberBox.IsEnabled = enabled;
        EndNumberBox.IsEnabled = enabled;
        SourcePathTextBox.IsEnabled = enabled;
        SourceInNumberBox.IsEnabled = enabled;
        SourceOutNumberBox.IsEnabled = enabled;
        SpeedNumberBox.IsEnabled = enabled;
        TrackNumberBox.IsEnabled = enabled;
        VolumeNumberBox.IsEnabled = enabled;
        MutedToggle.IsEnabled = enabled;
        FadeInNumberBox.IsEnabled = enabled;
        FadeOutNumberBox.IsEnabled = enabled;

        StartNumberBox.Value = lane?.StartSeconds ?? double.NaN;
        EndNumberBox.Value = lane?.EndSeconds ?? double.NaN;
        SourcePathTextBox.Text = lane?.SourcePath ?? string.Empty;
        SourceInNumberBox.Value = lane?.SourceInSeconds ?? double.NaN;
        SourceOutNumberBox.Value = lane?.SourceOutSeconds ?? double.NaN;
        SpeedNumberBox.Value = lane?.Speed ?? double.NaN;
        TrackNumberBox.Value = lane is null ? double.NaN : lane.TrackIndex + 1;
        VolumeNumberBox.Value = lane?.Volume ?? double.NaN;
        MutedToggle.IsOn = lane?.Muted ?? false;
        FadeInNumberBox.Value = lane?.FadeInSeconds ?? double.NaN;
        FadeOutNumberBox.Value = lane?.FadeOutSeconds ?? double.NaN;
    }

    private async void Clip_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (sender is not Border border ||
            border.Tag is not string stableId ||
            _timelineDocument is null)
        {
            return;
        }

        TimelineLaneDocument? lane = _lanes.FirstOrDefault(item => item.StableId == stableId);
        if (lane is null)
        {
            return;
        }

        SelectLane(stableId);
        var localPoint = e.GetCurrentPoint(border);
        _dragMode = localPoint.Position.X <= 8
            ? DragMode.TrimStart
            : localPoint.Position.X >= border.ActualWidth - 8
                ? DragMode.TrimEnd
                : DragMode.Move;
        _dragOriginalLane = lane;
        _dragProvisionalLane = lane;
        _dragBeforeSnapshot = CloneDocument(_timelineDocument);
        _dragBorder = border;
        _dragPointerId = e.Pointer.PointerId;
        _dragStartPoint = e.GetCurrentPoint(TimelineCanvas).Position;
        border.CapturePointer(e.Pointer);
        e.Handled = true;
        await RefreshPreviewAsync(force: false);
    }

    private void Clip_PointerMoved(object sender, PointerRoutedEventArgs e)
    {
        if (_dragBorder is null ||
            _dragOriginalLane is null ||
            e.Pointer.PointerId != _dragPointerId)
        {
            return;
        }

        Point current = e.GetCurrentPoint(TimelineCanvas).Position;
        double deltaSeconds = (current.X - _dragStartPoint.X) / _pixelsPerSecond;
        TimelineLaneDocument candidate;
        try
        {
            switch (_dragMode)
            {
                case DragMode.TrimStart:
                    candidate = TimelineProjection.Trim(
                        _dragOriginalLane,
                        SnapTime(_dragOriginalLane.StartSeconds + deltaSeconds),
                        _dragOriginalLane.EndSeconds,
                        _durationSeconds);
                    break;
                case DragMode.TrimEnd:
                    candidate = TimelineProjection.Trim(
                        _dragOriginalLane,
                        _dragOriginalLane.StartSeconds,
                        SnapTime(_dragOriginalLane.EndSeconds + deltaSeconds),
                        _durationSeconds);
                    break;
                default:
                    candidate = TimelineProjection.Move(
                        _dragOriginalLane,
                        SnapTime(_dragOriginalLane.StartSeconds + deltaSeconds),
                        _durationSeconds);
                    int trackIndex = Math.Clamp(
                        (int)Math.Floor(current.Y / TrackHeight),
                        0,
                        Math.Max(0, TrackCount - 1));
                    candidate = TimelineProjection.ReassignTrack(candidate, trackIndex);
                    break;
            }
        }
        catch (ArgumentOutOfRangeException)
        {
            return;
        }

        _dragProvisionalLane = candidate;
        Canvas.SetLeft(_dragBorder, candidate.StartSeconds * _pixelsPerSecond);
        Canvas.SetTop(
            _dragBorder,
            (candidate.TrackIndex * TrackHeight) + ClipVerticalInset);
        _dragBorder.Width = Math.Max(
            8,
            (candidate.EndSeconds - candidate.StartSeconds) * _pixelsPerSecond);
        e.Handled = true;
    }

    private async void Clip_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        if (_dragBorder is null ||
            _dragOriginalLane is null ||
            _dragProvisionalLane is null ||
            _dragBeforeSnapshot is null ||
            e.Pointer.PointerId != _dragPointerId)
        {
            return;
        }

        Border border = _dragBorder;
        TimelineLaneDocument original = _dragOriginalLane;
        TimelineLaneDocument provisional = _dragProvisionalLane;
        JsonObject before = _dragBeforeSnapshot;
        ResetDragState();
        border.ReleasePointerCapture(e.Pointer);

        if (LaneGeometryEquals(original, provisional))
        {
            RenderTimeline();
            return;
        }

        ReplaceLaneByStableId(original.StableId, provisional);
        await CommitLanesAsync(before, "timeline clip edited", provisional.StableId);
        e.Handled = true;
    }

    private void Clip_PointerCanceled(object sender, PointerRoutedEventArgs e)
    {
        if (_dragBorder is null || e.Pointer.PointerId != _dragPointerId)
        {
            return;
        }

        ResetDragState();
        RenderTimeline();
    }

    private void ResetDragState()
    {
        _dragOriginalLane = null;
        _dragProvisionalLane = null;
        _dragBeforeSnapshot = null;
        _dragBorder = null;
        _dragPointerId = 0;
        _dragMode = DragMode.None;
    }

    private static bool LaneGeometryEquals(
        TimelineLaneDocument left,
        TimelineLaneDocument right) =>
        Math.Abs(left.StartSeconds - right.StartSeconds) < 0.0001 &&
        Math.Abs(left.EndSeconds - right.EndSeconds) < 0.0001 &&
        left.TrackIndex == right.TrackIndex;

    private void ReplaceLaneByStableId(
        string stableId,
        TimelineLaneDocument replacement)
    {
        var updated = _lanes.ToList();
        int index = updated.FindIndex(lane => lane.StableId == stableId);
        if (index >= 0)
        {
            updated[index] = replacement;
            _lanes = updated;
        }
    }

    private async Task CommitLanesAsync(
        JsonObject before,
        string reason,
        string? selectionId)
    {
        if (_timelineDocument is null)
        {
            return;
        }

        _timelineDocument = TimelineProjection.Rebuild(_timelineDocument, _lanes);
        PushUndo(before);
        _selectedLaneId = selectionId;
        _isDirty = true;
        RefreshEditor(updateRawText: true);
        await AutosaveAsync(reason);
        await RefreshPreviewAsync(force: false);
    }

    private async Task CommitDocumentAsync(
        JsonObject before,
        JsonObject document,
        string reason,
        string? selectionId = null)
    {
        _timelineDocument = document;
        PushUndo(before);
        _selectedLaneId = selectionId;
        _isDirty = true;
        RefreshEditor(updateRawText: true);
        await AutosaveAsync(reason);
        await RefreshPreviewAsync(force: false);
    }

    private void PushUndo(JsonObject snapshot)
    {
        _undoHistory.Add(CloneDocument(snapshot));
        if (_undoHistory.Count > HistoryLimit)
        {
            _undoHistory.RemoveAt(0);
        }

        _redoHistory.Clear();
    }

    private static JsonObject CloneDocument(JsonObject source) =>
        source.DeepClone() as JsonObject
        ?? throw new InvalidOperationException("Timeline cloning failed.");

    private static JsonElement ToJsonElement(JsonObject source) =>
        JsonDocument.Parse(source.ToJsonString()).RootElement.Clone();

    private async Task AutosaveAsync(string reason)
    {
        if (_timelineDocument is null || string.IsNullOrWhiteSpace(_loadedProjectId))
        {
            return;
        }

        try
        {
            JsonElement metadata = JsonSerializer.SerializeToElement(new
            {
                editor = "winui",
                selected_clip_id = _selectedLaneId
            });
            await App.Services.ApiClient.AutosaveTimelineAsync(
                _loadedProjectId,
                ToJsonElement(_timelineDocument),
                metadata,
                reason,
                _pageCancellation?.Token ?? CancellationToken.None);
            StatusText.Text = "Autosaved.";
            await RefreshRecoveryAsync();
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception ex)
        {
            ShowInfo($"Autosave failed: {ex.Message}", InfoBarSeverity.Warning);
        }
    }

    private async void Undo_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || _undoHistory.Count == 0)
        {
            return;
        }

        _redoHistory.Add(CloneDocument(_timelineDocument));
        JsonObject snapshot = _undoHistory[^1];
        _undoHistory.RemoveAt(_undoHistory.Count - 1);
        _timelineDocument = CloneDocument(snapshot);
        _isDirty = true;
        RefreshEditor(updateRawText: true);
        await AutosaveAsync("timeline undo");
        await RefreshPreviewAsync(force: false);
    }

    private async void Redo_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || _redoHistory.Count == 0)
        {
            return;
        }

        _undoHistory.Add(CloneDocument(_timelineDocument));
        JsonObject snapshot = _redoHistory[^1];
        _redoHistory.RemoveAt(_redoHistory.Count - 1);
        _timelineDocument = CloneDocument(snapshot);
        _isDirty = true;
        RefreshEditor(updateRawText: true);
        await AutosaveAsync("timeline redo");
        await RefreshPreviewAsync(force: false);
    }

    private async void SaveTimeline_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || string.IsNullOrWhiteSpace(_loadedProjectId))
        {
            return;
        }

        SetBusy(true);
        try
        {
            await App.Services.ApiClient.SaveTimelineAsync(
                _loadedProjectId,
                ToJsonElement(_timelineDocument),
                _pageCancellation?.Token ?? CancellationToken.None);
            _isDirty = false;
            StatusText.Text = "Timeline saved.";
            ShowInfo("Timeline changes were saved to the project.", InfoBarSeverity.Success);
            await RefreshRecoveryAsync();
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception ex)
        {
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        if (_isDirty &&
            !await ConfirmAsync(
                "Reload timeline?",
                "Reloading discards unsaved local edits. Autosaved recovery data remains available.",
                "Reload"))
        {
            return;
        }

        await LoadActiveProjectAsync();
    }

    private async void ApplyInspector_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || SelectedLane is not TimelineLaneDocument lane)
        {
            return;
        }

        if (!TryReadFinite(StartNumberBox, out double start) ||
            !TryReadFinite(EndNumberBox, out double end) ||
            !TryReadFinite(SourceInNumberBox, out double sourceIn) ||
            !TryReadFinite(SourceOutNumberBox, out double sourceOut) ||
            !TryReadFinite(SpeedNumberBox, out double speed) ||
            !TryReadFinite(TrackNumberBox, out double track) ||
            !TryReadFinite(VolumeNumberBox, out double volume) ||
            !TryReadFinite(FadeInNumberBox, out double fadeIn) ||
            !TryReadFinite(FadeOutNumberBox, out double fadeOut))
        {
            ShowInfo("Inspector values must be finite numbers.", InfoBarSeverity.Warning);
            return;
        }

        if (start < 0 ||
            end - start < TimelineProjection.MinimumDurationSeconds ||
            end > _durationSeconds ||
            sourceIn < 0 ||
            sourceOut < 0 ||
            speed is < 0.25 or > 4 ||
            track < 1 ||
            volume is < 0 or > 2 ||
            fadeIn < 0 ||
            fadeOut < 0)
        {
            ShowInfo(
                "Check the clip range, track, speed, volume, source, and fade values.",
                InfoBarSeverity.Warning);
            return;
        }

        JsonObject before = CloneDocument(_timelineDocument);
        TimelineLaneDocument updated = TimelineProjection.Trim(
            lane,
            start,
            end,
            _durationSeconds);
        updated.SourcePath = SourcePathTextBox.Text.Trim();
        updated.SourceInSeconds = sourceIn;
        updated.SourceOutSeconds = sourceOut;
        updated.Speed = speed;
        updated.Volume = volume;
        updated.Muted = MutedToggle.IsOn;
        updated.FadeInSeconds = fadeIn;
        updated.FadeOutSeconds = fadeOut;
        updated = TimelineProjection.ReassignTrack(
            updated,
            Math.Max(0, (int)Math.Round(track, MidpointRounding.AwayFromZero) - 1));
        ReplaceLaneByStableId(lane.StableId, updated);
        await CommitLanesAsync(before, "timeline inspector edit", updated.StableId);
    }

    private async void SplitClip_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || SelectedLane is not TimelineLaneDocument lane)
        {
            return;
        }

        try
        {
            JsonObject before = CloneDocument(_timelineDocument);
            var (left, right) = TimelineProjection.Split(lane, _positionSeconds);
            var updated = _lanes.ToList();
            int index = updated.FindIndex(item => item.StableId == lane.StableId);
            updated[index] = left;
            updated.Insert(index + 1, right);
            _lanes = updated;
            await CommitLanesAsync(before, "timeline clip split", right.StableId);
        }
        catch (ArgumentOutOfRangeException ex)
        {
            ShowInfo(ex.Message, InfoBarSeverity.Warning);
        }
    }

    private async void DuplicateClip_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || SelectedLane is not TimelineLaneDocument lane)
        {
            return;
        }

        JsonObject before = CloneDocument(_timelineDocument);
        TimelineLaneDocument duplicate = TimelineProjection.DuplicateAt(
            lane,
            SnapTime(_positionSeconds),
            _durationSeconds);
        _lanes = [.. _lanes, duplicate];
        await CommitLanesAsync(before, "timeline clip duplicated", duplicate.StableId);
    }

    private async void DeleteSelectedClip_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || SelectedLane is not TimelineLaneDocument lane)
        {
            return;
        }

        if (!await ConfirmAsync(
            "Delete selected clip?",
            $"Delete “{lane.Name}” from the timeline?",
            "Delete"))
        {
            return;
        }

        JsonObject before = CloneDocument(_timelineDocument);
        _lanes = _lanes.Where(item => item.StableId != lane.StableId).ToArray();
        await CommitLanesAsync(before, "timeline clip deleted", selectionId: null);
    }

    private void PlayPause_Click(object sender, RoutedEventArgs e)
    {
        if (_isPlaying)
        {
            StopPlayback();
            return;
        }

        if (_positionSeconds >= _durationSeconds)
        {
            SetPosition(LoopToggle.IsChecked == true ? ResolveLoopBounds().Start : 0, requestPreview: false);
        }

        _transportAnchorSeconds = _positionSeconds;
        _transportWatch.Restart();
        _transportTimer.Start();
        _isPlaying = true;
        UpdateTransportUi();
    }

    private void StepBackward_Click(object sender, RoutedEventArgs e)
    {
        StopPlayback();
        SetPosition(_positionSeconds - (1 / DefaultFps), requestPreview: true);
    }

    private void StepForward_Click(object sender, RoutedEventArgs e)
    {
        StopPlayback();
        SetPosition(_positionSeconds + (1 / DefaultFps), requestPreview: true);
    }

    private void TransportTimer_Tick(object? sender, object e)
    {
        if (!_isPlaying)
        {
            return;
        }

        double position = _transportAnchorSeconds + _transportWatch.Elapsed.TotalSeconds;
        if (LoopToggle.IsChecked == true)
        {
            (double start, double end) = ResolveLoopBounds();
            if (position >= end)
            {
                _transportAnchorSeconds = start;
                _transportWatch.Restart();
                position = start;
            }
        }
        else if (position >= _durationSeconds)
        {
            SetPosition(_durationSeconds, requestPreview: true);
            StopPlayback();
            return;
        }

        SetPosition(position, requestPreview: true);
    }

    private void StopPlayback()
    {
        _transportTimer.Stop();
        _transportWatch.Stop();
        _isPlaying = false;
        UpdateTransportUi();
    }

    private void SetPosition(double position, bool requestPreview)
    {
        _positionSeconds = Math.Clamp(position, 0, _durationSeconds);
        _updatingPosition = true;
        PositionSlider.Value = _positionSeconds;
        _updatingPosition = false;
        UpdateTransportUi();
        RenderPlayhead();
        if (requestPreview)
        {
            _ = RefreshPreviewAsync(force: false);
        }
    }

    private void RenderPlayhead()
    {
        if (_playheadLine is null)
        {
            return;
        }

        double x = _positionSeconds * _pixelsPerSecond;
        _playheadLine.X1 = x;
        _playheadLine.X2 = x;
    }

    private void UpdateTransportUi()
    {
        TimecodeText.Text = FormatTimecode(_positionSeconds);
        PlayPauseButton.Content = _isPlaying ? "Pause" : "Play";
    }

    private void PositionSlider_ValueChanged(
        object sender,
        RangeBaseValueChangedEventArgs e)
    {
        if (_updatingPosition || _timelineDocument is null)
        {
            return;
        }

        _positionSeconds = Math.Clamp(e.NewValue, 0, _durationSeconds);
        UpdateTransportUi();
        RenderPlayhead();
        if (_positionPointerActive || !_isPlaying)
        {
            _ = RefreshPreviewAsync(force: false);
        }
    }

    private void PositionSlider_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        _positionPointerActive = true;
        StopPlayback();
    }

    private void PositionSlider_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        _positionPointerActive = false;
        _ = RefreshPreviewAsync(force: true);
    }

    private void ZoomSlider_ValueChanged(
        object sender,
        RangeBaseValueChangedEventArgs e)
    {
        _pixelsPerSecond = Math.Clamp(
            80 * e.NewValue,
            MinimumPixelsPerSecond,
            MaximumPixelsPerSecond);
        if (_timelineDocument is not null)
        {
            RenderRuler();
            RenderTimeline();
        }
    }

    private void FitTimeline_Click(object sender, RoutedEventArgs e)
    {
        if (_durationSeconds <= 0)
        {
            return;
        }

        double viewport = TimelineScroll.ViewportWidth > 0
            ? TimelineScroll.ViewportWidth
            : 900;
        _pixelsPerSecond = Math.Clamp(
            viewport / _durationSeconds,
            MinimumPixelsPerSecond,
            MaximumPixelsPerSecond);
        ZoomSlider.Value = Math.Clamp(_pixelsPerSecond / 80, 0.25, 4);
        RenderRuler();
        RenderTimeline();
        TimelineScroll.ChangeView(0, null, null, true);
    }

    private void TrackHeaderScroll_ViewChanged(
        object sender,
        ScrollViewerViewChangedEventArgs e)
    {
        if (_syncingScroll)
        {
            return;
        }

        _syncingScroll = true;
        TimelineScroll.ChangeView(
            TimelineScroll.HorizontalOffset,
            TrackHeaderScroll.VerticalOffset,
            null,
            true);
        _syncingScroll = false;
    }

    private void TimelineScroll_ViewChanged(
        object sender,
        ScrollViewerViewChangedEventArgs e)
    {
        if (_syncingScroll)
        {
            return;
        }

        _syncingScroll = true;
        TrackHeaderScroll.ChangeView(
            null,
            TimelineScroll.VerticalOffset,
            null,
            true);
        RulerScroll.ChangeView(
            TimelineScroll.HorizontalOffset,
            null,
            null,
            true);
        _syncingScroll = false;
    }

    private void TimelineCanvas_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        Point point = e.GetCurrentPoint(TimelineCanvas).Position;
        StopPlayback();
        SelectLane(null);
        SetPosition(SnapTime(point.X / _pixelsPerSecond), requestPreview: true);
    }

    private double SnapTime(double value)
    {
        double clamped = Math.Clamp(value, 0, _durationSeconds);
        string mode = GetSelectedTag(SnapCombo) ?? "off";
        if (string.Equals(mode, "off", StringComparison.OrdinalIgnoreCase))
        {
            return clamped;
        }

        double bpm = _project?.Bpm is double projectBpm &&
                     double.IsFinite(projectBpm) &&
                     projectBpm > 0
            ? projectBpm
            : 120;
        double beatSeconds = 60 / bpm;
        double interval = mode switch
        {
            "half" => beatSeconds / 2,
            "quarter" => beatSeconds / 4,
            _ => beatSeconds
        };
        return Math.Clamp(
            Math.Round(clamped / interval, MidpointRounding.AwayFromZero) * interval,
            0,
            _durationSeconds);
    }

    private (double Start, double End) ResolveLoopBounds()
    {
        double start = ReadFiniteOrDefault(LoopInNumberBox, 0);
        double end = ReadFiniteOrDefault(LoopOutNumberBox, _durationSeconds);
        start = Math.Clamp(start, 0, _durationSeconds);
        end = Math.Clamp(end, start + TimelineProjection.MinimumDurationSeconds, _durationSeconds);
        return (start, end);
    }

    private async Task RefreshPreviewAsync(bool force)
    {
        CancelPreview();
        if (_timelineDocument is null ||
            string.IsNullOrWhiteSpace(_loadedProjectId) ||
            !TimelineProjection.HasRenderableVideoClip(_timelineDocument))
        {
            PreviewSurface.ShowUnsupported("No renderable video clip is present at this timeline.");
            PreviewHintText.Text = "Add a video clip with a source path to enable preview.";
            return;
        }

        var cancellation = CancellationTokenSource.CreateLinkedTokenSource(
            _pageCancellation?.Token ?? CancellationToken.None);
        _previewCancellation = cancellation;
        long generation = ++_previewGeneration;
        try
        {
            if (!force)
            {
                await Task.Delay(TimeSpan.FromMilliseconds(90), cancellation.Token);
            }

            PreviewHintText.Text = $"Rendering frame at {FormatClock(_positionSeconds)}...";
            double requestPosition = _positionSeconds;
            await App.Services.ApiClient.StreamTimelineFrameAsync(
                _loadedProjectId,
                requestPosition,
                1280,
                720,
                force,
                async (file, token) =>
                {
                    if (generation != _previewGeneration)
                    {
                        return false;
                    }

                    await PreviewSurface.LoadStreamAsync(
                        file.Stream,
                        file.ContentHeaders.ContentType?.MediaType,
                        token);
                    return true;
                },
                cancellation.Token);
            if (generation == _previewGeneration)
            {
                PreviewHintText.Text = $"Frame {FormatClock(requestPosition)}";
            }
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            if (generation == _previewGeneration)
            {
                PreviewSurface.ShowError(ex.Message);
                PreviewHintText.Text = "Timeline preview failed.";
            }
        }
        finally
        {
            if (ReferenceEquals(_previewCancellation, cancellation))
            {
                _previewCancellation = null;
            }

            cancellation.Dispose();
        }
    }

    private void CancelPreview()
    {
        _previewGeneration++;
        _previewCancellation?.Cancel();
        _previewCancellation = null;
    }

    private async void RenderMaster_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null || string.IsNullOrWhiteSpace(_loadedProjectId))
        {
            return;
        }

        string name = OutputNameTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ShowInfo("Enter an output name before rendering.", InfoBarSeverity.Warning);
            return;
        }

        string mode = GetSelectedTag(ModeComboBox) ?? "final";
        string aspect = GetSelectedTag(AspectRatioComboBox) ?? "16:9";
        (int width, int height) = ResolveRenderDimensions(mode, aspect);
        string quality = string.Equals(mode, "preview", StringComparison.OrdinalIgnoreCase)
            ? "medium"
            : "high";

        SetBusy(true);
        StatusText.Text = "Queueing timeline render...";
        try
        {
            var request = new TimelineRenderRequest(
                width,
                height,
                DefaultFps,
                "h264",
                "aac",
                quality,
                name);
            TimelineRenderResponse response =
                await App.Services.ApiClient.QueueTimelineRenderAsync(
                    _loadedProjectId,
                    request,
                    _pageCancellation?.Token ?? CancellationToken.None);
            if (!response.Ok)
            {
                throw new InvalidOperationException("The backend did not accept the timeline render.");
            }

            StatusText.Text = $"Render {response.Job.Id}: {response.Job.Status}";
            ShowInfo(
                $"Timeline render queued as job {response.Job.Id}.",
                InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception ex)
        {
            StatusText.Text = "Render could not be queued.";
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private static (int Width, int Height) ResolveRenderDimensions(
        string mode,
        string aspect)
    {
        int longEdge = string.Equals(mode, "preview", StringComparison.OrdinalIgnoreCase)
            ? 1280
            : 1920;
        int shortEdge = string.Equals(mode, "preview", StringComparison.OrdinalIgnoreCase)
            ? 720
            : 1080;
        return aspect switch
        {
            "9:16" => (shortEdge, longEdge),
            "1:1" => (shortEdge, shortEdge),
            "4:5" => (
                string.Equals(mode, "preview", StringComparison.OrdinalIgnoreCase) ? 864 : 1080,
                string.Equals(mode, "preview", StringComparison.OrdinalIgnoreCase) ? 1080 : 1350),
            _ => (longEdge, shortEdge)
        };
    }

    private async Task RefreshRecoveryAsync()
    {
        if (string.IsNullOrWhiteSpace(_loadedProjectId))
        {
            return;
        }

        try
        {
            JsonElement response = await App.Services.ApiClient.GetRecoveryAsync(
                _loadedProjectId,
                _pageCancellation?.Token ?? CancellationToken.None);
            _recoveryDocument = JsonNode.Parse(response.GetRawText()) as JsonObject;
            RefreshRecoverySummary();
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception ex)
        {
            BackupSummaryText.Text = $"Recovery status unavailable: {ex.Message}";
        }
    }

    private void RefreshRecoverySummary()
    {
        bool needsRecovery = _recoveryDocument?["needs_recovery"]?.GetValue<bool>() == true;
        int candidateCount = (_recoveryDocument?["candidates"] as JsonArray)?.Count ?? 0;
        BackupSummaryText.Text = needsRecovery
            ? $"{candidateCount} recovery candidate{(candidateCount == 1 ? string.Empty : "s")} available."
            : candidateCount > 0
                ? $"{candidateCount} clean backup candidate{(candidateCount == 1 ? string.Empty : "s")} available."
                : "No recovery candidates are available.";
        RestoreBackupButton.IsEnabled = !_isBusy && needsRecovery && candidateCount > 0;
        ExportRecoveryButton.IsEnabled = !_isBusy && _recoveryDocument is not null;
        DeleteRecoveryButton.IsEnabled = !_isBusy && needsRecovery;
    }

    private async void RestoreBackup_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_loadedProjectId) ||
            !TryGetRecoveryCandidate(out string source, out string? snapshotName))
        {
            ShowInfo("No recovery candidate is available.", InfoBarSeverity.Warning);
            return;
        }

        if (!await ConfirmAsync(
            "Restore recovery data?",
            "The selected recovery candidate will replace the current project timeline.",
            "Restore"))
        {
            return;
        }

        SetBusy(true);
        try
        {
            await App.Services.ApiClient.ApplyRecoveryAsync(
                _loadedProjectId,
                new RecoveryApplyRequest(source, snapshotName),
                _pageCancellation?.Token ?? CancellationToken.None);
            await LoadActiveProjectAsync(forceReload: true);
            ShowInfo("Recovery data was restored.", InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception ex)
        {
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private bool TryGetRecoveryCandidate(out string source, out string? snapshotName)
    {
        if (!TimelineRecovery.TrySelectCrashRecovery(
                _recoveryDocument,
                out TimelineRecoveryCandidate candidate))
        {
            source = "journal";
            snapshotName = null;
            return false;
        }

        source = candidate.Source;
        snapshotName = candidate.SnapshotName;
        return true;
    }

    private async void ExportRecovery_Click(object sender, RoutedEventArgs e)
    {
        if (_recoveryDocument is null || App.MainWindowInstance is null)
        {
            return;
        }

        try
        {
            var picker = new FileSavePicker
            {
                SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
                SuggestedFileName = $"{_project?.Name ?? "timeline"}-recovery"
            };
            picker.FileTypeChoices.Add("JSON document", [".json"]);
            nint windowHandle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowInstance);
            WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
            StorageFile? file = await picker.PickSaveFileAsync();
            if (file is null)
            {
                return;
            }

            await FileIO.WriteTextAsync(
                file,
                _recoveryDocument.ToJsonString(new JsonSerializerOptions
                {
                    WriteIndented = true
                }));
            ShowInfo("Recovery metadata was exported.", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void DeleteRecovery_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_loadedProjectId) ||
            !await ConfirmAsync(
                "Discard recovery journal?",
                "This marks the autosave journal clean. Recovery snapshots and project files are not deleted.",
                "Discard"))
        {
            return;
        }

        SetBusy(true);
        try
        {
            await App.Services.ApiClient.DiscardRecoveryAsync(
                _loadedProjectId,
                _pageCancellation?.Token ?? CancellationToken.None);
            await RefreshRecoveryAsync();
            ShowInfo("The recovery journal was discarded.", InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception ex)
        {
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void ApplyRaw_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null)
        {
            return;
        }

        JsonObject? parsed;
        try
        {
            parsed = JsonNode.Parse(TimelineTextBox.Text) as JsonObject;
        }
        catch (JsonException ex)
        {
            ShowInfo($"Invalid JSON: {ex.Message}", InfoBarSeverity.Error);
            return;
        }

        if (parsed is null)
        {
            ShowInfo("Timeline JSON must be an object.", InfoBarSeverity.Warning);
            return;
        }

        try
        {
            _ = TimelineProjection.Project(parsed);
            JsonObject before = CloneDocument(_timelineDocument);
            await CommitDocumentAsync(before, parsed, "timeline raw JSON applied");
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException)
        {
            ShowInfo(ex.Message, InfoBarSeverity.Error);
        }
    }

    private void RevertRaw_Click(object sender, RoutedEventArgs e)
    {
        if (_timelineDocument is null)
        {
            return;
        }

        TimelineTextBox.Text = _timelineDocument.ToJsonString(new JsonSerializerOptions
        {
            WriteIndented = true
        });
        PageInfoBar.IsOpen = false;
    }

    private void UpdateCommandState()
    {
        bool hasTimeline = _timelineDocument is not null && !_isBusy;
        bool hasSelection = SelectedLane is not null && !_isBusy;
        UndoButton.IsEnabled = hasTimeline && _undoHistory.Count > 0;
        RedoButton.IsEnabled = hasTimeline && _redoHistory.Count > 0;
        SaveButton.IsEnabled = hasTimeline;
        PlayPauseButton.IsEnabled = hasTimeline;
        ApplyInspectorButton.IsEnabled = hasSelection;
        SplitClipButton.IsEnabled = hasSelection;
        DuplicateClipButton.IsEnabled = hasSelection;
        DeleteClipButton.IsEnabled = hasSelection;
        RenderMasterButton.IsEnabled = hasTimeline;
        ApplyRawButton.IsEnabled = hasTimeline;
        RevertRawButton.IsEnabled = hasTimeline;
        RefreshRecoverySummary();
    }

    private void SetBusy(bool busy)
    {
        _isBusy = busy;
        UpdateCommandState();
    }

    private void ShowInfo(string message, InfoBarSeverity severity)
    {
        PageInfoBar.Message = message;
        PageInfoBar.Severity = severity;
        PageInfoBar.IsOpen = true;
    }

    private async Task<bool> ConfirmAsync(
        string title,
        string message,
        string primaryButtonText)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = title,
            Content = message,
            PrimaryButtonText = primaryButtonText,
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }

    private static bool TryReadFinite(NumberBox numberBox, out double value)
    {
        value = numberBox.Value;
        return double.IsFinite(value);
    }

    private static double ReadFiniteOrDefault(NumberBox numberBox, double fallback) =>
        double.IsFinite(numberBox.Value) ? numberBox.Value : fallback;

    private static string? GetSelectedTag(ComboBox comboBox) =>
        (comboBox.SelectedItem as ComboBoxItem)?.Tag?.ToString();

    private static string FormatClock(double seconds)
    {
        TimeSpan time = TimeSpan.FromSeconds(Math.Max(0, seconds));
        return time.TotalHours >= 1
            ? $"{(int)time.TotalHours:00}:{time.Minutes:00}:{time.Seconds:00}"
            : $"{time.Minutes:00}:{time.Seconds:00}";
    }

    private static string FormatRulerTime(double seconds)
    {
        TimeSpan time = TimeSpan.FromSeconds(Math.Max(0, seconds));
        return time.TotalHours >= 1
            ? $"{(int)time.TotalHours}:{time.Minutes:00}:{time.Seconds:00}"
            : $"{time.Minutes}:{time.Seconds:00}";
    }

    private static string FormatTimecode(double seconds)
    {
        double clamped = Math.Max(0, seconds);
        int totalFrames = (int)Math.Round(clamped * DefaultFps);
        int frames = totalFrames % (int)DefaultFps;
        int totalSeconds = totalFrames / (int)DefaultFps;
        int hours = totalSeconds / 3600;
        int minutes = (totalSeconds / 60) % 60;
        int remainingSeconds = totalSeconds % 60;
        return $"{hours:00}:{minutes:00}:{remainingSeconds:00}:{frames:00}";
    }

    private enum DragMode
    {
        None,
        Move,
        TrimStart,
        TrimEnd
    }
}
