import React from "react";
import { apiPost } from "../components/api";
import AudioReactiveWorkbench from "../workbenches/AudioReactiveWorkbench";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";
import type { PageProps } from "../types/pageProps";

export default function ReactiveLab({ onNavigate }: PageProps) {
  const { projects, projectId, setProjectId, project, refreshProject } = useStudioWorkbenchProject();

  const syncReactiveLab = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project before applying reactive motion to the renderer.");
    await apiPost(`/v1/projects/${projectId}/reactive_lab/apply`, payload);
    await refreshProject(projectId);
    return `${project?.name || "Selected project"} now has the reactive motion track and camera data wired into the internal renderer timeline.`;
  };

  return (
    <div className="studio-workbenchHost">
      <div className="card studio-workbenchBridge">
        <div>
          <div className="timeline-kicker">Studio Workbench</div>
          <h1>Reactive Lab</h1>
          <div className="small studio-workbenchCopy">
            Generate audio-reactive schedules, cue events, and handoff manifests here, then
            shape timing and renders in the main Studio timeline.
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
          <button onClick={() => onNavigate?.("timeline")}>Timeline</button>
          <button className="secondary" onClick={() => onNavigate?.("render")}>
            Render
          </button>
          <button className="secondary" onClick={() => onNavigate?.("outputs")}>
            Outputs
          </button>
        </div>
      </div>
      <AudioReactiveWorkbench
        studioProjectId={projectId}
        studioProjectName={project?.name || ""}
        onSyncToStudio={syncReactiveLab}
      />
    </div>
  );
}
