using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace EdmgStudio.WinUI.Pages;

public sealed partial class RenderPage : Page
{
    private string? _projectId;
    private bool _isBusy;
    private CancellationTokenSource? _pageCancellation;

    public RenderPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _pageCancellation?.Cancel();
        _pageCancellation?.Dispose();
        _pageCancellation = new CancellationTokenSource();

        string activeProjectId = App.Services.Session.ActiveProjectId;
        _projectId = string.IsNullOrWhiteSpace(activeProjectId) ? null : activeProjectId.Trim();
        ActiveProjectText.Text = _projectId is null
            ? "No active project"
            : $"Project {StudioPageHelpers.ShortId(_projectId)}";
        ApplySelectedVariant();
        SetBusyState();

        if (_projectId is null)
        {
            ShowStatus(
                "Choose an active project before running a project render workflow.",
                InfoBarSeverity.Warning);
        }
        else
        {
            ShowStatus(
                "Render tools are ready. Results and backend diagnostics appear below.",
                InfoBarSeverity.Informational);
        }
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _pageCancellation?.Cancel();
        base.OnNavigatedFrom(e);
    }

    private void ApplySelectedVariant()
    {
        int variantIndex = Math.Max(0, App.Services.Session.SelectedVariantIndex);
        WorkflowVariantBox.Value = variantIndex;
        ToolsVariantBox.Value = variantIndex;
        TensorVariantBox.Value = variantIndex;
        AssemblyVariantBox.Value = variantIndex;
        DeforumVariantBox.Value = variantIndex;
        ComfyExportVariantBox.Value = variantIndex;
    }

    private JsonElement BuildInternalRenderRequest()
    {
        string prompt = PromptBox.Text.Trim();
        long seed = LongNumber(SeedBox, -1);
        string? refinerModel = EmptyToNull(RefinerModelBox.Text);
        string? sourceAsset = EmptyToNull(MotionSourceBox.Text);
        JsonNode? parseqManifest = ParseOptionalNode(ParseqBox.Text, "Parseq manifest", JsonValueKind.Object);

        var request = new JsonObject
        {
            ["variant_index"] = Math.Max(0, App.Services.Session.SelectedVariantIndex),
            ["fps_output"] = Number(FpsBox, 24),
            ["fps_render"] = Math.Min(Number(FpsBox, 24), 30),
            ["width"] = Number(WidthBox, 1280),
            ["height"] = Number(HeightBox, 720),
            ["steps"] = Number(StepsBox, 28),
            ["cfg"] = Number(CfgBox, 7.0),
            ["sampler"] = Selected(SamplerComboBox, "euler"),
            ["seed"] = seed < 0 ? null : seed,
            ["keyframe_interval_s"] = 1.0,
            ["interpolation_engine"] = Selected(InterpolationComboBox, "auto"),
            ["model_id"] = EmptyToNull(ModelBox.Text) ?? "auto",
            ["render_mode"] = Selected(ModeComboBox, "auto"),
            ["render_tier"] = Selected(TierComboBox, "balanced"),
            ["device_preference"] = Selected(DeviceComboBox, "auto"),
            ["allow_hosted_fallback"] = true,
            ["hosted_service"] = Selected(HostedProviderComboBox, "default"),
            ["hosted_model"] = EmptyToNull(HostedModelBox.Text),
            ["negative_prompt"] = NegativePromptBox.Text.Trim(),
            ["loras"] = ParseLoras(LorasBox.Text),
            ["vae"] = EmptyToNull(VaeBox.Text),
            ["refiner"] = refinerModel is null
                ? null
                : new JsonObject { ["model"] = refinerModel, ["switch_at"] = 0.8 },
            ["temporal_mode"] = "keyframes",
            ["temporal_strength"] = Number(TemporalConsistencyBox, 0.75),
            ["motion_strategy"] = Number(MotionStrengthBox, 1.0) > 1.0
                ? "storyboard_full_motion"
                : "manual",
            ["parseq_enabled"] = parseqManifest is not null,
            ["parseq_manifest"] = parseqManifest,
            ["source_asset"] = sourceAsset,
            ["source_strength"] = Math.Clamp(Number(MotionStrengthBox, 1.0) / 5.0, 0.05, 0.95),
            ["deforum_prompts"] = string.IsNullOrWhiteSpace(prompt)
                ? null
                : new JsonObject { ["0"] = prompt },
        };

        return StudioPageHelpers.ToElement(request);
    }

    private async void Preflight_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Running internal render preflight",
            PreflightResultBox,
            (projectId, token) => App.Services.ApiClient.PreflightInternalRenderAsync(
                projectId,
                BuildInternalRenderRequest(),
                token),
            "Internal render preflight completed.");

    private async void Render_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Queueing internal render",
            PreflightResultBox,
            (projectId, token) => App.Services.ApiClient.StartInternalRenderAsync(
                projectId,
                BuildInternalRenderRequest(),
                token),
            "Internal render request was accepted. Review the response and project jobs.");

    private PipelineRunOptions BuildPipelineOptions() =>
        new(
            Number(WorkflowVariantBox, 0),
            Selected(PipelinePresetComboBox, "balanced"),
            Selected(PipelineModeComboBox, "auto"),
            Selected(PipelineEngineComboBox, "auto"));

    private async void ValidatePipeline_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Validating pipeline",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.ValidatePipelineAsync(
                projectId,
                BuildPipelineOptions(),
                token),
            "Pipeline validation completed.");

    private async void RunPipeline_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Running pipeline",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.RunPipelineAsync(
                projectId,
                BuildPipelineOptions(),
                token),
            "Pipeline run request completed.");

    private RenderConductorPlanRequest BuildConductorPlanRequest() =>
        new(
            Number(WorkflowVariantBox, 0),
            Selected(ConductorPresetComboBox, "balanced"),
            Selected(ConductorAspectComboBox, "16:9"),
            Selected(ConductorOutputModeComboBox, "full_video"),
            Selected(ConductorQualityComboBox, "quality"),
            Number(ConductorContinuityBox, 0.8),
            Number(ConductorSpeedBox, 0.4),
            Number(ConductorStyleLockBox, 0.75),
            ParseStringList(ConductorAllowedEnginesBox.Text),
            Selected(ConductorFallbackComboBox, "auto"),
            []);

    private async void InspectConductorPlan_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Inspecting conductor plan",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.GetRenderConductorPlanAsync(
                projectId,
                Number(WorkflowVariantBox, 0),
                token),
            "Conductor plan loaded.");

    private async void CreateConductorPlan_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Creating conductor plan",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.CreateRenderConductorPlanAsync(
                projectId,
                BuildConductorPlanRequest(),
                token),
            "Conductor plan created.");

    private async void PromoteConductorPlan_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Promoting conductor scenes",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.PromoteRenderConductorPlanAsync(
                projectId,
                new RenderConductorPromoteRequest(
                    EmptyToNull(ConductorPlanIdBox.Text),
                    ParseStringList(ConductorSceneIdsBox.Text),
                    Selected(ConductorTargetEngineComboBox, "internal"),
                    Selected(ConductorPromoteQualityComboBox, "quality"),
                    EmptyToNull(ConductorPromoteReasonBox.Text)),
                token),
            "Conductor promotion request completed.");

    private async void InspectConductorContinuity_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Inspecting conductor continuity",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.GetRenderConductorContinuityAsync(
                projectId,
                Number(WorkflowVariantBox, 0),
                token),
            "Conductor continuity loaded.");

    private async void InspectPerformerPlan_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Inspecting performer plan",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.GetRenderPerformerPlanAsync(
                projectId,
                Number(WorkflowVariantBox, 0),
                token),
            "Performer plan loaded.");

    private async void CreatePerformerPlan_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Creating performer plan",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.CreateRenderPerformerPlanAsync(
                projectId,
                new PerformerWorkflowPlanRequest(
                    Number(WorkflowVariantBox, 0),
                    ParseStringList(PerformerSceneIdsBox.Text),
                    RequiredText(PerformerModelBox.Text, "Performer model")),
                token),
            "Performer plan created.");

    private async void RunPerformer_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Running performer workflow",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.RunRenderPerformerAsync(
                projectId,
                new PerformerWorkflowRunRequest(
                    Number(WorkflowVariantBox, 0),
                    EmptyToNull(PerformerPlanIdBox.Text),
                    Selected(PerformerProviderComboBox, "auto"),
                    PerformerMockFallbackToggle.IsOn,
                    ParseObjectDictionary(PerformerSettingsBox.Text, "Performer render settings")),
                token),
            "Performer run request completed.");

    private MotionSequencerOptions BuildMotionOptions() =>
        new(Number(WorkflowVariantBox, 0), Number(MotionSequencerFpsBox, 24));

    private async void InspectMotionSequencer_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Inspecting motion sequencer",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.GetMotionSequencerAsync(
                projectId,
                BuildMotionOptions(),
                token),
            "Motion sequencer state loaded.");

    private async void ApplyMotionSequencer_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Applying motion sequencer",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.ApplyMotionSequencerAsync(
                projectId,
                new ParseqMotionApplyRequest(
                    Number(WorkflowVariantBox, 0),
                    Number(MotionSequencerFpsBox, 24),
                    ParseOptionalElement(MotionSequencerManifestBox.Text, "Motion manifest", JsonValueKind.Object),
                    MotionSequencerActivateToggle.IsOn),
                token),
            "Motion sequencer manifest applied.");

    private async void AutoRender_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Running automatic render",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.AutoRenderAsync(
                projectId,
                new AutoAnimateRequest(
                    RequiredText(AutoPresetBox.Text, "Auto-render preset"),
                    Selected(AutoEngineComboBox, "auto"),
                    Number(ToolsVariantBox, 0),
                    EmptyToNull(AutoSourceBox.Text),
                    AutoRunToggle.IsOn,
                    NullableNumber(AutoFpsBox)),
                token),
            "Automatic render request completed.");

    private LayeredAnimateRequest BuildLayeredAnimateRequest() =>
        new(
            RequiredText(LayerSourceBox.Text, "Layer source asset"),
            Selected(LayerModeComboBox, "parallax"),
            EmptyToNull(LayerMotionBox.Text),
            Number(LayerBandsBox, 3),
            ParseLayerMasks(LayerMasksBox.Text),
            Number(LayerSubjectMotionBox, 1.0),
            Number(LayerBackgroundMotionBox, 0.12),
            Number(LayerFpsBox, 24),
            Number(LayerDurationBox, 5.0),
            Number(LayerWidthBox, 768),
            Number(LayerHeightBox, 432),
            LayerIncludeAudioToggle.IsOn,
            LayerRefineToggle.IsOn,
            EmptyToNull(LayerRefineModelBox.Text) ?? "auto",
            Selected(LayerDeviceComboBox, "auto"),
            null,
            string.Empty,
            0.3,
            20,
            7.0,
            null);

    private async void AnimateLayers_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Animating layers",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.AnimateLayersAsync(
                projectId,
                BuildLayeredAnimateRequest(),
                token),
            "Animated-layer render request completed.");

    private RenderScenesRequest BuildSceneStillsRequest() =>
        new(
            variantIndex: Number(ToolsVariantBox, 0),
            modelId: EmptyToNull(StillsModelBox.Text),
            checkpoint: EmptyToNull(StillsCheckpointBox.Text),
            workflowFamily: Selected(StillsWorkflowComboBox, "auto"),
            seed: NullableLongNumber(StillsSeedBox),
            referenceAsset: EmptyToNull(StillsReferenceBox.Text),
            sourceAsset: EmptyToNull(StillsSourceBox.Text),
            inpaintMask: EmptyToNull(StillsMaskBox.Text),
            conditioningMode: "raw",
            denoiseStrength: Number(StillsDenoiseBox, 0.75),
            width: Number(StillsWidthBox, 1024),
            height: Number(StillsHeightBox, 576),
            steps: Number(StillsStepsBox, 28),
            cfg: Number(StillsCfgBox, 7.0),
            sampler: "euler",
            negativePrompt: StillsNegativeBox.Text.Trim());

    private async void RenderStills_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Rendering scene stills",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.RenderSceneStillsAsync(
                projectId,
                BuildSceneStillsRequest(),
                token),
            "Scene-still render request completed.");

    private RenderMotionRequest BuildMotionScenesRequest() =>
        new(
            variantIndex: Number(ToolsVariantBox, 0),
            modelId: EmptyToNull(MotionModelBox.Text),
            checkpoint: EmptyToNull(MotionCheckpointBox.Text),
            engine: Selected(MotionEngineComboBox, "animatediff"),
            fps: Number(MotionFpsBox, 12),
            maxFramesPerScene: Number(MotionFramesBox, 240),
            width: Number(MotionWidthBox, 768),
            height: Number(MotionHeightBox, 432),
            steps: Number(MotionStepsBox, 24),
            negativePrompt: MotionNegativeBox.Text.Trim(),
            device: Selected(MotionDeviceComboBox, "cuda"));

    private async void RenderMotionScenes_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Rendering ComfyUI motion scenes",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.RenderComfyUiMotionScenesAsync(
                projectId,
                BuildMotionScenesRequest(),
                token),
            "ComfyUI motion-scene request completed.");

    private async void SmartVideo_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Running smart video",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.RenderSmartVideoAsync(
                projectId,
                ParseRequiredElement(SmartVideoJsonBox.Text, "Smart-video request", JsonValueKind.Object),
                token),
            "Smart-video request completed.");

    private TensorRtStandaloneRenderRequest BuildTensorRtRequest() =>
        new(
            variantIndex: Number(TensorVariantBox, 0),
            modelId: EmptyToNull(TensorModelBox.Text),
            prompt: EmptyToNull(TensorPromptBox.Text),
            seed: NullableLongNumber(TensorSeedBox),
            width: Number(TensorWidthBox, 1024),
            height: Number(TensorHeightBox, 1024),
            steps: Number(TensorStepsBox, 28),
            cfg: Number(TensorCfgBox, 7.0),
            sampler: Selected(TensorSamplerComboBox, "pndm"),
            negativePrompt: TensorNegativeBox.Text.Trim(),
            batchSize: Number(TensorBatchBox, 1));

    private async void PreviewTensorRt_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Generating TensorRT preview",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.PreviewTensorRtStandaloneAsync(
                projectId,
                BuildTensorRtRequest(),
                token),
            "TensorRT preview completed.");

    private async void RunTensorRt_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Running standalone TensorRT render",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.RenderTensorRtStandaloneAsync(
                projectId,
                BuildTensorRtRequest(),
                token),
            "Standalone TensorRT render completed.");

    private async void AssembleVideo_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Assembling video",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.AssembleVideoAsync(
                projectId,
                new AssembleVideoRequest(
                    Number(AssemblyVariantBox, 0),
                    Number(AssemblyFpsBox, 30)),
                token),
            "Scene assembly request completed.");

    private async void ExportDeforum_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Exporting Deforum settings",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.ExportDeforumAsync(
                projectId,
                new ExportDeforumRequest(
                    Number(DeforumVariantBox, 0),
                    Number(DeforumFpsBox, 30),
                    Number(DeforumWidthBox, 1024),
                    Number(DeforumHeightBox, 576),
                    Selected(DeforumPresetComboBox, "cinematic"),
                    Number(DeforumSensitivityBox, 1.0)),
                token),
            "Deforum export completed.");

    private ComfyUiWorkflowExportOptions BuildComfyUiExportOptions()
    {
        var advanced = ParseRequiredElement(
            ComfyExportAdvancedBox.Text,
            "ComfyUI advanced query",
            JsonValueKind.Object);

        string? JsonOption(string name) =>
            advanced.TryGetProperty(name, out var value) &&
            value.ValueKind is not JsonValueKind.Null and not JsonValueKind.Undefined
                ? value.GetRawText()
                : null;

        string? StringOption(string name) =>
            advanced.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
                ? EmptyToNull(value.GetString())
                : null;

        double NumberOption(string name, double fallback) =>
            advanced.TryGetProperty(name, out var value) && value.TryGetDouble(out var number)
                ? number
                : fallback;

        long? LongOption(string name) =>
            advanced.TryGetProperty(name, out var value) && value.TryGetInt64(out var number)
                ? number
                : null;

        return new ComfyUiWorkflowExportOptions(
            VariantIndex: Number(ComfyExportVariantBox, 0),
            ModelId: EmptyToNull(ComfyExportModelBox.Text),
            WorkflowFamily: Selected(ComfyExportFamilyComboBox, "auto"),
            SourceAsset: EmptyToNull(ComfyExportSourceBox.Text),
            ReferenceAsset: EmptyToNull(ComfyExportReferenceBox.Text),
            InpaintMask: EmptyToNull(ComfyExportMaskBox.Text),
            ControlnetModel: StringOption("controlnet_model"),
            ConditioningMode: StringOption("conditioning_mode") ?? "raw",
            Width: Number(ComfyExportWidthBox, 1024),
            Height: Number(ComfyExportHeightBox, 576),
            Steps: Number(ComfyExportStepsBox, 28),
            Cfg: NumberOption("cfg", 7.0),
            Sampler: StringOption("sampler") ?? "euler",
            NegativePrompt: StringOption("negative_prompt") ?? "blurry, low quality, watermark, text, logo",
            Seed: LongOption("seed"),
            DenoiseStrength: NumberOption("denoise_strength", 0.75),
            LorasJson: JsonOption("loras"),
            OutpaintJson: JsonOption("outpaint"),
            ControlnetUnitsJson: JsonOption("controlnet_units"),
            HiresFixJson: JsonOption("hires_fix"),
            RefinerJson: JsonOption("refiner"),
            Upscaler: StringOption("upscaler"));
    }

    private async void ExportComfyUi_Click(object sender, RoutedEventArgs e) =>
        await RunProjectJsonAsync(
            "Exporting ComfyUI workflows",
            GlobalResultBox,
            (projectId, token) => App.Services.ApiClient.ExportComfyUiWorkflowsAsync(
                projectId,
                BuildComfyUiExportOptions(),
                token),
            "ComfyUI workflow export completed.");

    private async void UploadReference_Click(object sender, RoutedEventArgs e) =>
        await PickAndUploadAssetAsync("reference");

    private async void UploadMask_Click(object sender, RoutedEventArgs e) =>
        await PickAndUploadAssetAsync("mask");

    private async void UploadOverlay_Click(object sender, RoutedEventArgs e) =>
        await PickAndUploadAssetAsync("overlay");

    private async Task PickAndUploadAssetAsync(string assetKind)
    {
        string? projectId = RequireActiveProject();
        if (projectId is null)
        {
            return;
        }

        if (App.MainWindowInstance is null)
        {
            ShowFailure("The Studio window is not ready for file selection.");
            return;
        }

        var picker = new Microsoft.Windows.Storage.Pickers.FileOpenPicker(
            App.MainWindowInstance.AppWindow.Id)
        {
            SuggestedStartLocation = Microsoft.Windows.Storage.Pickers.PickerLocationId.PicturesLibrary,
            ViewMode = Microsoft.Windows.Storage.Pickers.PickerViewMode.Thumbnail,
        };
        picker.FileTypeFilter.Add("*");
        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            ShowStatus("No file was selected.", InfoBarSeverity.Informational);
            AppendLog($"Canceled {assetKind} asset selection.");
            return;
        }

        string fileName = Path.GetFileName(file.Path);
        string fileType = Path.GetExtension(fileName);
        await RunBusyAsync($"Uploading {assetKind} asset", async token =>
        {
            await using Stream stream = File.OpenRead(file.Path);
            string contentType = ContentTypeFor(fileType);
            JsonElement result = assetKind switch
            {
                "reference" => await App.Services.ApiClient.UploadReferenceAssetAsync(
                    projectId,
                    stream,
                    fileName,
                    contentType,
                    token),
                "mask" => await App.Services.ApiClient.UploadMaskAssetAsync(
                    projectId,
                    stream,
                    fileName,
                    contentType,
                    token),
                "overlay" => await App.Services.ApiClient.UploadOverlayAssetAsync(
                    projectId,
                    stream,
                    fileName,
                    contentType,
                    token),
                _ => throw new InvalidOperationException($"Unsupported asset kind '{assetKind}'."),
            };
            TextBox uploadedPathBox = assetKind switch
            {
                "reference" => UploadedReferenceBox,
                "mask" => UploadedMaskBox,
                "overlay" => UploadedOverlayBox,
                _ => throw new InvalidOperationException($"Unsupported asset kind '{assetKind}'."),
            };
            uploadedPathBox.Text = GetProjectAssetPath(result, assetKind, fileName);
            DisplayResult(GlobalResultBox, result);
            ShowStatus($"{fileName} uploaded as a {assetKind} asset.", InfoBarSeverity.Success);
            AppendLog($"Uploaded {assetKind} asset {fileName}.");
        });
    }

    private async void WorkerTick_Click(object sender, RoutedEventArgs e) =>
        await RunGlobalJsonAsync(
            "Running one worker tick",
            GlobalResultBox,
            token => App.Services.ApiClient.TickWorkerAsync(token),
            "Manual worker tick completed.");

    private async void GetEdmgStatus_Click(object sender, RoutedEventArgs e) =>
        await RunGlobalJsonAsync(
            "Loading EDMG status",
            GlobalResultBox,
            token => App.Services.ApiClient.GetEdmgStatusAsync(token),
            "EDMG status loaded.");

    private async void VerifyEdmg_Click(object sender, RoutedEventArgs e) =>
        await RunGlobalJsonAsync(
            "Verifying EDMG environment",
            GlobalResultBox,
            token => App.Services.ApiClient.VerifyEdmgAsync(token),
            "EDMG verification completed.");

    private async void RefreshJobs_Click(object sender, RoutedEventArgs e)
    {
        string? projectId = RequireActiveProject();
        if (projectId is null)
        {
            return;
        }

        await RunBusyAsync("Refreshing project jobs", async token =>
        {
            StudioJobListResponse response = await App.Services.ApiClient.GetProjectJobsAsync(projectId, token);
            JsonElement result = JsonSerializer.SerializeToElement(
                response,
                StudioJson.GetTypeInfo<StudioJobListResponse>());
            DisplayResult(JobFeedbackBox, result);
            ShowStatus($"Loaded {response.Jobs.Count} project job(s).", InfoBarSeverity.Success);
            AppendLog($"Loaded {response.Jobs.Count} project job(s).");
        });
    }

    private void ClearLog_Click(object sender, RoutedEventArgs e)
    {
        ActionLogBox.Text = string.Empty;
    }

    private async Task RunProjectJsonAsync(
        string action,
        TextBox target,
        Func<string, CancellationToken, Task<JsonElement>> operation,
        string successMessage)
    {
        string? projectId = RequireActiveProject();
        if (projectId is null)
        {
            return;
        }

        await RunBusyAsync(action, async token =>
        {
            JsonElement result = await operation(projectId, token);
            DisplayResult(target, result);
            ShowStatus(successMessage, InfoBarSeverity.Success);
            AppendLog(successMessage);
        });
    }

    private async Task RunGlobalJsonAsync(
        string action,
        TextBox target,
        Func<CancellationToken, Task<JsonElement>> operation,
        string successMessage)
    {
        await RunBusyAsync(action, async token =>
        {
            JsonElement result = await operation(token);
            DisplayResult(target, result);
            ShowStatus(successMessage, InfoBarSeverity.Success);
            AppendLog(successMessage);
        });
    }

    private async Task RunBusyAsync(string action, Func<CancellationToken, Task> operation)
    {
        if (_isBusy)
        {
            ShowStatus("Another render operation is already in progress.", InfoBarSeverity.Warning);
            return;
        }

        _isBusy = true;
        SetBusyState(action);
        AppendLog($"{action} started.");
        try
        {
            CancellationToken token = _pageCancellation?.Token ?? CancellationToken.None;
            await operation(token);
        }
        catch (OperationCanceledException) when (_pageCancellation?.IsCancellationRequested == true)
        {
            AppendLog($"{action} canceled because the page was closed.");
        }
        catch (Exception exception)
        {
            string message = StudioPageHelpers.UserMessage(exception);
            ShowFailure(message);
            GlobalResultBox.Text =
                $"{action} failed.{Environment.NewLine}{message}{Environment.NewLine}{Environment.NewLine}{exception}";
            AppendLog($"{action} failed: {message}");
        }
        finally
        {
            _isBusy = false;
            SetBusyState();
        }
    }

    private string? RequireActiveProject()
    {
        if (_projectId is not null)
        {
            return _projectId;
        }

        const string message = "Choose an active project before running this workflow.";
        ShowFailure(message);
        GlobalResultBox.Text = message;
        AppendLog(message);
        return null;
    }

    private void SetBusyState(string? action = null)
    {
        WorkflowTabView.IsEnabled = !_isBusy;
        BusyRing.IsActive = _isBusy;
        BusyProgressBar.IsIndeterminate = _isBusy;
        BusyProgressBar.Visibility = _isBusy ? Visibility.Visible : Visibility.Collapsed;
        BusyText.Text = _isBusy ? action ?? "Working…" : "Ready";
    }

    private void DisplayResult(TextBox target, JsonElement result)
    {
        string formatted = StudioPageHelpers.PrettyJson(result);
        target.Text = formatted;
        GlobalResultBox.Text = formatted;
    }

    private void ShowFailure(string message) => ShowStatus(message, InfoBarSeverity.Error);

    private void ShowStatus(string message, InfoBarSeverity severity)
    {
        StatusInfoBar.Title = severity switch
        {
            InfoBarSeverity.Success => "Completed",
            InfoBarSeverity.Warning => "Attention",
            InfoBarSeverity.Error => "Render workflow failed",
            _ => "Render status",
        };
        StatusInfoBar.Message = message;
        StatusInfoBar.Severity = severity;
        StatusInfoBar.IsOpen = true;
    }

    private void AppendLog(string message)
    {
        string entry = $"[{DateTimeOffset.Now:HH:mm:ss}] {message}";
        string updated = string.IsNullOrWhiteSpace(ActionLogBox.Text)
            ? entry
            : $"{ActionLogBox.Text}{Environment.NewLine}{entry}";
        ActionLogBox.Text = updated.Length <= 24_000 ? updated : updated[^24_000..];
    }

    private static JsonArray ParseLoras(string value)
    {
        var result = new JsonArray();
        foreach (string entry in ParseStringList(value))
        {
            string[] parts = entry.Split('@', 2, StringSplitOptions.TrimEntries);
            if (parts[0].Length == 0)
            {
                continue;
            }

            double weight = parts.Length == 2
                && double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed)
                    ? Math.Clamp(parsed, -4.0, 4.0)
                    : 1.0;
            result.Add((JsonNode)new JsonObject { ["name"] = parts[0], ["weight"] = weight });
        }

        return result;
    }

    private static IReadOnlyList<RenderIntentSection> ParseRenderIntentSections(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return [];
        }

        using JsonDocument document = ParseDocument(value, "Conductor intent sections");
        if (document.RootElement.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException("Conductor intent sections must be a JSON array.");
        }

        var result = new List<RenderIntentSection>();
        foreach (JsonElement item in document.RootElement.EnumerateArray())
        {
            EnsureObject(item, "Each conductor intent section");
            result.Add(new RenderIntentSection(
                RequiredPropertyString(item, "scene_id", "Conductor intent section"),
                PropertyDouble(item, "start_s", 0.0),
                PropertyDouble(item, "end_s", 0.0),
                PropertyString(item, "creative_goal"),
                OptionalPropertyDouble(item, "continuity_priority"),
                OptionalPropertyDouble(item, "speed_priority"),
                PropertyStringArray(item, "notes")));
        }

        return result;
    }

    private static IReadOnlyList<LayerMaskSpec> ParseLayerMasks(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return [];
        }

        using JsonDocument document = ParseDocument(value, "Layer masks");
        if (document.RootElement.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException("Layer masks must be a JSON array.");
        }

        var result = new List<LayerMaskSpec>();
        foreach (JsonElement item in document.RootElement.EnumerateArray())
        {
            EnsureObject(item, "Each layer mask");
            result.Add(new LayerMaskSpec(
                RequiredPropertyString(item, "mask_asset", "Layer mask"),
                PropertyString(item, "prompt"),
                PropertyDouble(item, "depth", 1.0),
                PropertyDouble(item, "motion_scale", 1.0),
                PropertyDouble(item, "strength", 1.0)));
        }

        return result;
    }

    private static IReadOnlyDictionary<string, JsonElement> ParseObjectDictionary(string value, string label)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return new Dictionary<string, JsonElement>();
        }

        using JsonDocument document = ParseDocument(value, label);
        if (document.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException($"{label} must be a JSON object.");
        }

        return document.RootElement
            .EnumerateObject()
            .ToDictionary(property => property.Name, property => property.Value.Clone(), StringComparer.Ordinal);
    }

    private static JsonElement ParseRequiredElement(string value, string label, JsonValueKind expectedKind)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new InvalidOperationException($"{label} is required.");
        }

        using JsonDocument document = ParseDocument(value, label);
        if (document.RootElement.ValueKind != expectedKind)
        {
            throw new InvalidOperationException($"{label} must be a JSON {KindLabel(expectedKind)}.");
        }

        return document.RootElement.Clone();
    }

    private static JsonElement? ParseOptionalElement(string value, string label, JsonValueKind expectedKind) =>
        string.IsNullOrWhiteSpace(value)
            ? null
            : ParseRequiredElement(value, label, expectedKind);

    private static JsonNode? ParseOptionalNode(string value, string label, JsonValueKind expectedKind)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        JsonElement element = ParseRequiredElement(value, label, expectedKind);
        return JsonNode.Parse(element.GetRawText());
    }

    private static JsonDocument ParseDocument(string value, string label)
    {
        try
        {
            return JsonDocument.Parse(value);
        }
        catch (JsonException exception)
        {
            throw new InvalidOperationException($"{label} contains invalid JSON: {exception.Message}", exception);
        }
    }

    private static void EnsureObject(JsonElement value, string label)
    {
        if (value.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException($"{label} must be a JSON object.");
        }
    }

    private static string RequiredPropertyString(JsonElement value, string propertyName, string label)
    {
        string? result = PropertyString(value, propertyName);
        return string.IsNullOrWhiteSpace(result)
            ? throw new InvalidOperationException($"{label} requires a non-empty '{propertyName}'.")
            : result;
    }

    private static string? PropertyString(JsonElement value, string propertyName)
    {
        if (!value.TryGetProperty(propertyName, out JsonElement property)
            || property.ValueKind == JsonValueKind.Null)
        {
            return null;
        }

        if (property.ValueKind != JsonValueKind.String)
        {
            throw new InvalidOperationException($"'{propertyName}' must be a string.");
        }

        return property.GetString();
    }

    private static double PropertyDouble(JsonElement value, string propertyName, double fallback)
    {
        if (!value.TryGetProperty(propertyName, out JsonElement property)
            || property.ValueKind == JsonValueKind.Null)
        {
            return fallback;
        }

        if (!property.TryGetDouble(out double result))
        {
            throw new InvalidOperationException($"'{propertyName}' must be a number.");
        }

        return result;
    }

    private static double? OptionalPropertyDouble(JsonElement value, string propertyName)
    {
        if (!value.TryGetProperty(propertyName, out JsonElement property)
            || property.ValueKind == JsonValueKind.Null)
        {
            return null;
        }

        if (!property.TryGetDouble(out double result))
        {
            throw new InvalidOperationException($"'{propertyName}' must be a number.");
        }

        return result;
    }

    private static IReadOnlyList<string> PropertyStringArray(JsonElement value, string propertyName)
    {
        if (!value.TryGetProperty(propertyName, out JsonElement property)
            || property.ValueKind == JsonValueKind.Null)
        {
            return [];
        }

        if (property.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException($"'{propertyName}' must be an array of strings.");
        }

        var result = new List<string>();
        foreach (JsonElement item in property.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String)
            {
                throw new InvalidOperationException($"'{propertyName}' must contain only strings.");
            }

            string? text = item.GetString();
            if (!string.IsNullOrWhiteSpace(text))
            {
                result.Add(text);
            }
        }

        return result;
    }

    private static IReadOnlyList<string> ParseStringList(string value) =>
        value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private static string RequiredText(string value, string label) =>
        string.IsNullOrWhiteSpace(value)
            ? throw new InvalidOperationException($"{label} is required.")
            : value.Trim();

    private static int Number(NumberBox numberBox, int fallback) =>
        double.IsNaN(numberBox.Value) ? fallback : Convert.ToInt32(numberBox.Value);

    private static double Number(NumberBox numberBox, double fallback) =>
        double.IsNaN(numberBox.Value) ? fallback : numberBox.Value;

    private static int? NullableNumber(NumberBox numberBox) =>
        double.IsNaN(numberBox.Value) ? null : Convert.ToInt32(numberBox.Value);

    private static long LongNumber(NumberBox numberBox, long fallback) =>
        double.IsNaN(numberBox.Value) ? fallback : Convert.ToInt64(numberBox.Value);

    private static long? NullableLongNumber(NumberBox numberBox) =>
        double.IsNaN(numberBox.Value) || numberBox.Value < 0
            ? null
            : Convert.ToInt64(numberBox.Value);

    private static string Selected(ComboBox comboBox, string fallback) =>
        comboBox.SelectedItem switch
        {
            ComboBoxItem { Tag: not null } item => item.Tag.ToString() ?? fallback,
            ComboBoxItem { Content: not null } item => item.Content.ToString() ?? fallback,
            string value when !string.IsNullOrWhiteSpace(value) => value,
            _ when comboBox.SelectedValue is string value && !string.IsNullOrWhiteSpace(value) => value,
            _ => fallback,
        };

    private static string? EmptyToNull(string? value) =>
        string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static string KindLabel(JsonValueKind kind) =>
        kind switch
        {
            JsonValueKind.Object => "object",
            JsonValueKind.Array => "array",
            _ => kind.ToString().ToLowerInvariant(),
        };

    private static string GetProjectAssetPath(JsonElement response, string assetKind, string fallbackFileName)
    {
        string folder = assetKind switch
        {
            "reference" => "refs",
            "mask" => "masks",
            "overlay" => "overlays",
            _ => throw new InvalidOperationException($"Unsupported asset kind '{assetKind}'."),
        };

        string? assetName = response.TryGetProperty("asset", out JsonElement asset)
            && asset.ValueKind == JsonValueKind.String
                ? asset.GetString()
                : null;
        if (string.IsNullOrWhiteSpace(assetName)
            && response.TryGetProperty("path", out JsonElement path)
            && path.ValueKind == JsonValueKind.String)
        {
            assetName = Path.GetFileName(path.GetString()?.Replace('\\', '/'));
        }

        assetName = string.IsNullOrWhiteSpace(assetName)
            ? Path.GetFileName(fallbackFileName)
            : Path.GetFileName(assetName);
        return $"assets/{folder}/{assetName}";
    }

    private static string ContentTypeFor(string extension) =>
        extension.ToLowerInvariant() switch
        {
            ".png" => "image/png",
            ".jpg" or ".jpeg" => "image/jpeg",
            ".webp" => "image/webp",
            ".gif" => "image/gif",
            ".bmp" => "image/bmp",
            ".mp4" => "video/mp4",
            ".webm" => "video/webm",
            ".mov" => "video/quicktime",
            _ => "application/octet-stream",
        };
}
