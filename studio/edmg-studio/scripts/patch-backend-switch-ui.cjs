const fs = require("node:fs");
const path = require("node:path");

const root = process.cwd();

function read(rel) {
  return fs.readFileSync(path.join(root, rel), "utf8");
}

function write(rel, text) {
  fs.writeFileSync(path.join(root, rel), text, "utf8");
}

function patch(rel, before, after, marker) {
  let text = read(rel);
  if (marker && text.includes(marker)) {
    console.log(`[skip] ${rel} already has ${marker}`);
    return;
  }
  if (!text.includes(before)) {
    throw new Error(`Pattern not found in ${rel}`);
  }
  write(rel, text.replace(before, after));
  console.log(`[patch] ${rel}`);
}

patch(
  "src/components/api.ts",
`function rememberBackendUrl(value: string): string {
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
`,
`function rememberBackendUrl(value: string): string {
  const resolved = String(value || "").trim();
  if (typeof window !== "undefined" && resolved) {
    window.__EDMG_BACKEND_URL__ = resolved;
  }
  return resolved;
}

export function setActiveBackendUrl(value: string): string {
  return rememberBackendUrl(value);
}

export function getBackendUrl(): string {
  return rememberBackendUrl(
    readQueryBackendUrl() ||
    window.__EDMG_BACKEND_URL__ ||
    readEnvBackendUrl() ||
    window.edmg?.backendUrl?.() ||
    readSameOriginBackendUrl() ||
    "http://127.0.0.1:7863"
  );
}

export async function getBackendUrlAsync(): Promise<string> {
  const explicit = readQueryBackendUrl();
  if (explicit) return rememberBackendUrl(explicit);
  if (typeof window !== "undefined" && window.__EDMG_BACKEND_URL__) {
    return rememberBackendUrl(window.__EDMG_BACKEND_URL__);
  }
  try {
    const bridged = await window.edmg?.getBackendUrl?.();
    if (typeof bridged === "string" && bridged.trim()) {
      return rememberBackendUrl(bridged);
    }
  } catch {
    // Fall through to env and sync fallback chain below.
  }
  const envBackendUrl = readEnvBackendUrl();
  if (envBackendUrl) return rememberBackendUrl(envBackendUrl);
  return rememberBackendUrl(getBackendUrl());
}
`,
"setActiveBackendUrl"
);

patch(
  "src/App.tsx",
`import { apiGet, getBackendUrl, getBackendUrlAsync } from "./components/api";`,
`import { apiGet, getBackendUrl, getBackendUrlAsync, setActiveBackendUrl } from "./components/api";`,
"setActiveBackendUrl"
);

patch(
  "src/App.tsx",
`  const commonProps = useMemo(() => ({ backendUrl, config }), [backendUrl, config]);
`,
`  const commonProps = useMemo(() => ({ backendUrl, config }), [backendUrl, config]);
  const handleBackendUrlChange = (nextUrl: string) => {
    const resolved = setActiveBackendUrl(nextUrl);
    setBackendUrl(resolved);
    setConfig(null);
    setBackendConfigError("");
    setSetupChecked(false);
  };
`,
"handleBackendUrlChange"
);

patch(
  "src/App.tsx",
`  if (page === "settings") content = <Settings {...commonProps} />;`,
`  if (page === "settings") content = <Settings {...commonProps} onBackendUrlChange={handleBackendUrlChange} />;`,
"onBackendUrlChange={handleBackendUrlChange}"
);

patch(
  "src/pages/Settings.tsx",
`import { apiGet, apiPost } from "../components/api";`,
`import { apiGet, apiPost, setActiveBackendUrl } from "../components/api";`,
"setActiveBackendUrl"
);

patch(
  "src/pages/Settings.tsx",
`type StudioBackendSettings = {
  mode: string;
  host: string;
  port: string;
  url: string;
  source?: string;
};
`,
`type StudioBackendSettings = {
  mode: string;
  host: string;
  port: string;
  url: string;
  source?: string;
};

type SettingsProps = PageProps & {
  onBackendUrlChange?: (url: string) => void;
};
`,
"SettingsProps"
);

