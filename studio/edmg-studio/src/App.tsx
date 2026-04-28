import React, { Suspense, lazy, useEffect, useMemo, useState } from "react";
import Sidebar, { Page } from "./components/Sidebar";
import { apiGet, getBackendUrl, getBackendUrlAsync } from "./components/api";

import Dashboard from "./pages/Dashboard";
import Projects from "./pages/Projects";
import Setup from "./pages/Setup";
import { isStudioForgeEnabled } from "./features";

const Workspace = lazy(() => import("./pages/Workspace"));
const Timeline = lazy(() => import("./pages/Timeline"));
const Render = lazy(() => import("./pages/Render"));
const RenderQueue = lazy(() => import("./pages/RenderQueue"));
const Outputs = lazy(() => import("./pages/Outputs"));
const Cloud = lazy(() => import("./pages/Cloud"));
const Settings = lazy(() => import("./pages/Settings"));
const Models = lazy(() => import("./pages/Models"));
const AiPlannerLab = lazy(() => import("./pages/AiPlannerLab"));
const ReactiveLab = lazy(() => import("./pages/ReactiveLab"));
const StudioForge = lazy(() => import("./pages/StudioForge"));

const PAGE_LABELS: Record<Page, string> = {
  dashboard: "Dashboard",
  projects: "Projects",
  workspace: "Workspace",
  timeline: "Timeline",
  render: "Render",
  queue: "Render Queue",
  outputs: "Outputs",
  cloud: "Cloud",
  settings: "Settings",
  setup: "Setup Wizard",
  models: "Models",
  plannerLab: "AI Planner Lab",
  reactiveLab: "Reactive Lab",
  studioForge: "Studio Forge",
};

const PAGE_LOADERS: Partial<Record<Page, () => Promise<unknown>>> = {
  workspace: () => import("./pages/Workspace"),
  timeline: () => import("./pages/Timeline"),
  render: () => import("./pages/Render"),
  queue: () => import("./pages/RenderQueue"),
  outputs: () => import("./pages/Outputs"),
  cloud: () => import("./pages/Cloud"),
  settings: () => import("./pages/Settings"),
  models: () => import("./pages/Models"),
  plannerLab: () => import("./pages/AiPlannerLab"),
  reactiveLab: () => import("./pages/ReactiveLab"),
  studioForge: () => import("./pages/StudioForge"),
};

export function getPageLoadingDetails(page: Page): { label: string; detail: string } {
  const label = PAGE_LABELS[page];
  const detailByPage: Record<Page, string> = {
    dashboard: "Refreshing status cards and studio overview context.",
    projects: "Loading project cards and recent session context.",
    workspace: "Preparing ingest, planning, and creative direction controls.",
    timeline: "Preparing transport, cue, and arrangement controls.",
    render: "Loading render presets, engines, and output actions.",
    queue: "Loading queue state, progress, and retry controls.",
    outputs: "Loading generated media, active jobs, and review actions.",
    cloud: "Loading remote integration settings and bundle actions.",
    settings: "Loading desktop backend, storage, and preference controls.",
    setup: "Loading runtime health, installers, and dependency checks.",
    models: "Loading model packs, availability, and install actions.",
    plannerLab: "Preparing AI planning tools and Studio handoff controls.",
    reactiveLab: "Preparing audio-reactive scheduling and handoff controls.",
    studioForge: "Preparing runtime preview cards and builder recipe registries.",
  };
  return { label, detail: detailByPage[page] };
}

export function getPagesToPreload(page: Page): Page[] {
  const preloadByPage: Record<Page, Page[]> = {
    dashboard: ["projects", "workspace", "setup"],
    projects: ["workspace", "dashboard"],
    workspace: ["timeline", "render", "plannerLab", "reactiveLab"],
    timeline: ["render", "outputs", "workspace"],
    render: ["queue", "outputs", "timeline"],
    queue: ["outputs", "render"],
    outputs: ["render", "queue"],
    cloud: ["settings", "models"],
    settings: ["setup", "cloud", "models"],
    setup: ["workspace", "models", "settings"],
    models: ["render", "setup", "workspace"],
    plannerLab: ["workspace", "timeline", "render"],
    reactiveLab: ["workspace", "timeline", "outputs"],
    studioForge: ["setup", "models", "render"],
  };
  return preloadByPage[page];
}

const BASE_PAGES: Page[] = [
  "dashboard",
  "projects",
  "workspace",
  "timeline",
  "render",
  "queue",
  "outputs",
  "cloud",
  "settings",
  "setup",
  "models",
  "plannerLab",
  "reactiveLab",
];

function getAllowedPages(): Page[] {
  return isStudioForgeEnabled() ? [...BASE_PAGES, "studioForge"] : BASE_PAGES;
}

function isPage(value: string): value is Page {
  return getAllowedPages().includes(value as Page);
}

function getInitialPage(): Page {
  if (typeof window === "undefined") return "dashboard";
  const raw = new URLSearchParams(window.location.search).get("page");
  return raw && isPage(raw) ? raw : "dashboard";
}

function getForcedPage(): Page | null {
  if (typeof window === "undefined") return null;
  const raw = new URLSearchParams(window.location.search).get("page");
  return raw && isPage(raw) ? raw : null;
}

