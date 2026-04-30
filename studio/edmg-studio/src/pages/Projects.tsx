import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { useStudioPageLayout } from "../components/studioLayout";
import type { PageProps } from "../types/pageProps";

type ProjectsPanelId = "composer" | "library" | "workflow";

export default function Projects(_props: PageProps) {
  const [projects, setProjects] = useState<any[]>([]);
  const [name, setName] = useState("My Project");
  const [err, setErr] = useState<string | null>(null);

  const refresh = () =>
    apiGet("/v1/projects")
      .then((d) => setProjects(d.projects || []))
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    refresh();
  }, []);

  const panelDefinitions = useMemo(
    () => [
      {
        id: "composer" as const,
        label: "Create project",
        description: "Create a project or refresh the current Studio project list.",
      },
      {
        id: "library" as const,
        label: "Project library",
        description: "Existing Studio projects stored in the current backend workspace.",
      },
      {
        id: "workflow" as const,
        label: "Workflow handoff",
        description: "Next steps after creating a project.",
      },
    ],
    [],
  );
  const {
    layoutState,
    visibleOrder,
    movePanel,
    updateHidden,
    resetLayout,
  } = useStudioPageLayout<ProjectsPanelId>(
    "projects",
    panelDefinitions.map((panel) => panel.id),
  );
  const panelDefinitionById = useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<ProjectsPanelId, (typeof panelDefinitions)[number]>,
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

  const create = async () => {
    setErr(null);
    try {
      await apiPost("/v1/projects", { name });
      await refresh();
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const panelContent: Record<ProjectsPanelId, React.ReactNode> = {
    composer: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Create project</div>
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} />
          <button onClick={create}>Create</button>
          <button className="secondary" onClick={refresh}>
            Refresh
          </button>
        </div>
        {err && <div style={{ color: "var(--danger)", marginTop: 10 }}>{err}</div>}
      </div>
    ),
    library: (
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontWeight: 800 }}>Project library</div>
          <div className="small" style={{ opacity: 0.8 }}>
            {projects.length} project{projects.length === 1 ? "" : "s"}
          </div>
        </div>
        {!projects.length ? <div className="small" style={{ marginTop: 10 }}>No projects yet.</div> : null}
        {projects.length ? (
          <div className="grid2" style={{ marginTop: 10 }}>
            {projects.map((project) => (
              <div key={project.id} className="card" style={{ margin: 0 }}>
                <div style={{ fontWeight: 800 }}>{project.name}</div>
                <div className="small">{project.id}</div>
                <div className="small">created: {project.created_at}</div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    ),
    workflow: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Workflow handoff</div>
        <div className="small">
          Use Workspace to select a project and run audio/plan/render/export.
        </div>
      </div>
    ),
  };

  return (
    <div>
      <h1>Projects</h1>
      <StudioLayoutCustomizer
        title="Project layout"
        description="Reorder or hide Project page panels without changing project storage, selection, or render behavior."
        items={panelControlItems}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      <div className="grid2">
        {visibleOrder.map((panelId) => (
          <React.Fragment key={panelId}>{panelContent[panelId]}</React.Fragment>
        ))}
      </div>
    </div>
  );
}
