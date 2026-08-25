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
    private bool _modelGuidanceUiReady;
    private CancellationTokenSource? _pageCancellation;
    private ModelCatalogueResponse? _modelCatalogue;
    private ModelRenderGuidance? _modelGuidance;
    private JsonElement? _hardwareProfile;

    public RenderPage()
    {
        InitializeComponent();
        _modelGuidanceUiReady = true;
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

        _ = LoadModelGuidanceAsync(_pageCancellation.Token);
        _ = LoadHardwareCapabilitiesAsync(_pageCancellation.Token);
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _pageCancellation?.Cancel();
        base.OnNavigatedFrom(e);
    }

    private async Task LoadModelGuidanceAsync(CancellationToken cancellationToken)
    {
        ModelGuidanceProgressRing.IsActive = true;
        ModelGuidanceProgressRing.Visibility = Visibility.Visible;
        ModelGuidanceSummaryText.Text = "Loading the model catalogue. Manual render controls remain available.";

        try
        {
            _modelCatalogue = await App.Services.ApiClient.GetTypedModelCatalogueAsync(cancellationToken);
            UpdateModelGuidance();
            UpdateRuntimeCapabilityUi();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            _modelCatalogue = null;
            _modelGuidance = null;
            ModelGuidanceSummaryText.Text =
                $"Model guidance is unavailable: {ex.Message} Manual render controls remain available.";
            PrimaryModelGuidanceText.Text = "Primary model: catalogue unavailable";
            VideoModelGuidanceText.Text = "Video model: catalogue unavailable";
            ModelGuidanceBlockersText.Visibility = Visibility.Collapsed;
            ApplyRecommendedPrimaryModelButton.IsEnabled = false;
            ApplyRecommendedVideoModelButton.IsEnabled = false;
            UpdateRuntimeCapabilityUi();
        }
        finally
        {
            ModelGuidanceProgressRing.IsActive = false;
            ModelGuidanceProgressRing.Visibility = Visibility.Collapsed;
        }
    }

    private async Task LoadHardwareCapabilitiesAsync(CancellationToken cancellationToken)
    {
        RuntimeCapabilityProgressRing.IsActive = true;
        RuntimeCapabilityProgressRing.Visibility = Visibility.Visible;
        RuntimeAcceleratorText.Text = "Checking backend hardware and accelerator settings...";

        try
        {
            _hardwareProfile = await App.Services.ApiClient.GetHardwareAsync(cancellationToken);
            UpdateRuntimeCapabilityUi();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
        }
        catch (Exception ex)
        {
            _hardwareProfile = null;
            RuntimeAcceleratorText.Text = $"Compute readiness is unavailable: {StudioPageHelpers.GetUserFacingError(ex)}";
            RuntimeCudaText.Text = "CUDA status could not be loaded. Manual render controls remain available.";
            RuntimeTensorCoreText.Text = "RTX Tensor Core hardware was not confirmed.";
            RuntimeTensorRtText.Text = _modelCatalogue?.TensorRtMigration?.Canonical.RendererReady == true
                ? "TensorRT SD 1.5 keyframe renderer is installed and verified."
                : "TensorRT readiness is available from Models when the backend reconnects.";
            RuntimeTritonText.Text = "Triton is backend-managed and has no independent render switch.";
        }
        finally
        {
            RuntimeCapabilityProgressRing.IsActive = false;
            RuntimeCapabilityProgressRing.Visibility = Visibility.Collapsed;
        }
    }

    private void UpdateRuntimeCapabilityUi()
    {
        if (_hardwareProfile is not JsonElement hardware)
        {
            return;
        }

        try
        {
            RenderRuntimeCapabilities capabilities = RenderRuntimeCapabilities.Evaluate(
                hardware,
                _modelCatalogue);
            RuntimeAcceleratorText.Text = capabilities.AcceleratorSummary;
            RuntimeCudaText.Text = capabilities.CudaSummary;
            RuntimeTensorCoreText.Text = capabilities.TensorCoreSummary;
            RuntimeTensorRtText.Text = capabilities.TensorRtSummary;
            RuntimeTritonText.Text = capabilities.TritonSummary;
        }
        catch (ArgumentException ex)
        {
            RuntimeAcceleratorText.Text = $"Backend hardware report could not be read: {ex.Message}";
        }
    }

    private async void RefreshRuntimeCapabilities_Click(object sender, RoutedEventArgs e)
    {
        if (_pageCancellation is null)
        {
            return;
        }

        await Task.WhenAll(
            LoadHardwareCapabilitiesAsync(_pageCancellation.Token),
            LoadModelGuidanceAsync(_pageCancellation.Token));
    }

    private void UpdateModelGuidance()
    {
        if (!_modelGuidanceUiReady || _modelCatalogue is null)
        {
            return;
        }

        var configuration = new ModelRenderConfiguration(
            ModelBox.Text.Trim(),
            VideoModelBox.Text.Trim(),
            Selected(ModeComboBox, "auto"),
            Selected(DeviceComboBox, "auto"),
            Selected(TemporalModeComboBox, "keyframes"),
            Selected(VideoModelEngineComboBox, "auto"),
            Selected(KeyframeRendererComboBox, "internal"),
            KeyframeModelBox.Text.Trim());

        _modelGuidance = ModelRenderGuidanceEvaluator.Evaluate(_modelCatalogue, configuration);
        ModelGuidanceSummaryText.Text = _modelGuidance.IsReady
            ? "The selected models are ready for this render path."
            : "Resolve the blockers below before rendering with this model configuration.";
        PrimaryModelGuidanceText.Text = FormatModelGuidance("Primary model", _modelGuidance.Primary);
        VideoModelGuidanceText.Text = configuration.TemporalMode.Equals(
            "video_model",
            StringComparison.OrdinalIgnoreCase)
                ? FormatModelGuidance("Video model", _modelGuidance.Video)
                : "Video model: not required for the selected temporal mode.";

        ModelGuidanceBlockersText.Text = string.Join(Environment.NewLine, _modelGuidance.Blockers.Select(
            blocker => $"- {blocker}"));
        ModelGuidanceBlockersText.Visibility =
            _modelGuidance.Blockers.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        ApplyRecommendedPrimaryModelButton.IsEnabled =
            !string.IsNullOrWhiteSpace(_modelGuidance.RecommendedPrimaryModelId);
        ApplyRecommendedVideoModelButton.IsEnabled =
            configuration.TemporalMode.Equals("video_model", StringComparison.OrdinalIgnoreCase)
            && !string.IsNullOrWhiteSpace(_modelGuidance.RecommendedVideoModelId);
    }

    private static string FormatModelGuidance(string label, ModelRenderCandidate? candidate)
    {
        if (candidate is null)
        {
            return $"{label}: no compatible selection";
        }

        string installed = candidate.IsInstalled ? "installed" : "not installed";
        string lane = string.IsNullOrWhiteSpace(candidate.Lane) ? "unclassified lane" : $"{candidate.Lane} lane";
        string license = string.IsNullOrWhiteSpace(candidate.LicenseId)
            ? string.Empty
            : $", license {candidate.LicenseId}";
        return $"{label}: {candidate.Name} ({candidate.ModelId}) - {installed}, {lane}{license}.";
    }

    private void ModelGuidanceSelection_Changed(object sender, SelectionChangedEventArgs e) =>
        UpdateModelGuidance();

    private void ModelGuidanceText_Changed(object sender, TextChangedEventArgs e) =>
        UpdateModelGuidance();

    private void ApplyRecommendedPrimaryModel_Click(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_modelGuidance?.RecommendedPrimaryModelId))
        {
            ModelBox.Text = _modelGuidance.RecommendedPrimaryModelId;
        }
    }

    private void ApplyRecommendedVideoModel_Click(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_modelGuidance?.RecommendedVideoModelId))
        {
            VideoModelBox.Text = _modelGuidance.RecommendedVideoModelId;
        }
    }

    private async void RefreshModelGuidance_Click(object sender, RoutedEventArgs e)
    {
        if (_pageCancellation is not null)
        {
            await LoadModelGuidanceAsync(_pageCancellation.Token);
        }
    }

    private void OpenModels_Click(object sender, RoutedEventArgs e) =>
        App.Navigate("models");

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
        var settings = new InternalVideoRenderSettings
        {
            VariantIndex = App.Services.Session.SelectedVariantIndex,
            OutputFps = (int)Number(FpsBox, 24),
            RenderFps = (int)Number(RenderFpsBox, 3),
            Width = (int)Number(WidthBox, 1280),
            Height = (int)Number(HeightBox, 720),
            Steps = (int)Number(StepsBox, 28),
            Cfg = Number(CfgBox, 7.0),
            Sampler = Selected(SamplerComboBox, "euler"),
            Seed = seed < 0 ? null : seed,
            KeyframeIntervalSeconds = Number(KeyframeIntervalBox, 5.0),
            InterpolationEngine = Selected(InterpolationComboBox, "auto"),
            ModelId = EmptyToNull(ModelBox.Text) ?? "auto",
            RenderMode = Selected(ModeComboBox, "auto"),
            RenderTier = Selected(TierComboBox, "balanced"),
            DevicePreference = Selected(DeviceComboBox, "auto"),
            AllowHostedFallback = HostedFallbackToggle.IsOn,
            HostedService = Selected(HostedProviderComboBox, "default"),
            HostedModel = EmptyToNull(HostedModelBox.Text),
            HostedStylePreset = EmptyToNull(HostedStyleBox.Text),
            NegativePrompt = NegativePromptBox.Text,
            Loras = LorasBox.Text,
            Vae = EmptyToNull(VaeBox.Text),
            RefinerEnabled = EnableRefinerToggle.IsOn,
            RefinerModelId = EmptyToNull(RefinerModelBox.Text),
            RefinerSwitchAt = Number(RefinerSwitchBox, 0.8),
            TemporalMode = Selected(TemporalModeComboBox, "keyframes"),
            TemporalStrength = Number(TemporalConsistencyBox, 0.75),
            TemporalSteps = NullableNumber(TemporalStepsBox),
            RefineEveryNFrames = (int)Number(RefineEveryBox, 1),
            AnchorStrength = Number(AnchorStrengthBox, 0.2),
            PromptBlend = PromptBlendToggle.IsOn,
            ResumeExistingFrames = ResumeFramesToggle.IsOn,
            MotionStrategy = Selected(MotionStrategyComboBox, "manual"),
            StoryboardShotMaxSeconds = Number(StoryboardShotMaxBox, 4.0),
            VideoModelEngine = Selected(VideoModelEngineComboBox, "auto"),
            VideoModelId = EmptyToNull(VideoModelBox.Text),
            VideoModelMaxFramesPerScene = (int)Number(FramesBox, 25),
            VideoModelMotionBucketId = (int)Number(MotionBucketBox, 127),
            VideoModelNoiseAugStrength = Number(NoiseAugBox, 0.02),
            VideoModelDecodeChunkSize = (int)Number(DecodeChunkBox, 8),
            VideoModelDtype = Selected(VideoDtypeComboBox, "auto"),
            VideoModelCpuOffload = VideoCpuOffloadToggle.IsOn,
            VideoModelMotionScoreMode = Selected(MotionScoreModeComboBox, "auto"),
            VideoModelManualMotionScore = (int)Number(ManualMotionScoreBox, 4),
            VideoModelAnchorMode = Selected(VideoAnchorModeComboBox, "start"),
            VideoModelPromptRefine = VideoPromptRefineToggle.IsOn,
            VideoModelSceneMotion = Selected(SceneMotionComboBox, "subject"),
            VideoModelApplyTimelineCamera = TimelineCameraToggle.IsOn,
            VideoModelKeyframeRenderer = Selected(KeyframeRendererComboBox, "internal"),
            VideoModelKeyframeModelId = EmptyToNull(KeyframeModelBox.Text),
            MotionScoreSchedule = MotionScoreScheduleBox.Text,
            NoiseAugSchedule = NoiseAugScheduleBox.Text,
            AnchorStrengthSchedule = AnchorStrengthScheduleBox.Text,
            ParseqEnabled = ParseqToggle.IsOn,
            ParseqManifest = ParseqBox.Text,
            SourceAsset = EmptyToNull(MotionSourceBox.Text),
            SourceStrength = Number(SourceStrengthBox, 0.55),
            DeforumPrompts = string.IsNullOrWhiteSpace(prompt)
                ? string.Empty
                : JsonSerializer.Serialize(new Dictionary<string, string> { ["0"] = prompt }),
            DeforumNegativePrompts = DeforumNegativePromptsBox.Text,
            DeforumZoom = DeforumZoomBox.Text,
            DeforumAngle = DeforumAngleBox.Text,
            DeforumTranslationX = DeforumTranslationXBox.Text,
            DeforumTranslationY = DeforumTranslationYBox.Text,
            DeforumTranslationZ = DeforumTranslationZBox.Text,
            DeforumRotationX = DeforumRotationXBox.Text,
            DeforumRotationY = DeforumRotationYBox.Text,
            DeforumRotationZ = DeforumRotationZBox.Text,
            DeforumFov = DeforumFovBox.Text,
            DeforumStrength = DeforumStrengthBox.Text,
            DeforumCfg = DeforumCfgBox.Text,
            DeforumSteps = DeforumStepsBox.Text,
            DeforumDenoise = DeforumDenoiseBox.Text,
        };
        return InternalVideoRenderRequestBuilder.Build(settings);
    }

    private RenderQuickSetup ResolveQuickSetup() =>
        RenderQuickSetup.Resolve(
            Selected(QuickGoalComboBox, "auto"),
            Selected(QuickQualityComboBox, "balanced"),
            Selected(QuickResolutionComboBox, "768x432"),
            (int)Number(QuickFpsBox, 24));

    private RenderQuickSetup ApplyQuickSetup()
    {
        RenderQuickSetup setup = ResolveQuickSetup();

        string model = QuickModelBox.Text.Trim();
        string selectedModel = string.IsNullOrWhiteSpace(model) ? "auto" : model;
        SelectComboValue(PipelinePresetComboBox, setup.Quality);
        SelectComboValue(PipelineModeComboBox, "auto");

        if (setup.Route == "stills")
        {
            StillsWidthBox.Value = setup.Width;
            StillsHeightBox.Value = setup.Height;
            StillsStepsBox.Value = setup.Steps;
            StillsCfgBox.Value = setup.Cfg;
            StillsModelBox.Text = selectedModel;
        }
        else if (setup.Route == "motion")
        {
            SelectComboValue(MotionEngineComboBox, setup.VideoModelEngine);
            MotionWidthBox.Value = setup.Width;
            MotionHeightBox.Value = setup.Height;
            MotionFpsBox.Value = setup.MotionFps;
            MotionFramesBox.Value = setup.MaximumFrames;
            MotionStepsBox.Value = setup.Steps;
            MotionModelBox.Text = selectedModel;
        }
        else if (setup.Route == "internal")
        {
            SelectComboValue(ModeComboBox, "auto");
            SelectComboValue(TierComboBox, setup.RenderTier);
            SelectComboValue(TemporalModeComboBox, setup.TemporalMode);
            SelectComboValue(VideoModelEngineComboBox, setup.VideoModelEngine);
            SelectComboValue(MotionStrategyComboBox, setup.MotionStrategy);
            WidthBox.Value = setup.Width;
            HeightBox.Value = setup.Height;
            FpsBox.Value = setup.OutputFps;
            RenderFpsBox.Value = setup.RenderFps;
            StepsBox.Value = setup.Steps;
            CfgBox.Value = setup.Cfg;
            ModelBox.Text = selectedModel;
            VideoModelBox.Text = selectedModel == "auto" ? string.Empty : selectedModel;
            MotionStrengthBox.Value = 1.5;
        }

        QuickSetupSummaryText.Text = setup.OpensTimeline
            ? "Timeline editor · captured, imported, and rendered media"
            : $"{QuickGoalLabel(setup.Goal)} · {setup.RenderTier} · {setup.Width} × {setup.Height} · "
              + $"{setup.OutputFps} FPS delivery / {setup.RenderFps} FPS generation · "
              + $"{setup.TemporalMode} · {setup.VideoModelEngine}";
        return setup;
    }

    private void OpenAiPlanner_Click(object sender, RoutedEventArgs e) => App.Navigate("plannerLab");

    private void ApplyQuickSetup_Click(object sender, RoutedEventArgs e) => ApplyQuickSetup();

    private void QuickPreflight_Click(object sender, RoutedEventArgs e)
    {
        RenderQuickSetup setup = ResolveQuickSetup();
        if (setup.OpensTimeline)
        {
            Frame.Navigate(typeof(TimelinePage));
            return;
        }

        if (setup.Route == "pipeline")
        {
            ValidatePipeline_Click(sender, e);
        }
        else if (setup.Route == "internal")
        {
            Preflight_Click(sender, e);
        }
        else
        {
            ShowStatus(
                $"{QuickGoalLabel(setup.Goal)} settings are ready. This render path validates when it starts.",
                InfoBarSeverity.Informational);
        }
    }

    private void QuickRender_Click(object sender, RoutedEventArgs e)
    {
        RenderQuickSetup setup = ResolveQuickSetup();
        if (setup.OpensTimeline)
        {
            Frame.Navigate(typeof(TimelinePage));
            return;
        }

        switch (setup.Route)
        {
            case "pipeline":
                RunPipeline_Click(sender, e);
                break;
            case "stills":
                RenderStills_Click(sender, e);
                break;
            case "motion":
                RenderMotionScenes_Click(sender, e);
                break;
            default:
                Render_Click(sender, e);
                break;
        }
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

    private static JsonNode? ParseSchedule(string value, string label)
    {
        string schedule = value.Trim();
        if (schedule.Length == 0)
        {
            return null;
        }

        return schedule.StartsWith('{')
            ? ParseOptionalNode(schedule, label, JsonValueKind.Object)
            : JsonValue.Create(schedule);
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

    private static void SelectComboValue(ComboBox comboBox, string value)
    {
        foreach (object itemValue in comboBox.Items)
        {
            if (itemValue is not ComboBoxItem item)
            {
                continue;
            }

            string candidate = item.Tag?.ToString() ?? item.Content?.ToString() ?? string.Empty;
            if (string.Equals(candidate, value, StringComparison.OrdinalIgnoreCase))
            {
                comboBox.SelectedItem = item;
                return;
            }
        }
    }

    private static string QuickGoalLabel(string goal) =>
        goal switch
        {
            "stills" => "Still scenes",
            "motion_ad" => "AnimateDiff motion",
            "motion_svd" => "SVD image to video",
            "full_video" => "Full-motion video",
            _ => "Automatic internal",
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
