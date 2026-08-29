export type InternalModelKey = "sd15" | "sdxl" | "sd35" | "flux" | "svd" | "animatediff";

export type InternalModelCatalogEntry = {
  id: string;
  name?: string;
  kind?: string;
  source?: string;
  recommended?: string;
  installable?: boolean;
  license_id?: string;
};

export type InternalModelTask = {
  id?: string;
  model_id?: string;
  modelId?: string;
  name?: string;
  status?: string;
  progress?: number;
  message?: string;
  error?: string;
};

export type InternalModelState = "installed" | "installing" | "failed" | "cloud" | "missing";

const INTERNAL_MODELS: Record<
  InternalModelKey,
  { id: string; label: string; role: "still" | "motion" }
> = {
  sd15: { id: "hf_sd15_internal", label: "SD 1.5", role: "still" },
  sdxl: { id: "hf_sdxl_internal", label: "SDXL", role: "still" },
  sd35: { id: "hf_sd35_medium_internal", label: "SD3.5 Medium", role: "still" },
  flux: { id: "hf_flux1_schnell_internal", label: "FLUX.1 Schnell", role: "still" },
  svd: { id: "hf_svd_xt_1_1_internal", label: "SVD", role: "motion" },
  animatediff: {
    id: "hf_animatediff_motion_adapter_v15_2_internal",
    label: "AnimateDiff",
    role: "motion",
  },
};

const STILL_MODEL_PREFERENCE: InternalModelKey[] = ["flux", "sd35", "sdxl", "sd15"];

function taskModelId(task: InternalModelTask): string {
  return String(task.model_id ?? task.modelId ?? "").trim();
}

function normalizedTaskStatus(task: InternalModelTask | undefined): string {
  return String(task?.status ?? "").trim().toLowerCase();
}

function taskProgressLabel(task: InternalModelTask): string {
  const raw = Number(task.progress);
  if (!Number.isFinite(raw) || raw <= 0) return "";
  const percent = raw <= 1 ? Math.round(raw * 100) : Math.round(raw);
  return ` ${Math.min(100, Math.max(1, percent))}%`;
}

export function buildInternalModelReadiness<T extends InternalModelCatalogEntry>({
  catalog = [],
  installed = {},
  cloud = {},
  modelCache = "cloud cache",
  tasks = [],
}: {
  catalog?: T[];
  installed?: Record<string, boolean>;
  cloud?: Record<string, unknown>;
  modelCache?: string | null;
  tasks?: InternalModelTask[];
}) {
  const entries = Object.fromEntries(
    (Object.keys(INTERNAL_MODELS) as InternalModelKey[]).map((key) => [
      key,
      catalog.find((model) => model.id === INTERNAL_MODELS[key].id),
    ]),
  ) as Record<InternalModelKey, T | undefined>;

  const installedInternal = Object.fromEntries(
    (Object.keys(INTERNAL_MODELS) as InternalModelKey[]).map((key) => [
      key,
      Boolean(installed[INTERNAL_MODELS[key].id]),
    ]),
  ) as Record<InternalModelKey, boolean>;

  const cloudInternal = Object.fromEntries(
    (Object.keys(INTERNAL_MODELS) as InternalModelKey[]).map((key) => [
      key,
      Boolean(cloud[INTERNAL_MODELS[key].id]),
    ]),
  ) as Record<InternalModelKey, boolean>;

  const availableInternal = Object.fromEntries(
    (Object.keys(INTERNAL_MODELS) as InternalModelKey[]).map((key) => [
      key,
      installedInternal[key] || cloudInternal[key],
    ]),
  ) as Record<InternalModelKey, boolean>;

  const taskByModel = new Map<string, InternalModelTask>();
  for (const task of tasks) {
    const modelId = taskModelId(task);
    if (!modelId) continue;
    // ModelTaskManager.list() returns newest-first. Preserve the first task for
    // each model so an older failure or completion cannot replace current state.
    if (!taskByModel.has(modelId)) {
      taskByModel.set(modelId, task);
    }
  }

  const state = (key: InternalModelKey): InternalModelState => {
    if (installedInternal[key]) return "installed";
    const task = taskByModel.get(INTERNAL_MODELS[key].id);
    const taskStatus = normalizedTaskStatus(task);
    if (taskStatus === "queued" || taskStatus === "running") return "installing";
    if (taskStatus === "failed" || taskStatus === "error") return "failed";
    if (cloudInternal[key]) return "cloud";
    return "missing";
  };

  const status = (key: InternalModelKey): string => {
    const current = state(key);
    const task = taskByModel.get(INTERNAL_MODELS[key].id);
    if (current === "installed") return "installed locally";
    if (current === "installing") {
      const verb = normalizedTaskStatus(task) === "queued" ? "queued" : "installing";
      return `${verb}${task ? taskProgressLabel(task) : ""}`;
    }
    if (current === "failed") {
      const detail = String(task?.error ?? task?.message ?? "").trim();
      return detail ? `failed — ${detail}` : "install failed";
    }
    if (current === "cloud") return `stored in ${modelCache || "cloud cache"}; restore needed`;
    return "missing";
  };

  const preferredLocalKey = STILL_MODEL_PREFERENCE.find((key) => installedInternal[key]);
  const preferredAvailableKey = STILL_MODEL_PREFERENCE.find((key) => availableInternal[key]);
  const preferredKey = preferredLocalKey ?? preferredAvailableKey;
  const preferred = preferredKey
    ? `${INTERNAL_MODELS[preferredKey].label}${preferredLocalKey ? "" : " (restore needed)"}`
    : "none";

  const latestTasks = [...taskByModel.values()];
  const activeTasks = latestTasks.filter((task) => ["queued", "running"].includes(normalizedTaskStatus(task)));
  const failedTasks = latestTasks.filter((task) => ["failed", "error"].includes(normalizedTaskStatus(task)));
  const hasLocalMotionModel = installedInternal.svd
    || (installedInternal.animatediff && installedInternal.sd15);
  const hasRestorableMotionModel = !hasLocalMotionModel && (
    (cloudInternal.svd && !installedInternal.svd)
    || (
      availableInternal.animatediff
      && availableInternal.sd15
      && (cloudInternal.animatediff || cloudInternal.sd15)
    )
  );

  return {
    ...entries,
    entries,
    installedInternal,
    cloudInternal,
    availableInternal,
    state,
    status,
    preferred,
    preferredLocalKey,
    preferredAvailableKey,
    hasLocalStillModel: STILL_MODEL_PREFERENCE.some((key) => installedInternal[key]),
    hasRestorableStillModel: STILL_MODEL_PREFERENCE.some(
      (key) => cloudInternal[key] && !installedInternal[key],
    ),
    hasLocalMotionModel,
    hasRestorableMotionModel,
    activeTasks,
    failedTasks,
  };
}

export const INTERNAL_MODEL_LABELS = Object.fromEntries(
  (Object.keys(INTERNAL_MODELS) as InternalModelKey[]).map((key) => [key, INTERNAL_MODELS[key].label]),
) as Record<InternalModelKey, string>;
