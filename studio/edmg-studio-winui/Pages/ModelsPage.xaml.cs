using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class ModelsPage : Page
{
    private readonly EdmgStudio.Core.Services.StudioApiClient _apiClient = App.Services.ApiClient;

    public ObservableCollection<ModelEntry> Models { get; } = [];
    public ObservableCollection<ModelPack> Packs { get; } = [];

    public ModelsPage()
    {
        InitializeComponent();
        PackComboBox.ItemsSource = Packs;
        Loaded += ModelsPage_Loaded;
    }

    private async void ModelsPage_Loaded(object sender, RoutedEventArgs e) => await RefreshAsync();
    private async void RefreshButton_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async Task RefreshAsync()
    {
        SetBusy(true);
        try
        {
            Models.Clear();
            Packs.Clear();
            var response = StudioPageHelpers.ToObject(await _apiClient.GetModelCatalogAsync());
            var installed = response["installed"] as JsonObject;
            AddEntries(response["catalog"] as JsonArray, false, installed);
            AddEntries(response["user"] as JsonArray, true, installed);

            if (response["packs"] is JsonArray packs)
            {
                foreach (var pack in packs.OfType<JsonObject>())
                {
                    var id = pack["id"]?.GetValue<string>() ?? pack["name"]?.GetValue<string>() ?? string.Empty;
                    if (!string.IsNullOrWhiteSpace(id))
                    {
                        Packs.Add(new ModelPack(id, pack["name"]?.GetValue<string>() ?? id));
                    }
                }
            }

            StorageText.Text = $"Storage: {response["storage_mode"]?.ToString() ?? "default"} • Cache: {response["model_cache"]?.ToString() ?? "backend managed"} • {Models.Count} models";
            ShowStatus("Model catalogue loaded.", InfoBarSeverity.Success);
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

    private void AddEntries(JsonArray? entries, bool isUserModel, JsonObject? installed)
    {
        if (entries is null)
        {
            return;
        }

        foreach (var item in entries.OfType<JsonObject>())
        {
            var id = item["id"]?.GetValue<string>() ?? string.Empty;
            if (string.IsNullOrWhiteSpace(id))
            {
                continue;
            }

            var isInstalled = installed?.ContainsKey(id) == true;
            Models.Add(new ModelEntry(id, item["name"]?.GetValue<string>() ?? id, isUserModel, isInstalled, item.DeepClone().AsObject()));
        }
    }

    private void ModelsList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ModelsList.SelectedItem is not ModelEntry model)
        {
            SelectedModelText.Text = "Select a model";
            ModelStatusText.Text = string.Empty;
            ModelJsonTextBox.Text = string.Empty;
            LaneComboBox.SelectedIndex = 1;
            return;
        }

        SelectedModelText.Text = model.DisplayName;
        ModelStatusText.Text = $"{model.Id} • {(model.IsInstalled ? "installed" : "not installed")} • {model.Lane} • license {model.LicenseId}";
        ModelJsonTextBox.Text = StudioPageHelpers.FormatJson(model.Data);
        LaneComboBox.SelectedItem = model.Lane;
    }

    private async void AcceptLicenseButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModelsList.SelectedItem is not ModelEntry model)
        {
            ShowStatus("Select a model first.", InfoBarSeverity.Warning);
            return;
        }
        await RunActionAsync(() => _apiClient.AcceptModelLicenseAsync(model.Id, model.LicenseId), "License accepted.");
    }

    private async void InstallButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModelsList.SelectedItem is not ModelEntry model)
        {
            ShowStatus("Select a model first.", InfoBarSeverity.Warning);
            return;
        }
        await RunActionAsync(() => _apiClient.InstallModelAsync(model.Id), "Install task queued.");
    }

    private async void RestoreButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModelsList.SelectedItem is not ModelEntry model)
        {
            ShowStatus("Select a model first.", InfoBarSeverity.Warning);
            return;
        }
        await RunActionAsync(() => _apiClient.RestoreLocalModelAsync(model.Id), "Restore task queued.");
    }

    private async void RemoveButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModelsList.SelectedItem is not ModelEntry model || !model.IsUserModel)
        {
            ShowStatus("Select a user-supplied model to remove.", InfoBarSeverity.Warning);
            return;
        }

        var confirmation = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Remove user model?",
            Content = $"Remove {model.DisplayName} ({model.Id}) from this device? You can add it again later.",
            PrimaryButtonText = "Remove",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await confirmation.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        await RunActionAsync(() => _apiClient.RemoveUserModelAsync(model.Id), "User model removed.");
    }

    private async void PromoteButton_Click(object sender, RoutedEventArgs e)
    {
        if (ModelsList.SelectedItem is not ModelEntry model || LaneComboBox.SelectedItem is not string lane)
        {
            ShowStatus("Select a model and lane first.", InfoBarSeverity.Warning);
            return;
        }
        await RunActionAsync(() => _apiClient.PromoteModelAsync(model.Id, lane), "Model lane updated.");
    }

    private async void InstallPackButton_Click(object sender, RoutedEventArgs e)
    {
        if (PackComboBox.SelectedItem is not ModelPack pack)
        {
            ShowStatus("Choose a model pack first.", InfoBarSeverity.Warning);
            return;
        }
        await RunActionAsync(() => _apiClient.InstallModelPackAsync(pack.Id), "Pack installation queued.");
    }

    private async Task RunActionAsync(Func<Task> action, string successMessage)
    {
        SetBusy(true);
        try
        {
            await action();
            ShowStatus(successMessage, InfoBarSeverity.Success);
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

    private void SetBusy(bool value)
    {
        BusyRing.IsActive = value;
        RefreshButton.IsEnabled = !value;
        StudioPageHelpers.SetControlsEnabled(ContentGrid, !value);
    }

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }
}

public sealed class ModelPack
{
    public ModelPack(string id, string name)
    {
        Id = id;
        Name = name;
    }

    public string Id { get; set; }
    public string Name { get; set; }
}

public sealed class ModelEntry
{
    public ModelEntry(string id, string displayName, bool isUserModel, bool isInstalled, JsonObject data)
    {
        Id = id;
        DisplayName = displayName;
        IsUserModel = isUserModel;
        IsInstalled = isInstalled;
        Data = data;
    }

    public string Id { get; set; }
    public string DisplayName { get; set; }
    public bool IsUserModel { get; set; }
    public bool IsInstalled { get; set; }
    public JsonObject Data { get; set; }
    public string Lane => Data["lane"]?.GetValue<string>() ?? "recommended";
    public string LicenseId => Data["license_id"]?.GetValue<string>() ?? "unknown";
    public string Summary => $"{(IsUserModel ? "User" : "Catalogue")} • {(IsInstalled ? "installed" : "available")} • {Lane}";
}
