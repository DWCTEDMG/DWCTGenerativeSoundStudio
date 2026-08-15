using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class OutputsPage : Page
{
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
    private string? _projectId;
    private string? _cachedPreviewPath;
    private CancellationTokenSource? _previewCancellation;
    private int _previewGeneration;

    public ObservableCollection<OutputEntry> Items { get; } = [];

    public OutputsPage()
    {
        InitializeComponent();
        Loaded += OutputsPage_Loaded;
        Unloaded += OutputsPage_Unloaded;
    }

    private async void OutputsPage_Loaded(object sender, RoutedEventArgs e)
    {
        _projectId = App.Services.Session.ActiveProjectId;
        await RefreshAsync();
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async Task RefreshAsync()
    {
        if (string.IsNullOrWhiteSpace(_projectId))
        {
            ShowStatus("Open a project to browse outputs.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            CancelPreview();
            ClearOutputDetails();
            OutputsList.SelectedItem = null;
            Items.Clear();
            var payload = StudioPageHelpers.ToObject(await _apiClient.GetOutputsAsync(_projectId));
            foreach (var group in payload)
            {
                if (group.Value is not JsonArray entries)
                {
                    continue;
                }

                foreach (var node in entries.OfType<JsonObject>())
                {
                    var path = node["path"]?.GetValue<string>() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(path))
                    {
                        continue;
                    }

                    var name = node["name"]?.GetValue<string>() ?? Path.GetFileName(path);
                    var size = node["size_bytes"]?.GetValue<long?>() ?? 0;
                    Items.Add(new OutputEntry(group.Key, name, path, size, node.DeepClone().AsObject()));
                }
            }

            ShowStatus(Items.Count == 0 ? "No outputs have been produced for this project yet." : $"{Items.Count} outputs loaded.",
                Items.Count == 0 ? InfoBarSeverity.Informational : InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void OutputsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        CancelPreview();
        var generation = ++_previewGeneration;
        _cachedPreviewPath = null;
        ImagePreview.Source = null;
        ImagePreview.Visibility = Visibility.Collapsed;
        RevealButton.IsEnabled = false;

        if (OutputsList.SelectedItem is not OutputEntry entry || string.IsNullOrWhiteSpace(_projectId))
        {
            ClearOutputDetails();
            return;
        }

        _previewCancellation = new CancellationTokenSource();
        var cancellationToken = _previewCancellation.Token;
        SelectedNameText.Text = entry.Name;
        SelectedPathText.Text = entry.Path;
        MetadataText.Text = StudioPageHelpers.FormatJson(entry.Metadata);
        PreviewPlaceholder.Visibility = Visibility.Visible;
        PreviewPlaceholder.Text = "Loading authenticated preview…";
        SaveButton.IsEnabled = true;

        if (!entry.IsImage)
        {
            PreviewPlaceholder.Text = entry.IsVideo
                ? "Video preview is available after saving a local copy."
                : "This output does not have an inline preview.";
            return;
        }

        try
        {
            var bytes = await _apiClient.DownloadProjectFileAsync(_projectId, entry.Path, cancellationToken);
            var extension = Path.GetExtension(entry.Name);
            var file = await ApplicationData.Current.TemporaryFolder.CreateFileAsync(
                $"edmg-preview-{Guid.NewGuid():N}{extension}", CreationCollisionOption.ReplaceExisting);
            await FileIO.WriteBytesAsync(file, bytes);
            cancellationToken.ThrowIfCancellationRequested();
            if (generation != _previewGeneration || !ReferenceEquals(OutputsList.SelectedItem, entry))
            {
                await file.DeleteAsync(StorageDeleteOption.PermanentDelete);
                return;
            }

            _cachedPreviewPath = file.Path;
            ImagePreview.Source = new BitmapImage(new Uri(file.Path));
            ImagePreview.Visibility = Visibility.Visible;
            PreviewPlaceholder.Visibility = Visibility.Collapsed;
            RevealButton.IsEnabled = true;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            if (generation != _previewGeneration)
            {
                return;
            }
            PreviewPlaceholder.Text = "Preview failed to load.";
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
    }

    private void OutputsPage_Unloaded(object sender, RoutedEventArgs e) => CancelPreview();

    private void CancelPreview()
    {
        _previewCancellation?.Cancel();
        _previewCancellation?.Dispose();
        _previewCancellation = null;
    }

    private void ClearOutputDetails()
    {
        _cachedPreviewPath = null;
        SelectedNameText.Text = "Select an output";
        SelectedPathText.Text = string.Empty;
        MetadataText.Text = string.Empty;
        ImagePreview.Source = null;
        ImagePreview.Visibility = Visibility.Collapsed;
        PreviewPlaceholder.Text = "Preview appears here";
        PreviewPlaceholder.Visibility = Visibility.Visible;
        SaveButton.IsEnabled = false;
        RevealButton.IsEnabled = false;
    }

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        if (OutputsList.SelectedItem is not OutputEntry entry || string.IsNullOrWhiteSpace(_projectId))
        {
            return;
        }

        var picker = new FileSavePicker
        {
            SuggestedFileName = Path.GetFileNameWithoutExtension(entry.Name)
        };
        var extension = Path.GetExtension(entry.Name);
        picker.FileTypeChoices.Add("Output file", [string.IsNullOrWhiteSpace(extension) ? ".bin" : extension]);
        var window = App.MainWindowInstance
            ?? throw new InvalidOperationException("The Studio window is not available.");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(window));
        var destination = await picker.PickSaveFileAsync();
        if (destination is null)
        {
            return;
        }

        try
        {
            var bytes = await _apiClient.DownloadProjectFileAsync(_projectId, entry.Path);
            await FileIO.WriteBytesAsync(destination, bytes);
            ShowStatus($"Saved {destination.Name}.", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(ex), InfoBarSeverity.Error);
        }
    }

    private void RevealButton_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_cachedPreviewPath) || !File.Exists(_cachedPreviewPath))
        {
            return;
        }

        Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{_cachedPreviewPath}\"") { UseShellExecute = true });
    }

    private void SetBusy(bool value)
    {
        BusyRing.IsActive = value;
        RefreshButton.IsEnabled = !value;
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }
}

public sealed class OutputEntry
{
    public OutputEntry(string group, string name, string path, long sizeBytes, JsonObject metadata)
    {
        Group = group;
        Name = name;
        Path = path;
        SizeBytes = sizeBytes;
        Metadata = metadata;
    }

    public string Group { get; set; }
    public string Name { get; set; }
    public string Path { get; set; }
    public long SizeBytes { get; set; }
    public JsonObject Metadata { get; set; }
    public string Summary => $"{Group.Replace('_', ' ')} • {SizeBytes / 1024.0:N1} KB";
    public bool IsImage => new[] { ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif" }.Contains(System.IO.Path.GetExtension(Name), StringComparer.OrdinalIgnoreCase);
    public bool IsVideo => new[] { ".mp4", ".mov", ".webm", ".mkv", ".avi" }.Contains(System.IO.Path.GetExtension(Name), StringComparer.OrdinalIgnoreCase);
}
