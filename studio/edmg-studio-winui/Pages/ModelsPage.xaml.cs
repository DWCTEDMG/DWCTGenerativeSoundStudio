using System.Collections.ObjectModel;
using System.Text.Json;
using EdmgStudio.Core.Models;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage.Pickers;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class ModelsPage : Page, IStudioRefreshable
{
    private const string TensorRtModelId = "local_sd15_tensorrt_bundle";
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
    private readonly DispatcherQueueTimer _pollTimer;
    private readonly ObservableCollection<ModelPresentation> _visibleModels = [];
    private readonly ObservableCollection<ModelPackPresentation> _packs = [];
    private readonly ObservableCollection<ModelTaskPresentation> _tasks = [];
    private CancellationTokenSource? _pageCancellation;
    private ModelCatalogueResponse? _catalogue;
    private ModelPresentation? _selectedModel;
    private TensorRtMigrationStatus? _tensorRtStatus;
    private string? _taskFingerprint;
    private bool _isRefreshing;
    private bool _isPolling;
    private bool _isCommandRunning;

    public ModelsPage()
    {
        InitializeComponent();
        ModelList.ItemsSource = _visibleModels;
        PackCombo.ItemsSource = _packs;
        TaskItems.ItemsSource = _tasks;
        _pollTimer = DispatcherQueue.CreateTimer();
        _pollTimer.Interval = TimeSpan.FromSeconds(15);
        _pollTimer.Tick += PollTimer_Tick;
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        if (_isRefreshing)
        {
            return;
        }

        _isRefreshing = true;
        try
        {
            ModelCatalogueResponse response = await _apiClient.GetTypedModelCatalogueAsync(cancellationToken);
            _catalogue = response;
            _tensorRtStatus = response.TensorRtMigration;
            RebuildModels();
            RebuildPacks();
            UpdateStorage(response);
            if (_tensorRtStatus is null)
            {
                _tensorRtStatus = await _apiClient.GetTensorRtLegacyStatusAsync(cancellationToken);
            }
            UpdateTensorRt();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
        }
        finally
        {
            _isRefreshing = false;
        }
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        _pageCancellation?.Cancel();
        _pageCancellation?.Dispose();
        _pageCancellation = new CancellationTokenSource();
        CancellationToken cancellationToken = _pageCancellation.Token;
        await RefreshAsync(cancellationToken);
        await PollTasksAsync(cancellationToken);
        if (!cancellationToken.IsCancellationRequested)
        {
            _pollTimer.Start();
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        _pollTimer.Stop();
        _pageCancellation?.Cancel();
    }

    private async void PollTimer_Tick(DispatcherQueueTimer sender, object args)
    {
        if (_pageCancellation is { IsCancellationRequested: false } cancellation)
        {
            await PollTasksAsync(cancellation.Token);
        }
    }

    private async Task PollTasksAsync(CancellationToken cancellationToken)
    {
        if (_isPolling)
        {
            return;
        }

        _isPolling = true;
        try
        {
            ModelTaskListResponse response = await _apiClient.GetModelTasksAsync(cancellationToken);
            IReadOnlyList<ModelTask> tasks = response.Tasks ?? [];
            string fingerprint = ModelTask.Fingerprint(tasks);
            bool catalogueChanged = _taskFingerprint is not null
                && !string.Equals(_taskFingerprint, fingerprint, StringComparison.Ordinal);
            _taskFingerprint = fingerprint;

            _tasks.Clear();
            foreach (ModelTask task in tasks.Take(12))
            {
                _tasks.Add(new ModelTaskPresentation(task));
            }

            bool hasActiveTasks = tasks.Any(task => task.IsActive);
            _pollTimer.Interval = hasActiveTasks ? TimeSpan.FromSeconds(1) : TimeSpan.FromSeconds(15);
            TaskCountText.Text = tasks.Count == 0 ? string.Empty : $"{tasks.Count} total";
            NoTasksText.Visibility = tasks.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            UpdateTensorRt();

            if (catalogueChanged)
            {
                await RefreshAsync(cancellationToken);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception exception)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
            _pollTimer.Interval = TimeSpan.FromSeconds(15);
        }
        finally
        {
            _isPolling = false;
        }
    }

    private void RebuildModels()
    {
        string? selectedId = _selectedModel?.Entry.Id;
        _visibleModels.Clear();
        if (_catalogue is null)
        {
            ClearSelection();
            return;
        }

        IEnumerable<ModelPresentation> models =
            (_catalogue.Catalog ?? []).Select(entry => CreatePresentation(entry, false))
            .Concat((_catalogue.User ?? []).Select(entry => CreatePresentation(entry, true)));
        string query = SearchBox.Text.Trim();
        foreach (ModelPresentation model in models
            .Where(model => model.Matches(query))
            .OrderByDescending(model => model.IsInstalled)
            .ThenBy(model => model.DisplayName, StringComparer.OrdinalIgnoreCase))
        {
            _visibleModels.Add(model);
        }

        ModelPresentation? selected = _visibleModels.FirstOrDefault(model => model.Entry.Id == selectedId);
        if (selected is not null)
        {
            SelectModel(selected);
        }
        else if (_visibleModels.Count > 0)
        {
            SelectModel(_visibleModels[0]);
        }
        else
        {
            ClearSelection();
        }
    }

    private ModelPresentation CreatePresentation(ModelCatalogueEntry entry, bool isUserModel)
    {
        bool accepted = _catalogue?.Accepted?.ContainsKey(entry.Id) == true;
        bool installed = entry.Installed || _catalogue?.Installed?.ContainsKey(entry.Id) == true;
        return new ModelPresentation(entry, isUserModel, accepted, installed);
    }

    private void RebuildPacks()
    {
        string? selectedId = (PackCombo.SelectedItem as ModelPackPresentation)?.Pack.Id;
        _packs.Clear();
        foreach (ModelPackEntry pack in _catalogue?.Packs ?? [])
        {
            _packs.Add(new ModelPackPresentation(pack));
        }

        PackCombo.SelectedItem = _packs.FirstOrDefault(pack => pack.Pack.Id == selectedId);
        if (PackCombo.SelectedItem is null && _packs.Count > 0)
        {
            PackCombo.SelectedIndex = 0;
        }
        UpdatePackSelection();
    }

    private void SearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_catalogue is not null)
        {
            RebuildModels();
        }
    }

    private void ModelList_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is ModelPresentation model)
        {
            SelectModel(model);
        }
    }

    private void SelectModel(ModelPresentation model)
    {
        _selectedModel = model;
        ModelList.SelectedItem = model;
        ModelNameText.Text = model.DisplayName;
        ModelDescriptionText.Text = string.IsNullOrWhiteSpace(model.Entry.Description)
            ? "No model description was supplied."
            : model.Entry.Description;
        ModelMetadataText.Text =
            $"{model.Entry.Id}\nKind: {model.Kind}  |  Source: {model.Source}  |  Lane: {model.Lane}\n"
            + $"State: {model.StateLabel}";
        LicenseText.Text = model.RequiresLicense
            ? $"{model.Entry.LicenseName ?? model.Entry.LicenseId ?? "Model license"}"
                + (model.IsAccepted ? " - accepted" : " - acceptance required before installation")
            : "No separate license acceptance is required.";
        UpdateActionState();
    }

    private void ClearSelection()
    {
        _selectedModel = null;
        ModelList.SelectedItem = null;
        ModelNameText.Text = "Select a model";
        ModelDescriptionText.Text = "Choose a catalogue or imported model to view its controls.";
        ModelMetadataText.Text = string.Empty;
        LicenseText.Text = string.Empty;
        UpdateActionState();
    }

    private void UpdateActionState()
    {
        ModelPresentation? model = _selectedModel;
        bool available = model is not null && !_isCommandRunning;
        bool canInstall = available && !model!.IsInstalled;
        PrimaryActionButton.IsEnabled = canInstall;
        PrimaryActionButton.Content = model switch
        {
            null => "Install",
            { IsInstalled: true } => "Installed",
            { IsUserModel: true } => "Restore local model",
            { RequiresLicense: true, IsAccepted: false } => "Accept and install",
            _ => "Install"
        };
        AcceptLicenseButton.IsEnabled = available && model!.RequiresLicense && !model.IsAccepted;
        BenchmarkButton.IsEnabled = available;
        RemoveButton.IsEnabled = available && model!.IsUserModel;
        PromoteButton.IsEnabled = available;
        RefreshButton.IsEnabled = !_isCommandRunning;
        CivitaiImportButton.IsEnabled = !_isCommandRunning && !string.IsNullOrWhiteSpace(CivitaiUrlBox.Text);
        InstallPackButton.IsEnabled = !_isCommandRunning && PackCombo.SelectedItem is ModelPackPresentation;
        UpdateTensorRt();
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        if (_pageCancellation is { IsCancellationRequested: false } cancellation)
        {
            await RefreshAsync(cancellation.Token);
            await PollTasksAsync(cancellation.Token);
        }
    }

    private async void PrimaryAction_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedModel is not { } model)
        {
            return;
        }

        if (model.IsUserModel)
        {
            await RunCommandAsync(
                token => _apiClient.RestoreLocalModelAsync(model.Entry.Id, token),
                "Local model restore queued.");
            return;
        }

        if (model.RequiresLicense && !model.IsAccepted)
        {
            ContentDialogResult result = await ShowLicenseDialogAsync(
                model,
                "Accept and install",
                $"Review and accept the license for {model.DisplayName}, then queue installation.");
            if (result != ContentDialogResult.Primary)
            {
                return;
            }
        }

        await RunCommandAsync(
            async token =>
            {
                if (model.RequiresLicense && !model.IsAccepted)
                {
                    await _apiClient.AcceptModelLicenseAsync(
                        model.Entry.Id,
                        model.Entry.LicenseId ?? "unknown",
                        token);
                }
                await _apiClient.InstallModelAsync(model.Entry.Id, token);
            },
            "Model installation queued.");
    }

    private async void AcceptLicense_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedModel is not { RequiresLicense: true } model)
        {
            return;
        }

        if (await ShowLicenseDialogAsync(
            model,
            "Accept license",
            $"Accept the license for {model.DisplayName}?") != ContentDialogResult.Primary)
        {
            return;
        }

        await RunCommandAsync(
            token => _apiClient.AcceptModelLicenseAsync(
                model.Entry.Id,
                model.Entry.LicenseId ?? "unknown",
                token),
            "Model license accepted.");
    }

    private async Task<ContentDialogResult> ShowLicenseDialogAsync(
        ModelPresentation model,
        string primaryButtonText,
        string prompt)
    {
        var content = new StackPanel { Spacing = 10 };
        content.Children.Add(new TextBlock { Text = prompt, TextWrapping = TextWrapping.Wrap });
        content.Children.Add(new TextBlock
        {
            Text = model.Entry.LicenseName ?? model.Entry.LicenseId ?? "Model license",
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap
        });
        if (Uri.TryCreate(model.Entry.LicenseUrl, UriKind.Absolute, out Uri? licenseUri))
        {
            content.Children.Add(new HyperlinkButton
            {
                Content = "Open license terms",
                NavigateUri = licenseUri,
                HorizontalAlignment = HorizontalAlignment.Left
            });
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Model license",
            Content = content,
            PrimaryButtonText = primaryButtonText,
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        return await dialog.ShowAsync();
    }

    private async void Benchmark_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedModel is { } model)
        {
            await RunCommandAsync(
                token => _apiClient.RecordModelBenchmarkAsync(model.Entry.Id, token),
                "Benchmark record saved.");
        }
    }

    private async void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedModel is not { IsUserModel: true } model)
        {
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Remove user model?",
            Content = $"Remove {model.DisplayName} from this Studio Home? You can import it again later.",
            PrimaryButtonText = "Remove",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        await RunCommandAsync(
            token => _apiClient.RemoveUserModelAsync(model.Entry.Id, token),
            "User model removed.");
    }

    private async void Promote_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedModel is null || LaneCombo.SelectedItem is not ComboBoxItem { Tag: string lane })
        {
            return;
        }

        await RunCommandAsync(
            token => _apiClient.PromoteModelAsync(_selectedModel.Entry.Id, lane, token),
            $"Model promoted to {lane}.");
    }

    private void PackCombo_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdatePackSelection();

    private void UpdatePackSelection()
    {
        if (PackCombo.SelectedItem is not ModelPackPresentation pack)
        {
            PackDescriptionText.Text = "No model packs are available.";
            InstallPackButton.IsEnabled = false;
            return;
        }

        PackDescriptionText.Text = pack.Description;
        InstallPackButton.IsEnabled = !_isCommandRunning;
    }

    private async void InstallPack_Click(object sender, RoutedEventArgs e)
    {
        if (PackCombo.SelectedItem is not ModelPackPresentation pack || _catalogue is null)
        {
            return;
        }

        Dictionary<string, ModelCatalogueEntry> entries = (_catalogue.Catalog ?? [])
            .Concat(_catalogue.User ?? [])
            .ToDictionary(entry => entry.Id, StringComparer.Ordinal);
        List<ModelCatalogueEntry> licenses = (pack.Pack.Models ?? [])
            .Where(entries.ContainsKey)
            .Select(id => entries[id])
            .Where(entry =>
                !string.Equals(entry.Source, "ollama", StringComparison.OrdinalIgnoreCase)
                && _catalogue.Accepted?.ContainsKey(entry.Id) != true)
            .ToList();

        if (licenses.Count > 0)
        {
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = "Accept licenses and install pack?",
                Content =
                    $"{pack.DisplayName} requires acceptance for {licenses.Count} model license(s): "
                    + string.Join(", ", licenses.Select(entry => entry.Name ?? entry.Id))
                    + ". Studio will record each acceptance before queuing the pack.",
                PrimaryButtonText = "Accept and install",
                CloseButtonText = "Cancel",
                DefaultButton = ContentDialogButton.Close
            };
            if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            {
                return;
            }
        }

        await RunCommandAsync(
            async token =>
            {
                foreach (ModelCatalogueEntry entry in licenses)
                {
                    await _apiClient.AcceptModelLicenseAsync(
                        entry.Id,
                        entry.LicenseId ?? "unknown",
                        token);
                }
                await _apiClient.InstallModelPackAsync(pack.Pack.Id, token);
            },
            "Model pack installation queued.");
    }

    private void CivitaiUrlBox_TextChanged(object sender, TextChangedEventArgs e) => UpdateActionState();

    private async void CivitaiImport_Click(object sender, RoutedEventArgs e)
    {
        string url = CivitaiUrlBox.Text.Trim();
        if (url.Length == 0)
        {
            return;
        }

        await RunCommandAsync(
            token => _apiClient.ImportCivitaiModelAsync(url, token),
            "Civitai model imported.");
        CivitaiUrlBox.Text = string.Empty;
    }

    private async void LocalImport_Click(object sender, RoutedEventArgs e)
    {
        if (App.MainWindowInstance is null)
        {
            ShowStatus("The Studio window is not ready for file selection.", InfoBarSeverity.Error);
            return;
        }

        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.Downloads,
            ViewMode = PickerViewMode.List
        };
        foreach (string extension in new[] { ".safetensors", ".ckpt", ".pt", ".bin" })
        {
            picker.FileTypeFilter.Add(extension);
        }

        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance.WindowHandle);
        Windows.Storage.StorageFile? file = await picker.PickSingleFileAsync();
        if (file is null || LocalFolderCombo.SelectedItem is not ComboBoxItem { Tag: string folder })
        {
            return;
        }

        await RunCommandAsync(
            token => _apiClient.ImportLocalModelAsync(file.Path, folder, cancellationToken: token),
            $"Imported {file.Name}.");
    }

    private async void TensorRtImport_Click(object sender, RoutedEventArgs e)
    {
        if (_tensorRtStatus?.Migration.Available != true)
        {
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Verify and copy TensorRT engines?",
            Content =
                "Studio will create a complete second copy of the four legacy TensorRT engines in the canonical managed bundle. "
                + "The operation can take several minutes, requires the reported free disk space, and verifies every copied file by SHA-256 before publishing it. "
                + "The original legacy files remain unchanged.",
            PrimaryButtonText = "Verify and copy",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        await RunCommandAsync(
            async token =>
            {
                ModelTaskActionResponse response = await _apiClient.ImportLegacyTensorRtAsync(token);
                UpsertTask(response.Task);
            },
            "Verification and safe copy started. The legacy source will remain in place.");
    }

    private async void TensorRtCancel_Click(object sender, RoutedEventArgs e)
    {
        ModelTaskPresentation? active = _tasks.FirstOrDefault(
            task => task.Task.ModelId == TensorRtModelId && task.Task.IsActive);
        if (active is null)
        {
            return;
        }

        await RunCommandAsync(
            async token =>
            {
                ModelTaskActionResponse response =
                    await _apiClient.CancelLegacyTensorRtImportAsync(active.Task.Id, token);
                UpsertTask(response.Task);
            },
            "Cancellation requested. Temporary copies will be removed; legacy engines remain unchanged.");
    }

    private void UpsertTask(ModelTask task)
    {
        ModelTaskPresentation? existing = _tasks.FirstOrDefault(item => item.Task.Id == task.Id);
        if (existing is not null)
        {
            _tasks.Remove(existing);
        }
        _tasks.Insert(0, new ModelTaskPresentation(task));
        UpdateTensorRt();
    }

    private void UpdateTensorRt()
    {
        ModelTaskPresentation? active = _tasks.FirstOrDefault(
            task => task.Task.ModelId == TensorRtModelId && task.Task.IsActive);
        TensorRtCancelButton.IsEnabled = !_isCommandRunning && active is not null;
        TensorRtImportButton.IsEnabled =
            !_isCommandRunning && active is null && _tensorRtStatus?.Migration.Available == true;

        if (_tensorRtStatus is null)
        {
            TensorRtSummaryText.Text = "Checking legacy TensorRT bundle status...";
            TensorRtDiskText.Text = string.Empty;
            return;
        }

        TensorRtLegacyStatus legacy = _tensorRtStatus.Legacy;
        TensorRtMigrationAvailability migration = _tensorRtStatus.Migration;
        TensorRtSummaryText.Text = active is not null
            ? $"Migration {active.Task.Status}: {active.Task.DisplayStage}"
            : legacy.Status switch
            {
                "absent" => "No root-level legacy TensorRT engine set was detected.",
                "partial" => "A partial legacy engine set was found. All expected safe, non-empty engines are required.",
                "ready_to_import" =>
                    $"Found {legacy.UsableFileCount} safe engine files ({FormatBytes(legacy.TotalBytes)}).",
                _ when _tensorRtStatus.Canonical.RendererReady => "The canonical TensorRT bundle is ready.",
                _ => $"Legacy status: {legacy.Status}"
            };
        TensorRtDiskStatus disk = migration.Disk;
        TensorRtDiskText.Text =
            $"Required free space: {FormatBytes(disk.RequiredFreeBytes)}  |  Available: "
            + (disk.AvailableFreeBytes.HasValue ? FormatBytes(disk.AvailableFreeBytes.Value) : "unknown")
            + (migration.Available
                ? "\nCopy-only migration is available; source files will be preserved."
                : $"\nMigration unavailable: {FormatBlockedReason(migration.BlockedReason)}");
    }

    private void UpdateStorage(ModelCatalogueResponse response)
    {
        StorageText.Text =
            $"Mode: {response.StorageMode ?? "local_cache"}\n"
            + $"Cache: {response.ModelCache ?? "Backend managed"}\n"
            + $"{(response.Catalog?.Count ?? 0) + (response.User?.Count ?? 0)} models, "
            + $"{response.Packs?.Count ?? 0} packs";
    }

    private async Task RunCommandAsync(Func<CancellationToken, Task> command, string successMessage)
    {
        if (_isCommandRunning)
        {
            return;
        }

        _isCommandRunning = true;
        CommandProgress.Visibility = Visibility.Visible;
        UpdateActionState();
        try
        {
            CancellationToken token = _pageCancellation?.Token ?? CancellationToken.None;
            await command(token);
            ShowStatus(successMessage, InfoBarSeverity.Success);
            await RefreshAsync(token);
            await PollTasksAsync(token);
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
        }
        catch (Exception exception)
        {
            ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
        }
        finally
        {
            _isCommandRunning = false;
            CommandProgress.Visibility = Visibility.Collapsed;
            UpdateActionState();
        }
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusBar.Message = message;
        StatusBar.Severity = severity;
        StatusBar.IsOpen = true;
    }

    private static string FormatBytes(long bytes)
    {
        string[] units = ["B", "KiB", "MiB", "GiB", "TiB"];
        double value = Math.Max(0, bytes);
        int unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }
        return $"{value:N1} {units[unit]}";
    }

    private static string FormatBlockedReason(string? reason) => reason switch
    {
        "canonical_ready" => "the canonical bundle is already ready",
        "canonical_exists" => "a canonical bundle already exists",
        "legacy_not_detected" => "legacy engines were not detected",
        "legacy_incomplete" => "the legacy engine set is incomplete",
        "insufficient_disk_space" => "insufficient free disk space",
        null or "" => "not currently available",
        _ => reason.Replace('_', ' ')
    };
}

