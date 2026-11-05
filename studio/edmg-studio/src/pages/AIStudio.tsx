import React from "react";
import { apiGet, apiPost, isProjectRevisionConflict } from "../components/api";
import AiNlpWorkbench from "../workbenches/AiNlpWorkbench";
import AudioReactiveWorkbench from "../workbenches/AudioReactiveWorkbench";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";
import type { PageProps } from "../types/pageProps";

type Stage = "evidence" | "direction" | "motion" | "review";

export default function AIStudio({ onNavigate }: PageProps) {
  const { projects, projectId, setProjectId, selectedVariant, project, refreshProject } = useStudioWorkbenchProject();
  const [stage, setStage] = React.useState<Stage>("evidence");
  const [workflow, setWorkflow] = React.useState<any>(null);
  const [message, setMessage] = React.useState("");

  const loadWorkflow = React.useCallback(async () => {
    if (!projectId) { setWorkflow(null); return null; }
    const next = await apiGet(`/v1/projects/${encodeURIComponent(projectId)}/director/workflow`);
    setWorkflow(next);
    return next;
  }, [projectId]);

  React.useEffect(() => {
    setMessage("");
    void loadWorkflow().catch((error) => setMessage(`Workflow unavailable: ${String(error)}`));
  }, [loadWorkflow]);

  const syncPlanner = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project first.");
    await apiPost(`/v1/projects/${encodeURIComponent(projectId)}/planner_lab/import`, payload);
    await refreshProject(projectId);
    await loadWorkflow();
    setStage("direction");
    return "Evidence and direction imported. Review the Director draft before moving to motion.";
  };

  const reviewMotion = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project first.");
    const current = await loadWorkflow();
    if (!current?.draft || current.status !== "draft") throw new Error("Prepare a current Director draft before reviewing motion.");
    try {
      const reviewed = await apiPost(`/v1/projects/${encodeURIComponent(projectId)}/director/workflow/reactive/review`, {
        draft_id: current.draft.draft_id,
        expected_revision: current.revision,
        payload,
      });
      setWorkflow(reviewed);
      setStage("review");
      return "Motion plan reviewed and held for approval. Nothing was applied to the timeline.";
    } catch (error) {
      if (isProjectRevisionConflict(error)) await loadWorkflow();
      throw error;
    }
  };

  const applyApproved = async () => {
    if (!projectId || !workflow?.draft) throw new Error("There is no reviewable Director draft.");
    const applied = await apiPost(`/v1/projects/${encodeURIComponent(projectId)}/director/workflow/reactive/apply`, {
      draft_id: workflow.draft.draft_id,
      expected_revision: workflow.revision,
    });
    setWorkflow(applied);
    await refreshProject(projectId);
    setMessage("Approved direction and motion plan applied to the canonical timeline.");
  };

  const stages: Array<{ id: Stage; label: string; detail: string }> = [
    { id: "evidence", label: "Evidence", detail: "Analysis, transcript, energy, and source context" },
    { id: "direction", label: "Direction", detail: "Planner + Director intent and scene constraints" },
    { id: "motion", label: "Motion & Reactivity", detail: "Constrained camera, motion, cues, and Parseq" },
    { id: "review", label: "Review", detail: "Approve the complete handoff before Render" },
  ];

  return (
    <div className="space-y-6">
      <div className="card">
        <div className="timeline-kicker">Unified creative control plane</div>
        <h1>AI Studio</h1>
        <p className="small">Evidence informs direction; direction constrains motion; review is required before the timeline or renderer changes.</p>
        <div className="studio-workbenchProjectRow">
          <label className="studio-workbenchField"><span>Studio project</span>
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {!projects.length && <option value="">No projects yet</option>}
              {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <div className="studio-workbenchMeta"><span>Workflow</span><strong>{workflow?.status || "not prepared"}</strong></div>
          <div className="studio-workbenchMeta"><span>Motion plan</span><strong>{workflow?.motion_plan?.status || "draft"}</strong></div>
        </div>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="AI Studio stages">
          {stages.map((item) => <button key={item.id} className={stage === item.id ? "primary" : "secondary"} onClick={() => setStage(item.id)}>{item.label}</button>)}
        </div>
        {message && <div className="small" role="status">{message}</div>}
      </div>

      {stage === "evidence" && <AiNlpWorkbench studioProjectId={projectId} studioProjectName={project?.name || ""} studioProject={project} studioSelectedVariant={selectedVariant} onSyncToStudio={syncPlanner} />}
      {stage === "direction" && <>
        <div className="card"><h2>Director direction</h2><p className="small">Planner output is imported as a draft. The Director remains the source of scene identity, timing, continuity, and creative constraints.</p><div className="row studio-workbenchActions"><button onClick={() => onNavigate?.("workspace")}>Open Workspace</button><button className="secondary" onClick={() => onNavigate?.("directorLab")}>Focused Director view</button></div></div>
        <AiNlpWorkbench studioProjectId={projectId} studioProjectName={project?.name || ""} studioProject={project} studioSelectedVariant={selectedVariant} onSyncToStudio={syncPlanner} />
      </>}
      {stage === "motion" && <>
        <div className="card"><h2>Motion &amp; Reactivity</h2><p className="small">Reactive Lab reads the approved Director draft and produces constrained motion overrides, camera schedules, cue events, and renderer handoff data.</p></div>
        <AudioReactiveWorkbench studioProjectId={projectId} studioProjectName={project?.name || ""} studioProject={project} studioReactiveDraft={workflow?.reactive} studioWorkflowDraftId={workflow?.draft?.draft_id} studioSelectedVariant={selectedVariant} onSyncToStudio={reviewMotion} />
      </>}
      {stage === "review" && <div className="card">
        <h2>Review and apply</h2>
        <p className="small">Review is explicit. Applying here updates the canonical direction, motion track, camera data, and render handoff together.</p>
        <div className="grid gap-3 md:grid-cols-3"><div><span className="small">Direction</span><strong>{workflow?.status || "not prepared"}</strong></div><div><span className="small">Motion</span><strong>{workflow?.motion_plan?.status || "draft"}</strong></div><div><span className="small">Render handoff</span><strong>{workflow?.motion_plan?.parseq_manifest ? "Parseq ready" : "Generated from schedule"}</strong></div></div>
        <div className="row studio-workbenchActions"><button className="primary" disabled={workflow?.motion_plan?.status !== "reviewed"} onClick={() => void applyApproved().catch((error) => setMessage(String(error)))}>Apply approved Studio plan</button><button className="secondary" onClick={() => onNavigate?.("render")}>Open Render</button><button className="secondary" onClick={() => onNavigate?.("timeline")}>Inspect Timeline</button></div>
      </div>}
    </div>
  );
}
