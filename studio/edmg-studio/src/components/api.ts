function readQueryBackendUrl(): string {
  if (typeof window === "undefined") return "";
  const params = new URLSearchParams(window.location.search);
  return (params.get("backendUrl") || params.get("backend") || "").trim();
}

function readEnvBackendUrl(): string {
  return String(import.meta.env.VITE_EDMG_BACKEND_URL || "").trim();
}

function readSameOriginBackendUrl(): string {
  if (typeof window === "undefined") return "";
  if (import.meta.env.DEV) return "";
  const protocol = window.location.protocol;
  if (protocol !== "http:" && protocol !== "https:") return "";
  return window.location.origin;
}

function rememberBackendUrl(value: string): string {
  const resolved = String(value || "").trim();
  if (typeof window !== "undefined" && resolved) {
    window.__EDMG_BACKEND_URL__ = resolved;
  }
  return resolved;
}

export function getBackendUrl(): string {
  return rememberBackendUrl(
    readQueryBackendUrl() ||
    readEnvBackendUrl() ||
    window.edmg?.backendUrl?.() ||
    window.__EDMG_BACKEND_URL__ ||
    readSameOriginBackendUrl() ||
    "http://127.0.0.1:7863"
  );
}

export async function getBackendUrlAsync(): Promise<string> {
  const explicit = readQueryBackendUrl();
  if (explicit) return rememberBackendUrl(explicit);
  const envBackendUrl = readEnvBackendUrl();
  if (envBackendUrl) return rememberBackendUrl(envBackendUrl);
  try {
    const bridged = await window.edmg?.getBackendUrl?.();
    if (typeof bridged === "string" && bridged.trim()) {
      return rememberBackendUrl(bridged);
    }
  } catch {
    // Fall through to the sync fallback chain below.
  }
  return rememberBackendUrl(getBackendUrl());
}

export function ensureBrowserBridge(): void {
  if (typeof window === "undefined" || window.edmg) return;
  const backendUrl = rememberBackendUrl(getBackendUrl());
  window.edmg = {
    backendUrl: () => backendUrl,
    getBackendUrl: async () => backendUrl,
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
