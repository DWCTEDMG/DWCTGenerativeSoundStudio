import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { useStudioPageLayout } from "../components/studioLayout";
import type { PageProps } from "../types/pageProps";

type DashboardPanelId = "backend" | "config" | "edmg" | "workflow";

export default function Dashboard({ backendUrl, config }: PageProps) {
  const [health, setHealth] = useState<any>(null);
  const [edmg, setEdmg] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiGet("/health").then(setHealth).catch((e) => setErr(String(e)));
    apiGet("/v1/edmg/status").then(setEdmg).catch(() => {});
  }, [backendUrl]);

  const panelDefinitions = useMemo(
    () => [
      {
        id: "backend" as const,
        label: "Backend",
        description: "Current backend endpoint and raw health payload.",
      },
      {
        id: "config" as const,
        label: "Config",
        description: "Active Studio config snapshot passed into the shell.",
      },
      {
        id: "edmg" as const,
        label: "EDMG Core",
        description: "Optional EDMG Core integration status and handoff guidance.",
      },
      {
        id: "workflow" as const,
        label: "Workflow",
        description: "Current production flow from project creation through export.",
      },
    ],
    [],
  );
  const { profileOptions, activeProfile, setActiveProfile, layoutState, visibleOrder, movePanel, updateHidden, resetLayout } =
    useStudioPageLayout<DashboardPanelId>(
      "dashboard",
      panelDefinitions.map((panel) => panel.id),
    );
  const panelDefinitionById = useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<DashboardPanelId, (typeof panelDefinitions)[number]>,
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

  const panelContent: Record<DashboardPanelId, React.ReactNode> = {
    backend: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Backend</div>
        <div className="small">{backendUrl}</div>
        <hr />
        {health && <pre>{JSON.stringify(health, null, 2)}</pre>}
      </div>
    ),
    config: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Config</div>
        {!config && <div className="small">Loading…</div>}
        {config && <pre>{JSON.stringify(config, null, 2)}</pre>}
      </div>
    ),
    edmg: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>EDMG Core</div>
        {!edmg && <div className="small">Not detected (optional).</div>}
        {edmg && <pre>{JSON.stringify(edmg, null, 2)}</pre>}
        <div className="small" style={{ marginTop: 10 }}>
          Studio backend installs now target EDMG Core by default. If it is missing here, repair it from Setup.
        </div>
      </div>
    ),
    workflow: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Workflow</div>
        <ol style={{ margin: 0, paddingLeft: 18, color: "var(--text)" }}>
          <li>Create a project</li>
          <li>Upload audio</li>
          <li>Analyze/transcribe</li>
          <li>Generate plan variants</li>
          <li>Render with the internal renderer by default, or use ComfyUI optionally</li>
          <li>Assemble MP4 (FFmpeg)</li>
          <li>Export Deforum JSON (optional)</li>
        </ol>
      </div>
    ),
  };

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="small" style={{ marginTop: 6 }}>
        Reorder or hide overview cards for your own workflow. This only changes the local page layout.
      </div>
      <StudioLayoutCustomizer
        title="Dashboard layout"
        description="Reorder or hide overview panels without changing backend status, EDMG integration, or project data."
        items={panelControlItems}
        profileOptions={profileOptions}
        activeProfile={activeProfile}
        onSelectProfile={setActiveProfile}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      {err && <div style={{ color: "var(--danger)", marginTop: 12 }}>{err}</div>}
      <div className="grid2" style={{ marginTop: 14 }}>
        {visibleOrder.map((panelId) => (
          <React.Fragment key={panelId}>{panelContent[panelId]}</React.Fragment>
        ))}
      </div>
    </div>
  );
}
