import React, { useEffect, useMemo, useState } from "react";
import Sidebar, { Page } from "./components/Sidebar";
import { apiGet, getBackendUrl, getBackendUrlAsync } from "./components/api";

import Dashboard from "./pages/Dashboard";
import Projects from "./pages/Projects";
import Workspace from "./pages/Workspace";
import Timeline from "./pages/Timeline";
import Render from "./pages/Render";
import RenderQueue from "./pages/RenderQueue";
import Outputs from "./pages/Outputs";
import Cloud from "./pages/Cloud";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";
import Models from "./pages/Models";
import AiPlannerLab from "./pages/AiPlannerLab";
import ReactiveLab from "./pages/ReactiveLab";

function isPage(value: string): value is Page {
  const allowed: Page[] = [
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
  return allowed.includes(value as Page);
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

export default function App() {
  const [page, setPage] = useState<Page>(getInitialPage);
  const [forcedPage] = useState<Page | null>(getForcedPage);
  const [backendUrl, setBackendUrl] = useState<string>("");
  const [config, setConfig] = useState<any>(null);
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
      .then(setConfig)
      .catch(() => {});
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

  const commonProps = useMemo(() => ({ backendUrl, config }), [backendUrl, config]);

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

  const mainClassName = page === "timeline" ? "main main--timeline" : "main";

  return (
    <div className="app-shell">
      <Sidebar page={page} onNavigate={setPage} />
      <div className={mainClassName}>{content}</div>
    </div>
  );
}
