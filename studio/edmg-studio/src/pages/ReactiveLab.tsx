import React from "react";
import { apiGet, apiPost, isProjectRevisionConflict } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { useStudioPageLayout } from "../components/studioLayout";
import AudioReactiveWorkbench from "../workbenches/AudioReactiveWorkbench";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";
import type { PageProps } from "../types/pageProps";

type ReactiveLabPanelId = "bridge" | "reactiveWorkbench";

export default function ReactiveLab({ onNavigate }: PageProps) {
  const { projects, projectId, setProjectId, selectedVariant, project, refreshProject } = useStudioWorkbenchProject();
  const [workflow, setWorkflow] = React.useState<any>(null);
  const [workflowMessage, setWorkflowMessage] = React.useState("");

  const loadWorkflow = React.useCallback(async () => {
    if (!projectId) {
      setWorkflow(null);
      return null;
    }
    const next = await apiGet(`/v1/projects/${encodeURIComponent(projectId)}/director/workflow`);
    setWorkflow(next);
    return next;
  }, [projectId]);

  React.useEffect(() => {
    setWorkflowMessage("");
    void loadWorkflow().catch((reason) => setWorkflowMessage(`Workflow unavailable: ${String(reason)}`));
  }, [loadWorkflow]);

  const syncReactiveLab = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project before applying reactive motion to the renderer.");
    const current = await loadWorkflow();
    if (!current?.draft || current.status === "not_prepared") {
      throw new Error("No Workspace draft is prepared. Prepare direction in Workspace before reviewing reactive motion.");
    }
    if (current.status === "stale") {
      throw new Error("This Workspace draft is stale. Refresh or prepare it again before applying reactive motion.");
    }
    if (current.status === "applied") {
      throw new Error("The current Workspace draft is already applied. Prepare a new draft before making another reactive pass.");
    }
    try {
      const reviewed = await apiPost(
        `/v1/projects/${encodeURIComponent(projectId)}/director/workflow/reactive/review`,
        { draft_id: current.draft.draft_id, expected_revision: current.revision, payload },
      );
      const applied = await apiPost(
        `/v1/projects/${encodeURIComponent(projectId)}/director/workflow/apply`,
        { draft_id: reviewed.draft.draft_id, expected_revision: reviewed.revision },
      );
      setWorkflow(applied);
    } catch (reason) {
      if (isProjectRevisionConflict(reason)) {
        await loadWorkflow();
        throw new Error("The project changed while you were reviewing it. Your local edits are preserved; refresh the draft and review again.");
      }
      throw reason;
    }
    await refreshProject(projectId);
    return `${project?.name || "Selected project"} now uses the reviewed reactive draft. The previous Timeline remained active until this explicit apply.`;
  };

  const panelDefinitions = React.useMemo(
    () => [
      {
        id: "bridge" as const,
        label: "Studio bridge",
        description: "Project targeting, renderer handoff context, and navigation back into the main Studio flow.",
      },
      {
        id: "reactiveWorkbench" as const,
        label: "Reactive workbench",
        description: "Embedded audio-reactive workspace and sync handoff into the selected Studio project.",
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
  } = useStudioPageLayout<ReactiveLabPanelId>(
    "reactive_lab",
    panelDefinitions.map((panel) => panel.id),
  );
  const panelDefinitionById = React.useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<ReactiveLabPanelId, (typeof panelDefinitions)[number]>,
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

  const panelContent: Record<ReactiveLabPanelId, React.ReactNode> = {
    bridge: (
      <div className="card studio-workbenchBridge">
        <div>
          <div className="timeline-kicker">Studio Workbench</div>
          <h2>Reactive bridge</h2>
          <div className="small studio-workbenchCopy">
            Generate audio-reactive schedules, cue events, and handoff manifests here, then
            continue in Workspace, Timeline, and Render with the canonical Studio flow.
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
          <button onClick={() => onNavigate?.("timeline")}>Timeline</button>
          <button className="secondary" onClick={() => onNavigate?.("render")}>
            Render
          </button>
          <button className="secondary" onClick={() => onNavigate?.("outputs")}>
            Outputs
          </button>
        </div>
        <div className="small" role="status">
         {workflowMessage || (workflow?.status === "not_prepared"
           ? "No Workspace draft is prepared. Prepare direction in Workspace before editing reactive keyframes."
           : workflow?.status === "stale"
             ? "The prepared Workspace draft is stale. Your local Reactive Lab edits are preserved; refresh or prepare the draft again before apply."
             : workflow?.draft
               ? `Workspace draft ${workflow.draft.draft_id} · ${workflow.status}`
               : "Loading the shared Workspace draft…")}
        </div>
      </div>
    ),
    reactiveWorkbench: (
      <AudioReactiveWorkbench
        studioProjectId={projectId}
        studioProjectName={project?.name || ""}
        studioProject={project}
        studioReactiveDraft={workflow?.reactive}
        studioWorkflowDraftId={workflow?.draft?.draft_id}
        studioSelectedVariant={selectedVariant}
        onSyncToStudio={syncReactiveLab}
      />
    ),
  };

  return (
    <div>
      <h1>Reactive Lab</h1>
      <div className="small" style={{ marginTop: 6 }}>
        Reorder or hide the bridge and reactive workbench sections for your own motion-design flow. This only changes the local Labs layout and does not alter project sync, cue generation, Timeline, Render, or Outputs behavior.
      </div>
      <StudioLayoutCustomizer
        title="Reactive Lab layout"
        description="Reorder or hide the Studio bridge and reactive workbench without changing reactive apply behavior or internal renderer handoff."
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
