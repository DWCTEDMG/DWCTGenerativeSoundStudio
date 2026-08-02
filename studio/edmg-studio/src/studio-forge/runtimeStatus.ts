import {
  buildInternalModelReadiness,
  type InternalModelCatalogEntry,
  type InternalModelTask,
} from "../shared/internalModelReadiness";
import type {
  StudioForgeCapability,
  StudioForgePrerequisite,
  StudioForgeRecipe,
  StudioForgeRecipeStage,
} from "./types";

export type StudioForgeStatusLevel = "ready" | "running" | "degraded" | "blocked" | "unknown";

export type StudioForgeStatusCard = {
  id: string;
  label: string;
  role: string;
  status: StudioForgeStatusLevel;
  detail: string;
  impact: string;
};

export type StudioForgeRuntimeSnapshot = {
  health?: unknown;
  systemReadiness?: unknown;
  setupStatus?: unknown;
  backendConfig?: unknown;
  aiStatus?: unknown;
  renderProviders?: unknown;
  comfyCapabilities?: unknown;
  modelCatalog?: unknown;
  modelTasks?: unknown;
};

export type StudioForgeProjectSnapshot = {
  projectId?: string;
  project?: unknown;
  selectedVariant?: number;
  outputs?: unknown;
  jobs?: unknown;
  unrealPreview?: unknown;
  livePublishStatus?: unknown;
};

export type StudioForgeRecipeStageState = {
  stage: StudioForgeRecipeStage;
  state: "complete" | "current" | "blocked";
  missingCapabilities: StudioForgeCapability[];
  missingPrerequisites: StudioForgePrerequisite[];
};

const CAPABILITY_LABELS: Record<StudioForgeCapability, string> = {
  backend: "Backend",
  systemReady: "System readiness",
  ollama: "Ollama",
  openaiCompatible: "OpenAI-compatible planner",
  comfyui: "ComfyUI",
  comfyMotion: "ComfyUI motion nodes",
  ffmpeg: "FFmpeg",
  internalRenderer: "Local internal still model",
  internalMotion: "Local internal motion model",
  cuda: "CUDA",
  hostedRenderer: "Hosted renderer",
  edmgCore: "EDMG Core",
};

export const STUDIO_FORGE_PREREQUISITE_LABELS: Record<StudioForgePrerequisite, string> = {
  project: "active project",
  audio: "source audio",
  analysis: "saved analysis",
  plan: "valid plan variant",
  renderOutput: "registered render output",
  deforumExport: "Deforum export",
  unrealBundle: "Unreal handoff bundle",
};

export { CAPABILITY_LABELS as STUDIO_FORGE_CAPABILITY_LABELS };

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown, fallback = ""): string {
  const normalized = String(value ?? "").trim();
  return normalized || fallback;
}

function taskRows(value: unknown): InternalModelTask[] {
  const payload = asRecord(value);
  return asArray(payload.tasks ?? payload.jobs)
    .filter((task) => task && typeof task === "object") as InternalModelTask[];
}

function taskPayloadKnown(value: unknown): boolean {
  const payload = asRecord(value);
  return Array.isArray(payload.tasks) || Array.isArray(payload.jobs);
}

function newestTasksByName(tasks: InternalModelTask[]): InternalModelTask[] {
  const newest = new Map<string, InternalModelTask>();
  for (const task of tasks) {
    const identity = stringValue(task.name ?? task.model_id ?? task.modelId ?? task.id);
    if (identity && !newest.has(identity)) newest.set(identity, task);
  }
  return [...newest.values()];
}

function taskStatus(task: InternalModelTask): string {
  return stringValue(task.status).toLowerCase();
}

function activeTaskCount(tasks: InternalModelTask[]): number {
  return tasks.filter((task) => ["queued", "running"].includes(taskStatus(task))).length;
}

function failedTaskCount(tasks: InternalModelTask[]): number {
  return tasks.filter((task) => ["failed", "error"].includes(taskStatus(task))).length;
}

function providerIsUsable(provider: Record<string, unknown>): boolean {
  if (provider.active === true || provider.visible === true) return true;
  return provider.configured === true && provider.enabled !== false;
}