public sealed class ModelPresentation
{
    public ModelPresentation(
        ModelCatalogueEntry entry,
        bool isUserModel,
        bool isAccepted,
        bool isInstalled)
    {
        Entry = entry;
        IsUserModel = isUserModel;
        IsAccepted = isAccepted;
        IsInstalled = isInstalled;
    }

    public ModelCatalogueEntry Entry { get; }
    public bool IsUserModel { get; }
    public bool IsAccepted { get; }
    public bool IsInstalled { get; }
    public string DisplayName => Entry.Name ?? Entry.Id;
    public string Kind => Entry.Kind ?? ReadString("type") ?? "model";
    public string Source => Entry.Source ?? (IsUserModel ? "local" : "catalogue");
    public string Lane => ReadString("lane") ?? "recommended";
    public bool RequiresLicense => !string.Equals(Source, "ollama", StringComparison.OrdinalIgnoreCase);
    public string StateLabel => IsInstalled ? "Installed" : IsUserModel ? "Imported" : "Available";
    public string Subtitle => $"{Kind} - {Source} - {Lane}";

    public bool Matches(string query) =>
        query.Length == 0
        || DisplayName.Contains(query, StringComparison.OrdinalIgnoreCase)
        || Entry.Id.Contains(query, StringComparison.OrdinalIgnoreCase)
        || Kind.Contains(query, StringComparison.OrdinalIgnoreCase)
        || Source.Contains(query, StringComparison.OrdinalIgnoreCase)
        || Lane.Contains(query, StringComparison.OrdinalIgnoreCase);

