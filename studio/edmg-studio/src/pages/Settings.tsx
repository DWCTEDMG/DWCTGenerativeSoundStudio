import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, normalizeBackendUrl, setBrowserBackendUrl } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { StructuredSummary } from "../components/StructuredSummary";
import BackendSecurityPanel from "../components/BackendSecurityPanel";
import { STUDIO_THEME_OPTIONS, useStudioAppearance } from "../components/studioAppearance";
import { useStudioPageLayout } from "../components/studioLayout";
import { useUiMode } from "../components/uiMode";
import { clearRenderDefaults, readRenderDefaults, writeRenderDefaults } from "../components/renderDefaults";
import type { PageProps } from "../types/pageProps";

type SecretName = "hf_token" | "civitai_api_key" | "openai_compat_api_key" | "stability_api_key" | "nvidia_api_key" | "adobe_client_id" | "adobe_client_secret" | "imagineart_api_key" | "azure_foundry_api_key";

type StudioAiSettings = {
  mode: string;
  provider: string;
  aiBaseUrl: string;
  ollamaUrl: string;
  ollamaModel: string;
  openaiCompatBaseUrl: string;
  openaiCompatModel: string;
  nvidiaBaseUrl?: string;
  nvidiaModel?: string;
  source?: string;
};

type StudioBackendSettings = {
  mode: string;
  host: string;
  port: string;
  url: string;
  source?: string;
};

type TranscriptionSettings = {
  provider: string;
  model: string;
  device: string;
  compute_type: string;
  fallback_to_whisper: boolean;
  separate_vocals: boolean;
  separation_model: string;
};

type SettingsPanelId =
  | "uiMode"
  | "appearance"
  | "renderDefaults"
  | "systemReadiness"
  | "desktopBackend"
  | "aiProvider"
  | "transcription"
  | "backendConfig"
  | "liveAiStatus"
  | "tokens"
  | "renderRuntime"
  | "comfyui"
  | "deforum";

const NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1";
const NEMOTRON_ULTRA_MODEL = "nvidia/llama-3.1-nemotron-ultra-253b-v1";
const DIFFUSIONGEMMA_MODEL = "google/diffusiongemma-26B-A4B-it";
const LEGACY_OPENAI_COMPAT_BASE_URL = "http://127.0.0.1:8000";
const LEGACY_OPENAI_COMPAT_MODEL = "qwen3-8b";

const DEFAULT_AI_SETTINGS: StudioAiSettings = {
  mode: "local",
  provider: "nemotron_cloud",
  aiBaseUrl: "http://127.0.0.1:7862",
  ollamaUrl: "http://127.0.0.1:11434",
  ollamaModel: "qwen3:8b",
  openaiCompatBaseUrl: NVIDIA_NIM_BASE_URL,
  openaiCompatModel: NEMOTRON_ULTRA_MODEL,
  nvidiaBaseUrl: NVIDIA_NIM_BASE_URL,
  nvidiaModel: NEMOTRON_ULTRA_MODEL,
  source: "default",
};

type NvidiaPromptModelPreset = {
  id?: string;
  label: string;
  model: string;
  family?: string;
  description?: string;
};

const DEFAULT_NVIDIA_PROMPT_MODEL_PRESETS: NvidiaPromptModelPreset[] = [
  {
    id: "nemotron_ultra",
    label: "Nemotron Ultra 253B",
    model: NEMOTRON_ULTRA_MODEL,
    family: "nemotron",
    description: "High-quality creative planning and storyboard reasoning through NVIDIA's OpenAI-compatible API.",
  },
  {
    id: "diffusiongemma",
    label: "DiffusionGemma 26B A4B",
    model: DIFFUSIONGEMMA_MODEL,
    family: "diffusiongemma",
    description: "Fast parallel text generation for planner and prompt refinement on NVIDIA NIM or vLLM endpoints.",
  },
];

function normalizeNvidiaPromptModelPreset(raw: any): NvidiaPromptModelPreset | null {
  const model = String(raw?.model ?? "").trim();
  if (!model) return null;
  const label = String(raw?.label ?? model).trim() || model;
  return {
    id: String(raw?.id ?? label).trim() || label,
    label,
    model,
    family: String(raw?.family ?? "").trim() || undefined,
    description: String(raw?.description ?? "").trim() || undefined,
  };
}

function collectNvidiaPromptModelPresets(cfg: any, aiStatus: any): NvidiaPromptModelPreset[] {
  const merged = new Map<string, NvidiaPromptModelPreset>();
  for (const preset of DEFAULT_NVIDIA_PROMPT_MODEL_PRESETS) {
    merged.set(preset.model, preset);
  }
  const candidates = [
    ...(Array.isArray(cfg?.ai_nvidia_model_presets) ? cfg.ai_nvidia_model_presets : []),
    ...(Array.isArray(aiStatus?.ai_config?.model_presets) ? aiStatus.ai_config.model_presets : []),
  ];
  for (const candidate of candidates) {
    const preset = normalizeNvidiaPromptModelPreset(candidate);
    if (preset) merged.set(preset.model, preset);
  }
  return Array.from(merged.values());
}

function nvidiaModelPresetValue(model: string | undefined, presets: NvidiaPromptModelPreset[]): string {
  const current = String(model || "").trim();
  return presets.some((preset) => preset.model === current) ? current : "custom";
}

function nvidiaModelFamily(model: string | undefined, presets: NvidiaPromptModelPreset[]): string {
  const current = String(model || "").trim().toLowerCase();
  const preset = presets.find((item) => item.model.toLowerCase() === current);
  if (preset?.family) return preset.family;
  if (current.includes("diffusiongemma") || current.includes("diffusion-gemma")) return "diffusiongemma";
  if (current.includes("nemotron")) return "nemotron";
  return "custom";
}

function normalizeOpenAiCompatDefaults(
  rawBaseUrl: string | undefined,
  rawModel: string | undefined,
): { baseUrl: string; model: string } {
  const baseUrl = String(rawBaseUrl ?? "").trim();
  const model = String(rawModel ?? "").trim();
  if (
    (baseUrl === LEGACY_OPENAI_COMPAT_BASE_URL && (!model || model === LEGACY_OPENAI_COMPAT_MODEL)) ||
    (!baseUrl && model === LEGACY_OPENAI_COMPAT_MODEL)
  ) {
    return {
      baseUrl: DEFAULT_AI_SETTINGS.openaiCompatBaseUrl,
      model: DEFAULT_AI_SETTINGS.openaiCompatModel,
    };
  }
  return {
    baseUrl: baseUrl || DEFAULT_AI_SETTINGS.openaiCompatBaseUrl,
    model: model || DEFAULT_AI_SETTINGS.openaiCompatModel,
  };
}

const DEFAULT_BACKEND_SETTINGS: StudioBackendSettings = {
  mode: "managed",
  host: "127.0.0.1",
  port: "7863",
  url: "",
  source: "default",
};

const DEFAULT_TRANSCRIPTION_SETTINGS: TranscriptionSettings = {
  provider: "faster_whisper",
  model: "turbo",
  device: "auto",
  compute_type: "auto",
  fallback_to_whisper: true,
  separate_vocals: false,
  separation_model: "htdemucs",
};

function normalizeAiSettings(payload?: Partial<StudioAiSettings> | null): StudioAiSettings {
  const current = payload ?? {};
  const mode = String(current.mode ?? DEFAULT_AI_SETTINGS.mode).trim().toLowerCase();
  const providerRaw = String(current.provider ?? DEFAULT_AI_SETTINGS.provider).trim().toLowerCase();
  const provider =
    providerRaw === "openai" || providerRaw === "openai-compatible"
      ? "openai_compat"
      : providerRaw === "nvidia_nim" || providerRaw === "nemotron"
      ? "nemotron_cloud"
      : providerRaw || DEFAULT_AI_SETTINGS.provider;
  const openaiCompat = normalizeOpenAiCompatDefaults(
    current.openaiCompatBaseUrl,
    current.openaiCompatModel,
  );

  return {
    mode: mode === "http" || mode === "remote" ? "http" : "local",
    provider: provider || DEFAULT_AI_SETTINGS.provider,
    aiBaseUrl: String(current.aiBaseUrl ?? DEFAULT_AI_SETTINGS.aiBaseUrl).trim() || DEFAULT_AI_SETTINGS.aiBaseUrl,
    ollamaUrl: String(current.ollamaUrl ?? DEFAULT_AI_SETTINGS.ollamaUrl).trim() || DEFAULT_AI_SETTINGS.ollamaUrl,
    ollamaModel: String(current.ollamaModel ?? DEFAULT_AI_SETTINGS.ollamaModel).trim() || DEFAULT_AI_SETTINGS.ollamaModel,
    openaiCompatBaseUrl: openaiCompat.baseUrl,
    openaiCompatModel: openaiCompat.model,
    nvidiaBaseUrl:
      String(current.nvidiaBaseUrl ?? DEFAULT_AI_SETTINGS.nvidiaBaseUrl ?? "").trim() ||
      DEFAULT_AI_SETTINGS.nvidiaBaseUrl,
    nvidiaModel:
      String(current.nvidiaModel ?? DEFAULT_AI_SETTINGS.nvidiaModel ?? "").trim() ||
      DEFAULT_AI_SETTINGS.nvidiaModel,
    source: String(current.source ?? DEFAULT_AI_SETTINGS.source),
  };
}

function aiSettingsFingerprint(settings: Partial<StudioAiSettings> | null | undefined): string {
  const normalized = normalizeAiSettings(settings);
  return JSON.stringify({
    mode: normalized.mode,
    provider: normalized.provider,
    aiBaseUrl: normalized.aiBaseUrl,
    ollamaUrl: normalized.ollamaUrl,
    ollamaModel: normalized.ollamaModel,
    openaiCompatBaseUrl: normalized.openaiCompatBaseUrl,
    openaiCompatModel: normalized.openaiCompatModel,
    nvidiaBaseUrl: normalized.nvidiaBaseUrl,
    nvidiaModel: normalized.nvidiaModel,
  });
}

function normalizeBackendSettings(payload?: Partial<StudioBackendSettings> | null): StudioBackendSettings {
  const current = payload ?? {};
  const modeRaw = String(current.mode ?? DEFAULT_BACKEND_SETTINGS.mode).trim().toLowerCase();
  const mode = modeRaw === "external" || modeRaw === "remote" || modeRaw === "connect" ? "external" : "managed";
  const host = String(current.host ?? DEFAULT_BACKEND_SETTINGS.host).trim() || DEFAULT_BACKEND_SETTINGS.host;
  const portRaw = String(current.port ?? DEFAULT_BACKEND_SETTINGS.port).trim();
  const portNumber = Number(portRaw);
  const port =
    Number.isInteger(portNumber) && portNumber >= 1 && portNumber <= 65535
      ? String(portNumber)
      : DEFAULT_BACKEND_SETTINGS.port;
  const rawUrl = String(current.url ?? "").trim();
  const normalizedUrl = sanitizeBackendUrl(rawUrl);

  return {
    mode,
    host,
    port,
    url: mode === "external" ? (rawUrl ? normalizedUrl || rawUrl : "") : "",
    source: String(current.source ?? DEFAULT_BACKEND_SETTINGS.source),
  };
}

function backendSettingsFingerprint(settings: Partial<StudioBackendSettings> | null | undefined): string {
  const normalized = normalizeBackendSettings(settings);
  return JSON.stringify({
    mode: normalized.mode,
    host: normalized.host,
    port: normalized.port,
    url: normalized.mode === "external" ? normalized.url : "",
  });
}

function buildBackendUrl(settings: Partial<StudioBackendSettings> | null | undefined): string {
  const normalized = normalizeBackendSettings(settings);
  if (normalized.mode === "external") {
    return sanitizeBackendUrl(normalized.url) || normalized.url || buildManagedBackendUrl(normalized.host, normalized.port);
  }
  return buildManagedBackendUrl(normalized.host, normalized.port);
}

function buildManagedBackendUrl(host: string, port: string): string {
  return `http://${host}:${port}`;
}

function sanitizeBackendUrl(rawUrl: string): string {
  return normalizeBackendUrl(rawUrl);
}

function parseBackendUrl(rawUrl: string): Partial<StudioBackendSettings> {
  const sanitized = sanitizeBackendUrl(rawUrl);
  if (!sanitized) return {};
  try {
    const parsed = new URL(sanitized);
    return {
      host: parsed.hostname || DEFAULT_BACKEND_SETTINGS.host,
      port: parsed.port || (parsed.protocol === "https:" ? "443" : "80"),
      url: sanitized,
    };
  } catch {
    return {};
  }
}