export function deriveStudioForgeRuntime(snapshot: StudioForgeRuntimeSnapshot) {
  const health = asRecord(snapshot.health);
  const readiness = asRecord(snapshot.systemReadiness);
  const checks = asRecord(readiness.checks);
  const ffmpegCheck = asRecord(checks.ffmpeg);
  const runtimeCheck = asRecord(checks.runtime);
  const gpuCheck = asRecord(checks.gpu);
  const diskCheck = asRecord(checks.disk);
  const writableCheck = asRecord(checks.writable_paths);
  const modelsCheck = asRecord(checks.models);
  const setup = asRecord(snapshot.setupStatus);
  const ollama = asRecord(setup.ollama);
  const setupAiConfig = asRecord(setup.ai_config);
  const edmg = asRecord(setup.edmg);
  const config = asRecord(snapshot.backendConfig);
  const aiStatus = asRecord(snapshot.aiStatus);
  const ai = asRecord(aiStatus.ai);
  const providers = asRecord(snapshot.renderProviders);
  const cuda = asRecord(providers.cuda);
  const directml = asRecord(providers.directml);
  const proxy = asRecord(providers.proxy);
  const catalog = asRecord(snapshot.modelCatalog);
  const catalogRows = asArray(catalog.catalog) as InternalModelCatalogEntry[];
  const installed = asRecord(catalog.installed) as Record<string, boolean>;
  const cloud = asRecord(catalog.cloud);
  const modelTaskList = taskRows(snapshot.modelTasks);
  const setupTaskList = taskRows(snapshot.setupStatus);
  const internalModels = buildInternalModelReadiness({
    catalog: catalogRows,
    installed,
    cloud,
    modelCache: stringValue(catalog.model_cache, "configured model cache"),
    tasks: modelTaskList,
  });

  const backendReady = health.ok === true;
  const readinessStatus = stringValue(readiness.status, "unknown").toLowerCase();
  const readinessKnown = Object.keys(readiness).length > 0 && readinessStatus !== "unknown";
  const systemBlocked = readinessStatus === "blocked" || readiness.ok === false;
  const systemReady = readiness.ok === true && !systemBlocked;
  const ffmpegReady = ffmpegCheck.ok === true || asRecord(setup.ffmpeg).ok === true;
  const ollamaRequired = setupAiConfig.ollama_required === true;
  const ollamaReady = ollama.ok === true && (!setupAiConfig.model_required || ollama.model_present === true);
  const comfy = asRecord(snapshot.comfyCapabilities);
  const comfyReady = Object.keys(comfy).length > 0 && comfy.ok !== false;
  const comfyMotionReady = comfyReady && (
    asRecord(comfy.animatediff).available === true
    || asRecord(comfy.svd).available === true
  );
  const planningProvider = stringValue(
    ai.provider ?? config.ai_provider ?? config.provider ?? setupAiConfig.provider,
    "not configured",
  ).toLowerCase();
  const planningReady = Object.keys(ai).length ? ai.ok === true : aiStatus.ok === true;
  const openaiCompatibleReady = planningReady
    && ["openai_compat", "nemotron_cloud", "nvidia_nim", "nemotron"].includes(planningProvider);
  const cudaReady = cuda.active === true;
  const hostedProviders = [providers.stability, providers.imagineart, providers.firefly, providers.cosmos]
    .map(asRecord)
    .filter(providerIsUsable);
  const hostedReady = hostedProviders.length > 0;

  const capabilities: StudioForgeCapability[] = [];
  if (backendReady) capabilities.push("backend");
  if (systemReady) capabilities.push("systemReady");
  if (ffmpegReady) capabilities.push("ffmpeg");
  if (ollamaReady) capabilities.push("ollama");
  if (openaiCompatibleReady) capabilities.push("openaiCompatible");
  if (comfyReady) capabilities.push("comfyui");
  if (comfyMotionReady) capabilities.push("comfyMotion");
  if (internalModels.hasLocalStillModel) capabilities.push("internalRenderer");
  if (internalModels.hasLocalMotionModel) capabilities.push("internalMotion");
  if (cudaReady) capabilities.push("cuda");
  if (hostedReady) capabilities.push("hostedRenderer");
  if (edmg.available === true) capabilities.push("edmgCore");

  const writablePaths = asArray(writableCheck.paths).map(asRecord);
  const blockedPaths = writablePaths.filter((path) => path.writable === false);
  const storageMode = stringValue(catalog.storage_mode, "local_cache");
  const modelsDir = stringValue(modelsCheck.models_dir, "Models path unavailable");
  const diskStatus = stringValue(diskCheck.status, "unknown").toLowerCase();
  const modelTasksKnown = taskPayloadKnown(snapshot.modelTasks);
  const setupTasksKnown = taskPayloadKnown(snapshot.setupStatus);
  const taskSourcesKnown = modelTasksKnown && setupTasksKnown;
  const latestSetupTasks = newestTasksByName(setupTaskList);
  const activeTasks = internalModels.activeTasks.length + activeTaskCount(latestSetupTasks);
  const failedTasks = internalModels.failedTasks.length + failedTaskCount(latestSetupTasks);
  const acceleratorName = stringValue(cuda.device_name ?? gpuCheck.device_name, "CPU");
  const vramGb = Number(cuda.vram_gb ?? gpuCheck.vram_gb ?? 0);

  const cards: StudioForgeStatusCard[] = [
    {
      id: "backend",
      label: "Studio backend",
      role: "Required",
      status: backendReady ? "ready" : Object.keys(health).length ? "blocked" : "unknown",
      detail: backendReady ? "The local FastAPI backend responded." : "The Studio backend did not return a healthy response.",
      impact: "Forge reads canonical Studio APIs and never substitutes its own project or render state.",
    },
    {
      id: "system",
      label: "System readiness",
      role: "Required",
      status: systemBlocked
        ? "blocked"
        : readinessStatus === "warn"
          ? "degraded"
          : systemReady
            ? "ready"
            : "unknown",
      detail: stringValue(readiness.summary, systemReady ? "Ready" : "Readiness has not been checked."),
      impact: stringValue(runtimeCheck.hint ?? readiness.hint, "Locked runtime, FFmpeg, storage, and GPU checks come from the shared readiness service."),
    },
    {
      id: "storage",
      label: "Storage",
      role: "Required",
      status: blockedPaths.length || diskStatus === "blocked"
        ? "blocked"
        : diskStatus === "warn"
          ? "degraded"
          : writablePaths.length
            ? "ready"
            : "unknown",
      detail: `${modelsDir} • mode ${storageMode}${catalog.model_cache ? ` • cache ${String(catalog.model_cache)}` : ""}`,
      impact: blockedPaths.length
        ? `Not writable: ${blockedPaths.map((path) => stringValue(path.path, "unknown path")).join(", ")}`
        : stringValue(diskCheck.hint, "All reported Studio paths are writable."),
    },
    {
      id: "accelerator",
      label: "GPU accelerator",
      role: "Optional",
      status: cudaReady ? "ready" : cuda.available === true || directml.available === true ? "degraded" : "degraded",
      detail: cudaReady
        ? `${acceleratorName}${vramGb > 0 ? ` • ${vramGb.toFixed(1)} GB VRAM` : ""} • CUDA enabled`
        : cuda.available === true
          ? `${acceleratorName}${vramGb > 0 ? ` • ${vramGb.toFixed(1)} GB VRAM` : ""} • CUDA available but inactive`
          : directml.available === true
            ? `${stringValue(directml.device_name, acceleratorName)} • DirectML available${directml.enabled === false ? " but disabled" : ""}`
            : `${acceleratorName} • local GPU acceleration is not ready`,
      impact: cuda.available === true && cuda.enabled === false
        ? "CUDA is detected but disabled in Settings."
        : cuda.available === true
          ? "CUDA is installed, but this backend session is not actively using the CUDA profile."
          : stringValue(gpuCheck.hint, "CPU and hosted routes remain available when configured."),
    },
    {
      id: "models",
      label: "Internal models",
      role: "Required for local AI render",
      status: internalModels.hasLocalStillModel
        ? "ready"
        : internalModels.activeTasks.length
          ? "running"
          : internalModels.hasRestorableStillModel
            ? "degraded"
            : internalModels.failedTasks.length
              ? "blocked"
              : "blocked",
      detail: `SD 1.5 ${internalModels.status("sd15")} • SDXL ${internalModels.status("sdxl")} • motion ${internalModels.hasLocalMotionModel ? "installed" : "missing"}`,
      impact: internalModels.hasLocalStillModel
        ? `Preferred installed path: ${internalModels.preferred}.`
        : internalModels.hasRestorableStillModel
          ? "A model exists in remote cache but must be restored locally before strict local preflight passes."
          : "Install a supported internal Diffusers model in Models for genuine local model rendering.",
    },
    {
      id: "planner",
      label: "Planning provider",
      role: ollamaRequired ? "Required" : "Configured path",
      status: planningReady && (!ollamaRequired || ollamaReady) ? "ready" : planningReady ? "degraded" : "blocked",
      detail: `${planningProvider}${ai.model ? ` • ${String(ai.model)}` : ""}${planningProvider === "ollama" ? (ollamaReady ? " • reachable" : " • unavailable") : " • configured"}`,
      impact: planningProvider === "rule_based"
        ? "Rule-based planning is available without an external model service."
        : "Provider status is reported separately from internal diffusion model readiness.",
    },
    {
      id: "render-providers",
      label: "Render routes",
      role: "Capability broker",
      status: internalModels.hasLocalStillModel || hostedReady || proxy.active === true ? "ready" : "blocked",
      detail: `${internalModels.hasLocalStillModel ? "local model" : "no local model"} • ${hostedProviders.length} hosted configured • proxy ${proxy.active === true ? "enabled" : "disabled"}`,
      impact: "Proxy is a draft fallback, not proof that CUDA model inference works.",
    },
    {
      id: "tasks",
      label: "Setup and model tasks",
      role: "Live status",
      status: !taskSourcesKnown ? "unknown" : activeTasks ? "running" : failedTasks ? "degraded" : "ready",
      detail: !taskSourcesKnown
        ? "Setup or model task status is unavailable."
        : activeTasks
          ? `${activeTasks} active task${activeTasks === 1 ? "" : "s"}`
          : "No active setup or model tasks.",
      impact: !taskSourcesKnown
        ? "Refresh after both Setup and Models task probes respond."
        : failedTasks
          ? `${failedTasks} unresolved latest task${failedTasks === 1 ? "" : "s"} reported failure.`
          : "Task state comes from Setup and Models, not inferred button state.",
    },
  ];

  const overall: StudioForgeStatusLevel = !backendReady || systemBlocked
    ? "blocked"
    : !readinessKnown
      || !taskSourcesKnown
      || readinessStatus === "warn"
      || !internalModels.hasLocalStillModel
      || !planningReady
      || failedTasks
      ? "degraded"
      : activeTasks
        ? "running"
        : "ready";

  return {
    overall,
    capabilities,
    cards,
    internalModels,
    storage: { mode: storageMode, modelCache: catalog.model_cache, modelsDir },
    activeTaskCount: activeTasks,
    failedTaskCount: failedTasks,
    planningProvider,
    cudaReady,
    ffmpegReady,
  };
}