patch(
  "src/pages/Settings.tsx",
`  const rawUrl = String(current.url ?? "").trim();
  const parsedUrl = parseBackendUrl(rawUrl);
  const normalizedUrl = sanitizeBackendUrl(rawUrl);

  return {
    mode,
    host: String(parsedUrl.host ?? host).trim() || host,
    port: String(parsedUrl.port ?? port).trim() || port,
    url: mode === "external" ? (rawUrl ? normalizedUrl || rawUrl : "") : "",
    source: String(current.source ?? DEFAULT_BACKEND_SETTINGS.source),
  };
}
`,
`  const rawUrl = String(current.url ?? "").trim();
  const normalizedUrl = sanitizeBackendUrl(rawUrl);

  return {
    mode,
    host,
    port,
    url: mode === "external" ? (rawUrl ? normalizedUrl || rawUrl : "") : "",
    source: String(current.source ?? DEFAULT_BACKEND_SETTINGS.source),
  };
}
`,
"host,\n    port,\n    url: mode === \"external\""
);

patch(
  "src/pages/Settings.tsx",
`export default function Settings(props: PageProps) {`,
`export default function Settings(props: SettingsProps) {`,
"SettingsProps) {"
);

patch(
  "src/pages/Settings.tsx",
`      const derived = backendUrl ? parseBackendUrl(backendUrl) : {};
      const response = await window.edmg.setBackendSettings({
        mode: normalizedDraft.mode,
        host: String(derived.host ?? normalizedDraft.host),
        port: String(derived.port ?? normalizedDraft.port),
        url: backendUrl,
      });
`,
`      const response = await window.edmg.setBackendSettings({
        mode: normalizedDraft.mode,
        host: normalizedDraft.host,
        port: normalizedDraft.port,
        url: backendUrl,
      });
`,
"host: normalizedDraft.host"
);

patch(
  "src/pages/Settings.tsx",
`      setLiveBackendUrl(nextLiveUrl);
      setBackendNotice(
        response.restartRequired
          ? "Saved. Restart Studio so it relaunches against the selected backend target."
          : "Saved."
      );
`,
`      setLiveBackendUrl(nextLiveUrl);
      setActiveBackendUrl(nextLiveUrl);
      props.onBackendUrlChange?.(nextLiveUrl);
      setBackendNotice(
        response.restartRequired
          ? "Saved. Restart is only needed for managed local backend launch changes."
          : "Applied now and saved as the default backend target."
      );
`,
"props.onBackendUrlChange?."
);

patch(
  "src/pages/Settings.tsx",
`            <button disabled={savingBackend || !backendSettingsDirty || !window.edmg?.setBackendSettings} onClick={saveBackendSettings}>
              {savingBackend ? "Saving…" : "Save backend startup settings"}
            </button>
`,
`            <button disabled={savingBackend || !window.edmg?.setBackendSettings} onClick={saveBackendSettings}>
              {savingBackend ? "Applying…" : "Apply backend now"}
            </button>
`,
"Apply backend now"
);

patch(
  "main-process/backend-runtime.mjs",
`}) {
  let currentBackendUrl = backendUrl || \`http://\${backendHost}:\${backendPort}\`;
  let backendProc = null;
`,
`}) {
  let currentBackendHost = String(backendHost || "127.0.0.1");
  let currentBackendPort = String(backendPort || "7863");
  let currentBackendUrl = backendUrl || \`http://\${currentBackendHost}:\${currentBackendPort}\`;
  let backendProc = null;
`,
"currentBackendHost"
);

patch(
  "main-process/backend-runtime.mjs",
`        args: ["serve", "--host", backendHost, "--port", String(backendPort)],`,
`        args: ["serve", "--host", currentBackendHost, "--port", String(currentBackendPort)],`,
"currentBackendHost, \"--port\""
);

patch(
  "main-process/backend-runtime.mjs",
`      args: ["-m", "edmg_studio_backend", "serve", "--host", backendHost, "--port", String(backendPort)],`,
`      args: ["-m", "edmg_studio_backend", "serve", "--host", currentBackendHost, "--port", String(currentBackendPort)],`,
"currentBackendHost, \"--port\""
);