    private string? ReadString(string propertyName) =>
        Entry.ExtensionData?.TryGetValue(propertyName, out JsonElement value) == true
        && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
}

public sealed class ModelPackPresentation
{
    public ModelPackPresentation(ModelPackEntry pack) => Pack = pack;

    public ModelPackEntry Pack { get; }
    public string DisplayName => Pack.Name ?? Pack.Id;
    public string Description
    {
        get
        {
            if (Pack.ExtensionData?.TryGetValue("description", out JsonElement value) == true
                && value.ValueKind == JsonValueKind.String)
            {
                return value.GetString() ?? string.Empty;
            }
            return $"{Pack.Models?.Count ?? 0} models: {string.Join(", ", Pack.Models ?? [])}";
        }
    }
}

public sealed class ModelTaskPresentation
{
    public ModelTaskPresentation(ModelTask task) => Task = task;

    public ModelTask Task { get; }
    public string DisplayName => string.IsNullOrWhiteSpace(Task.Name) ? Task.ModelId ?? Task.Id : Task.Name;
    public string StatusLabel => Task.Status;
    public double Progress => Task.ClampedProgress;
    public Visibility ProgressVisibility => Task.HasProgress ? Visibility.Visible : Visibility.Collapsed;
    public string Detail => Task.Error ?? Task.DisplayStage;
}