function projectHasAudio(project: Record<string, unknown>): boolean {
  const meta = asRecord(project.meta);
  const audio = meta.audio;
  if (typeof audio === "string") return Boolean(audio.trim());
  if (audio && typeof audio === "object") return true;
  const analysis = asRecord(meta.analysis);
  return Boolean(stringValue(analysis.audio_path ?? analysis.audioPath ?? analysis.source_path));
}

export function deriveStudioForgeProject(snapshot: StudioForgeProjectSnapshot) {
  const project = asRecord(snapshot.project);
  const projectId = stringValue(snapshot.projectId ?? project.id);
  const meta = asRecord(project.meta);
  const analysis = asRecord(meta.analysis);
  const plan = asRecord(meta.last_plan);
  const variants = asArray(plan.variants);
  const selectedVariant = Math.max(0, Number(snapshot.selectedVariant ?? 0) || 0);
  const outputs = asRecord(snapshot.outputs);
  const videos = asArray(outputs.videos);
  const images = asArray(outputs.images);
  const deforumExports = asArray(outputs.deforum_exports);
  const unrealExports = asArray(outputs.unreal_exports);
  const unrealReturns = asArray(outputs.unreal_returns);
  const projectJobs = taskRows(snapshot.jobs);
  const publisherPayload = asRecord(snapshot.livePublishStatus);
  const publisher = asRecord(publisherPayload.publish);

  const hasProject = Boolean(projectId);
  const hasAudio = hasProject && projectHasAudio(project);
  const hasAnalysis = hasProject && Object.keys(analysis).length > 0;
  const hasPlan = variants.length > 0;
  const selectedVariantValid = hasPlan && selectedVariant < variants.length;
  const hasRenderOutput = videos.length + images.length + unrealReturns.length > 0;
  const hasDeforumExport = deforumExports.length > 0;
  const hasUnrealBundle = unrealExports.length > 0;

  const prerequisites: StudioForgePrerequisite[] = [];
  if (hasProject) prerequisites.push("project");
  if (hasAudio) prerequisites.push("audio");
  if (hasAnalysis) prerequisites.push("analysis");
  if (selectedVariantValid) prerequisites.push("plan");
  if (hasRenderOutput) prerequisites.push("renderOutput");
  if (hasDeforumExport) prerequisites.push("deforumExport");
  if (hasUnrealBundle) prerequisites.push("unrealBundle");

  return {
    prerequisites,
    projectId,
    projectName: stringValue(project.name, projectId || "No active project"),
    hasProject,
    hasAudio,
    hasAnalysis,
    hasPlan,
    variantCount: variants.length,
    selectedVariant,
    selectedVariantValid,
    hasRenderOutput,
    outputCount: videos.length + images.length,
    deforumExportCount: deforumExports.length,
    unrealBundleCount: unrealExports.length,
    unrealReturnCount: unrealReturns.length,
    unrealPreviewReady: Object.keys(asRecord(snapshot.unrealPreview)).length > 0,
    livePublisherRunning: publisher.running === true,
    projectActiveTaskCount: activeTaskCount(projectJobs),
    projectFailedTaskCount: failedTaskCount(projectJobs),
  };
}