function PageLoadingFallback({ page }: { page: Page }) {
  const loading = getPageLoadingDetails(page);
  return (
    <div className="card">
      <div style={{ fontWeight: 800, marginBottom: 8 }}>Loading studio screen</div>
      <div className="small">
        Preparing <b>{loading.label}</b>.
      </div>
      <div className="small" style={{ marginTop: 8, opacity: 0.84 }}>
        {loading.detail}
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>(getInitialPage);
  const [forcedPage] = useState<Page | null>(getForcedPage);
  const [backendUrl, setBackendUrl] = useState<string>("");
  const [config, setConfig] = useState<any>(null);
  const [backendConfigError, setBackendConfigError] = useState<string>("");
  const [setupChecked, setSetupChecked] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const url = await getBackendUrlAsync();
        if (alive) setBackendUrl(url);
      } catch {
        if (alive) setBackendUrl(getBackendUrl());
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!backendUrl) return;
    apiGet("/v1/config")
      .then((nextConfig) => {
        setConfig(nextConfig);
        setBackendConfigError("");
      })
      .catch((error: any) => {
        setConfig(null);
        setBackendConfigError(String(error?.message ?? error));
      });
  }, [backendUrl]);

  useEffect(() => {
    if (!backendUrl || setupChecked) return;
    apiGet("/v1/setup/status")
      .then((s) => {
        const aiConfig = s?.ai_config ?? {};
        const ollamaRequired = !!aiConfig?.ollama_required;
        const modelRequired = !!aiConfig?.model_required;
        const backendBundleOk = !!s?.backend_bundle?.ok;
        const ffmpegOk = !!s?.ffmpeg?.ok;
        const ollamaOk = !!s?.ollama?.ok;
        const modelOk = !modelRequired || !!s?.ollama?.model_present;
        const need = !(backendBundleOk && ffmpegOk && (!ollamaRequired || (ollamaOk && modelOk)));
        if (need && !forcedPage) setPage("setup" as any);
        setSetupChecked(true);
      })
      .catch(() => setSetupChecked(true));
  }, [backendUrl, forcedPage, setupChecked]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const preloadTargets = getPagesToPreload(page)
      .filter((candidate) => candidate !== page)
      .filter((candidate) => candidate !== "studioForge" || isStudioForgeEnabled());

    if (!preloadTargets.length) return;

    let canceled = false;
    const runPreload = () => {
      if (canceled) return;
      preloadTargets.forEach((candidate) => {
        void PAGE_LOADERS[candidate]?.();
      });
    };

    const requestIdle = window.requestIdleCallback;
    if (typeof requestIdle === "function") {
      const idleId = requestIdle(runPreload, { timeout: 1200 });
      return () => {
        canceled = true;
        window.cancelIdleCallback?.(idleId);
      };
    }

    const timeoutId = window.setTimeout(runPreload, 150);
    return () => {
      canceled = true;
      window.clearTimeout(timeoutId);
    };
  }, [page]);

  const commonProps = useMemo(() => ({ backendUrl, config }), [backendUrl, config]);

  if (!backendUrl) {
    return (
      <div className="app-shell">
        <Sidebar page={page} onNavigate={setPage} />
        <div className="main">
          <div className="card">
            <div style={{ fontWeight: 800, marginBottom: 8 }}>Connecting to Studio backend</div>
            <div className="small">Resolving the active backend target before loading workspace screens.</div>
          </div>
        </div>
      </div>
    );
  }

  let content: React.ReactNode = null;
  if (page === "dashboard") content = <Dashboard {...commonProps} />;
  if (page === "projects") content = <Projects {...commonProps} />;
  if (page === "workspace") content = <Workspace {...commonProps} onNavigate={setPage as any} />;
  if (page === "timeline") content = <Timeline {...commonProps} onNavigate={setPage as any} />;
  if (page === "render") content = <Render {...commonProps} onNavigate={setPage as any} />;
  if (page === "queue") content = <RenderQueue {...commonProps} onNavigate={setPage as any} />;
  if (page === "outputs") content = <Outputs {...commonProps} onNavigate={setPage as any} />;
  if (page === "cloud") content = <Cloud {...commonProps} />;
  if (page === "settings") content = <Settings {...commonProps} />;
  if (page === "setup") content = <Setup onNavigate={setPage as any} />;
  if (page === "models") content = <Models {...commonProps} />;
  if (page === "plannerLab")
    content = <AiPlannerLab {...commonProps} onNavigate={setPage as any} />;
  if (page === "reactiveLab")
    content = <ReactiveLab {...commonProps} onNavigate={setPage as any} />;
  if (page === "studioForge" && isStudioForgeEnabled())
    content = <StudioForge {...commonProps} onNavigate={setPage as any} />;
  if (page === "studioForge" && !isStudioForgeEnabled())
    content = <Dashboard {...commonProps} />;

  const mainClassName = page === "timeline" ? "main main--timeline" : "main";

  return (
    <div className="app-shell">
      <Sidebar page={page} onNavigate={setPage} />
      <div className={mainClassName}>
        {backendConfigError ? (
          <div className="card" style={{ marginBottom: 14, borderColor: "var(--warning, #b58900)" }}>
            <div style={{ fontWeight: 800, marginBottom: 8 }}>Backend connection needs attention</div>
            <div className="small" style={{ marginBottom: 8 }}>
              Studio resolved <b>{backendUrl}</b> but could not load `/v1/config` from it.
            </div>
            <div className="small" style={{ opacity: 0.84 }}>
              If you intended to attach the desktop GUI to an external backend, open Settings and review Desktop Backend mode, host, and port. Error: {backendConfigError}
            </div>
          </div>
        ) : null}
        <Suspense fallback={<PageLoadingFallback page={page} />}>
          {content}
        </Suspense>
      </div>
    </div>
  );
}
