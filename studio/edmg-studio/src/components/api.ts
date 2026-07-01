export const BACKEND_URL_CHANGED_EVENT = "edmg:backend-url-changed";

const BROWSER_BACKEND_URL_STORAGE_KEY = "edmg.backendUrl";

function readQueryBackendUrl(): string {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search);
  return (params.get("backendUrl") || params.get("backend") || "").trim();
}

function readEnvBackendUrl(): string {
  return String(import.meta.env.VITE_EDMG_BACKEND_URL || import.meta.env.VITE_EDMG_STUDIO_BACKEND_URL || "").trim();
}

function readStoredBackendUrl(): string {
  if (typeof window === "undefined") return "";
  try {
    return String(window.localStorage?.getItem(BROWSER_BACKEND_URL_STORAGE_KEY) || "").trim();
  } catch {
    return "";
  }
}

function readSameOriginBackendUrl(): string {
  if (typeof window === "undefined") return "";
  if (import.meta.env.DEV) return "";
  const protocol = window.location.protocol;
  if (protocol !== "http:" && protocol !== "https:") return "";
  return window.location.origin;
}

export function normalizeBackendUrl(rawUrl: string): string {
  const candidate = String(rawUrl || "").trim();
  if (!candidate) return "";
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return "";
    }

    let normalizedPath =
      parsed.pathname && parsed.pathname !== "/"
        ? parsed.pathname.replace(/\/+$/, "")
        : "";
    normalizedPath = normalizedPath.replace(/\/(?:health|v1)$/i, "");

    return `${parsed.origin}${normalizedPath}`;
  } catch {
    return "";
  }
}

function pickBackendUrl(...values: unknown[]): string {
  for (const value of values) {
    const normalized = normalizeBackendUrl(String(value || ""));
    if (normalized) return normalized;
  }
  return "";
}

function rememberBackendUrl(value: string): string {
  const resolved = normalizeBackendUrl(value);
  if (typeof window !== "undefined" && resolved) {
    window.__EDMG_BACKEND_URL__ = resolved;
  }
  return resolved;
}

export function setBrowserBackendUrl(value: string): string {
  const resolved = normalizeBackendUrl(value);
  if (!resolved) return "";
  rememberBackendUrl(resolved);
  if (typeof window !== "undefined") {
    try {
      window.localStorage?.setItem(BROWSER_BACKEND_URL_STORAGE_KEY, resolved);
    } catch {
      // Browser storage can be disabled; the in-memory value above still updates this page.
    }
    window.dispatchEvent(new CustomEvent(BACKEND_URL_CHANGED_EVENT, { detail: { url: resolved } }));
  }
  return resolved;
}

export function getBackendUrl(): string {
  return rememberBackendUrl(
    pickBackendUrl(
      readQueryBackendUrl(),
      readStoredBackendUrl(),
      readEnvBackendUrl(),
      window.edmg?.backendUrl?.(),
      window.__EDMG_BACKEND_URL__,
      readSameOriginBackendUrl(),
      "http://127.0.0.1:7863"
    )
  );
}

export async function getBackendUrlAsync(): Promise<string> {
  const explicit = pickBackendUrl(readQueryBackendUrl());
  if (explicit) return rememberBackendUrl(explicit);
  try {
    const bridged = await window.edmg?.getBackendUrl?.();
    const bridgedUrl = pickBackendUrl(bridged);
    if (bridgedUrl) return rememberBackendUrl(bridgedUrl);
  } catch {
    // Fall through to the sync fallback chain below.
  }
  return rememberBackendUrl(getBackendUrl());
}

export function ensureBrowserBridge(): void {
  if (typeof window === "undefined" || window.edmg) return;
  const backendUrl = rememberBackendUrl(getBackendUrl());
  window.edmg = {
    backendUrl: () => getBackendUrl() || backendUrl,
    getBackendUrl: async () => getBackendUrl() || backendUrl,
    setBackendUrl: async (url: string) => setBrowserBackendUrl(url),
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
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] || {};
    const loc = Array.isArray(first.loc) ? first.loc.filter(Boolean).join(".") : "";
    const msg = first.msg || first.message || "Request validation failed";
    const suffix = detail.length > 1 ? ` (${detail.length} validation issues)` : "";
    return loc ? `${loc}: ${msg}${suffix}` : `${msg}${suffix}`;
  }
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