function missingStageCapabilities(
  stage: StudioForgeRecipeStage,
  availableCapabilities: Set<StudioForgeCapability>,
): StudioForgeCapability[] {
  const missing = (stage.requiredCapabilities ?? []).filter(
    (capability) => !availableCapabilities.has(capability),
  );
  if (stage.anyCapabilities?.length && !stage.anyCapabilities.some((capability) => availableCapabilities.has(capability))) {
    missing.push(...stage.anyCapabilities);
  }
  return [...new Set(missing)];
}

export function evaluateStudioForgeRecipeStages(
  recipe: StudioForgeRecipe,
  capabilities: StudioForgeCapability[],
  prerequisites: StudioForgePrerequisite[],
): StudioForgeRecipeStageState[] {
  const capabilitySet = new Set(capabilities);
  const prerequisiteSet = new Set(prerequisites);
  let foundCurrent = false;

  return recipe.stages.map((stage) => {
    const missingCapabilities = missingStageCapabilities(stage, capabilitySet);
    const missingPrerequisites = (stage.requiredPrerequisites ?? []).filter(
      (prerequisite) => !prerequisiteSet.has(prerequisite),
    );
    const complete = missingCapabilities.length === 0 && missingPrerequisites.length === 0;
    if (foundCurrent) {
      return { stage, state: "blocked" as const, missingCapabilities, missingPrerequisites };
    }
    if (complete) {
      return { stage, state: "complete" as const, missingCapabilities, missingPrerequisites };
    }
    foundCurrent = true;
    return { stage, state: "current" as const, missingCapabilities, missingPrerequisites };
  });
}