function normalizeTranscriptionSettings(payload?: Partial<TranscriptionSettings> | null): TranscriptionSettings {
  const current = payload ?? {};
  const providerRaw = String(current.provider ?? DEFAULT_TRANSCRIPTION_SETTINGS.provider).trim().toLowerCase();
  const provider =
    providerRaw === "parakeet" || providerRaw === "nvidia_parakeet"
      ? "parakeet"
      : "faster_whisper";
  const modelRaw = String(current.model ?? "").trim();
  let model = modelRaw || (provider === "parakeet" ? "nvidia/parakeet-tdt-0.6b-v3" : DEFAULT_TRANSCRIPTION_SETTINGS.model);
  if (provider === "parakeet") {
    const lower = model.toLowerCase().replaceAll("_", "-");
    if (lower === "v2" || lower.endsWith("parakeet-tdt-0.6b-v2")) {
      model = "nvidia/parakeet-tdt-0.6b-v2";
    } else if (lower === "v3" || lower.endsWith("parakeet-tdt-0.6b-v3")) {
      model = "nvidia/parakeet-tdt-0.6b-v3";
    } else {
      model = "nvidia/parakeet-tdt-0.6b-v3";
    }
  } else if (!["turbo", "large-v3", "medium", "small"].includes(model)) {
    model = DEFAULT_TRANSCRIPTION_SETTINGS.model;
  }

  const device = String(current.device ?? DEFAULT_TRANSCRIPTION_SETTINGS.device).trim().toLowerCase();
  const computeType = String(current.compute_type ?? DEFAULT_TRANSCRIPTION_SETTINGS.compute_type).trim().toLowerCase();

  return {
    provider,
    model,
    device: ["auto", "cuda", "cpu"].includes(device) ? device : DEFAULT_TRANSCRIPTION_SETTINGS.device,
    compute_type: ["auto", "float16", "int8", "int8_float16"].includes(computeType)
      ? computeType
      : DEFAULT_TRANSCRIPTION_SETTINGS.compute_type,
    fallback_to_whisper: current.fallback_to_whisper !== false,
    separate_vocals: current.separate_vocals === true,
    separation_model: String(current.separation_model ?? DEFAULT_TRANSCRIPTION_SETTINGS.separation_model).trim() || DEFAULT_TRANSCRIPTION_SETTINGS.separation_model,
  };
}

function cosmosNimLaunchCommand(size: string): string {
  const modelSize = size === "super" ? "super" : "nano";
  return [
    "docker run -it --rm \\",
    "  --runtime=nvidia --gpus all \\",
    "  --shm-size=32GB --ulimit nofile=65536:65536 \\",
    "  -e NGC_API_KEY=$NGC_API_KEY \\",
    `  -e NIM_MODEL_SIZE=${modelSize} \\`,
    "  -p 8000:8000 \\",
    "  nvcr.io/nim/nvidia/cosmos3-generator:1.0.0",
  ].join("\n");
}

