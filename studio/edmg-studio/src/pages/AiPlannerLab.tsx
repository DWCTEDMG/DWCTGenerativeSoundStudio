import React from "react";
import { apiPost } from "../components/api";
import AiNlpWorkbench from "../workbenches/AiNlpWorkbench";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";
import type { PageProps } from "../types/pageProps";

export default function AiPlannerLab({ onNavigate }: PageProps) {
  const { projects, projectId, setProjectId, project, refreshProject } = useStudioWorkbenchProject();

  const syncPlannerLab = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project before syncing the planner into the renderer.");
    await apiPost(`/v1/projects/${projectId}/planner_lab/import`, payload);
    await refreshProject(projectId);
    return `${project?.name || "Selected project"} now has the planner lab analysis, canonical plan, and renderer prompt/motion tracks applied.`;
  };

  return (
    <div className="studio-workbenchHost">
      <div className="card studio-workbenchBridge">
        <div>
          <div className="timeline-kicker">Studio Workbench</div>
          <h1>AI Planner Lab</h1>
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
      <AiNlpWorkbench
        studioProjectId={projectId}
        studioProjectName={project?.name || ""}
        onSyncToStudio={syncPlannerLab}
      />
    </div>
  );
}
