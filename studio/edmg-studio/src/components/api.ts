function readQueryBackendUrl(): string {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search);
  return (params.get("backendUrl") || params.get("backend") || "").trim();
}

function readEnvBackendUrl(): string {
  return String(import.meta.env.VITE_EDMG_BACKEND_URL || "").trim();
}

const LOCAL_DEV_BACKEND_CANDIDATES = [
  "http://127.0.0.1:8000",
  "http://127.0.0.1:7863",
];
const DESKTOP_DEFAULT_BACKEND_URL = "http://127.0.0.1:7863";
const BROWSER_DEV_DEFAULT_BACKEND_URL = LOCAL_DEV_BACKEND_CANDIDATES[0];
let localDevBackendDetection: Promise<string> | null = null;
let browserBridgeInstalled = false;

function readSameOriginBackendUrl(): string {
  if (typeof window === "undefined") return "";
  if (import.meta.env.DEV) return "";
  const protocol = window.location.protocol;
  if (protocol !== "http:" && protocol !== "https:") return "";
  return window.location.origin;
}

function shouldProbeLocalDevBackend(): boolean {
  if (typeof window === "undefined") return false;
  if (!import.meta.env.DEV) return false;
  if (window.edmg && !browserBridgeInstalled) return false;
  return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

function readBridgeBackendUrl(): string {
  if (typeof window === "undefined") return "";
  if (browserBridgeInstalled) return "";
  return String(window.edmg?.backendUrl?.() || "").trim();
}

async function readBridgeBackendUrlAsync(): Promise<string> {
  if (typeof window === "undefined") return "";
  if (browserBridgeInstalled) return "";
  const bridged = await window.edmg?.getBackendUrl?.();
  return String(bridged || "").trim();
}

function rememberBackendUrl(value: string): string {
  const resolved = String(value || "").trim();
  if (typeof window !== "undefined" && resolved) {
    window.__EDMG_BACKEND_URL__ = resolved;
  }
  return resolved;
}

async function probeBackendHealth(baseUrl: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 800);
  try {
    const response = await fetch(`${baseUrl}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function detectLocalDevBackendUrl(): Promise<string> {
  localDevBackendDetection ??= (async () => {
    for (const candidate of LOCAL_DEV_BACKEND_CANDIDATES) {
      if (await probeBackendHealth(candidate)) return candidate;
    }
    return "";
  })();
  return localDevBackendDetection;
}

function getFallbackBackendUrl(): string {
  if (shouldProbeLocalDevBackend()) return BROWSER_DEV_DEFAULT_BACKEND_URL;
  return readSameOriginBackendUrl() || DESKTOP_DEFAULT_BACKEND_URL;
}

export function getBackendUrl(): string {
  const configured =
    readQueryBackendUrl() ||
    readEnvBackendUrl() ||
    readBridgeBackendUrl() ||
    window.__EDMG_BACKEND_URL__;

  if (configured) return rememberBackendUrl(configured);
  return getFallbackBackendUrl();
}

export async function getBackendUrlAsync(): Promise<string> {
  const explicit = readQueryBackendUrl();
  if (explicit) return rememberBackendUrl(explicit);
  const envBackendUrl = readEnvBackendUrl();
  if (envBackendUrl) return rememberBackendUrl(envBackendUrl);
  try {
    const bridged = await readBridgeBackendUrlAsync();
    if (bridged) {
      return rememberBackendUrl(bridged);
    }
  } catch {
    // Fall through to the sync fallback chain below.
  }

  if (shouldProbeLocalDevBackend()) {
    const detected = await detectLocalDevBackendUrl();
    if (detected) return rememberBackendUrl(detected);
  }

  if (typeof window !== "undefined" && window.__EDMG_BACKEND_URL__) {
    return rememberBackendUrl(window.__EDMG_BACKEND_URL__);
  }

  return rememberBackendUrl(getBackendUrl());
}

export function ensureBrowserBridge(): void {
  if (typeof window === "undefined" || window.edmg) return;
  browserBridgeInstalled = true;
  window.edmg = {
    backendUrl: () => getBackendUrl(),
    getBackendUrl: async () => getBackendUrlAsync(),
    openExternal: async (url: string) => {
      window.open(String(url), "_blank", "noopener,noreferrer");
    },
  };
}

function formatBackendError(d: any, fallback: string): string {
  // New backend format: { error: { message, hint, code } }
  const e = d?.error;
  if (e?.message) {
    const hint = e?.hint ? `\nFix: ${e.hint}` : "";
    return `${e.message}${hint}`;
  }
  // FastAPI HTTPException: { detail: ... }
  const detail = d?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) {
    const hint = detail?.hint ? `\nFix: ${detail.hint}` : "";
    return `${detail.message}${hint}`;
  }
  if (typeof d?.error === "string") return d.error;
  return fallback;
}

export async function apiGet(path: string) {
  const base = await getBackendUrlAsync();
  const r = await fetch(`${base}${path}`);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(formatBackendError(d, `GET ${path} failed`));
  return d;
}

export async function apiPost(path: string, body: any) {
  const base = await getBackendUrlAsync();
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(formatBackendError(d, `POST ${path} failed`));
  return d;
}

export async function apiDelete(path: string) {
  const base = await getBackendUrlAsync();
  const r = await fetch(`${base}${path}`, { method: "DELETE" });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(formatBackendError(d, `DELETE ${path} failed`));
  return d;
}

export async function apiUpload(path: string, file: File) {
  const base = await getBackendUrlAsync();
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${base}${path}`, { method: "POST", body: fd });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(formatBackendError(d, `UPLOAD ${path} failed`));
  return d;
}
