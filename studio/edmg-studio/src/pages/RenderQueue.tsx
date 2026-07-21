import React, { useEffect, useMemo, useState } from "react";
import { apiGet, getBackendUrl } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { useStudioPageLayout } from "../components/studioLayout";
import { ProjectJobsPanel } from "../shared/jobs/ProjectJobsPanel";
import { useProjectJobs } from "../shared/jobs/useProjectJobs";
import type { PageProps } from "../types/pageProps";

type RenderQueuePanelId = "controls" | "jobs";

export default function RenderQueue(props: PageProps) {
  const backendUrl = props.backendUrl || getBackendUrl();
  const [projects, setProjects] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [info, setInfo] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const {
    jobs,
    selectedLog,
    setSelectedLog,
    lastRefreshAt,
    error,
    setError,
    refresh,
    loadJobLog,
    runJobAction,
    resumeFromCheckpoint,
    restartClean,
    tickWorker,
  } = useProjectJobs({ global: true, autoRefresh, refreshIntervalMs: 2500 });

  useEffect(() => {
    apiGet("/v1/projects")
      .then((payload) => {
        const ps = payload.projects || [];
        setProjects(ps);
        if (!projectId && ps.length) setProjectId(ps[0].id);
      })
      .catch((err) => setError(String(err)));
  }, [backendUrl, projectId, setError]);

  const filtered = projectId ? jobs.filter((job) => job.project_id === projectId) : jobs;

  const panelDefinitions = useMemo(
    () => [
      {
        id: "controls" as const,
        label: "Queue controls",
        description: "Worker tick, refresh, project filter, live polling, and desktop action status.",
      },
      {
        id: "jobs" as const,
        label: "Jobs table",
        description: "Queue state, progress, checkpoints, logs, and retry or resume actions.",
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
  } = useStudioPageLayout<RenderQueuePanelId>(
    "render_queue",
    panelDefinitions.map((panel) => panel.id),
  );
  const panelDefinitionById = useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<RenderQueuePanelId, (typeof panelDefinitions)[number]>,
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

  const panelContent: Record<RenderQueuePanelId, React.ReactNode> = {
    controls: (
      <div className="card" style={{ marginTop: 14 }}>
        <div className="row">
          <button onClick={() => void tickWorker()}>Tick Worker (process 1 job)</button>
          <button className="secondary" onClick={() => void refresh()}>Refresh</button>
          <div style={{ flex: 1 }} />
          <div>
            <div className="small">Project</div>
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="small" style={{ marginTop: 10 }}>
          This is intentionally local-first for reliability. The backend runs an always-on worker by default; use this view for logs, resume actions, and clean restarts.
        </div>
        {error ? <div style={{ marginTop: 10, color: "var(--danger)" }}>{error}</div> : null}
        {!error && info ? <div className="small" style={{ marginTop: 10, opacity: 0.82 }}>{info}</div> : null}
      </div>
    ),
    jobs: (
      <ProjectJobsPanel
        backendUrl={backendUrl}
        jobs={filtered}
        selectedLog={selectedLog}
        lastRefreshAt={lastRefreshAt}
        error={error}
        info={info}
        autoRefresh={autoRefresh}
        onAutoRefreshChange={setAutoRefresh}
        onRefresh={refresh}
        onViewLog={loadJobLog}
        onCloseLog={() => setSelectedLog(null)}
        onJobAction={runJobAction}
        onResumeFromCheckpoint={resumeFromCheckpoint}
        onRestartClean={restartClean}
        onDesktopActionMessage={setInfo}
        onDesktopActionError={(message) => {
          setInfo(null);
          setError(message);
        }}
        title="Render jobs"
        description="Pause, cancel, retry, reveal outputs, and inspect logs. Controls match Review and Render Lab."
      />
    ),
  };

  return (
    <div>
      <h1>Render Queue</h1>
      <div className="small" style={{ marginTop: 6 }}>
        Reorder or hide queue sections for your own troubleshooting flow. This only changes the local page layout and does not affect the worker, retries, or backend queue state.
      </div>
      <StudioLayoutCustomizer
        title="Render Queue layout"
        description="Reorder or hide queue panels without changing worker execution, logs, checkpoints, or retry behavior."
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
