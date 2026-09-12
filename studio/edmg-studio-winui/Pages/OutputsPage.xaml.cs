using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;
using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Controls;
using EdmgStudio.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.System;
using WinRT.Interop;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class OutputsPage : Page
{
    private readonly StudioApiClient _apiClient = App.Services.ApiClient;
    private readonly StudioProjectMediaClient _projectMediaClient = App.Services.ProjectMediaClient;
    private readonly StudioSessionService _session = App.Services.Session;
    private readonly BackendConfiguration _backendConfiguration = App.Services.Configuration;
    private readonly LatestRequestGate _previewRequests = new();
    private string? _previewTempPath;
    private readonly LatestRequestGate _refreshRequests = new();
    private bool _isInitialized;

    public OutputsPage()
    {
        InitializeComponent();
        _isInitialized = true;
    }

    public ObservableCollection<StudioOutputItem> Items { get; } = [];

    public ObservableCollection<StudioOutputItem> VisibleItems { get; } = [];

    private string ActiveProjectId => _session.ActiveProjectId;

    private StudioOutputItem? SelectedOutput => OutputsList.SelectedItem as StudioOutputItem;

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        await RefreshAsync();
    }

    protected override async void OnNavigatedFrom(NavigationEventArgs e)
    {
        _refreshRequests.Cancel();
        await CancelPreviewAsync(clearSurface: true);
        base.OnNavigatedFrom(e);
    }

    private async Task RefreshAsync(string? preferredStableIdentity = null)
    {
        using var request = _refreshRequests.Begin();
        string projectId = ActiveProjectId;
        string? selectionIdentity = preferredStableIdentity ?? SelectedOutput?.StableIdentity;
        if (string.IsNullOrWhiteSpace(ActiveProjectId))
        {
            Items.Clear();
            VisibleItems.Clear();
            await CancelPreviewAsync(clearSurface: true);
            SetStatus("Select a project", "Open Projects and select a project before browsing outputs.", InfoBarSeverity.Informational);
            return;
        }

        SetBusy(true);
        try
        {
            JsonElement outputs = await _apiClient.GetOutputsAsync(projectId, request.Token);
            if (!request.IsCurrent || projectId != ActiveProjectId) return;
            Items.Clear();
            foreach (StudioOutputItem item in StudioOutputCatalog.Project(outputs))
            {
                Items.Add(item);
            }

            ApplyFilters(selectionIdentity);
            SetStatus(
                "Outputs refreshed",
                $"{Items.Count} output record(s) loaded for project {ActiveProjectId}.",
                InfoBarSeverity.Success);
        }
        catch (OperationCanceledException) when (request.Token.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            if (request.IsCurrent && projectId == ActiveProjectId)
                SetStatus("Unable to load outputs", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            if (request.IsCurrent) SetBusy(false);
        }
    }

    private async void OutputsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        using var request = _previewRequests.Begin();
        string projectId = ActiveProjectId;
        StudioOutputItem? selected = SelectedOutput;
        OutputPreview.ShowEmpty("Loading selected output…");
        UpdateSelectionUi(selected);

        if (selected is null)
        {
            OutputPreview.ShowEmpty("Select an output to preview.");
            return;
        }

        if (!selected.SupportsMediaWorkflow)
        {
            OutputPreview.ShowUnsupported("This Unreal bundle is a workflow artifact, not previewable media.");
            return;
        }

        _session.SetSelectedArtifact(selected.Path);
        try
        {
            await _projectMediaClient.StreamProjectMediaAsync<bool>(
                projectId,
                selected.Path,
                async (file, cancellationToken) =>
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    if (!request.IsCurrent || projectId != ActiveProjectId) return false;
                    if (selected.IsVideo)
                    {
                        await OutputPreview.LoadVideoStreamAsync(file.Stream, file.ContentHeaders.ContentLength, cancellationToken);
                    }
                    else
                    {
                        await OutputPreview.LoadStreamAsync(
                            file.Stream,
                            file.ContentHeaders.ContentType?.MediaType,
                            cancellationToken);
                    }
                    return true;
                },
                request.Token);
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            if (request.IsCurrent && projectId == ActiveProjectId)
            {
                OutputPreview.ShowError(ex.Message);
                SetStatus("Preview failed", ex.Message, InfoBarSeverity.Warning);
            }
        }
    }

    private void UpdateSelectionUi(StudioOutputItem? selected)
    {
        bool mediaWorkflow = selected?.SupportsMediaWorkflow == true;
        bool bundleWorkflow = selected?.SupportsBundleWorkflow == true;

        SelectedNameText.Text = selected?.Name ?? "Select an output";
        SelectedPathText.Text = selected?.Path ?? string.Empty;
        MetadataText.Text = selected?.Metadata?.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) ?? string.Empty;
        UnrealBundlePanel.Visibility = bundleWorkflow ? Visibility.Visible : Visibility.Collapsed;

        SaveButton.IsEnabled = mediaWorkflow;
        RevealButton.IsEnabled = mediaWorkflow;
        ReviewButton.IsEnabled = mediaWorkflow;
        TimelineButton.IsEnabled = mediaWorkflow;
        RenderButton.IsEnabled = mediaWorkflow;
        BuildUnrealPlanButton.IsEnabled = bundleWorkflow;
        ImportUnrealReturnButton.IsEnabled = bundleWorkflow;
        RevealBundleButton.IsEnabled = bundleWorkflow;
        SaveManifestButton.IsEnabled = bundleWorkflow && !string.IsNullOrWhiteSpace(selected?.ManifestPath);
        SavePlanButton.IsEnabled = bundleWorkflow && !string.IsNullOrWhiteSpace(selected?.ImportPlanPath);
        SaveZipButton.IsEnabled = bundleWorkflow && !string.IsNullOrWhiteSpace(selected?.ZipPath);

        if (!mediaWorkflow)
        {
            _session.SetSelectedArtifact(null);
            _session.SetSourceAsset(null);
        }
    }

    private Task CancelPreviewAsync(bool clearSurface)
    {
        _previewRequests.Cancel();

        if (clearSurface)
        {
            OutputPreview.ShowEmpty();
        }

        DeletePreviewTemp();
        return Task.CompletedTask;
    }

    private void DeletePreviewTemp()
    {
        string? tempPath = Interlocked.Exchange(ref _previewTempPath, null);
        if (string.IsNullOrWhiteSpace(tempPath))
        {
            return;
        }

        try
        {
            File.Delete(tempPath);
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        StudioOutputItem? selected = SelectedOutput;
        if (selected?.IsDownloadable != true)
        {
            return;
        }

        try
        {
            await SaveProjectArtifactAsync(selected.Path, selected.Name, "Output file");
        }
        catch (Exception ex)
        {
            SetStatus("Save failed", ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void RevealButton_Click(object sender, RoutedEventArgs e)
    {
        StudioOutputItem? selected = SelectedOutput;
        if (selected?.IsDownloadable != true)
        {
            return;
        }

        SetBusy(true);
        try
        {
            DeletePreviewTemp();
            string extension = Path.GetExtension(selected.Name);
            _previewTempPath = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}{extension}");
            await _projectMediaClient.StreamProjectMediaAsync<bool>(
                ActiveProjectId,
                selected.Path,
                async (file, cancellationToken) =>
                {
                    await using FileStream destination = File.Create(_previewTempPath);
                    await file.Stream.CopyToAsync(destination, cancellationToken);
                    return true;
                });

            using System.Diagnostics.Process? process = System.Diagnostics.Process.Start(
                new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "explorer.exe",
                    Arguments = $"/select,\"{_previewTempPath}\"",
                    UseShellExecute = true,
                });
        }
        catch (Exception ex)
        {
            SetStatus("Reveal failed", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void ExportUnrealButton_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(ActiveProjectId))
        {
            SetStatus("Select a project", "Select a project before exporting an Unreal bundle.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            double displayedVariant = UnrealVariantNumber.Value;
            if (double.IsNaN(displayedVariant) ||
                displayedVariant < 1 ||
                displayedVariant > int.MaxValue ||
                displayedVariant != Math.Truncate(displayedVariant))
            {
                throw new InvalidOperationException("Plan variant must be a whole number of 1 or greater.");
            }

            UnrealBundleExportResponse response = await _apiClient.ExportUnrealBundleAsync(
                ActiveProjectId,
                new UnrealBundleExportRequest
                {
                    VariantIndex = checked((int)displayedVariant - 1),
                    BundleName = OptionalText(UnrealBundleNameBox.Text),
                    IncludeZip = UnrealIncludeZipCheckBox.IsChecked == true,
                });

            string stableIdentity = $"bundle:{StudioOutputCatalog.NormalizePath(response.Bundle.BundleDirectory)}";
            await RefreshAsync(stableIdentity);
            SetStatus(
                "Unreal bundle exported",
                $"Created {response.Bundle.BundleDirectory}.",
                InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            SetStatus("Unreal export failed", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void BuildUnrealPlanButton_Click(object sender, RoutedEventArgs e)
    {
        StudioOutputItem? selected = SelectedOutput;
        if (selected?.SupportsBundleWorkflow != true || string.IsNullOrWhiteSpace(selected.BundleDirectory))
        {
            return;
        }

        SetBusy(true);
        try
        {
            UnrealImportPlanResponse response = await _apiClient.BuildUnrealImportPlanAsync(
                ActiveProjectId,
                new UnrealImportPlanRequest
                {
                    BundleDirectory = selected.BundleDirectory,
                    ContentPath = OptionalText(UnrealContentPathBox.Text),
                    AssetName = OptionalText(UnrealAssetNameBox.Text),
                });

            await RefreshAsync(selected.StableIdentity);
            SetStatus("Unreal import plan created", $"Created {response.PlanPath}.", InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            SetStatus("Import plan failed", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void ImportUnrealReturnButton_Click(object sender, RoutedEventArgs e)
    {
        StudioOutputItem? selected = SelectedOutput;
        if (selected?.SupportsBundleWorkflow != true || string.IsNullOrWhiteSpace(selected.BundleDirectory))
        {
            return;
        }

        SetBusy(true);
        try
        {
            UnrealReturnImportResponse response = await _apiClient.ImportUnrealReturnsAsync(
                ActiveProjectId,
                new UnrealReturnImportRequest
                {
                    BundleDirectory = selected.BundleDirectory,
                    SourceDirectory = OptionalText(UnrealReturnSourceBox.Text),
                });

            await RefreshAsync(selected.StableIdentity);
            SetStatus(
                "Unreal returns imported",
                $"{response.Imported.Media.Count} returned media file(s) added to Studio.",
                InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            SetStatus("Return import failed", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void RevealBundleButton_Click(object sender, RoutedEventArgs e)
    {
        StudioOutputItem? selected = SelectedOutput;
        if (selected?.SupportsBundleWorkflow != true || string.IsNullOrWhiteSpace(selected.BundleDirectory))
        {
            return;
        }

        try
        {
            ManagedProjectPathResolution resolution = ManagedProjectPathResolver.Resolve(
                _backendConfiguration.Mode,
                _backendConfiguration.Paths.DataDirectory,
                ActiveProjectId,
                selected.BundleDirectory);
            if (!resolution.IsAvailable || string.IsNullOrWhiteSpace(resolution.FullPath))
            {
                throw new InvalidOperationException(resolution.ErrorMessage);
            }

            if (!Directory.Exists(resolution.FullPath))
            {
                throw new DirectoryNotFoundException("The Unreal bundle directory does not exist locally.");
            }

            StorageFolder folder = await StorageFolder.GetFolderFromPathAsync(resolution.FullPath);
            if (!await Launcher.LaunchFolderAsync(folder))
            {
                throw new InvalidOperationException("Windows could not open the Unreal bundle folder.");
            }
        }
        catch (Exception ex)
        {
            SetStatus("Reveal bundle failed", ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void SaveManifestButton_Click(object sender, RoutedEventArgs e) =>
        await SaveSelectedBundleArtifactAsync(
            SelectedOutput?.ManifestPath,
            "unreal-manifest.json",
            "Unreal manifest",
            "Manifest save failed");

    private async void SavePlanButton_Click(object sender, RoutedEventArgs e) =>
        await SaveSelectedBundleArtifactAsync(
            SelectedOutput?.ImportPlanPath,
            "unreal-import-plan.json",
            "Unreal import plan",
            "Import plan save failed");

    private async void SaveZipButton_Click(object sender, RoutedEventArgs e) =>
        await SaveSelectedBundleArtifactAsync(
            SelectedOutput?.ZipPath,
            "unreal-bundle.zip",
            "Unreal bundle archive",
            "Bundle save failed");

    private async Task SaveSelectedBundleArtifactAsync(
        string? projectRelativePath,
        string fallbackName,
        string description,
        string errorTitle)
    {
        if (SelectedOutput?.SupportsBundleWorkflow != true || string.IsNullOrWhiteSpace(projectRelativePath))
        {
            return;
        }

        try
        {
            string suggestedName = Path.GetFileName(projectRelativePath.Replace('/', Path.DirectorySeparatorChar));
            await SaveProjectArtifactAsync(
                projectRelativePath,
                string.IsNullOrWhiteSpace(suggestedName) ? fallbackName : suggestedName,
                description);
        }
        catch (Exception ex)
        {
            SetStatus(errorTitle, ex.Message, InfoBarSeverity.Error);
        }
    }

    private async Task SaveProjectArtifactAsync(string projectRelativePath, string suggestedName, string description)
    {
        string extension = Path.GetExtension(suggestedName);
        if (string.IsNullOrWhiteSpace(extension))
        {
            extension = ".bin";
        }

        FileSavePicker picker = new()
        {
            SuggestedFileName = Path.GetFileNameWithoutExtension(suggestedName),
        };
        picker.FileTypeChoices.Add(description, [extension]);
        MainWindow mainWindow = App.MainWindowInstance ??
            throw new InvalidOperationException("The Studio window is not available.");
        InitializeWithWindow.Initialize(picker, mainWindow.WindowHandle);
        StorageFile? destination = await picker.PickSaveFileAsync();
        if (destination is null)
        {
            return;
        }

        await _projectMediaClient.StreamProjectMediaAsync<bool>(
            ActiveProjectId,
            projectRelativePath,
            async (file, cancellationToken) =>
            {
                await using Stream output = await destination.OpenStreamForWriteAsync();
                output.SetLength(0);
                await file.Stream.CopyToAsync(output, cancellationToken);
                await output.FlushAsync(cancellationToken);
                return true;
            });

        SetStatus("File saved", $"Saved {destination.Name}.", InfoBarSeverity.Success);
    }

    private void SearchBox_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (_isInitialized && args.Reason == AutoSuggestionBoxTextChangeReason.UserInput)
        {
            ApplyFilters();
        }
    }

    private void Filter_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_isInitialized)
        {
            ApplyFilters();
        }
    }

    private void ApplyFilters(string? preferredStableIdentity = null)
    {
        string? selectionIdentity = preferredStableIdentity ?? SelectedOutput?.StableIdentity;
        string? kindFilter = KindFilter.SelectedIndex switch
        {
            1 => "IMAGES",
            2 => "VIDEOS",
            3 => "UNREAL",
            4 => "OTHER",
            _ => null,
        };
        StudioOutputSort sortOrder = SortOrder.SelectedIndex switch
        {
            1 => StudioOutputSort.Name,
            2 => StudioOutputSort.SizeDescending,
            _ => StudioOutputSort.Newest,
        };

        VisibleItems.Clear();
        foreach (StudioOutputItem item in StudioOutputCatalog.FilterAndSort(
                     Items,
                     SearchBox.Text,
                     kindFilter,
                     sortOrder))
        {
            VisibleItems.Add(item);
        }

        OutputsList.SelectedItem = VisibleItems.FirstOrDefault(
            item => string.Equals(item.StableIdentity, selectionIdentity, StringComparison.OrdinalIgnoreCase));
    }

    private void ReviewButton_Click(object sender, RoutedEventArgs e)
    {
        if (SelectedOutput?.SupportsMediaWorkflow != true)
        {
            return;
        }

        _session.SetLastWorkflowDestination("review");
        Frame.Navigate(typeof(ReviewPage));
    }

    private async void TimelineButton_Click(object sender, RoutedEventArgs e)
    {
        if (SelectedOutput?.SupportsMediaWorkflow != true)
        {
            return;
        }

        StudioOutputItem selected = SelectedOutput;
        string? jobId = FindMetadataString(selected.Metadata, "job_id");
        if (string.IsNullOrWhiteSpace(jobId))
        {
            StudioJobListResponse jobs = await _apiClient.GetProjectJobsAsync(ActiveProjectId);
            jobId = jobs.Jobs.FirstOrDefault(job =>
                job.Status == "succeeded" &&
                string.Equals(
                    NormalizeProjectPath(FindJobOutputPath(job.Result)),
                    NormalizeProjectPath(selected.Path),
                    StringComparison.OrdinalIgnoreCase))?.Id;
        }
        if (string.IsNullOrWhiteSpace(jobId))
        {
            SetStatus("Job identity required", "Select this completed render in Queue first, or use output metadata containing job_id.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            EditorState editor = await _apiClient.GetEditorStateAsync(ActiveProjectId);
            double startSeconds = _session.TimelineFocusSeconds ?? 0;
            await _apiClient.InsertRenderResultWithFallbackAsync(
                ActiveProjectId,
                new InsertRenderResultRequest(jobId, editor.Revision, StartSeconds: startSeconds),
                new RenderResultDescriptor(jobId, selected.Path, Metadata: selected.Metadata as JsonObject));
            _session.SetLastWorkflowDestination("timeline");
            Frame.Navigate(typeof(TimelinePage));
        }
        catch (Exception ex)
        {
            SetStatus("Timeline insertion failed", ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private static string? FindMetadataString(JsonNode? node, string name)
    {
        if (node is JsonObject obj)
        {
            if (obj[name] is JsonValue value && value.TryGetValue<string>(out string? result)) return result;
            foreach ((_, JsonNode? child) in obj)
            {
                string? nested = FindMetadataString(child, name);
                if (!string.IsNullOrWhiteSpace(nested)) return nested;
            }
        }
        else if (node is JsonArray array)
        {
            foreach (JsonNode? child in array)
            {
                string? nested = FindMetadataString(child, name);
                if (!string.IsNullOrWhiteSpace(nested)) return nested;
            }
        }
        return null;
    }

    private static string? FindJobOutputPath(JsonElement? result)
    {
        if (result is not JsonElement element) return null;
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (string name in new[] { "video", "output_path", "path", "video_path", "artifact_path" })
            {
                if (element.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String)
                    return value.GetString();
            }
            foreach (JsonProperty property in element.EnumerateObject())
            {
                string? nested = FindJobOutputPath(property.Value);
                if (!string.IsNullOrWhiteSpace(nested)) return nested;
            }
        }
        return null;
    }

    private static string NormalizeProjectPath(string? path) =>
        (path ?? string.Empty).Replace('\\', '/').TrimStart('/');

    private void RenderButton_Click(object sender, RoutedEventArgs e)
    {
        StudioOutputItem? selected = SelectedOutput;
        if (selected?.SupportsMediaWorkflow != true)
        {
            return;
        }

        _session.SetSourceAsset(selected.Path);
        _session.SetLastWorkflowDestination("render");
        Frame.Navigate(typeof(RenderPage));
    }

    private void SetBusy(bool busy)
    {
        BusyRing.IsActive = busy;
        RefreshButton.IsEnabled = !busy;
        ExportUnrealButton.IsEnabled = !busy;
        OutputsList.IsEnabled = !busy;
        if (busy)
        {
            SaveButton.IsEnabled = false;
            RevealButton.IsEnabled = false;
            ReviewButton.IsEnabled = false;
            TimelineButton.IsEnabled = false;
            RenderButton.IsEnabled = false;
            BuildUnrealPlanButton.IsEnabled = false;
            ImportUnrealReturnButton.IsEnabled = false;
            RevealBundleButton.IsEnabled = false;
            SaveManifestButton.IsEnabled = false;
            SavePlanButton.IsEnabled = false;
            SaveZipButton.IsEnabled = false;
        }
        else
        {
            UpdateSelectionUi(SelectedOutput);
        }
    }

    private void SetStatus(string title, string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Title = title;
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private static string? OptionalText(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();
}