patch(
  "main-process/backend-runtime.mjs",
`      EDMG_STUDIO_BACKEND_HOST: backendHost,
      EDMG_STUDIO_BACKEND_PORT: String(backendPort),`,
`      EDMG_STUDIO_BACKEND_HOST: currentBackendHost,
      EDMG_STUDIO_BACKEND_PORT: String(currentBackendPort),`,
"EDMG_STUDIO_BACKEND_HOST: currentBackendHost"
);

patch(
  "main-process/backend-runtime.mjs",
`  return {
    getCurrentBackendUrl,
    startBackendIfNeeded,
    stopBackend,
  };
}
`,
`  function setBackendTarget(settings = {}) {
    const mode = String(settings.mode ?? "").trim().toLowerCase();
    const host = String(settings.host || currentBackendHost || "127.0.0.1").trim() || "127.0.0.1";
    const port = String(settings.port || currentBackendPort || "7863").trim() || "7863";
    const url = String(settings.url || "").trim().replace(/\\/+$/, "");

    currentBackendHost = host;
    currentBackendPort = port;

    if ((mode === "external" || mode === "remote" || mode === "connect") && url) {
      currentBackendUrl = url;
      process.env.EDMG_STUDIO_SPAWN_BACKEND = "0";
    } else {
      currentBackendUrl = \`http://\${currentBackendHost}:\${currentBackendPort}\`;
      process.env.EDMG_STUDIO_SPAWN_BACKEND = "1";
    }

    process.env.EDMG_STUDIO_BACKEND_HOST = currentBackendHost;
    process.env.EDMG_STUDIO_BACKEND_PORT = String(currentBackendPort);
    process.env.EDMG_STUDIO_BACKEND_URL = currentBackendUrl;
    logBackendUrlMarker();
    return currentBackendUrl;
  }

  return {
    getCurrentBackendUrl,
    setBackendTarget,
    startBackendIfNeeded,
    stopBackend,
  };
}
`,
"setBackendTarget"
);

patch(
  "main.mjs",
`function normalizeBackendSettings(rawSettings = {}) {
  const current = rawSettings && typeof rawSettings === "object" ? rawSettings : {};
  const mode = normalizeBackendMode(current.mode);
  const host = pickConfiguredString(current.host, BACKEND_SETTINGS_DEFAULTS.host);
  const port = normalizeBackendPort(current.port);
  const fallbackUrl = buildManagedBackendUrl(host, port);
  const url = mode === "external" ? normalizeBackendUrl(current.url, fallbackUrl) : "";
  const derived = mode === "external" ? deriveBackendConnectionFromUrl(url) : {};

  return {
    mode,
    host: pickConfiguredString(derived.host, host),
    port: normalizeBackendPort(derived.port || port),
    url,
  };
}
`,
`function normalizeBackendSettings(rawSettings = {}) {
  const current = rawSettings && typeof rawSettings === "object" ? rawSettings : {};
  const mode = normalizeBackendMode(current.mode);
  const host = pickConfiguredString(current.host, BACKEND_SETTINGS_DEFAULTS.host);
  const port = normalizeBackendPort(current.port);
  const fallbackUrl = buildManagedBackendUrl(host, port);
  const url = mode === "external" ? normalizeBackendUrl(current.url, fallbackUrl) : "";

  return {
    mode,
    host,
    port,
    url,
  };
}
`,
"host,\n    port,\n    url"
);

patch(
  "main.mjs",
`    return {
      ok: true,
      restartRequired: true,
      currentBackendUrl: backendRuntime.getCurrentBackendUrl(),
      ...backendSettings,
    };
`,
`    const currentBackendUrl = backendRuntime.setBackendTarget(backendSettings);

    return {
      ok: true,
      restartRequired: backendSettings.mode !== "external",
      currentBackendUrl,
      ...backendSettings,
    };
`,
"backendRuntime.setBackendTarget"
);

console.log("DONE: in-app backend switching patch applied.");
