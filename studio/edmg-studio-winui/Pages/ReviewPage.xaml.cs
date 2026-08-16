using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class ReviewPage : Page
{
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;
    private string? _projectId;
    private CancellationTokenSource? _previewCancellation;
    private int _previewGeneration;

    public ObservableCollection<ReviewArtifact> Artifacts { get; } = [];

    public ReviewPage()
    {
        InitializeComponent();
        Loaded += ReviewPage_Loaded;
    }

    private async void ReviewPage_Loaded(object sender, RoutedEventArgs e)
    {
        _projectId = App.Services.Session.ActiveProjectId;
        await RefreshAsync();
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async Task RefreshAsync()
    {
        if (string.IsNullOrWhiteSpace(_projectId))
        {
            ShowStatus("Open a project to review variants.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            ClearArtifactDetails();
            ArtifactsList.SelectedItem = null;
            Artifacts.Clear();
            var response = StudioPageHelpers.ToObject(await _apiClient.GetVariantReviewAsync(_projectId));
            var review = response["variant_review"] as JsonObject ?? response;
            var variantCount = review["plan_variant_count"]?.GetValue<int?>() ?? 0;
            var artifactCount = review["artifact_count"]?.GetValue<int?>() ?? 0;
            var compareReady = review["compare_ready"]?.GetValue<bool?>() ?? false;
            SummaryText.Text = $"{variantCount} variants • {artifactCount} artifacts • comparison {(compareReady ? "ready" : "not ready")}";

            if (review["groups"] is JsonArray groups)
            {
                foreach (var group in groups.OfType<JsonObject>())
                {
                    var groupName = group["label"]?.GetValue<string>()
                        ?? "Artifacts";
                    var entries = group["artifacts"] as JsonArray ?? group["items"] as JsonArray;
                    if (entries is null)
                    {
                        continue;
                    }

                    foreach (var artifact in entries.OfType<JsonObject>())
                    {
                        var path = artifact["path"]?.GetValue<string>() ?? string.Empty;
                        var name = artifact["name"]?.GetValue<string>() ?? Path.GetFileName(path);
                        Artifacts.Add(new ReviewArtifact(groupName, name, path, artifact.DeepClone().AsObject()));
                    }
                }
            }

            ShowStatus(Artifacts.Count == 0 ? "No reviewable artifacts are available yet." : "Review state loaded.",
                Artifacts.Count == 0 ? InfoBarSeverity.Informational : InfoBarSeverity.Success);
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

    private async void ArtifactsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        CancelPreview();
        int generation = Interlocked.Increment(ref _previewGeneration);

        if (ArtifactsList.SelectedItem is not ReviewArtifact artifact)
        {
            ClearArtifactDetails();
            return;
        }

        SelectedArtifactText.Text = artifact.Name;
        SelectedPathText.Text = artifact.Path;
        NotesTextBox.Text = artifact.Data["review_notes"]?.GetValue<string>() ?? string.Empty;
        TraitsTextBox.Text = JoinValues(artifact.Data["cherry_pick_traits"]);
        LockFieldsTextBox.Text = JoinValues(artifact.Data["locks"]);
        MetadataTextBox.Text = StudioPageHelpers.FormatJson(artifact.Data);

        if ((!artifact.IsImage && !artifact.IsVideo) || string.IsNullOrWhiteSpace(_projectId))
        {
            ArtifactPreview.ShowUnsupported("This artifact does not have an inline preview.");
            return;
        }

        _previewCancellation = new CancellationTokenSource();
        CancellationToken cancellationToken = _previewCancellation.Token;
        try
        {
            await _apiClient.StreamProjectFileAsync(
                _projectId,
                artifact.Path,
                async (file, callbackToken) =>
                {
                    if (generation != Volatile.Read(ref _previewGeneration))
                    {
                        return false;
                    }

                    if (artifact.IsVideo)
                    {
                        await ArtifactPreview.LoadVideoStreamAsync(file.Stream, callbackToken);
                    }
                    else
                    {
                        await ArtifactPreview.LoadStreamAsync(
                            file.Stream,
                            file.ContentHeaders.ContentType?.MediaType,
                            callbackToken);
                    }
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
                ArtifactPreview.ShowError("Preview failed to load.");
                ShowStatus(StudioPageHelpers.GetErrorMessage(exception), InfoBarSeverity.Error);
            }
        }
    }

    private void ClearArtifactDetails()
    {
        SelectedArtifactText.Text = "Select an artifact";
        SelectedPathText.Text = string.Empty;
        NotesTextBox.Text = string.Empty;
        TraitsTextBox.Text = string.Empty;
        LockFieldsTextBox.Text = string.Empty;
        MetadataTextBox.Text = string.Empty;
        ArtifactPreview.ShowEmpty("Select an artifact to preview it here.");
    }

    private void ReviewPage_Unloaded(object sender, RoutedEventArgs e) => CancelPreview();

    private void CancelPreview()
    {
        Interlocked.Increment(ref _previewGeneration);
        CancellationTokenSource? cancellation = Interlocked.Exchange(ref _previewCancellation, null);
        cancellation?.Cancel();
        cancellation?.Dispose();
    }

    private async void ApproveButton_Click(object sender, RoutedEventArgs e) => await SaveDecisionAsync("approved");
    private async void RejectButton_Click(object sender, RoutedEventArgs e) => await SaveDecisionAsync("rejected");
    private async void CherryPickButton_Click(object sender, RoutedEventArgs e) => await SaveDecisionAsync("cherry_picked");
    private async void ClearButton_Click(object sender, RoutedEventArgs e) => await SaveDecisionAsync("unreviewed");

    private async Task SaveDecisionAsync(string decision)
    {
        if (ArtifactsList.SelectedItem is not ReviewArtifact artifact || string.IsNullOrWhiteSpace(_projectId))
        {
            ShowStatus("Select an artifact first.", InfoBarSeverity.Warning);
            return;
        }

        SetBusy(true);
        try
        {
            var request = new JsonObject
            {
                ["artifact_path"] = artifact.Path,
                ["decision"] = decision,
                ["notes"] = NotesTextBox.Text.Trim(),
                ["cherry_pick_traits"] = ToJsonArray(TraitsTextBox.Text),
                ["lock_fields"] = ToJsonArray(LockFieldsTextBox.Text)
            };
            await _apiClient.SaveVariantDecisionAsync(_projectId, request);
            ShowStatus($"Decision saved: {decision.Replace('_', ' ')}.", InfoBarSeverity.Success);
            await RefreshAsync();
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

    private static JsonArray ToJsonArray(string value)
        => new(value.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Select(item => JsonValue.Create(item)).ToArray());

    private static string JoinValues(JsonNode? node)
        => node is JsonArray array ? string.Join(", ", array.Select(item => item?.ToString()).Where(item => !string.IsNullOrWhiteSpace(item))) : string.Empty;

    private void SetBusy(bool value)
    {
        BusyRing.IsActive = value;
        RefreshButton.IsEnabled = !value;
        StudioPageHelpers.SetControlsEnabled(ReviewWorkspace, !value);
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }
}

public sealed class ReviewArtifact
{
    public ReviewArtifact(string group, string name, string path, JsonObject data)
    {
        Group = group;
        Name = name;
        Path = path;
        Data = data;
    }

    public string Group { get; set; }
    public string Name { get; set; }
    public string Path { get; set; }
    public JsonObject Data { get; set; }
    public bool IsImage => new[] { ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico" }
        .Contains(System.IO.Path.GetExtension(Name), StringComparer.OrdinalIgnoreCase);
    public bool IsVideo => new[] { ".mp4", ".mov", ".webm", ".mkv", ".avi" }
        .Contains(System.IO.Path.GetExtension(Name), StringComparer.OrdinalIgnoreCase);

    public string Summary
    {
        get
        {
            var state = Data["review_state"]?.GetValue<string>() ?? Data["decision"]?.GetValue<string>() ?? "unreviewed";
            var variant = Data["variant_index"]?.ToString();
            return string.IsNullOrWhiteSpace(variant) ? $"{Group} • {state}" : $"{Group} • variant {variant} • {state}";
        }
    }
}
