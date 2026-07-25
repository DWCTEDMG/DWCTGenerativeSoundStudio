import React from "react";
import { apiPost } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { useStudioPageLayout } from "../components/studioLayout";
import AiNlpWorkbench from "../workbenches/AiNlpWorkbench";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";
import type { PageProps } from "../types/pageProps";

type AiPlannerLabPanelId = "bridge" | "plannerWorkbench";

export default function AiPlannerLab({ onNavigate }: PageProps) {
  const { projects, projectId, setProjectId, selectedVariant, project, refreshProject } = useStudioWorkbenchProject();

  const syncPlannerLab = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project before syncing the planner into the renderer.");
    await apiPost(`/v1/projects/${projectId}/planner_lab/import`, payload);
    await refreshProject(projectId);
    return `${project?.name || "Selected project"} now has the planner lab analysis, canonical plan, and renderer prompt/motion tracks applied.`;
  };

  const panelDefinitions = React.useMemo(
    () => [
      {
        id: "bridge" as const,
        label: "Studio bridge",
        description: "Project targeting, renderer handoff context, and navigation back into the main Studio flow.",
      },
      {
        id: "plannerWorkbench" as const,
        label: "Planner workbench",
        description: "Embedded browser-side planning workspace and sync handoff into the selected Studio project.",
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
  } = useStudioPageLayout<AiPlannerLabPanelId>(
    "planner_lab",
    panelDefinitions.map((panel) => panel.id),
  );
  const panelDefinitionById = React.useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<AiPlannerLabPanelId, (typeof panelDefinitions)[number]>,
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

  const panelContent: Record<AiPlannerLabPanelId, React.ReactNode> = {
    bridge: (
      <div className="card studio-workbenchBridge">
        <div>
          <div className="timeline-kicker">Studio Workbench</div>
          <h2>AI Planner bridge</h2>
          <div className="small studio-workbenchCopy">
            Run the browser-side audio and NLP planning pass here, then continue in Workspace,
            Timeline, and Render with the canonical Studio flow.
          </div>
        </div>
        <div className="studio-workbenchProjectRow">
          <label className="studio-workbenchField">
            <span>Studio project</span>
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {!projects.length && <option value="">No projects yet</option>}
              {projects.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="studio-workbenchMeta">
            <span>Renderer target</span>
            <strong>{project?.name || "Select a project"}</strong>
          </div>
        </div>
        <div className="row studio-workbenchActions">
          <button onClick={() => onNavigate?.("workspace")}>Workspace</button>
          <button className="secondary" onClick={() => onNavigate?.("timeline")}>
            Timeline
          </button>
          <button className="secondary" onClick={() => onNavigate?.("render")}>
            Render
          </button>
        </div>
      </div>
    ),
    plannerWorkbench: (
      <AiNlpWorkbench
        studioProjectId={projectId}
        studioProjectName={project?.name || ""}
        studioProject={project}
        studioSelectedVariant={selectedVariant}
        onSyncToStudio={syncPlannerLab}
      />
    ),
  };

  return (
    <div>
      <h1>AI Planner Lab</h1>
      <div className="small" style={{ marginTop: 6 }}>
        Reorder or hide the bridge and planner workbench sections for your own planning flow. This only changes the local Labs layout and does not alter project sync, Workspace, Timeline, or Render behavior.
      </div>
      <StudioLayoutCustomizer
        title="AI Planner Lab layout"
        description="Reorder or hide the Studio bridge and planner workbench without changing project imports, canonical plans, or renderer handoff."
        items={panelControlItems}
        profileOptions={profileOptions}
        activeProfile={activeProfile}
        onSelectProfile={setActiveProfile}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      <div className="studio-workbenchHost">
        {visibleOrder.map((panelId) => (
          <React.Fragment key={panelId}>{panelContent[panelId]}</React.Fragment>
        ))}
      </div>
    </div>
  );
}