export default function Settings(props: PageProps) {
  const { mode, setMode } = useUiMode();
  const { theme, setTheme } = useStudioAppearance();
  const [cfg, setCfg] = useState<any>(null);
  const [aiStatus, setAiStatus] = useState<any>(null);
  const [edmgTemplate, setEdmgTemplate] = useState<any>(null);
  const [secrets, setSecrets] = useState<any>(null);
  const [hardware, setHardware] = useState<any>(null);
  const [systemReadiness, setSystemReadiness] = useState<any>(null);
  const [buildIdentity, setBuildIdentity] = useState<any>(null);
  const [backendHealth, setBackendHealth] = useState<any>(null);
  const [baselineMetrics, setBaselineMetrics] = useState<any>(null);
  const [renderProfiles, setRenderProfiles] = useState<any>(null);
  const [renderProviders, setRenderProviders] = useState<any>(null);
  const [renderProviderDraft, setRenderProviderDraft] = useState<any>(null);
  const [videoRoute, setVideoRoute] = useState<any>(null);
  const [transcriptionStatus, setTranscriptionStatus] = useState<any>(null);
  const [transcriptionDraft, setTranscriptionDraft] = useState<TranscriptionSettings>(DEFAULT_TRANSCRIPTION_SETTINGS);
  const [savedRenderDefaults, setSavedRenderDefaults] = useState<any>(() => readRenderDefaults());
  const [studioBackendSettings, setStudioBackendSettings] = useState<StudioBackendSettings>(DEFAULT_BACKEND_SETTINGS);
  const [backendDraft, setBackendDraft] = useState<StudioBackendSettings>(DEFAULT_BACKEND_SETTINGS);
  const [backendSettingsLoaded, setBackendSettingsLoaded] = useState<boolean>(false);
  const [studioAiSettings, setStudioAiSettings] = useState<StudioAiSettings>(DEFAULT_AI_SETTINGS);
  const [aiDraft, setAiDraft] = useState<StudioAiSettings>(DEFAULT_AI_SETTINGS);
  const [aiSettingsLoaded, setAiSettingsLoaded] = useState<boolean>(false);
  const [hfToken, setHfToken] = useState<string>("");
  const [civitaiKey, setCivitaiKey] = useState<string>("");
  const [openaiCompatApiKey, setOpenaiCompatApiKey] = useState<string>("");
  const [stabilityApiKey, setStabilityApiKey] = useState<string>("");
  const [nvidiaApiKey, setNvidiaApiKey] = useState<string>("");
  const [cosmosCmdCopied, setCosmosCmdCopied] = useState<boolean>(false);
  const [adobeClientId, setAdobeClientId] = useState<string>("");
  const [adobeClientSecret, setAdobeClientSecret] = useState<string>("");
  const [imagineartApiKey, setImagineartApiKey] = useState<string>("");
  const [azureFoundryApiKey, setAzureFoundryApiKey] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [savingBackend, setSavingBackend] = useState<boolean>(false);
  const [savingAi, setSavingAi] = useState<boolean>(false);
  const [savingProviders, setSavingProviders] = useState<boolean>(false);
  const [savingTranscription, setSavingTranscription] = useState<boolean>(false);
  const [backendRestartRequired, setBackendRestartRequired] = useState<boolean>(false);
  const [backendNotice, setBackendNotice] = useState<string | null>(null);
  const [aiRestartRequired, setAiRestartRequired] = useState<boolean>(false);
  const [aiNotice, setAiNotice] = useState<string | null>(null);
  const [liveBackendUrl, setLiveBackendUrl] = useState<string>(props.backendUrl || "");
  const [backendReachable, setBackendReachable] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const canPersistBackendSettings = typeof window !== "undefined" && !!window.edmg?.setBackendSettings;

  useEffect(() => {
    void refreshPage();
  }, []);

  const aiSettingsDirty = useMemo(
    () => aiSettingsFingerprint(aiDraft) !== aiSettingsFingerprint(studioAiSettings),
    [aiDraft, studioAiSettings]
  );

  const nvidiaPromptModelPresets = useMemo(
    () => collectNvidiaPromptModelPresets(cfg, aiStatus),
    [cfg, aiStatus]
  );
  const selectedNvidiaPromptPreset = useMemo(
    () => nvidiaModelPresetValue(aiDraft.nvidiaModel, nvidiaPromptModelPresets),
    [aiDraft.nvidiaModel, nvidiaPromptModelPresets]
  );
  const selectedNvidiaModelFamily = useMemo(
    () => nvidiaModelFamily(aiDraft.nvidiaModel, nvidiaPromptModelPresets),
    [aiDraft.nvidiaModel, nvidiaPromptModelPresets]
  );
  const selectedNvidiaPromptModel = nvidiaPromptModelPresets.find((preset) => preset.model === aiDraft.nvidiaModel);

  const backendSettingsDirty = useMemo(
    () => backendSettingsFingerprint(backendDraft) !== backendSettingsFingerprint(studioBackendSettings),
    [backendDraft, studioBackendSettings]
  );

  async function refreshPage() {
    try {
      const nextCfg = await apiGet("/v1/config");
      setCfg(nextCfg);
      await refreshBackendStartupSettings();
      await refreshAiStartupSettings(nextCfg);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
      await refreshBackendStartupSettings();
      await refreshAiStartupSettings(null);
    }

    apiGet("/v1/ai/status").then(setAiStatus).catch(() => {});
    apiGet("/v1/edmg/deforum_template").then(setEdmgTemplate).catch(() => {});
    apiGet("/v1/settings/secrets/status").then(setSecrets).catch(() => {});
    apiGet("/v1/hardware").then(setHardware).catch(() => {});
    apiGet("/v1/system/readiness").then(setSystemReadiness).catch(() => {});
    apiGet("/health").then(setBackendHealth).catch(() => {});
    window.edmg?.getBuildIdentity?.().then(setBuildIdentity).catch(() => {});
    apiGet("/v1/metrics/baseline").then(setBaselineMetrics).catch(() => {});
    apiGet("/v1/settings/render_profiles").then(setRenderProfiles).catch(() => {});
    apiGet("/v1/settings/render_providers").then((d) => {
      setRenderProviders(d);
      setRenderProviderDraft(d?.settings ?? null);
    }).catch(() => {});
    apiGet("/v1/render/route").then(setVideoRoute).catch(() => {});
    apiGet("/v1/settings/transcription").then((d) => {
      setTranscriptionStatus(d);
      setTranscriptionDraft(normalizeTranscriptionSettings(d?.settings));
    }).catch(() => {});
  }

  async function refreshAiStartupSettings(nextCfg: any) {
    try {
      if (window.edmg?.getAiSettings) {
        const saved = await window.edmg.getAiSettings();
        if (saved?.ok) {
          const normalized = normalizeAiSettings(saved);
          setStudioAiSettings(normalized);
          setAiDraft(normalized);
          setAiSettingsLoaded(true);
          return;
        }
      }
    } catch {
      // fall through to backend snapshot
    }

    const fallback = normalizeAiSettings({
      mode: nextCfg?.ai_mode,
      provider: nextCfg?.ai_provider,
      aiBaseUrl: nextCfg?.ai_base_url,
      ollamaUrl: nextCfg?.ai_ollama_url,
      ollamaModel: nextCfg?.ai_ollama_model,
      openaiCompatBaseUrl: nextCfg?.ai_openai_compat_base_url,
      openaiCompatModel: nextCfg?.ai_openai_compat_model,
      nvidiaBaseUrl: nextCfg?.ai_nvidia_base_url,
      nvidiaModel: nextCfg?.ai_nvidia_model,
      source: nextCfg ? "backend" : "default",
    });
    setStudioAiSettings(fallback);
    setAiDraft(fallback);
    setAiSettingsLoaded(true);
  }

  async function refreshBackendHealth(urlCandidate: string) {
    const target = sanitizeBackendUrl(urlCandidate);
    if (!target) {
      setBackendReachable(null);
      return;
    }

    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timeoutId = controller ? window.setTimeout(() => controller.abort(), 2500) : 0;
    try {
      const response = await fetch(`${target}/health`, {
        method: "GET",
        signal: controller?.signal,
      });
      setBackendReachable(!!response.ok);
    } catch {
      setBackendReachable(false);
    } finally {
      if (timeoutId) window.clearTimeout(timeoutId);
    }
  }

  async function refreshBackendStartupSettings() {
    try {
      if (window.edmg?.getBackendSettings) {
        const saved = await window.edmg.getBackendSettings();
        if (saved?.ok) {
          const normalized = normalizeBackendSettings(saved);
          const nextLiveUrl = String(saved.currentBackendUrl || props.backendUrl || buildBackendUrl(normalized)).trim();
          setStudioBackendSettings(normalized);
          setBackendDraft(normalized);
          setBackendSettingsLoaded(true);
          setLiveBackendUrl(nextLiveUrl);
          await refreshBackendHealth(nextLiveUrl);
          return;
        }
      }
    } catch {
      // fall through to runtime URL snapshot
    }

    const runtimeUrl = sanitizeBackendUrl(props.backendUrl);
    const fallback = normalizeBackendSettings({
      ...parseBackendUrl(runtimeUrl),
      mode: runtimeUrl ? "external" : "managed",
      url: runtimeUrl,
      source: runtimeUrl ? "runtime" : "default",
    });
    const nextLiveUrl = String(props.backendUrl || buildBackendUrl(fallback)).trim();
    setStudioBackendSettings(fallback);
    setBackendDraft(fallback);
    setBackendSettingsLoaded(true);
    setLiveBackendUrl(nextLiveUrl);
    await refreshBackendHealth(nextLiveUrl);
  }

  async function refreshSecrets() {
    try {
      const s = await apiGet("/v1/settings/secrets/status");
      setSecrets(s);
    } catch {
      // ignore
    }
  }

  async function refreshBackendAiStatus() {
    try {
      const nextCfg = await apiGet("/v1/config");
      setCfg(nextCfg);
    } catch {
      // ignore
    }

    try {
      const nextStatus = await apiGet("/v1/ai/status");
      setAiStatus(nextStatus);
    } catch {
      // ignore
    }
  }

  async function saveSecret(name: SecretName, value: string) {
    setSaving(true);
    setErr(null);
    try {
      await apiPost("/v1/settings/secrets/set", { name, value });
      if (name === "hf_token") setHfToken("");
      if (name === "civitai_api_key") setCivitaiKey("");
      if (name === "openai_compat_api_key") setOpenaiCompatApiKey("");
      if (name === "stability_api_key") setStabilityApiKey("");
      if (name === "nvidia_api_key") setNvidiaApiKey("");
      if (name === "adobe_client_id") setAdobeClientId("");
      if (name === "adobe_client_secret") setAdobeClientSecret("");
      if (name === "imagineart_api_key") setImagineartApiKey("");
      if (name === "azure_foundry_api_key") setAzureFoundryApiKey("");
      await refreshSecrets();
      await refreshBackendAiStatus();
      const nextProviders = await apiGet("/v1/settings/render_providers");
      setRenderProviders(nextProviders);
      setRenderProviderDraft(nextProviders?.settings ?? null);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setSaving(false);
    }
  }

  function applyRenderProfile(profileId: "laptop_safe" | "balanced_auto" | "high_quality") {
    const p = renderProfiles?.profiles?.[profileId];
    if (!p) return;
    const next = {
      profileId,
      renderPreset: p.render_preset,
      internalRenderTier: p.internal_render_tier,
      internalResumeExisting: !!p.resume_existing_frames,
    };
    writeRenderDefaults(next);
    setSavedRenderDefaults(next);
  }

  function resetRenderProfile() {
    clearRenderDefaults();
    setSavedRenderDefaults({});
  }

  function updateBackendDraft(patch: Partial<StudioBackendSettings>) {
    setBackendDraft((current) => {
      const merged = { ...current, ...patch, source: current.source };
      const nextMode = normalizeBackendSettings({ mode: merged.mode }).mode;
      if (nextMode === "external" && !String(merged.url ?? "").trim()) {
        merged.url = buildManagedBackendUrl(current.host, current.port);
      }
      return normalizeBackendSettings(merged);
    });
    setBackendNotice(null);
  }

  function updateAiDraft(patch: Partial<StudioAiSettings>) {
    setAiDraft((current) => normalizeAiSettings({ ...current, ...patch, source: current.source }));
    setAiNotice(null);
  }

  async function saveBackendSettings() {
    setSavingBackend(true);
    setErr(null);
    setBackendNotice(null);
    try {
      const normalizedDraft = normalizeBackendSettings(backendDraft);
      const backendUrl =
        normalizedDraft.mode === "external"
          ? sanitizeBackendUrl(normalizedDraft.url)
          : "";
      if (normalizedDraft.mode === "external" && !backendUrl) {
        throw new Error("Enter a valid backend URL starting with http:// or https://.");
      }
      const activeUrl =
        normalizedDraft.mode === "external"
          ? backendUrl
          : buildManagedBackendUrl(normalizedDraft.host, normalizedDraft.port);

      if (!canPersistBackendSettings) {
        const connectedUrl = setBrowserBackendUrl(activeUrl);
        if (!connectedUrl) {
          throw new Error("Enter a valid backend URL starting with http:// or https://.");
        }
        const normalized = normalizeBackendSettings({
          ...normalizedDraft,
          mode: normalizedDraft.mode === "external" ? "external" : "managed",
          url: normalizedDraft.mode === "external" ? connectedUrl : "",
          source: "browser",
        });
        setStudioBackendSettings(normalized);
        setBackendDraft(normalized);
        setBackendRestartRequired(false);
        setLiveBackendUrl(connectedUrl);
        setBackendNotice("Connected for this browser. Desktop startup persistence is available in Electron.");
        await refreshBackendHealth(connectedUrl);
        return;
      }

      const response = await window.edmg?.setBackendSettings?.({
        mode: normalizedDraft.mode,
        host: normalizedDraft.host,
        port: normalizedDraft.port,
        url: backendUrl,
      });
      if (!response?.ok) {
        throw new Error(response?.error || "Failed to save desktop backend settings.");
      }
      const normalized = normalizeBackendSettings({ ...response, source: "bootstrap" });
      const nextLiveUrl = String(response.currentBackendUrl || buildBackendUrl(normalized)).trim();
      setStudioBackendSettings(normalized);
      setBackendDraft(normalized);
      setBackendRestartRequired(!!response.restartRequired);
      setLiveBackendUrl(nextLiveUrl);
      setBackendNotice(
        response.restartRequired
          ? "Saved. Restart Studio so it relaunches against the selected backend target."
          : "Saved."
      );
      await refreshBackendHealth(nextLiveUrl);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setSavingBackend(false);
    }
  }

  async function saveAiSettings() {
    setSavingAi(true);
    setErr(null);
    setAiNotice(null);
    try {
      if (!window.edmg?.setAiSettings) {
        throw new Error("This Studio build cannot persist AI startup settings yet.");
      }
      const response = await window.edmg.setAiSettings(normalizeAiSettings(aiDraft));
      if (!response?.ok) {
        throw new Error(response?.error || "Failed to save AI startup settings.");
      }
      const normalized = normalizeAiSettings({ ...response, source: "bootstrap" });
      setStudioAiSettings(normalized);
      setAiDraft(normalized);
      setAiRestartRequired(!!response.restartRequired);
      setAiNotice(
        response.restartRequired
          ? "Saved. Restart Studio so the backend relaunches on the new AI provider."
          : "Saved."
      );
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setSavingAi(false);
    }
  }

  async function clearSecret(name: SecretName) {
    setSaving(true);
    setErr(null);
    try {
      await apiPost("/v1/settings/secrets/clear", { name });
      await refreshSecrets();
      await refreshBackendAiStatus();
      const nextProviders = await apiGet("/v1/settings/render_providers");
      setRenderProviders(nextProviders);
      setRenderProviderDraft(nextProviders?.settings ?? null);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setSaving(false);
    }
  }

  async function saveRenderProviders() {
    setSavingProviders(true);
    setErr(null);
    try {
      const draft = renderProviderDraft || {};
      const next = await apiPost("/v1/settings/render_providers", {
        ...draft,
        video: {
          ...(draft.video || {}),
          allow_proxy_renders: false,
        },
      });
      setRenderProviders(next?.status ?? next);
      setRenderProviderDraft(next?.settings ?? renderProviderDraft);
      apiGet("/v1/render/route").then(setVideoRoute).catch(() => {});
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setSavingProviders(false);
    }
  }

  function updateTranscriptionDraft(patch: Partial<TranscriptionSettings>) {
    setTranscriptionDraft((current) => {
      const merged = { ...current, ...patch };
      if (patch.provider === "parakeet" && current.provider !== "parakeet") {
        merged.model = "nvidia/parakeet-tdt-0.6b-v3";
        merged.device = current.device === "cpu" ? "cuda" : current.device;
        merged.compute_type = "auto";
      }
      if (patch.provider === "faster_whisper" && current.provider !== "faster_whisper") {
        merged.model = "turbo";
        merged.device = "cpu";
        merged.compute_type = "int8";
      }
      return normalizeTranscriptionSettings(merged);
    });
  }

  async function saveTranscriptionSettings() {
    setSavingTranscription(true);
    setErr(null);
    try {
      const next = await apiPost("/v1/settings/transcription", normalizeTranscriptionSettings(transcriptionDraft));
      setTranscriptionStatus(next?.status ?? next);
      setTranscriptionDraft(normalizeTranscriptionSettings(next?.settings ?? next?.status?.settings ?? transcriptionDraft));
      const nextCfg = await apiGet("/v1/config").catch(() => null);
      if (nextCfg) setCfg(nextCfg);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setSavingTranscription(false);
    }
  }

  const panelDefinitions = useMemo(
    () => [
      {
        id: "uiMode" as const,
        label: "UI Mode",
        description: "Simple vs advanced interface density and control exposure.",
      },
      {
        id: "appearance" as const,
        label: "Appearance",
        description: "Theme selection and future customization entrypoint.",
      },
      {
        id: "renderDefaults" as const,
        label: "Render defaults",
        description: "Saved profiles that the Render page can pick up automatically.",
      },
      {
        id: "systemReadiness" as const,
        label: "System readiness",
        description: "FFmpeg, Python runtime, GPU, disk, writable paths, and models health.",
      },
      {
        id: "desktopBackend" as const,
        label: "Desktop backend",
        description: "Startup mode and managed vs external backend target.",
      },
      {
        id: "aiProvider" as const,
        label: "AI Provider",
        description: "Saved startup provider, routing, and credential-adjacent controls.",
      },
      {
        id: "transcription" as const,
        label: "Transcription",
        description: "ASR provider, model, and GPU preferences for Analyze + transcribe.",
      },
      {
        id: "backendConfig" as const,
        label: "Backend config snapshot",
        description: "Raw `/v1/config` inspection card.",
      },
      {
        id: "liveAiStatus" as const,
        label: "Live Backend AI Status",
        description: "Read-only runtime provider status from the active backend.",
      },
      {
        id: "tokens" as const,
        label: "Tokens",
        description: "Saved gated-download and hosted-provider credentials status.",
      },
      {
        id: "renderRuntime" as const,
        label: "GPU / Render Runtime",
        description: "NVIDIA CUDA, Stability hosted, and AMD DirectML render preferences.",
      },
      {
        id: "comfyui" as const,
        label: "ComfyUI workflow",
        description: "Reference guidance for the optional ComfyUI routing path.",
      },
      {
        id: "deforum" as const,
        label: "Deforum template",
        description: "EDMG Core-derived Deforum export reference.",
      },
    ],
    [],
  );
  const {
    profileOptions,
    activeProfile,
    setActiveProfile,
    layoutState,
    visibleOrder,
    movePanel,
    updateHidden,
    resetLayout,
  } = useStudioPageLayout<SettingsPanelId>(
    "settings",
    panelDefinitions.map((panel) => panel.id),
  );
  const panelDefinitionById = useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<SettingsPanelId, (typeof panelDefinitions)[number]>,
    [panelDefinitions],
  );
  const panelControlItems = layoutState.order.map((panelId, index) => ({
    id: panelId,
    label: panelDefinitionById[panelId].label,
    description: panelDefinitionById[panelId].description,
    hidden: layoutState.hidden.includes(panelId),
    canMoveUp: index > 0,
    canMoveDown: index < layoutState.order.length - 1,
  }));

  const panelContent: Record<SettingsPanelId, React.ReactNode> = {
    uiMode: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>UI Mode</div>
        <div className="small" style={{ marginBottom: 10 }}>
          Simple keeps the day-to-day workflow one-click. Advanced exposes every knob (routing, parameters, debugging).
        </div>
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <button className={mode === "simple" ? "" : "secondary"} onClick={() => setMode("simple")}>Simple</button>
          <button className={mode === "advanced" ? "" : "secondary"} onClick={() => setMode("advanced")}>Advanced</button>
          <div className="small" style={{ opacity: 0.8 }}>current: <b>{mode}</b></div>
        </div>
      </div>
    ),
    appearance: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Appearance</div>
        <div className="small" style={{ marginBottom: 10 }}>
          Theme changes are frontend-only. They do not affect Setup Wizard, backend spawning, model installs, render settings, or package outputs.
        </div>
        <div style={{ display: "grid", gap: 12 }}>
          <div>
            <div className="small" style={{ fontWeight: 800, marginBottom: 6 }}>Studio theme</div>
            <select value={theme} onChange={(event) => setTheme(event.target.value as any)}>
              {STUDIO_THEME_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            <div className="studio-themeSwatches" aria-hidden="true">
              {STUDIO_THEME_OPTIONS.map((option) => (
                <div
                  key={option.id}
                  className="studio-themeSwatch"
                  data-theme={option.id}
                  title={`${option.label}: ${option.description}`}
                />
              ))}
            </div>
          </div>
          <div className="small" style={{ opacity: 0.86 }}>
            Current phase: Dashboard, Projects, Settings, Models, Studio Forge, and the advanced workbench pages support modular section ordering and visibility. These controls only change local presentation, not runtime behavior.
          </div>
        </div>
      </div>
    ),
    renderDefaults: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Render defaults</div>
        <div className="small" style={{ marginBottom: 10 }}>
          Save a hardware-aware quick profile here and the Render page will pick it up automatically. This is the safest place to tune laptop vs workstation behavior without changing project content.
        </div>
        <div className="small" style={{ marginBottom: 10, opacity: 0.9 }}>
          Hardware: <b>{hardware?.hardware?.device_name || "unknown"}</b> • backend family <b>{hardware?.hardware?.backend_family || "cpu_only"}</b> • recommended tier <b>{hardware?.hardware?.recommended_tier || "draft"}</b>
        </div>
        {renderProfiles ? (
          <div style={{ display: "grid", gap: 10 }}>
            {Object.entries(renderProfiles.profiles || {}).map(([id, profile]: any) => (
              <div key={id} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontWeight: 800 }}>{profile.label} {renderProfiles.recommended_profile === id ? <span className="small" style={{ marginLeft: 6, opacity: 0.8 }}>(recommended)</span> : null}</div>
                    <div className="small" style={{ opacity: 0.85 }}>{profile.description}</div>
                    <div className="small" style={{ marginTop: 4, opacity: 0.82 }}>Preset <b>{profile.render_preset}</b> • internal tier <b>{profile.internal_render_tier}</b> • resume caches <b>{profile.resume_existing_frames ? "on" : "off"}</b></div>
                  </div>
                  <button className={savedRenderDefaults?.profileId === id ? "" : "secondary"} onClick={() => applyRenderProfile(id as any)}>Use on Render page</button>
                </div>
              </div>
            ))}
            <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <button className="secondary" onClick={resetRenderProfile}>Clear saved defaults</button>
              <div className="small" style={{ opacity: 0.82 }}>Current saved profile: <b>{savedRenderDefaults?.profileId || "none"}</b></div>
            </div>
          </div>
        ) : (
          <div className="small" style={{ opacity: 0.75 }}>Loading render profiles…</div>
        )}
      </div>
    ),
    systemReadiness: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ fontWeight: 800 }}>System readiness</div>
          <button
            className="secondary"
            onClick={() => {
              apiGet("/v1/system/readiness").then(setSystemReadiness).catch(() => {});
              apiGet("/v1/metrics/baseline").then(setBaselineMetrics).catch(() => {});
              apiGet("/health").then(setBackendHealth).catch(() => {});
              window.edmg?.getBuildIdentity?.().then(setBuildIdentity).catch(() => {});
            }}
          >
            Refresh
          </button>
        </div>
        <div className="small" style={{ marginBottom: 12, opacity: 0.9 }}>
          Shared health check for FFmpeg, the locked Python runtime, GPU acceleration, disk space, writable Studio paths, and the models directory.
        </div>
        <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12, marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div style={{ fontWeight: 800 }}>Build identity</div>
            <div className="small" style={{ opacity: 0.82 }}>
              {buildIdentity?.desktop?.packaged ? "Packaged desktop" : "Source / browser session"}
            </div>
          </div>
          <div className="small" style={{ display: "grid", gap: 5, marginTop: 8, opacity: 0.9 }}>
            <div aria-label="Desktop build version">
              Desktop <b>{buildIdentity?.desktop?.version || "unavailable"}</b>
              {buildIdentity?.desktop?.platform ? (
                <> • {buildIdentity.desktop.platform}/{buildIdentity.desktop.arch || "unknown"}</>
              ) : null}
              {buildIdentity?.desktop?.electronVersion ? (
                <> • Electron {buildIdentity.desktop.electronVersion}</>
              ) : null}
            </div>
            <div aria-label="Desktop executable location" style={{ wordBreak: "break-all" }}>
              Running from <code>{buildIdentity?.desktop?.executablePath || "unavailable"}</code>
            </div>
            <div aria-label="Backend build version">
              Backend <b>{backendHealth?.version || "unavailable"}</b>
              {(buildIdentity?.backendBundle?.acceleratorProfile || systemReadiness?.checks?.runtime?.accelerator_profile) ? (
                <> • profile <b>{buildIdentity?.backendBundle?.acceleratorProfile || systemReadiness?.checks?.runtime?.accelerator_profile}</b></>
              ) : null}
              {buildIdentity?.backendBundle?.pythonVersion ? (
                <> • Python {buildIdentity.backendBundle.pythonVersion}</>
              ) : null}
            </div>
            {buildIdentity?.backendBundle?.available ? (
              <>
                <div>
                  Provenance <b>verified installed backend + release manifest v{buildIdentity.backendBundle.schemaVersion || "unknown"}</b>
                  {typeof buildIdentity.backendBundle.sourceFileCount === "number" ? (
                    <> • {buildIdentity.backendBundle.sourceFileCount} source files</>
                  ) : null}
                </div>
                <details>
                  <summary style={{ cursor: "pointer", fontWeight: 700 }}>Show technical fingerprints</summary>
                  <div style={{ display: "grid", gap: 5, marginTop: 7 }}>
                    <div style={{ wordBreak: "break-all" }}>
                      Source fingerprint <code>{buildIdentity.backendBundle.sourceHash}</code>
                    </div>
                    {buildIdentity.backendBundle.binarySha256 ? (
                      <div style={{ wordBreak: "break-all" }}>
                        Backend binary <code>{buildIdentity.backendBundle.binarySha256}</code>
                      </div>
                    ) : null}
                    {buildIdentity.backendBundle.lockSha256 ? (
                      <div style={{ wordBreak: "break-all" }}>
                        Dependency lock <code>{buildIdentity.backendBundle.lockSha256}</code>
                      </div>
                    ) : null}
                  </div>
                </details>
              </>
            ) : (
              <div style={{ opacity: 0.78 }}>
                Immutable backend bundle provenance is available in packaged releases; this session is using source or browser runtime metadata.
              </div>
            )}
          </div>
        </div>
        {systemReadiness ? (
          <div style={{ display: "grid", gap: 10 }}>
            <div className="small">
              Overall:{" "}
              <b style={{ color: systemReadiness.status === "blocked" ? "#c44" : systemReadiness.status === "warn" ? "#c90" : "green" }}>
                {systemReadiness.summary || systemReadiness.status || "unknown"}
              </b>
              {systemReadiness.checked_at ? <span style={{ opacity: 0.75 }}> • checked {systemReadiness.checked_at}</span> : null}
            </div>
            {Object.entries(systemReadiness.checks || {}).map(([id, check]: any) => (
              <div key={id} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <div style={{ fontWeight: 800, textTransform: "capitalize" }}>{id.replaceAll("_", " ")}</div>
                  <b style={{ color: check?.status === "blocked" ? "#c44" : check?.status === "warn" ? "#c90" : "green" }}>
                    {String(check?.status || "unknown")}
                  </b>
                </div>
                <div className="small" style={{ marginTop: 6, opacity: 0.88 }}>
                  {id === "ffmpeg" ? (
                    <>
                      Path <code>{check?.path || "ffmpeg"}</code>
                      {check?.version ? <> • {check.version}</> : null}
                    </>
                  ) : null}
                  {id === "runtime" ? (
                    <>
                      Python <code>{check?.python_version || "unknown"}</code>
                      {check?.uv_version ? <> • uv <code>{check.uv_version}</code></> : null}
                      {check?.accelerator_profile ? <> • profile <b>{check.accelerator_profile}</b></> : null}
                      {check?.sync_health ? <> • sync <b>{check.sync_health}</b></> : null}
                      {check?.lock_sha256 ? <> • lock <code>{String(check.lock_sha256).slice(0, 12)}…</code></> : null}
                      {check?.immutable ? <> • bundled release manifest</> : null}
                    </>
                  ) : null}
                  {id === "gpu" ? (
                    <>
                      {check?.device_name || "CPU"} • backend <b>{check?.backend || "cpu"}</b>
                      {typeof check?.vram_gb === "number" ? <> • VRAM {check.vram_gb} GB</> : null}
                      {Array.isArray(check?.available_backends) ? <> • [{check.available_backends.join(", ")}]</> : null}
                    </>
                  ) : null}
                  {id === "disk" && Array.isArray(check?.paths) ? (
                    <>
                      {check.paths.map((entry: any) => (
                        <div key={`${entry.path}-${entry.volume_path}`}>
                          {entry.free_gb} GB free / {entry.total_gb} GB on <code>{entry.volume_path || entry.path}</code>
                        </div>
                      ))}
                    </>
                  ) : null}
                  {id === "writable_paths" && Array.isArray(check?.paths) ? (
                    <>
                      {check.paths.map((entry: any) => (
                        <div key={entry.path}>
                          <b>{entry.label}</b>: {entry.writable ? "writable" : "not writable"} • <code>{entry.path}</code>
                        </div>
                      ))}
                    </>
                  ) : null}
                  {id === "models" ? (
                    <>
                      <code>{check?.models_dir || "unknown"}</code>
                      {typeof check?.entry_count === "number" ? <> • {check.entry_count} entries</> : null}
                    </>
                  ) : null}
                </div>
                {check?.hint ? (
                  <div className="small" style={{ marginTop: 6, color: check?.status === "blocked" ? "#c44" : "#c90" }}>
                    Fix: {check.hint}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="small" style={{ opacity: 0.75 }}>Loading system readiness…</div>
        )}
        <div style={{ marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
          <div style={{ fontWeight: 800, marginBottom: 8 }}>Baseline metrics (read-only stub)</div>
          <div className="small" style={{ marginBottom: 10, opacity: 0.88 }}>
            Advisory launch, project, timeline, analysis, and render-plan budgets until W7-04 named-hardware evidence lands.
          </div>
          {baselineMetrics ? (
            <div style={{ display: "grid", gap: 8 }}>
              {baselineMetrics.note ? (
                <div className="small" style={{ opacity: 0.82 }}>{baselineMetrics.note}</div>
              ) : null}
              {baselineMetrics.hardware ? (
                <div className="small">
                  Host <code>{String(baselineMetrics.hardware.host || "unknown")}</code>
                  {baselineMetrics.hardware.device_name ? (
                    <> • GPU <b>{String(baselineMetrics.hardware.device_name)}</b></>
                  ) : null}
                  {baselineMetrics.collected_at ? (
                    <span style={{ opacity: 0.75 }}> • collected {baselineMetrics.collected_at}</span>
                  ) : null}
                </div>
              ) : null}
              {Object.entries(baselineMetrics.samples || {}).map(([operation, sample]: any) => (
                <div key={operation} style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 10 }}>
                  <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                    <div style={{ fontWeight: 700 }}>{operation.replaceAll("_", " ")}</div>
                    <div className="small">
                      {sample?.count ? (
                        <>
                          last <b>{sample.last_ms} ms</b>
                          {typeof sample.budget_ms === "number" ? (
                            <> / budget {sample.budget_ms} ms</>
                          ) : null}
                          {typeof sample.within_budget === "boolean" ? (
                            <> • <b style={{ color: sample.within_budget ? "green" : "#c90" }}>
                              {sample.within_budget ? "within budget" : "over budget"}
                            </b></>
                          ) : null}
                        </>
                      ) : (
                        <>no samples yet{typeof sample?.budget_ms === "number" ? ` • budget ${sample.budget_ms} ms` : ""}</>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="small" style={{ opacity: 0.75 }}>Loading baseline metrics…</div>
          )}
        </div>
      </div>
    ),
    desktopBackend: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Desktop Backend</div>
        <div className="small" style={{ marginBottom: 10 }}>
          Choose whether Studio should launch and own its local backend or just connect the GUI to an already running backend. This keeps Windows-first packaging intact while making Ubuntu and Linux desktop installs first-class.
        </div>
        <div className="small" style={{ marginBottom: 12, opacity: 0.85 }}>
          Saved startup config: <b>{backendSettingsLoaded ? `${studioBackendSettings.mode} (${buildBackendUrl(studioBackendSettings)})` : "loading"}</b>
          {studioBackendSettings.source ? <span> • source <b>{studioBackendSettings.source}</b></span> : null}
        </div>
        <div className="small" style={{ marginBottom: 12, opacity: 0.82 }}>
          Live runtime target: <b>{liveBackendUrl || props.backendUrl || buildBackendUrl(backendDraft)}</b>
          {" "}• health{" "}
          <b>
            {backendReachable == null ? "checking" : backendReachable ? "reachable" : "unreachable"}
          </b>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <div>
            <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Mode</div>
            <select
              aria-label="Desktop backend mode"
              value={backendDraft.mode}
              onChange={(e) => updateBackendDraft({ mode: e.target.value })}
            >
              <option value="managed">Managed local backend</option>
              <option value="external">Connect to existing backend</option>
            </select>
          </div>

          {backendDraft.mode === "external" ? (
            <div>
              <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Desktop backend URL</div>
              <input
                aria-label="Desktop backend URL"
                value={backendDraft.url}
                onChange={(e) => updateBackendDraft({ url: e.target.value })}
                placeholder="https://edmg-backend.example.com"
              />
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
              <div>
                <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Backend host</div>
                <input
                  aria-label="Desktop backend host"
                  value={backendDraft.host}
                  onChange={(e) => updateBackendDraft({ host: e.target.value })}
                  placeholder="127.0.0.1"
                />
              </div>
              <div>
                <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Backend port</div>
                <input
                  aria-label="Desktop backend port"
                  inputMode="numeric"
                  value={backendDraft.port}
                  onChange={(e) => updateBackendDraft({ port: e.target.value })}
                  placeholder="7863"
                />
              </div>
            </div>
          )}

          <div className="small" style={{ opacity: 0.82 }}>
            Ubuntu/Linux desktop note: managed mode keeps the full GUI and bundled startup flow, while external mode is for cases where you want the desktop app to attach to a separately launched backend over `http://` or `https://`.
          </div>

          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button disabled={savingBackend || !backendSettingsDirty} onClick={saveBackendSettings}>
              {savingBackend ? "Saving…" : canPersistBackendSettings ? "Save backend startup settings" : "Use backend now"}
            </button>
            {backendRestartRequired && window.edmg?.relaunch ? (
              <button className="secondary" disabled={savingBackend} onClick={() => { void window.edmg?.relaunch?.(); }}>
                Restart now
              </button>
            ) : null}
            {backendNotice ? <div className="small" style={{ opacity: 0.84 }}>{backendNotice}</div> : null}
          </div>
          <BackendSecurityPanel backendUrl={liveBackendUrl || props.backendUrl || buildBackendUrl(backendDraft)} />
        </div>
      </div>
    ),
    aiProvider: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>AI Provider</div>
        <div className="small" style={{ marginBottom: 10 }}>
          These are Studio startup settings for planning and prompt generation. Save them here, then restart Studio so the backend relaunches on the selected provider.
        </div>
        <div className="small" style={{ marginBottom: 12, opacity: 0.85 }}>
          Saved startup config: <b>{aiSettingsLoaded ? `${aiDraft.mode === "http" ? "remote_ai_service" : aiDraft.provider}` : "loading"}</b>
          {studioAiSettings.source ? <span> • source <b>{studioAiSettings.source}</b></span> : null}
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <div>
            <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Mode</div>
            <select value={aiDraft.mode} onChange={(e) => updateAiDraft({ mode: e.target.value })}>
              <option value="local">Local provider inside Studio backend</option>
              <option value="http">Remote AI service over HTTP</option>
            </select>
          </div>

          {aiDraft.mode === "local" ? (
            <>
              <div>
                <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Local provider</div>
                <select value={aiDraft.provider} onChange={(e) => updateAiDraft({ provider: e.target.value })}>
                  <option value="nemotron_cloud">Nemotron Ultra (NVIDIA Cloud) ★ default</option>
                  <option value="ollama">Ollama (local)</option>
                  <option value="openai_compat">OpenAI-compatible endpoint</option>
                  <option value="rule_based">Rule-based fallback (no AI)</option>
                </select>
              </div>

              {aiDraft.provider === "nemotron_cloud" ? (
                <>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>NVIDIA NIM base URL</div>
                    <input
                      value={aiDraft.nvidiaBaseUrl || NVIDIA_NIM_BASE_URL}
                      onChange={(e) => updateAiDraft({ nvidiaBaseUrl: e.target.value })}
                      placeholder={NVIDIA_NIM_BASE_URL}
                    />
                  </div>
                  <label>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>NVIDIA prompt model preset</div>
                    <select
                      aria-label="NVIDIA prompt model preset"
                      value={selectedNvidiaPromptPreset}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value === "custom") return;
                        updateAiDraft({ nvidiaModel: value });
                      }}
                    >
                      {nvidiaPromptModelPresets.map((preset) => (
                        <option key={preset.model} value={preset.model}>{preset.label}</option>
                      ))}
                      <option value="custom">Custom NVIDIA/OpenAI-compatible model</option>
                    </select>
                  </label>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Model</div>
                    <input
                      aria-label="NVIDIA prompt model"
                      value={aiDraft.nvidiaModel || NEMOTRON_ULTRA_MODEL}
                      onChange={(e) => updateAiDraft({ nvidiaModel: e.target.value })}
                      placeholder={NEMOTRON_ULTRA_MODEL}
                    />
                  </div>
                  {selectedNvidiaModelFamily === "diffusiongemma" ? (
                    <div className="small" style={{ opacity: 0.82 }}>
                      DiffusionGemma is for planning and prompt text. It can speed prompt refinement on NVIDIA NIM or vLLM endpoints, but internal video still uses the selected renderer path.
                    </div>
                  ) : selectedNvidiaPromptModel?.description ? (
                    <div className="small" style={{ opacity: 0.82 }}>
                      {selectedNvidiaPromptModel.description}
                    </div>
                  ) : null}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8, alignItems: "center" }}>
                    <div>
                      <div className="small" style={{ fontWeight: 800 }}>NVIDIA API key</div>
                      <div className="small" style={{ opacity: 0.8 }}>
                        Get a free key at <a href="https://build.nvidia.com" target="_blank" rel="noreferrer">build.nvidia.com</a>. Required for cloud planning.
                      </div>
                      <input
                        type="password"
                        value={nvidiaApiKey}
                        onChange={(e) => setNvidiaApiKey(e.target.value)}
                        placeholder={secrets?.has_nvidia_api_key ? "(set) paste to replace" : "nvapi-…"}
                      />
                    </div>
                    <button disabled={saving || !nvidiaApiKey} onClick={() => saveSecret("nvidia_api_key", nvidiaApiKey)}>Save</button>
                    <button className="secondary" disabled={saving || !secrets?.has_nvidia_api_key} onClick={() => clearSecret("nvidia_api_key")}>Clear</button>
                  </div>
                  {!secrets?.has_nvidia_api_key && (
                    <div className="small" style={{ marginTop: 6, padding: "6px 10px", borderRadius: 6, background: "var(--warning-bg, #fff3cd)", color: "var(--warning-text, #856404)", border: "1px solid var(--warning-border, #ffc107)" }}>
                      ⚠ No NVIDIA API key saved — planning will fall back to rule-based mode until you save one above.
                    </div>
                  )}
                  <div className="small" style={{ opacity: 0.82 }}>
                    Uses NVIDIA's OpenAI-compatible API path for Studio planning and prompt generation. NVIDIA Studio Driver updates can help local CUDA/NIM/vLLM runtime behavior, but this setting is still a text-planning model, not a video renderer.
                  </div>
                </>
              ) : null}

              {aiDraft.provider === "ollama" ? (
                <>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Ollama URL</div>
                    <input value={aiDraft.ollamaUrl} onChange={(e) => updateAiDraft({ ollamaUrl: e.target.value })} placeholder="http://127.0.0.1:11434" />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Ollama model</div>
                    <input value={aiDraft.ollamaModel} onChange={(e) => updateAiDraft({ ollamaModel: e.target.value })} placeholder="qwen3:8b" />
                  </div>
                  <div className="small" style={{ opacity: 0.82 }}>
                    Recommended local planning default. Use <code>qwen3:4b</code> on lighter CPU-only or low-memory systems.
                  </div>
                </>
              ) : null}

              {aiDraft.provider === "openai_compat" ? (
                <>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>OpenAI-compatible base URL</div>
                    <input value={aiDraft.openaiCompatBaseUrl} onChange={(e) => updateAiDraft({ openaiCompatBaseUrl: e.target.value })} placeholder={NVIDIA_NIM_BASE_URL} />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Model</div>
                    <input value={aiDraft.openaiCompatModel} onChange={(e) => updateAiDraft({ openaiCompatModel: e.target.value })} placeholder={NEMOTRON_ULTRA_MODEL} />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8, alignItems: "center" }}>
                    <div>
                      <div className="small" style={{ fontWeight: 800 }}>API key</div>
                      <div className="small" style={{ opacity: 0.8 }}>
                        Optional for local tools like LM Studio. Required for hosted providers that expect bearer auth.
                      </div>
                      <input
                        value={openaiCompatApiKey}
                        onChange={(e) => setOpenaiCompatApiKey(e.target.value)}
                        placeholder={secrets?.has_openai_compat_api_key ? "(set) paste to replace" : "paste API key if needed"}
                      />
                    </div>
                    <button disabled={saving || !openaiCompatApiKey} onClick={() => saveSecret("openai_compat_api_key", openaiCompatApiKey)}>Save</button>
                    <button className="secondary" disabled={saving || !secrets?.has_openai_compat_api_key} onClick={() => clearSecret("openai_compat_api_key")}>Clear</button>
                  </div>
                  <div className="small" style={{ opacity: 0.82 }}>
                    Defaults to NVIDIA&apos;s OpenAI-compatible API. Use this for hosted gateways, self-hosted vLLM/TGI adapters, or local tools that expose <code>/v1/chat/completions</code>.
                  </div>
                </>
              ) : null}

              {aiDraft.provider === "rule_based" ? (
                <div className="small" style={{ opacity: 0.82 }}>
                  Dependency-free fallback. No external AI service is required, but planning quality will be simpler and more deterministic.
                </div>
              ) : null}
            </>
          ) : (
            <>
              <div>
                <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Remote AI service base URL</div>
                <input value={aiDraft.aiBaseUrl} onChange={(e) => updateAiDraft({ aiBaseUrl: e.target.value })} placeholder="http://127.0.0.1:7862" />
              </div>
              <div className="small" style={{ opacity: 0.82 }}>
                Use this when you want Studio to call a separate EDMG AI service over HTTP instead of running the local planner/provider path inside the Studio backend.
              </div>
            </>
          )}

          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button disabled={savingAi || !aiSettingsDirty || !window.edmg?.setAiSettings} onClick={saveAiSettings}>Save AI startup settings</button>
            {aiRestartRequired && window.edmg?.relaunch ? (
              <button className="secondary" disabled={savingAi} onClick={() => { void window.edmg?.relaunch?.(); }}>Restart now</button>
            ) : null}
            {aiNotice ? <div className="small" style={{ opacity: 0.84 }}>{aiNotice}</div> : null}
          </div>
        </div>
      </div>
    ),
    transcription: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Transcription</div>
        <div className="small" style={{ marginBottom: 12, opacity: 0.86 }}>
          Active backend ASR: <b>{transcriptionStatus?.active?.provider || transcriptionDraft.provider}</b>
          {" "}• model <b>{transcriptionStatus?.active?.model || transcriptionDraft.model}</b>
          {" "}• device <b>{transcriptionStatus?.active?.device || transcriptionDraft.device}</b>
          {" "}• vocals <b>{transcriptionStatus?.active?.separate_vocals ? "Demucs" : "off"}</b>
        </div>
        <div className="small" style={{ marginBottom: 12, opacity: 0.82 }}>
          Parakeet dependencies: <b>{transcriptionStatus?.dependencies?.parakeet_available ? "ready" : "missing"}</b>
          {" "}• faster-whisper: <b>{transcriptionStatus?.dependencies?.faster_whisper_available ? "ready" : "missing"}</b>
          {" "}• Demucs: <b>{transcriptionStatus?.dependencies?.demucs_available ? "ready" : "missing"}</b>
          {" "}• backend GPU <b>{transcriptionStatus?.hardware?.device_name || hardware?.hardware?.device_name || "unknown"}</b>
        </div>
        {transcriptionStatus?.acceleration ? (
          <div className="small" style={{ marginBottom: 12, opacity: 0.82 }}>
            ASR acceleration: <b>{transcriptionStatus.acceleration.asr_runtime || "auto"}</b>
            {" "}• TensorRT image bundle applies to ASR <b>{transcriptionStatus.acceleration.tensorrt_image_bundle_applicable ? "yes" : "no"}</b>
            {" "}• {transcriptionStatus.acceleration.tensorrt_note}
          </div>
        ) : null}

        <div style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            <div>
              <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>ASR provider</div>
              <select
                aria-label="ASR provider"
                value={transcriptionDraft.provider}
                onChange={(e) => updateTranscriptionDraft({ provider: e.target.value })}
              >
                <option value="faster_whisper">faster-whisper (local, CPU/GPU)</option>
                <option value="parakeet">NVIDIA Parakeet (local, requires NeMo)</option>
                <option value="parakeet_nim">
                  NVIDIA Parakeet NIM ☁ (cloud, uses NVIDIA API key)
                </option>
              </select>
              {transcriptionDraft.provider === "parakeet_nim" && !transcriptionStatus?.parakeet_nim_api_key_configured && (
                <div className="small" style={{ marginTop: 4, color: "var(--danger,#dc2626)" }}>
                  ⚠ No NVIDIA API key. Add it in AI Provider → NVIDIA API key (same key as Nemotron/Cosmos).
                </div>
              )}
              {transcriptionDraft.provider === "parakeet_nim" && transcriptionStatus?.parakeet_nim_ready && (
                <div className="small" style={{ marginTop: 4, color: "green" }}>
                  ✓ Ready — cloud ASR, no local GPU or NeMo install needed.
                </div>
              )}
            </div>

            <div>
              <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>ASR model</div>
              <select
                aria-label="ASR model"
                value={transcriptionDraft.model}
                onChange={(e) => updateTranscriptionDraft({ model: e.target.value })}
              >
                {transcriptionDraft.provider === "parakeet_nim" ? (
                  <>
                    <option value="parakeet-ctc-1.1b-asr">Parakeet CTC 1.1B (best accuracy)</option>
                    <option value="parakeet-tdt-0.6b-v2">Parakeet TDT 0.6B v2 (fast + timestamps)</option>
                    <option value="parakeet-ctc-0.6b-asr">Parakeet CTC 0.6B (fastest)</option>
                  </>
                ) : transcriptionDraft.provider === "parakeet" ? (
                  <>
                    <option value="nvidia/parakeet-tdt-0.6b-v3">Parakeet TDT 0.6B v3</option>
                    <option value="nvidia/parakeet-tdt-0.6b-v2">Parakeet TDT 0.6B v2</option>
                  </>
                ) : (
                  <>
                    <option value="turbo">Whisper large-v3-turbo</option>
                    <option value="large-v3">Whisper large-v3</option>
                    <option value="medium">Whisper medium</option>
                    <option value="small">Whisper small</option>
                  </>
                )}
              </select>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            <div>
              <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>ASR device</div>
              <select
                aria-label="ASR device"
                value={transcriptionDraft.device}
                onChange={(e) => updateTranscriptionDraft({ device: e.target.value })}
              >
                <option value="auto">auto</option>
                <option value="cuda">cuda</option>
                <option value="cpu">cpu</option>
              </select>
            </div>
            <div>
              <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Whisper compute</div>
              <select
                aria-label="ASR compute type"
                value={transcriptionDraft.compute_type}
                onChange={(e) => updateTranscriptionDraft({ compute_type: e.target.value })}
                disabled={transcriptionDraft.provider === "parakeet"}
              >
                <option value="auto">auto</option>
                <option value="float16">float16</option>
                <option value="int8">int8</option>
                <option value="int8_float16">int8_float16</option>
              </select>
            </div>
          </div>

          {transcriptionDraft.provider === "parakeet" ? (
            <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                style={{ width: "auto" }}
                checked={!!transcriptionDraft.fallback_to_whisper}
                onChange={(e) => updateTranscriptionDraft({ fallback_to_whisper: e.target.checked })}
              />
              Fall back to faster-whisper if Parakeet is unavailable
            </label>
          ) : null}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
            <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                style={{ width: "auto" }}
                checked={!!transcriptionDraft.separate_vocals}
                onChange={(e) => updateTranscriptionDraft({ separate_vocals: e.target.checked })}
              />
              Separate vocals before transcription
            </label>
            <div>
              <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Vocal separation model</div>
              <select
                aria-label="Vocal separation model"
                value={transcriptionDraft.separation_model}
                onChange={(e) => updateTranscriptionDraft({ separation_model: e.target.value })}
                disabled={!transcriptionDraft.separate_vocals}
              >
                <option value="htdemucs">Hybrid Transformer Demucs</option>
                <option value="htdemucs_ft">Hybrid Transformer Demucs fine-tuned</option>
              </select>
            </div>
          </div>

          {!transcriptionStatus?.dependencies?.parakeet_available ? (
            <div className="small" style={{ opacity: 0.82 }}>
              Parakeet: <code>uv sync --frozen --extra PROFILE --extra parakeet</code> from <code>python_backend</code>.
            </div>
          ) : null}

          {transcriptionDraft.separate_vocals && !transcriptionStatus?.dependencies?.demucs_available ? (
            <div className="small" style={{ opacity: 0.82 }}>
              Vocal separation: <code>uv sync --frozen --extra PROFILE --extra source-separation</code> from <code>python_backend</code>.
            </div>
          ) : null}

          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button disabled={savingTranscription} onClick={saveTranscriptionSettings}>
              {savingTranscription ? "Saving…" : "Save transcription settings"}
            </button>
          </div>
        </div>
      </div>
    ),
    backendConfig: cfg ? (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Backend Configuration</div>
        <div style={{ display: "grid", gap: 10 }}>
          {[
            ["Backend host", cfg.backend_host],
            ["Backend port", cfg.backend_port],
            ["Backend URL", cfg.backend_url],
            ["AI mode", cfg.ai_mode],
            ["AI provider", cfg.ai_provider],
            ["AI model", cfg.ai_nvidia_model ?? cfg.ai_openai_compat_model ?? cfg.ai_ollama_model],
            ["AI model family", cfg.ai_nvidia_model_family],
            ["ComfyUI URL", cfg.comfyui_url],
            ["Studio home", cfg.studio_home],
            ["Data dir", cfg.data_dir],
            ["Models dir", cfg.models_dir],
          ].map(([label, value]) => value != null ? (
            <div key={String(label)} className="small" style={{ display: "flex", gap: 10 }}>
              <span style={{ opacity: 0.7, minWidth: 130 }}>{label}</span>
              <code style={{ wordBreak: "break-all" }}>{String(value)}</code>
            </div>
          ) : null)}
        </div>
        <details style={{ marginTop: 12 }}>
          <summary className="small" style={{ cursor: "pointer", opacity: 0.7 }}>Show full JSON</summary>
          <pre style={{ marginTop: 8, fontSize: 11, overflow: "auto", maxHeight: 300 }}>{JSON.stringify(cfg, null, 2)}</pre>
        </details>
      </div>
    ) : null,
    liveAiStatus: aiStatus ? (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Live Backend AI Status</div>
        <div className="small" style={{ marginBottom: 10 }}>
          This is the provider the backend is using right now. If it differs from the saved startup config above, restart Studio to apply your latest change.
        </div>
        {aiStatus?.ai_config?.warning && (
          <div className="small" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 8, background: "var(--warning-bg, #fff3cd)", color: "var(--warning-text, #856404)", border: "1px solid var(--warning-border, #ffc107)" }}>
            ⚠ {aiStatus.ai_config.warning}
          </div>
        )}
        <div style={{ display: "grid", gap: 6 }}>
          {[
            ["Provider", aiStatus?.ai_config?.provider],
            ["Label", aiStatus?.ai_config?.label],
            ["Model", aiStatus?.ai_config?.model],
            ["Model family", aiStatus?.ai_config?.model_family],
            ["Base URL", aiStatus?.ai_config?.base_url],
            ["NVIDIA key", aiStatus?.ai_config?.nvidia_api_key_configured != null
              ? (aiStatus.ai_config.nvidia_api_key_configured ? "configured" : "not set")
              : undefined],
            ["Mode", aiStatus?.ai_config?.mode],
            ["Hint", aiStatus?.ai_config?.hint],
          ].map(([label, value]) => value != null ? (
            <div key={String(label)} className="small" style={{ display: "flex", gap: 10 }}>
              <span style={{ opacity: 0.7, minWidth: 100 }}>{label}</span>
              <span style={{ wordBreak: "break-all" }}>{String(value)}</span>
            </div>
          ) : null)}
        </div>
        <details style={{ marginTop: 10 }}>
          <summary className="small" style={{ cursor: "pointer", opacity: 0.7 }}>Show full JSON</summary>
          <pre style={{ marginTop: 6, fontSize: 11, overflow: "auto", maxHeight: 260 }}>{JSON.stringify(aiStatus, null, 2)}</pre>
        </details>
      </div>
    ) : null,
    tokens: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Tokens</div>
        <div className="small" style={{ marginBottom: 10 }}>
          Optional. Used for gated Hugging Face downloads and some Civitai downloads. Studio checks explicit HF environment tokens, your local <code>hf auth login</code> session, then this saved token. Saved tokens are stored in OS keychain when available; otherwise stored locally under the Studio data directory.
        </div>
        {secrets ? (
          <div className="small" style={{ marginBottom: 10, opacity: 0.9 }}>
            Storage: <b>{secrets.store}</b>
            {secrets.note ? <span style={{ marginLeft: 10, opacity: 0.85 }}>{secrets.note}</span> : null}
            <span style={{ marginLeft: 10, opacity: 0.85 }}>
              HF auth: <b>{secrets.hf_auth_available ? (secrets.hf_auth_token_source || "available") : "not found"}</b>
              {secrets.hf_cli_available ? <> · CLI: <code>{secrets.hf_login_command || "hf auth login"}</code></> : " · CLI: hf not found"}
            </span>
          </div>
        ) : (
          <div className="small" style={{ marginBottom: 10, opacity: 0.75 }}>Loading token status…</div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8, alignItems: "center" }}>
          <div>
            <div className="small" style={{ fontWeight: 800 }}>Hugging Face token</div>
            <div className="small" style={{ opacity: 0.8 }}>Manual fallback for gated HF models/checkpoints when the backend is not logged in with <code>hf auth login</code>.</div>
            <input
              value={hfToken}
              onChange={(e) => setHfToken(e.target.value)}
              placeholder={secrets?.has_hf_token ? "(set) paste to replace" : "paste token"}
            />
          </div>
          <button disabled={saving || !hfToken} onClick={() => saveSecret("hf_token", hfToken)}>Save</button>
          <button className="secondary" disabled={saving || !secrets?.has_hf_token} onClick={() => clearSecret("hf_token")}>Clear</button>

          <div>
            <div className="small" style={{ fontWeight: 800 }}>Civitai API key</div>
            <div className="small" style={{ opacity: 0.8 }}>Used for some Civitai imports/downloads.</div>
            <input
              value={civitaiKey}
              onChange={(e) => setCivitaiKey(e.target.value)}
              placeholder={secrets?.has_civitai_api_key ? "(set) paste to replace" : "paste API key"}
            />
          </div>
          <button disabled={saving || !civitaiKey} onClick={() => saveSecret("civitai_api_key", civitaiKey)}>Save</button>
          <button className="secondary" disabled={saving || !secrets?.has_civitai_api_key} onClick={() => clearSecret("civitai_api_key")}>Clear</button>

          <div>
            <div className="small" style={{ fontWeight: 800 }}>Stability API key</div>
            <div className="small" style={{ opacity: 0.8 }}>Used for the hosted Stability keyframe fallback inside Studio&apos;s internal video renderer.</div>
            <input
              value={stabilityApiKey}
              onChange={(e) => setStabilityApiKey(e.target.value)}
              placeholder={secrets?.has_stability_api_key ? "(set) paste to replace" : "paste Stability API key"}
            />
          </div>
          <button disabled={saving || !stabilityApiKey} onClick={() => saveSecret("stability_api_key", stabilityApiKey)}>Save</button>
          <button className="secondary" disabled={saving || !secrets?.has_stability_api_key} onClick={() => clearSecret("stability_api_key")}>Clear</button>

          <div>
            <div className="small" style={{ fontWeight: 800 }}>ImagineArt API key</div>
            <div className="small" style={{ opacity: 0.8 }}>Used for hosted ImagineArt stills and optional native video clips (same API as the ImagineArt MCP server).</div>
            <input
              value={imagineartApiKey}
              onChange={(e) => setImagineartApiKey(e.target.value)}
              placeholder={renderProviders?.imagineart?.has_api_key ? "(set) paste to replace" : "paste ImagineArt API key"}
            />
          </div>
          <button disabled={saving || !imagineartApiKey} onClick={() => saveSecret("imagineart_api_key", imagineartApiKey)}>Save</button>
          <button className="secondary" disabled={saving || !renderProviders?.imagineart?.has_api_key} onClick={() => clearSecret("imagineart_api_key")}>Clear</button>

          <div>
            <div className="small" style={{ fontWeight: 800 }}>Azure AI Foundry API key</div>
            <div className="small" style={{ opacity: 0.8 }}>Key for your Azure AI Foundry managed-compute deployment (Cosmos3-Super hosted endpoint).</div>
            <input
              value={azureFoundryApiKey}
              onChange={(e) => setAzureFoundryApiKey(e.target.value)}
              placeholder={renderProviders?.azure_foundry?.has_api_key ? "(set) paste to replace" : "paste Azure AI Foundry API key"}
            />
          </div>
          <button disabled={saving || !azureFoundryApiKey} onClick={() => saveSecret("azure_foundry_api_key", azureFoundryApiKey)}>Save</button>
          <button className="secondary" disabled={saving || !renderProviders?.azure_foundry?.has_api_key} onClick={() => clearSecret("azure_foundry_api_key")}>Clear</button>
        </div>
      </div>
    ),
    renderRuntime: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>GPU / Render Runtime</div>
        <div className="small" style={{ marginBottom: 10 }}>
          Controls for NVIDIA CUDA GPU acceleration, Stability hosted keyframes, and AMD DirectML. These affect the internal render pipeline — not the AI planning provider above.
        </div>
        {!renderProviders || !renderProviderDraft ? (
          <div className="small" style={{ opacity: 0.75 }}>Loading render provider settings…</div>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>

            {/* ── Video Generation Route ────────────────────────────────── */}
            <div style={{ border: "2px solid var(--accent, #3b82f6)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800, marginBottom: 6 }}>Video Generation — GPU vs Cloud</div>
              {videoRoute && (
                <div className="small" style={{ marginBottom: 10, padding: "6px 10px", borderRadius: 6,
                  background: videoRoute.route === "none" ? "var(--warning-bg,#fff3cd)" : "var(--success-bg,#d1fae5)",
                  color: videoRoute.route === "none" ? "var(--warning-text,#856404)" : "var(--success-text,#065f46)" }}>
                  <b>Active route:</b> {videoRoute.route === "local_gpu" ? "🖥 Local GPU" : videoRoute.route === "cosmos_cloud" ? "☁ NVIDIA Cosmos Cloud" : videoRoute.route === "azure_foundry_cloud" ? "☁ Azure AI Foundry Cosmos3" : "⚠ None available"}
                  {" "}— {videoRoute.reason}
                  {videoRoute.fallback_available ? <span style={{ opacity: 0.8 }}> (Cosmos fallback available)</span> : null}
                </div>
              )}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Preference</div>
                  <select
                    value={renderProviderDraft?.video?.preference || "auto"}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), video: { ...(c?.video || {}), preference: e.target.value },
                    }))}
                  >
                    <option value="auto">Auto (smart routing)</option>
                    <option value="local_gpu">Always use Local GPU</option>
                    <option value="cosmos_cloud">Always use NVIDIA Cosmos Cloud</option>
                    <option value="azure_foundry_cloud">Always use Azure AI Foundry Cosmos3</option>
                    <option value="imagineart_cloud">Always use ImagineArt Cloud</option>
                    <option value="comfyui">Always use ComfyUI</option>
                  </select>
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input type="checkbox"
                      checked={!!renderProviderDraft?.video?.auto_prefer_gpu}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), video: { ...(c?.video || {}), auto_prefer_gpu: e.target.checked },
                      }))}
                    />
                    Auto: prefer GPU when available
                  </label>
                  <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input type="checkbox"
                      checked={!!renderProviderDraft?.video?.cosmos_fallback}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), video: { ...(c?.video || {}), cosmos_fallback: e.target.checked },
                      }))}
                    />
                    Fall back to Cosmos if GPU render fails
                  </label>
                  <div className="small">
                    Synthetic proxy rendering is disabled. Studio blocks the render when no genuine local model or authenticated hosted provider can serve it.
                  </div>
                </div>
              </div>
              <div className="small" style={{ marginTop: 10, opacity: 0.8 }}>
                Local GPU: {videoRoute?.local_ready ? <b style={{color:"green"}}>ready — {videoRoute?.local_detail?.device} ({videoRoute?.local_detail?.vram_gb} GB)</b> : <b style={{color:"#888"}}>not available</b>}
                {" "}• Cosmos Cloud: {videoRoute?.cosmos_ready ? <b style={{color:"green"}}>configured</b> : <b style={{color:"#888"}}>not configured (add NVIDIA API key)</b>}
                {" "}• Azure Foundry: {videoRoute?.azure_foundry_ready ? <b style={{color:"green"}}>configured</b> : <b style={{color:"#888"}}>not configured (add Azure AI Foundry API key)</b>}
              </div>
            </div>

            {/* ── NVIDIA CUDA ───────────────────────────────────────────── */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800 }}>NVIDIA CUDA GPU</div>
              <div className="small" style={{ marginTop: 6, opacity: 0.86 }}>
                GPU detected: <b>{renderProviders?.cuda?.device_name || "none"}</b>
                {renderProviders?.cuda?.vram_gb ? <> • <b>{renderProviders.cuda.vram_gb} GB</b> VRAM</> : null}
                {" "}• runtime ready: <b>{renderProviders?.cuda?.available ? "yes" : "no"}</b>
                {" "}• active: <b>{renderProviders?.cuda?.active ? "yes" : "no"}</b>
              </div>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.cuda?.enabled}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cuda: { ...(c?.cuda || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable CUDA GPU acceleration for internal renders
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.cuda?.allow_auto_selection}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cuda: { ...(c?.cuda || {}), allow_auto_selection: e.target.checked },
                    }))}
                  />
                  Let Studio auto-select CUDA when available
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.cuda?.enable_tf32}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cuda: { ...(c?.cuda || {}), enable_tf32: e.target.checked },
                    }))}
                  />
                  Enable TF32 / cuDNN benchmark (faster on Ampere+ GPUs)
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.cuda?.optimize_comfyui}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cuda: { ...(c?.cuda || {}), optimize_comfyui: e.target.checked },
                    }))}
                  />
                  Optimize ComfyUI for CUDA (cuda-malloc, cross-attention, CUDNN env vars)
                </label>
                <div style={{ maxWidth: 340 }}>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Preferred CUDA internal model</div>
                  <select
                    value={renderProviderDraft?.cuda?.preferred_model || "auto"}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cuda: { ...(c?.cuda || {}), preferred_model: e.target.value },
                    }))}
                  >
                    <option value="auto">auto (pick by VRAM)</option>
                    <option value="hf_sd35_medium_internal">SD 3.5 Medium (requires ≥ 14 GB VRAM)</option>
                    <option value="hf_sdxl_internal">SDXL (requires ≥ 6 GB VRAM)</option>
                    <option value="hf_sd15_internal">SD 1.5 (works on 4 GB+)</option>
                  </select>
                </div>
                {!renderProviders?.cuda?.available && (
                  <div className="small" style={{ opacity: 0.8, color: "var(--danger)" }}>
                    CUDA not detected. Install CUDA-enabled PyTorch via Setup → Install Backend Runtime (NVIDIA CUDA).
                  </div>
                )}
              </div>
            </div>

            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800 }}>Stability hosted fallback</div>
              <div className="small" style={{ marginTop: 6, opacity: 0.86 }}>
                API key saved: <b>{renderProviders?.stability?.has_api_key ? "yes" : "no"}</b>
                {" "}• active in Render/Models: <b>{renderProviders?.stability?.visible ? "yes" : "no"}</b>
                {" "}• service: <b>{renderProviderDraft?.stability?.service || "sd3"}</b>
              </div>
              <div className="small" style={{ marginTop: 4, opacity: 0.82 }}>
                {renderProviders?.stability?.note}
              </div>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.stability?.enabled}
                    onChange={(e) => setRenderProviderDraft((current: any) => ({
                      ...(current || {}),
                      stability: { ...(current?.stability || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable Stability hosted fallback
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.stability?.allow_auto_fallback}
                    onChange={(e) => setRenderProviderDraft((current: any) => ({
                      ...(current || {}),
                      stability: { ...(current?.stability || {}), allow_auto_fallback: e.target.checked },
                    }))}
                  />
                  Allow automatic fallback when local internal diffusion is unavailable
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Service</div>
                    <select
                      value={renderProviderDraft?.stability?.service || "sd3"}
                      onChange={(e) => setRenderProviderDraft((current: any) => ({
                        ...(current || {}),
                        stability: { ...(current?.stability || {}), service: e.target.value },
                      }))}
                    >
                      {(renderProviders?.stability_services || []).map((item: string) => (
                        <option key={item} value={item}>{item}</option>
                      ))}
                    </select>
                  </div>
                  {(renderProviderDraft?.stability?.service || "sd3") === "sd3" ? (
                    <div>
                      <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>SD3 model</div>
                      <select
                        value={renderProviderDraft?.stability?.model || "sd3.5-large-turbo"}
                        onChange={(e) => setRenderProviderDraft((current: any) => ({
                          ...(current || {}),
                          stability: { ...(current?.stability || {}), model: e.target.value },
                        }))}
                      >
                        {(renderProviders?.stability_models || []).map((item: string) => (
                          <option key={item} value={item}>{item}</option>
                        ))}
                      </select>
                    </div>
                  ) : null}
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Style preset</div>
                    <select
                      value={renderProviderDraft?.stability?.style_preset || "none"}
                      onChange={(e) => setRenderProviderDraft((current: any) => ({
                        ...(current || {}),
                        stability: { ...(current?.stability || {}), style_preset: e.target.value },
                      }))}
                    >
                      {(renderProviders?.style_presets || []).map((item: string) => (
                        <option key={item} value={item}>{item}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Output format</div>
                    <select
                      value={renderProviderDraft?.stability?.output_format || "png"}
                      onChange={(e) => setRenderProviderDraft((current: any) => ({
                        ...(current || {}),
                        stability: { ...(current?.stability || {}), output_format: e.target.value },
                      }))}
                    >
                      <option value="png">png</option>
                      <option value="jpeg">jpeg</option>
                      <option value="webp">webp</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>

            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800 }}>AMD / DirectML internal runtime</div>
              <div className="small" style={{ marginTop: 6, opacity: 0.86 }}>
                Runtime ready: <b>{renderProviders?.directml?.runtime_ready ? "yes" : "no"}</b>
                {" "}• available on this machine: <b>{renderProviders?.directml?.available ? "yes" : "no"}</b>
                {" "}• active backend: <b>{renderProviders?.directml?.active ? "yes" : "no"}</b>
              </div>
              <div className="small" style={{ marginTop: 4, opacity: 0.82 }}>
                Device: <b>{renderProviders?.directml?.device_name || "not detected"}</b>
              </div>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.directml?.enabled}
                    onChange={(e) => setRenderProviderDraft((current: any) => ({
                      ...(current || {}),
                      directml: { ...(current?.directml || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable DirectML internal renders on Windows when available
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.directml?.allow_auto_selection}
                    onChange={(e) => setRenderProviderDraft((current: any) => ({
                      ...(current || {}),
                      directml: { ...(current?.directml || {}), allow_auto_selection: e.target.checked },
                    }))}
                  />
                  Let Studio auto-select DirectML on supported AMD / Windows hardware
                </label>
                <div style={{ maxWidth: 320 }}>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Preferred DirectML internal model</div>
                  <select
                    value={renderProviderDraft?.directml?.preferred_model || "auto"}
                    onChange={(e) => setRenderProviderDraft((current: any) => ({
                      ...(current || {}),
                      directml: { ...(current?.directml || {}), preferred_model: e.target.value },
                    }))}
                  >
                    <option value="auto">auto</option>
                    <option value="hf_sdxl_internal">hf_sdxl_internal</option>
                    <option value="hf_sd15_internal">hf_sd15_internal</option>
                  </select>
                </div>
              </div>
            </div>

            {/* ── NVIDIA Cosmos ─────────────────────────────────────────── */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800 }}>NVIDIA Cosmos Video Generation</div>
              <div className="small" style={{ marginTop: 6, opacity: 0.86 }}>
                Status: <b>{renderProviders?.cosmos?.configured ? "ready" : "API key not set"}</b>
                {" "}• model: <b>{renderProviderDraft?.cosmos?.model || "cosmos3"}</b>
                {(renderProviderDraft?.cosmos?.model || "cosmos3") === "cosmos3" && (
                  <> {" "}• size: <b>{renderProviderDraft?.cosmos?.model_size || "nano"}</b></>
                )}
              </div>
              <div className="small" style={{ marginTop: 4, opacity: 0.8 }}>{renderProviders?.cosmos?.note}</div>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.cosmos?.enabled}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cosmos: { ...(c?.cosmos || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable NVIDIA Cosmos video generation (uses NVIDIA API key above)
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Model</div>
                    <select
                      value={renderProviderDraft?.cosmos?.model || "cosmos3"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), cosmos: { ...(c?.cosmos || {}), model: e.target.value },
                      }))}
                    >
                      <option value="cosmos3">Cosmos 3 Generator — text→video (recommended)</option>
                      <option value="text2world">Cosmos-Predict1 7B — text→video (legacy)</option>
                      <option value="video2world">Cosmos-Predict1 7B — image→video</option>
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Model size</div>
                    <select
                      title="Cosmos 3 Generator size"
                      value={renderProviderDraft?.cosmos?.model_size || "nano"}
                      disabled={(renderProviderDraft?.cosmos?.model || "cosmos3") !== "cosmos3"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), cosmos: { ...(c?.cosmos || {}), model_size: e.target.value },
                      }))}
                    >
                      <option value="nano">Nano — 8B (fast, default)</option>
                      <option value="super">Super — 32B (highest quality)</option>
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Frames</div>
                    <input type="number" min={25} max={480} step={1}
                      value={renderProviderDraft?.cosmos?.num_frames ?? 121}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), cosmos: { ...(c?.cosmos || {}), num_frames: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Steps</div>
                    <input type="number" min={10} max={100} step={5}
                      value={renderProviderDraft?.cosmos?.steps ?? 50}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), cosmos: { ...(c?.cosmos || {}), steps: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Guidance scale</div>
                    <input type="number" min={1} max={20} step={0.5}
                      value={renderProviderDraft?.cosmos?.guidance_scale ?? 7.5}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), cosmos: { ...(c?.cosmos || {}), guidance_scale: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Timeout (s)</div>
                    <input type="number" min={60} max={1800} step={60}
                      value={renderProviderDraft?.cosmos?.timeout_s ?? 600}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), cosmos: { ...(c?.cosmos || {}), timeout_s: Number(e.target.value) },
                      }))}
                    />
                  </div>
                </div>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.cosmos?.prompt_upsampling}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cosmos: { ...(c?.cosmos || {}), prompt_upsampling: e.target.checked },
                    }))}
                  />
                  Prompt upsampling (Cosmos expands short prompts automatically)
                </label>
                <div>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Self-hosted NIM base URL (optional)</div>
                  <input
                    value={renderProviderDraft?.cosmos?.base_url || ""}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), cosmos: { ...(c?.cosmos || {}), base_url: e.target.value },
                    }))}
                    placeholder="http://127.0.0.1:8000 (leave blank to use NVIDIA cloud)"
                  />
                  <div className="small" style={{ marginTop: 4, opacity: 0.75 }}>
                    Model size applies to the Cosmos 3 Generator. On the NVIDIA cloud the served size is fixed;
                    for a self-hosted NIM it must match your container's <code>NIM_MODEL_SIZE</code>
                    {" "}(e.g. <code>-e NIM_MODEL_SIZE=super</code>).
                  </div>
                </div>
                {(renderProviderDraft?.cosmos?.model || "cosmos3") === "cosmos3" && (
                  <div style={{ marginTop: 4 }}>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>
                      Self-hosted NIM launch command
                    </div>
                    <pre style={{
                      margin: 0, padding: "8px 10px", borderRadius: 8, overflowX: "auto",
                      background: "var(--code-bg,#0f172a)", color: "var(--code-fg,#e2e8f0)",
                      fontSize: 12, lineHeight: 1.5, whiteSpace: "pre",
                    }}>{cosmosNimLaunchCommand(renderProviderDraft?.cosmos?.model_size || "nano")}</pre>
                    <div className="row" style={{ gap: 8, marginTop: 6, alignItems: "center" }}>
                      <button
                        type="button"
                        className="secondary"
                        onClick={async () => {
                          const cmd = cosmosNimLaunchCommand(renderProviderDraft?.cosmos?.model_size || "nano");
                          try {
                            await navigator.clipboard.writeText(cmd);
                            setCosmosCmdCopied(true);
                            setTimeout(() => setCosmosCmdCopied(false), 2000);
                          } catch {
                            setCosmosCmdCopied(false);
                          }
                        }}
                      >
                        Copy launch command
                      </button>
                      {cosmosCmdCopied && <span className="small" style={{ color: "var(--success-text,#16a34a)" }}>Copied!</span>}
                    </div>
                    <div className="small" style={{ marginTop: 4, opacity: 0.7 }}>
                      Requires Docker, an NVIDIA GPU (Hopper/Blackwell), and <code>NGC_API_KEY</code> set in your shell.
                      After it reports ready, set the base URL above to <code>http://127.0.0.1:8000</code>.
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* ── Azure AI Foundry Cosmos3 ─────────────────────────────────── */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800 }}>Azure AI Foundry Cosmos3 (managed compute)</div>
              <div className="small" style={{ marginTop: 6, opacity: 0.86 }}>
                Status: <b>{renderProviders?.azure_foundry?.configured ? "ready" : "not configured"}</b>
                {" "}• deployment: <b>{renderProviderDraft?.azure_foundry?.deployment_name || "(not set)"}</b>
                {" "}• resolution: <b>{renderProviderDraft?.azure_foundry?.resolution || "720_16_9"}</b>
              </div>
              <div className="small" style={{ marginTop: 4, opacity: 0.8 }}>{renderProviders?.azure_foundry?.note}</div>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.azure_foundry?.enabled}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable Azure AI Foundry Cosmos3 video generation (uses Azure AI Foundry API key above)
                </label>
                <div>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Endpoint URL</div>
                  <input
                    value={renderProviderDraft?.azure_foundry?.endpoint_url || ""}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), endpoint_url: e.target.value },
                    }))}
                    placeholder="https://<your-resource>.services.ai.azure.com"
                  />
                  <div className="small" style={{ marginTop: 4, opacity: 0.75 }}>
                    Base URL of your Azure AI Foundry resource (the deployment path is appended automatically).
                  </div>
                </div>
                <div>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Deployment name</div>
                  <input
                    value={renderProviderDraft?.azure_foundry?.deployment_name || ""}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), deployment_name: e.target.value },
                    }))}
                    placeholder="cosmos3-super-deployment"
                  />
                  <div className="small" style={{ marginTop: 4, opacity: 0.75 }}>
                    The managed-compute deployment name from your Foundry project (Cosmos3-Super).
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Resolution</div>
                    <select
                      value={renderProviderDraft?.azure_foundry?.resolution || "720_16_9"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), resolution: e.target.value },
                      }))}
                    >
                      <optgroup label="720p tier">
                        <option value="720_16_9">720p 16:9 (1280×720)</option>
                        <option value="720_9_16">720p 9:16 (720×1280)</option>
                        <option value="720_1_1">720p 1:1 (960×960)</option>
                        <option value="720_4_3">720p 4:3 (1104×832)</option>
                        <option value="720_3_4">720p 3:4 (832×1104)</option>
                      </optgroup>
                      <optgroup label="480p tier">
                        <option value="480_16_9">480p 16:9 (832×480)</option>
                        <option value="480_9_16">480p 9:16 (480×832)</option>
                        <option value="480_1_1">480p 1:1 (640×640)</option>
                        <option value="480_4_3">480p 4:3 (736×544)</option>
                        <option value="480_3_4">480p 3:4 (544×736)</option>
                      </optgroup>
                      <optgroup label="256p tier">
                        <option value="256_16_9">256p 16:9 (320×192)</option>
                        <option value="256_9_16">256p 9:16 (192×320)</option>
                        <option value="256_1_1">256p 1:1 (256×256)</option>
                        <option value="256_4_3">256p 4:3 (320×256)</option>
                        <option value="256_3_4">256p 3:4 (256×320)</option>
                      </optgroup>
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Frames</div>
                    <input type="number" min={25} max={480} step={1}
                      value={renderProviderDraft?.azure_foundry?.num_frames ?? 121}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), num_frames: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>FPS</div>
                    <input type="number" min={1} max={60} step={1}
                      value={renderProviderDraft?.azure_foundry?.fps ?? 24}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), fps: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Steps</div>
                    <input type="number" min={1} max={100} step={1}
                      value={renderProviderDraft?.azure_foundry?.steps ?? 50}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), steps: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Guidance scale</div>
                    <input type="number" min={1} max={7} step={0.5}
                      value={renderProviderDraft?.azure_foundry?.guidance_scale ?? 7.0}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), guidance_scale: Number(e.target.value) },
                      }))}
                    />
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Timeout (s)</div>
                    <input type="number" min={60} max={1800} step={60}
                      value={renderProviderDraft?.azure_foundry?.timeout_s ?? 600}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), timeout_s: Number(e.target.value) },
                      }))}
                    />
                  </div>
                </div>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.azure_foundry?.allow_auto_fallback}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), azure_foundry: { ...(c?.azure_foundry || {}), allow_auto_fallback: e.target.checked },
                    }))}
                  />
                  Allow automatic fallback to Azure AI Foundry when other video routes are unavailable
                </label>
              </div>
            </div>

            {/* ── Adobe Firefly ─────────────────────────────────────────── */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800 }}>Adobe Firefly (custom model / standard)</div>
              <div className="small" style={{ marginTop: 6, opacity: 0.86 }}>
                Credentials: Client ID <b>{renderProviders?.firefly?.has_client_id ? "✓" : "not set"}</b>
                {" "}• Client Secret <b>{renderProviders?.firefly?.has_client_secret ? "✓" : "not set"}</b>
                {" "}• configured: <b>{renderProviders?.firefly?.configured ? "yes" : "no"}</b>
              </div>
              {renderProviders?.firefly?.note && (
                <div className="small" style={{ marginTop: 4, opacity: 0.8 }}>{renderProviders.firefly.note}</div>
              )}

              {/* Credentials */}
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8, alignItems: "end" }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Adobe Client ID</div>
                    <div className="small" style={{ opacity: 0.75, marginBottom: 4 }}>
                      From <a href="https://developer.adobe.com/console/" target="_blank" rel="noreferrer">Adobe Developer Console</a> → your Firefly API project.
                    </div>
                    <input
                      value={adobeClientId}
                      onChange={(e) => setAdobeClientId(e.target.value)}
                      placeholder={secrets?.has_adobe_client_id ? "(set) paste to replace" : "paste Client ID"}
                    />
                  </div>
                  <button disabled={saving || !adobeClientId} onClick={() => saveSecret("adobe_client_id", adobeClientId)}>Save</button>
                  <button className="secondary" disabled={saving || !secrets?.has_adobe_client_id} onClick={() => clearSecret("adobe_client_id")}>Clear</button>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8, alignItems: "end" }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Adobe Client Secret</div>
                    <input
                      type="password"
                      value={adobeClientSecret}
                      onChange={(e) => setAdobeClientSecret(e.target.value)}
                      placeholder={secrets?.has_adobe_client_secret ? "(set) paste to replace" : "paste Client Secret"}
                    />
                  </div>
                  <button disabled={saving || !adobeClientSecret} onClick={() => saveSecret("adobe_client_secret", adobeClientSecret)}>Save</button>
                  <button className="secondary" disabled={saving || !secrets?.has_adobe_client_secret} onClick={() => clearSecret("adobe_client_secret")}>Clear</button>
                </div>

                {/* Enable toggles */}
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.firefly?.enabled}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), firefly: { ...(c?.firefly || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable Adobe Firefly as a hosted render provider
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={!!renderProviderDraft?.firefly?.allow_auto_fallback}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), firefly: { ...(c?.firefly || {}), allow_auto_fallback: e.target.checked },
                    }))}
                  />
                  Allow automatic Firefly fallback when other providers are unavailable
                </label>

                {/* Custom model ID */}
                <div>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Custom Model ID</div>
                  <div className="small" style={{ opacity: 0.75, marginBottom: 4 }}>
                    From Adobe Firefly custom model training (e.g. <code>urn:firefly:...</code>). Leave blank to use standard Firefly Image 3.
                  </div>
                  <input
                    value={renderProviderDraft?.firefly?.custom_model_id || ""}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), firefly: { ...(c?.firefly || {}), custom_model_id: e.target.value },
                    }))}
                    placeholder="urn:firefly:... (optional)"
                  />
                </div>

                {/* Style + content class */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Style</div>
                    <select
                      value={renderProviderDraft?.firefly?.style || "none"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), firefly: { ...(c?.firefly || {}), style: e.target.value },
                      }))}
                    >
                      {(renderProviders?.firefly_styles || ["none","photo","art","graphic","illustration","sketch","watercolor","pixel-art"]).map((s: string) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Content class</div>
                    <select
                      value={renderProviderDraft?.firefly?.content_class || "photo"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), firefly: { ...(c?.firefly || {}), content_class: e.target.value },
                      }))}
                    >
                      {(renderProviders?.firefly_content_classes || ["photo","art"]).map((s: string) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Video generation */}
                <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid rgba(255,255,255,0.08)" }}>
                  <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Video generation (beta)</div>
                  <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input
                      type="checkbox"
                      checked={!!renderProviderDraft?.firefly?.video_enabled}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), firefly: { ...(c?.firefly || {}), video_enabled: e.target.checked },
                      }))}
                    />
                    Enable native Firefly video clips (text-to-video)
                  </label>
                  <div style={{ marginTop: 6 }}>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Clip duration (seconds)</div>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={renderProviderDraft?.firefly?.video_duration_s ?? 5}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}),
                        firefly: {
                          ...(c?.firefly || {}),
                          video_duration_s: Math.max(1, Math.min(10, Number(e.target.value) || 5)),
                        },
                      }))}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* ── ImagineArt ─────────────────────────────────────────────── */}
            <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12 }}>
              <div style={{ fontWeight: 800, marginBottom: 6 }}>ImagineArt (hosted cloud)</div>
              <div className="small" style={{ marginBottom: 8 }}>
                API key saved: <b>{renderProviders?.imagineart?.has_api_key ? "yes" : "no"}</b>
                {" "}• active in Render: <b>{renderProviders?.imagineart?.visible ? "yes" : "no"}</b>
                {" "}• image style: <b>{renderProviderDraft?.imagineart?.image_style || "imagine-turbo"}</b>
                {" "}• video style: <b>{renderProviderDraft?.imagineart?.video_style || "kling-1.0-pro"}</b>
              </div>
              <div className="small" style={{ marginBottom: 8, opacity: 0.8 }}>{renderProviders?.imagineart?.note}</div>
              <div style={{ display: "grid", gap: 8 }}>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input type="checkbox"
                    checked={!!renderProviderDraft?.imagineart?.enabled}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), imagineart: { ...(c?.imagineart || {}), enabled: e.target.checked },
                    }))}
                  />
                  Enable ImagineArt hosted rendering
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input type="checkbox"
                    checked={!!renderProviderDraft?.imagineart?.allow_auto_fallback}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), imagineart: { ...(c?.imagineart || {}), allow_auto_fallback: e.target.checked },
                    }))}
                  />
                  Allow auto fallback to ImagineArt when local GPU is unavailable
                </label>
                <label className="small" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input type="checkbox"
                    checked={!!renderProviderDraft?.imagineart?.video_enabled}
                    onChange={(e) => setRenderProviderDraft((c: any) => ({
                      ...(c || {}), imagineart: { ...(c?.imagineart || {}), video_enabled: e.target.checked },
                    }))}
                  />
                  Enable native ImagineArt video clips (text-to-video / image-to-video)
                </label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Image style</div>
                    <select
                      value={renderProviderDraft?.imagineart?.image_style || "imagine-turbo"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), imagineart: { ...(c?.imagineart || {}), image_style: e.target.value },
                      }))}
                    >
                      {(renderProviders?.imagineart_image_styles || ["imagine-turbo", "realistic", "anime"]).map((s: string) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Video style</div>
                    <select
                      value={renderProviderDraft?.imagineart?.video_style || "kling-1.0-pro"}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), imagineart: { ...(c?.imagineart || {}), video_style: e.target.value },
                      }))}
                    >
                      {(renderProviders?.imagineart_video_styles || ["kling-1.0-pro", "imagine-v2"]).map((s: string) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div className="small" style={{ fontWeight: 800, marginBottom: 4 }}>Timeout (seconds)</div>
                    <input
                      type="number"
                      min={60}
                      max={1800}
                      value={renderProviderDraft?.imagineart?.timeout_s ?? 600}
                      onChange={(e) => setRenderProviderDraft((c: any) => ({
                        ...(c || {}), imagineart: { ...(c?.imagineart || {}), timeout_s: Number(e.target.value) },
                      }))}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <button disabled={savingProviders} onClick={saveRenderProviders}>
                {savingProviders ? "Saving…" : "Save render provider settings"}
              </button>
              <div className="small" style={{ opacity: 0.82 }}>
                Render and Models will only surface the hosted Stability controls after a key is saved and the hosted fallback is enabled.
                If you changed the CUDA enabled toggle, restart the backend and re-start ComfyUI via the ComfyUI panel below for the new mode to take effect.
              </div>
            </div>
          </div>
        )}
      </div>
    ),
    comfyui: (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>ComfyUI</div>

        {/* Quick-start controls */}
        <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12, marginBottom: 14 }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Quick start</div>
          <div className="small" style={{ marginBottom: 10, opacity: 0.86 }}>
            Status: <b>{hardware?.hardware?.backend === "cuda" && renderProviders?.cuda?.enabled
              ? "CUDA GPU available — NVIDIA mode recommended"
              : hardware?.hardware?.backend
              ? String(hardware.hardware.backend).toUpperCase()
              : "unknown"
            }</b>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button
              onClick={() => apiPost("/v1/setup/comfyui/portable/start", { flavor: "nvidia" }).catch(() => {})}
            >
              Start ComfyUI (NVIDIA CUDA)
            </button>
            <button
              className="secondary"
              onClick={() => apiPost("/v1/setup/comfyui/portable/start", { flavor: "cpu" }).catch(() => {})}
            >
              Start ComfyUI (CPU)
            </button>
            <button
              className="secondary"
              onClick={() => apiPost("/v1/setup/comfyui/portable/start", { flavor: "auto" }).catch(() => {})}
            >
              Start ComfyUI (auto)
            </button>
          </div>
          <div className="small" style={{ marginTop: 8, opacity: 0.75 }}>
            NVIDIA mode adds <code>--cuda-malloc --use-pytorch-cross-attention</code> and CUDA memory env vars for maximum GPU throughput.
            "auto" picks NVIDIA if CUDA is enabled in GPU / Render Runtime settings above, otherwise CPU.
          </div>
        </div>

        <div className="small">
          Studio ships curated ComfyUI routing for plain stills, AnimateDiff motion, SVD image-to-video, and reference-driven ControlNet stills. The fallback checkpoint override uses <code>EDMG_COMFYUI_CHECKPOINT</code> when no catalog-backed model is selected.
        </div>
        <ul className="guide-list" style={{ marginTop: 8 }}>
          <li>Setup installs ComfyUI and makes it reachable at the configured URL.</li>
          <li>Models controls which checkpoints and ControlNet units Studio routes through ComfyUI.</li>
          <li>GPU / Render Runtime → CUDA settings control whether ComfyUI starts in NVIDIA mode.</li>
          <li>Render exposes ComfyUI paths only when the selected model uses the ComfyUI engine and the server is live.</li>
        </ul>
      </div>
    ),
    deforum: edmgTemplate ? (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Deforum template (from EDMG Core)</div>
        <div className="small">This is an editing surface / reference for Deforum exports.</div>
        <div style={{ marginTop: 10 }}>
          <StructuredSummary value={edmgTemplate} showJson maxItems={32} jsonMaxHeight={420} />
        </div>
      </div>
    ) : null,
  };

  return (
    <div>
      <h1>Settings</h1>
      {err && <div style={{ color: "var(--danger)" }}>{err}</div>}
      <StudioLayoutCustomizer
        title="Settings layout"
        description="Reorder or hide Settings panels for your own workflow. This does not change what any setting saves or how the desktop/backend behaves."
        items={panelControlItems}
        profileOptions={profileOptions}
        activeProfile={activeProfile}
        onSelectProfile={setActiveProfile}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      {visibleOrder.map((panelId) => (
        <React.Fragment key={panelId}>{panelContent[panelId]}</React.Fragment>
      ))}
    </div>
  );
}
