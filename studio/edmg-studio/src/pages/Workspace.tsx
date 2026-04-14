import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiUpload, getBackendUrl } from "../components/api";
import { CreativeDirectionPanel } from "../components/CreativeDirectionPanel";
import { ProgressBar } from "../components/ProgressBar";
import { useOperationProgress } from "../components/useOperationProgress";
import { useStudioSession } from "../components/studioSession";
import { useUiMode } from "../components/uiMode";
import type { PageProps } from "../types/pageProps";
import AiNlpWorkbench from "../workbenches/AiNlpWorkbench";
import AudioReactiveWorkbench from "../workbenches/AudioReactiveWorkbench";

type WorkspaceView = "overview" | "planner" | "reactive" | "storyboard";
type OverviewSectionId = "project" | "audio" | "references" | "plan" | "handoff";

const WORKSPACE_MIN_ZOOM = 4;
const WORKSPACE_MAX_ZOOM = 240;

const DEFAULT_OVERVIEW_SECTIONS: Record<OverviewSectionId, boolean> = {
  project: true,
  audio: true,
  references: false,
  plan: true,
  handoff: true,
};

function clampZoom(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min));
}

function bytes(n: number) {
  if (!Number.isFinite(n)) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let u = 0, v = n;
  while (v > 1024 && u < units.length - 1) { v /= 1024; u++; }
  return `${v.toFixed(u === 0 ? 0 : 2)} ${units[u]}`;
}

function sceneDurationSeconds(scene: any, fallback = 5) {
  const start = Number(scene?.start_s ?? 0);
  const end = Number(scene?.end_s ?? start + fallback);
  return Math.max(0.2, end - start || fallback);
}

function resequenceStoryboardScenes(scenes: any[]) {
  let cursor = 0;
  return scenes.map((scene, index) => {
    const duration = sceneDurationSeconds(scene);
    const nextScene = {
      ...scene,
      name: scene?.name || `Scene ${index + 1}`,
      start_s: Number(cursor.toFixed(2)),
      end_s: Number((cursor + duration).toFixed(2)),
    };
    cursor += duration;
    return nextScene;
  });
}

function moveStoryboardItem<T>(items: T[], fromIndex: number, toIndex: number) {
  const next = [...items];
  const [item] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, item);
  return next;
}

function shuffleStoryboardItems<T>(items: T[]) {
  const next = [...items];
  for (let index = next.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [next[index], next[swapIndex]] = [next[swapIndex], next[index]];
  }
  return next;
}

function OverviewSection(props: {
  id: OverviewSectionId;
  title: string;
  description: string;
  progress: number;
  open: boolean;
  onToggle: (id: OverviewSectionId, open: boolean) => void;
  children: React.ReactNode;
}) {
  const { id, title, description, progress, open, onToggle, children } = props;

  return (
    <details
      className={`workspace-accordionSection${open ? " is-open" : ""}`}
      open={open}
      onToggle={(event) => onToggle(id, (event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="workspace-accordionSummary">
        <div className="workspace-accordionHead">
          <div>
            <div className="workspace-sectionTitle">{title}</div>
            <div className="small">{description}</div>
          </div>
          <div className="workspace-accordionMeta">
            <span className="badge">{Math.round(progress)}%</span>
            <ProgressBar value={progress} compact />
          </div>
        </div>
      </summary>
      <div className="workspace-accordionBody">{children}</div>
    </details>
  );
}

export default function Workspace({ onNavigate }: PageProps) {
  const { mode: uiMode } = useUiMode();
  const {
    projectId,
    setProjectId,
    selectedVariant,
    setSelectedVariant,
    lastHandoff,
    noteHandoff,
  } = useStudioSession();
  const backendUrl = useMemo(() => getBackendUrl(), []);
  const [projects, setProjects] = useState<any[]>([]);
  const [project, setProject] = useState<any>(null);

  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [refFile, setRefFile] = useState<File | null>(null);
  const [assets, setAssets] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);

  const [planMode, setPlanMode] = useState<"auto" | "ai" | "local">("auto");

  const [timelineZoom, setTimelineZoom] = useState<number>(60); // px per second
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("overview");
  const [overviewSections, setOverviewSections] =
    useState<Record<OverviewSectionId, boolean>>(DEFAULT_OVERVIEW_SECTIONS);

  const [info, setInfo] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const timelineScrollerRef = useRef<HTMLDivElement | null>(null);
  const previewAutoFitKeyRef = useRef<string>("");
  const { progress, runOperation } = useOperationProgress();

  const refreshProjects = async () => {
    const d = await apiGet("/v1/projects");
    const ps = d.projects || [];
    setProjects(ps);
    if (!projectId && ps.length) setProjectId(ps[0].id);
  };

  const refreshProject = async (id: string) => {
    if (!id) return;
    const d = await apiGet(`/v1/projects/${id}`);
    setProject(d.project);
    setAnalysis(d.project?.meta?.analysis || null);
    setPlan(d.project?.meta?.last_plan || null);
    const variantCount = Array.isArray(d.project?.meta?.last_plan?.variants)
      ? d.project.meta.last_plan.variants.length
      : 0;
    if (variantCount > 0 && selectedVariant > variantCount - 1) setSelectedVariant(0);
    try {
      const a = await apiGet(`/v1/projects/${id}/assets`);
      setAssets(a.assets);
    } catch {
      setAssets(null);
    }
  };

  useEffect(() => { refreshProjects().catch(() => {}); }, []);

  useEffect(() => { if (projectId) refreshProject(projectId).catch(() => {}); }, [projectId]);
  // Workspace stays focused on project + timeline. Rendering lives in the Render page.

  const uploadAudio = async () => {
    if (!audioFile) return;
    setErr(null); setInfo(null);
    try {
      await runOperation(
        {
          label: "Uploading audio",
          detail: audioFile.name,
          successDetail: "Track uploaded and project refreshed.",
        },
        async () => {
          await apiUpload(`/v1/projects/${projectId}/assets/audio`, audioFile);
          await refreshProject(projectId);
        },
      );
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const uploadRef = async () => {
    if (!refFile) return;
    setErr(null); setInfo(null);
    try {
      await runOperation(
        {
          label: "Uploading reference",
          detail: refFile.name,
          successDetail: "Reference image saved to the current project.",
        },
        async () => {
          await apiUpload(`/v1/projects/${projectId}/assets/refs`, refFile);
          setRefFile(null);
          await refreshProject(projectId);
        },
      );
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const runAnalysis = async () => {
    setErr(null); setInfo(null);
    try {
      const d = await runOperation(
        {
          label: "Analyzing audio",
          detail: "Beat detection, transcription, and feature extraction.",
          successDetail: "Analysis complete.",
        },
        () => apiPost(`/v1/projects/${projectId}/analyze_audio`, {}),
      );
      setAnalysis(d);
      await refreshProject(projectId);
    } catch (e: any) { setErr(String(e)); }
  };

  const generatePlan = async () => {
    setErr(null); setInfo(null);
    try {
      const d = await runOperation(
        {
          label: "Generating plan variants",
          detail: `Mode: ${planMode}`,
          successDetail: "Plan variants refreshed for the active project.",
        },
        () =>
          apiPost(`/v1/projects/${projectId}/plan?mode=${planMode}`, {
            title: project?.name || "Untitled",
            style_prefs: "cinematic, coherent subject, high detail, consistent style",
            num_variants: 3,
            max_scenes: 12
          }),
      );
      setPlan(d);
      setSelectedVariant(0);
      await refreshProject(projectId);
    } catch (e: any) { setErr(String(e)); }
  };

  const fileUrl = (pid: string, rel: string) => `${backendUrl}/v1/projects/${pid}/file?path=${encodeURIComponent(rel)}`;

  const variantScenes = plan?.variants?.[selectedVariant]?.scenes || [];
  const durationS = analysis?.features?.duration_s || analysis?.features?.duration || plan?.duration_s || 0;
  const refAssets = Array.isArray(assets?.refs) ? assets.refs : [];
  const variantCount = Array.isArray(plan?.variants) ? plan.variants.length : 0;
  const selectedVariantName =
    plan?.variants?.[selectedVariant]?.name || (variantCount ? `Variant ${selectedVariant + 1}` : "none");
  const analysisReady = Boolean(analysis);
  const audioReady = Boolean(project?.meta?.audio);
  const storyboardReady = Boolean(variantScenes.length);
  const plannerImportedAt = Number(project?.meta?.last_planner_lab?.imported_at || 0);
  const reactiveAppliedAt = Number(project?.meta?.last_reactive_lab?.applied_at || 0);
  const plannerSceneCount = Number(project?.meta?.last_plan?.variants?.[selectedVariant]?.scenes?.length || 0);
  const reactiveSectionCount = Number(project?.meta?.last_reactive_lab?.sections?.length || 0);
  const projectProgress = projectId ? 100 : 0;
  const audioProgress = analysisReady ? 100 : audioReady ? 58 : 0;
  const referenceProgress = refAssets.length ? Math.min(100, 30 + refAssets.length * 22) : 0;
  const planProgress = storyboardReady ? 100 : variantCount ? 70 : 0;
  const handoffProgress = reactiveAppliedAt ? 100 : plannerImportedAt ? 62 : 0;

  const toggleOverviewSection = (sectionId: OverviewSectionId, isOpen: boolean) => {
    setOverviewSections((current) => ({ ...current, [sectionId]: isOpen }));
  };

  const applyTimelinePlan = async (overwrite: boolean) => {
    if (!projectId || !plan?.variants?.length) return;
    setErr(null);
    try {
      await runOperation(
        {
          label: overwrite ? "Overwriting timeline" : "Applying plan to timeline",
          detail: `Variant ${selectedVariant + 1}`,
          successDetail: "Timeline updated from the selected storyboard variant.",
        },
        () =>
          apiPost(`/v1/projects/${projectId}/timeline/apply_plan`, {
            variant_index: selectedVariant,
            overwrite,
          }),
      );
      await refreshProject(projectId);
      setWorkspaceView("storyboard");
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const updateStoryboardScenes = async (nextScenes: any[], detail: string) => {
    if (!projectId || !plan?.variants?.length) return;
    setErr(null);
    const resequencedScenes = resequenceStoryboardScenes(nextScenes);
    try {
      const result = await runOperation(
        {
          label: "Saving storyboard order",
          detail,
          successDetail: "Storyboard order saved to the current project variant.",
        },
        () =>
          apiPost(`/v1/projects/${projectId}/plan/variant`, {
            variant_index: selectedVariant,
            scenes: resequencedScenes,
          }),
      );
      if (result?.plan) setPlan(result.plan);
      await refreshProject(projectId);
    } catch (e: any) {
      setErr(String(e));
    }
  };

  const moveStoryboardScene = async (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction;
    if (!variantScenes.length || nextIndex < 0 || nextIndex >= variantScenes.length) return;
    await updateStoryboardScenes(
      moveStoryboardItem(variantScenes, index, nextIndex),
      `Scene ${index + 1} moved ${direction < 0 ? "earlier" : "later"}.`,
    );
  };

  const shuffleStoryboardScenes = async () => {
    if (variantScenes.length < 2) return;
    await updateStoryboardScenes(shuffleStoryboardItems(variantScenes), "Reordered prompt beats for a different scene flow.");
  };

  const syncPlannerLab = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project before syncing the planner into the renderer.");
    await runOperation(
      {
        label: "Syncing planner handoff",
        detail: "Importing planner scenes and renderer prompts.",
        successDetail: "Planner handoff applied to the current session.",
      },
      async () => {
        await apiPost(`/v1/projects/${projectId}/planner_lab/import`, payload);
        await refreshProject(projectId);
      },
    );
    noteHandoff({
      type: "planner",
      projectId,
      at: Date.now(),
      summary: `${project?.name || "Selected project"} planner scenes and prompt tracks synced.`,
    });
    setWorkspaceView("storyboard");
    return `${project?.name || "Selected project"} now has synced planner analysis, canonical storyboard scenes, and renderer prompt/motion tracks.`;
  };

  const syncReactiveLab = async (payload: any) => {
    if (!projectId) throw new Error("Select a Studio project before applying reactive motion to the renderer.");
    await runOperation(
      {
        label: "Syncing reactive handoff",
        detail: "Applying motion schedules and camera keyframes.",
        successDetail: "Reactive handoff applied to the timeline.",
      },
      async () => {
        await apiPost(`/v1/projects/${projectId}/reactive_lab/apply`, payload);
        await refreshProject(projectId);
      },
    );
    noteHandoff({
      type: "reactive",
      projectId,
      at: Date.now(),
      summary: `${project?.name || "Selected project"} reactive motion track and camera data synced.`,
    });
    return `${project?.name || "Selected project"} now has the reactive motion track and camera data wired into the internal renderer timeline.`;
  };

  const setTimelineZoomWithFocus = (nextZoom: number, focusSeconds?: number) => {
    const scroller = timelineScrollerRef.current;
    const clamped = clampZoom(nextZoom, WORKSPACE_MIN_ZOOM, WORKSPACE_MAX_ZOOM);
    if (!scroller) {
      setTimelineZoom(clamped);
      return;
    }

    const currentZoom = Math.max(1, timelineZoom);
    const rect = scroller.getBoundingClientRect();
    const fallbackFocus = (scroller.scrollLeft + rect.width / 2) / currentZoom;
    const focus = Math.max(0, focusSeconds ?? fallbackFocus);
    setTimelineZoom(clamped);
    requestAnimationFrame(() => {
      const nextLeft = Math.max(0, focus * clamped - rect.width / 2);
      if (typeof scroller.scrollTo === "function") {
        scroller.scrollTo({
          left: nextLeft,
          behavior: "smooth",
        });
      } else {
        scroller.scrollLeft = nextLeft;
      }
    });
  };

  const fitTimelinePreview = () => {
    const maxDur = Math.max(
      Number(durationS) || 0,
      Number(variantScenes[variantScenes.length - 1]?.end_s ?? 0),
      30,
    );
    const viewport = timelineScrollerRef.current?.clientWidth ?? 920;
    const nextZoom = (Math.max(280, viewport) - 48) / Math.max(1, maxDur);
    setTimelineZoomWithFocus(nextZoom, 0);
  };

  const onTimelinePreviewWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const scroller = timelineScrollerRef.current;
    if (!scroller) return;
    event.preventDefault();
    const rect = scroller.getBoundingClientRect();
    const focusSeconds =
      (scroller.scrollLeft + (event.clientX - rect.left)) / Math.max(1, timelineZoom);
    const nextZoom = event.deltaY < 0 ? timelineZoom * 1.12 : timelineZoom / 1.12;
    setTimelineZoomWithFocus(nextZoom, focusSeconds);
  };

  useEffect(() => {
    const maxDur = Math.max(
      Number(durationS) || 0,
      Number(variantScenes[variantScenes.length - 1]?.end_s ?? 0),
      30,
    );
    if (!projectId || !maxDur) return;
    const key = `${projectId}:${selectedVariant}:${variantScenes.length}:${maxDur.toFixed(2)}`;
    if (previewAutoFitKeyRef.current === key) return;
    previewAutoFitKeyRef.current = key;
    const useRaf = typeof window.requestAnimationFrame === "function";
    const handle = useRaf
      ? window.requestAnimationFrame(() => fitTimelinePreview())
      : window.setTimeout(() => fitTimelinePreview(), 0);
    return () => {
      if (useRaf) window.cancelAnimationFrame(handle);
      else window.clearTimeout(handle);
    };
  }, [projectId, selectedVariant, variantScenes, durationS]);

  const TimelinePreview = ({ detailed = false }: { detailed?: boolean }) => {
    if (!variantScenes.length) return <div className="small">No scenes. Generate a plan to see a timeline.</div>;
    const lastEnd = Number(variantScenes[variantScenes.length - 1]?.end_s ?? 60);
    const maxDur = Math.max(Number(durationS) || 0, lastEnd);
    const widthPx = Math.max(600, Math.round(maxDur * timelineZoom));
    const tickEvery = 5;
    const ticks: number[] = [];
    const maxT = Math.ceil(maxDur / tickEvery) * tickEvery;
    for (let t = 0; t <= maxT; t += tickEvery) ticks.push(t);
    return (
      <div className="workspace-timelinePane">
        <div className="workspace-timelineToolbar">
          <div className="workspace-timelineZoomGroup">
            <div className="small">Zoom</div>
            <div className="workspace-zoomButtons">
              <button className="secondary" type="button" onClick={() => setTimelineZoomWithFocus(timelineZoom / 1.18)}>
                -
              </button>
              <button className="secondary" type="button" onClick={() => setTimelineZoomWithFocus(timelineZoom * 1.18)}>
                +
              </button>
              <button className="secondary" type="button" onClick={fitTimelinePreview}>
                Fit all
              </button>
            </div>
          </div>
          <input
            className="workspace-timelineRange"
            type="range"
            min={WORKSPACE_MIN_ZOOM}
            max={WORKSPACE_MAX_ZOOM}
            value={timelineZoom}
            onChange={(e) => setTimelineZoomWithFocus(Number(e.target.value))}
          />
          <div className="small workspace-zoomReadout">{Math.round(timelineZoom)}px/s</div>
        </div>
        <div
          className="workspace-timelineScroller"
          ref={timelineScrollerRef}
          onWheel={onTimelinePreviewWheel}
        >
          <div className="workspace-timelineCanvas" style={{ width: widthPx }}>
            <div className="workspace-timelineRuler">
              {ticks.map((t) => (
                <div key={t} className="workspace-timelineTick" style={{ left: t * timelineZoom }}>
                  <div className="workspace-timelineTickLine" />
                  <div className="small workspace-timelineTickLabel">{t}s</div>
                </div>
              ))}
            </div>
            <div className="workspace-sceneStage">
              {variantScenes.map((sc: any, i: number) => {
                const s = Number(sc.start_s ?? (i * 5));
                const e = Number(sc.end_s ?? (s + 5));
                const left = Math.max(0, s * timelineZoom);
                const w = Math.max(10, (e - s) * timelineZoom);
                return (
                  <div
                    key={i}
                    title={sc.prompt}
                    className="workspace-sceneBar"
                    style={{
                      position: "absolute",
                      left,
                      top: 20 + (i % 4) * 24,
                      width: w,
                    }}
                  >
                    {i + 1}. {String(sc.name || "Scene")}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        <div className="small workspace-timelineHint">
          Use `Ctrl/Cmd + mouse wheel` or the zoom buttons to inspect pacing without losing your place.
        </div>
        <div className="workspace-sceneList">
          <div className="workspace-sectionTitle">{detailed ? "Storyboard scenes" : "Scene list"}</div>
          {variantScenes.map((sc: any, i: number) => (
            <div key={i} className="workspace-sceneRow">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 700 }}>{i + 1}. {sc.name || "Scene"}</div>
                <div className="small">{Number(sc.start_s ?? i * 5).toFixed(2)}s → {Number(sc.end_s ?? (i * 5 + 5)).toFixed(2)}s</div>
              </div>
              <div className="small" style={{ marginTop: 6 }}>{sc.prompt}</div>
              {detailed && sc.transition ? (
                <div className="small workspace-sceneMeta">Transition: {String(sc.transition)}</div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
    );
  };

  const workflowTabs: Array<{ id: WorkspaceView; label: string; meta: string }> = [
    { id: "overview", label: "Overview", meta: `${variantCount || 0} variants` },
    { id: "planner", label: "AI Planner", meta: audioReady ? "ready to run" : "audio first" },
    { id: "reactive", label: "Reactive Lab", meta: analysisReady ? "audio-driven motion" : "analyze first" },
    { id: "storyboard", label: "Storyboard", meta: storyboardReady ? `${variantScenes.length} scenes` : "sync or plan first" },
  ];

  return (
    <div className="workspace-page">
      <div className="workspace-header">
        <div>
          <div className="timeline-kicker">Studio Session</div>
          <h1>Workspace</h1>
          <div className="small workspace-headerCopy">
            Ingest, analyze, shape creative direction, and hand the session off to Timeline and Render.
          </div>
        </div>
        <div className="workspace-statusStrip">
          <div className="workspace-stat">
            <span className="small">Project</span>
            <strong>{project?.name || "none"}</strong>
          </div>
          <div className="workspace-stat">
            <span className="small">Audio</span>
            <strong>{audioReady ? "ready" : "missing"}</strong>
          </div>
          <div className="workspace-stat">
            <span className="small">Analysis</span>
            <strong>{analysisReady ? "ready" : "pending"}</strong>
          </div>
          <div className="workspace-stat">
            <span className="small">Variant</span>
            <strong>{selectedVariantName}</strong>
          </div>
        </div>
      </div>

      <div className="workspace-flowTabs" role="tablist" aria-label="Workspace workflow">
        {workflowTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={workspaceView === tab.id}
            className={`workspace-flowTab${workspaceView === tab.id ? " is-active" : ""}`}
            onClick={() => setWorkspaceView(tab.id)}
          >
            <span>{tab.label}</span>
            <span className="workspace-flowTabMeta">{tab.meta}</span>
          </button>
        ))}
      </div>

      <div className="workspace-sessionStrip">
        <div className="workspace-sessionCard">
          <div className="workspace-sessionLabel">Shared session</div>
          <div className="workspace-sessionValue">
            {project?.name || "No active project"} • {selectedVariantName}
          </div>
          <div className="small">
            Workspace, Timeline, and the standalone labs now follow the same active project and variant.
          </div>
        </div>
        {lastHandoff ? (
          <div className="workspace-sessionCard workspace-sessionCard--accent">
            <div className="workspace-sessionLabel">Last handoff</div>
            <div className="workspace-sessionValue">
              {lastHandoff.type === "planner" ? "Planner sync" : "Reactive sync"}
            </div>
            <div className="small">{lastHandoff.summary}</div>
          </div>
        ) : null}
      </div>

      {progress.label ? (
        <div className="card workspace-progressCard">
          <ProgressBar
            value={progress.value}
            label={progress.label}
            detail={progress.detail}
            tone={progress.tone}
          />
        </div>
      ) : null}

      <details className="card workspace-guideCard">
        <summary className="workspace-guideSummary">
          {workspaceView === "overview" ? "Quick guide and capabilities" : workspaceView === "planner" ? "Planner guide and capabilities" : "Storyboard guide and capabilities"}
        </summary>
        <div className="workspace-guideBody">
          {workspaceView === "overview" ? (
            <div className="guide-grid">
              <section className="guide-block">
                <div className="guide-kicker">What this view does</div>
                <p>Overview is the operator surface for project intake, analysis, variant generation, reactive prep, and first-pass timeline review. It is the fastest place to confirm that a project is ready before moving deeper into planning or rendering.</p>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Capabilities</div>
                <ul className="guide-list">
                  <li>Upload the song and run analysis plus transcription.</li>
                  <li>Add reference images that influence style, character, or mood.</li>
                  <li>Generate plan variants, open the integrated planner or reactive lab, and apply or overwrite the timeline.</li>
                </ul>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Recommended flow</div>
                <ul className="guide-list">
                  <li>Choose the project, upload audio, and confirm references are attached.</li>
                  <li>Review Creative Direction, then use Timeline Preview to verify rhythm and full-track coverage.</li>
                  <li>Open AI Planner for scene design, Reactive Lab for motion scheduling, or Storyboard for dense scene-by-scene review.</li>
                </ul>
              </section>
            </div>
          ) : workspaceView === "planner" ? (
            <div className="guide-grid">
              <section className="guide-block">
                <div className="guide-kicker">What this view does</div>
                <p>The AI Planner is the detailed ideation and prompt-authoring surface. It lets you shape scene intent, prompt detail, storyboard structure, and repair strategy without committing changes until you explicitly sync them.</p>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Capabilities</div>
                <ul className="guide-list">
                  <li>Analyze a song, build a scene plan, and generate prompts tuned for different output targets.</li>
                  <li>Approve scenes, isolate weak scenes, and prepare rerender or repair instructions.</li>
                  <li>Sync the finished plan into the current Studio project without losing the standalone planner page.</li>
                </ul>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Recommended flow</div>
                <ul className="guide-list">
                  <li>Use Setup for audio and planning controls, then move into Prompt Pack for scene review.</li>
                  <li>Open Storyboard to read the ordered shot list, and use Repairs only when specific scenes need recovery.</li>
                  <li>Use Sync to internal renderer when the plan is ready to become the saved Studio storyboard and timeline base, while the standalone Planner Lab stays available from the sidebar.</li>
                </ul>
              </section>
            </div>
          ) : workspaceView === "reactive" ? (
            <div className="guide-grid">
              <section className="guide-block">
                <div className="guide-kicker">What this view does</div>
                <p>Reactive Lab turns saved audio analysis into motion, cue, and camera schedules that can be applied into the renderer timeline without breaking the standalone lab workflow.</p>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Capabilities</div>
                <ul className="guide-list">
                  <li>Build deterministic keyframes from the current track and inspect section energy before render.</li>
                  <li>Export handoff bundles, cue CSVs, and compressed schedules for downstream tools.</li>
                  <li>Apply approved reactive motion directly into the project timeline and renderer camera data.</li>
                </ul>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Recommended flow</div>
                <ul className="guide-list">
                  <li>Run audio analysis first so the reactive pass starts from the saved project track.</li>
                  <li>Use Fit all in the preview to see the whole track before approving dense sections.</li>
                  <li>Apply to the internal renderer, then open Timeline for clip refinement or Render for final output.</li>
                </ul>
              </section>
            </div>
          ) : (
            <div className="guide-grid">
              <section className="guide-block">
                <div className="guide-kicker">What this view does</div>
                <p>Storyboard is the saved project-level reading view for the active variant. It keeps the timing preview and the scene cards together so you can evaluate pacing and prompt continuity in one place.</p>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Capabilities</div>
                <ul className="guide-list">
                  <li>Switch variants without leaving Workspace.</li>
                  <li>Inspect scene prompts, notes, and durations next to the zoomable preview.</li>
                  <li>Apply or overwrite the timeline, then jump directly into full Timeline or Render.</li>
                </ul>
              </section>
              <section className="guide-block">
                <div className="guide-kicker">Recommended flow</div>
                <ul className="guide-list">
                  <li>Use Fit all to see the full sequence, then zoom into dense sections when a transition needs closer review.</li>
                  <li>Read the scene cards in order to confirm narrative continuity and prompt variety.</li>
                  <li>Apply the version you want, then open Timeline for detailed arrangement edits.</li>
                </ul>
              </section>
            </div>
          )}
        </div>
      </details>

      {workspaceView === "overview" ? <div className="workspace-shell">
        <div className="card workspace-sideCard">
          <OverviewSection
            id="project"
            title="Project"
            description="Choose the active session and inspect current ingest status."
            progress={projectProgress}
            open={overviewSections.project}
            onToggle={toggleOverviewSection}
          >
            {projects.length ? (
              <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            ) : (
              <div className="small">No projects yet. Create one in Projects tab.</div>
            )}
          </OverviewSection>

          <OverviewSection
            id="audio"
            title="Audio"
            description="Upload the track, then analyze and transcribe it."
            progress={audioProgress}
            open={overviewSections.audio}
            onToggle={toggleOverviewSection}
          >
            <input type="file" accept="audio/*" onChange={(e) => setAudioFile(e.target.files?.[0] || null)} />
            <div className="row workspace-actionRow" style={{ marginTop: 10 }}>
              <button onClick={uploadAudio} disabled={!audioFile || !projectId}>Upload</button>
              <button className="secondary" onClick={runAnalysis} disabled={!projectId}>Analyze + Transcribe</button>
            </div>
            {project?.meta?.audio && (
              <div className="small" style={{ marginTop: 10 }}>
                uploaded: {project.meta.audio.filename} ({bytes(project.meta.audio.size_bytes)})
              </div>
            )}
          </OverviewSection>

          <OverviewSection
            id="references"
            title="Reference Assets"
            description="Style and character anchors that guide image and motion prompts."
            progress={referenceProgress}
            open={overviewSections.references}
            onToggle={toggleOverviewSection}
          >
            <div className="small">Reference images (style/character anchors)</div>
            <input type="file" accept="image/*" onChange={(e) => setRefFile(e.target.files?.[0] || null)} />
            <div className="row workspace-actionRow" style={{ marginTop: 10 }}>
              <button onClick={uploadRef} disabled={!refFile || !projectId}>Upload ref</button>
              <button className="secondary" onClick={() => projectId && refreshProject(projectId)} disabled={!projectId}>Refresh assets</button>
            </div>
            <div className="workspace-assetsGrid">
              {refAssets.map((r: any) => (
                <a key={r.path} href={fileUrl(projectId, r.path)} target="_blank" rel="noreferrer">
                  <img src={fileUrl(projectId, r.path)} className="workspace-assetThumb" />
                </a>
              ))}
              {!refAssets.length && <div className="small">No refs yet.</div>}
            </div>
          </OverviewSection>

          <OverviewSection
            id="plan"
            title="Plan Variants"
            description="Generate multiple scene structures, then apply the best one to the timeline."
            progress={planProgress}
            open={overviewSections.plan}
            onToggle={toggleOverviewSection}
          >
            <div className="row workspace-actionRow" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <label className="small row" style={{ gap: 6, alignItems: "center" }}>
                Plan mode
                <select value={planMode} onChange={(e) => setPlanMode(e.target.value as any)}>
                  <option value="auto">Auto</option>
                  <option value="ai">AI-only</option>
                  <option value="local">Local-only</option>
                </select>
              </label>
              <button onClick={generatePlan} disabled={!projectId}>Generate Plan Variants</button>
            </div>

            {plan?.variants?.length ? (
              <>
              <div style={{ marginTop: 12 }}>
                <div className="small">Select variant</div>
                <select value={selectedVariant} onChange={(e) => setSelectedVariant(Number(e.target.value))}>
                  {plan.variants.map((v: any, idx: number) => (
                    <option key={idx} value={idx}>{idx + 1}. {v.name}</option>
                  ))}
                </select>
              </div>
              <div className="row workspace-actionRow" style={{ gap: 10, marginTop: 10, flexWrap: "wrap" }}>
                <button
                  onClick={() => void applyTimelinePlan(false)}
                  disabled={!projectId || !plan?.variants?.length}
                >
                  Apply variant to timeline
                </button>
                <button
                  className="secondary"
                  onClick={() => void applyTimelinePlan(true)}
                  disabled={!projectId || !plan?.variants?.length}
                >
                  Apply (overwrite)
                </button>
                <button className="secondary" onClick={() => setWorkspaceView("planner")} disabled={!projectId}>
                  Open AI Planner
                </button>
                <button className="secondary" onClick={() => setWorkspaceView("reactive")} disabled={!projectId || !analysisReady}>
                  Open Reactive Lab
                </button>
              </div>
              </>
            ) : (
              <div className="small" style={{ marginTop: 10 }}>No plan generated yet.</div>
            )}
          </OverviewSection>

          <OverviewSection
            id="handoff"
            title="Handoff"
            description="Move from planning and reactive motion into arrangement, rendering, and output review."
            progress={handoffProgress}
            open={overviewSections.handoff}
            onToggle={toggleOverviewSection}
          >
            <div className="small" style={{ marginBottom: 10 }}>
              Workspace is the integrated hub. Standalone Planner Lab and Reactive Lab remain available from the sidebar when you want full-screen specialist views.
            </div>
            <div className="workspace-handoffGrid">
              <div className="workspace-handoffCard">
                <div className="workspace-handoffLabel">Planner handoff</div>
                <strong>{plannerImportedAt ? `${plannerSceneCount} scenes synced` : "Not synced yet"}</strong>
              </div>
              <div className="workspace-handoffCard">
                <div className="workspace-handoffLabel">Reactive handoff</div>
                <strong>{reactiveAppliedAt ? `${reactiveSectionCount} sections applied` : "Not synced yet"}</strong>
              </div>
            </div>
            <div className="row workspace-actionRow" style={{ gap: 10, flexWrap: "wrap" }}>
              <button className="secondary" onClick={() => setWorkspaceView("planner")} disabled={!projectId}>Planner</button>
              <button className="secondary" onClick={() => setWorkspaceView("reactive")} disabled={!projectId || !analysisReady}>Reactive Lab</button>
              <button onClick={() => onNavigate?.("render")} disabled={!plan?.variants?.length}>Go to Render</button>
              <button className="secondary" onClick={() => setWorkspaceView("storyboard")} disabled={!storyboardReady}>Open Storyboard</button>
              <button className="secondary" onClick={() => onNavigate?.("outputs")}>Outputs</button>
              <button className="secondary" onClick={() => onNavigate?.("queue")}>Render Queue</button>
            </div>
          </OverviewSection>

          {err && <div style={{ marginTop: 12, color: "var(--danger)" }}>{err}</div>}
        </div>

        <div className="workspace-mainStack">
          <div className="card workspace-featureCard">
            <CreativeDirectionPanel
              projectId={projectId}
              analysis={analysis}
              plan={plan}
              selectedVariant={selectedVariant}
              onNavigate={onNavigate}
            />
          </div>

          <div className="card workspace-featureCard">
            <div className="workspace-sectionHead">
              <div className="workspace-sectionTitle">Timeline Preview</div>
              <div className="small">Scene structure and pacing before the full arrangement pass.</div>
            </div>
            <TimelinePreview />
          </div>

          <details className="card workspace-inspectCard" open={uiMode === "advanced"}>
            <summary className="workspace-inspectSummary">Inspect</summary>
            <div style={{ marginTop: 10 }}>
              <div style={{ fontWeight: 800, marginBottom: 10 }}>Selected variant (raw)</div>
              {plan?.variants?.length ? (
                <pre>{JSON.stringify(plan.variants[selectedVariant], null, 2)}</pre>
              ) : (
                <div className="small">No plan.</div>
              )}

              <hr />
              <div style={{ fontWeight: 800, marginBottom: 10 }}>Analysis</div>
              {!analysis && <div className="small">No analysis yet.</div>}
              {analysis && <pre>{JSON.stringify(analysis, null, 2)}</pre>}

              <hr />
              <div style={{ fontWeight: 800, marginBottom: 10 }}>Last action result</div>
              {!info && <div className="small">No recent action.</div>}
              {info && <pre>{JSON.stringify(info, null, 2)}</pre>}
            </div>
          </details>
        </div>
      </div> : null}

      {workspaceView === "planner" ? (
        <div className="workspace-panel card workspace-workbenchCard">
          <div className="workspace-panelHeader">
            <div>
              <div className="workspace-sectionTitle">AI Planner + Storyboard Builder</div>
              <div className="small">
                The detailed planner now runs inside the current project workflow, so prompt generation and renderer sync stay tied to the same session.
              </div>
            </div>
            <div className="workspace-panelActions">
              <button className="secondary" onClick={() => setWorkspaceView("overview")}>
                Back to overview
              </button>
              <button className="secondary" onClick={() => onNavigate?.("plannerLab")} disabled={!projectId}>
                Open standalone
              </button>
              <button className="secondary" onClick={() => setWorkspaceView("storyboard")} disabled={!storyboardReady}>
                Saved storyboard
              </button>
            </div>
          </div>
          <AiNlpWorkbench
            compact
            studioProjectId={projectId}
            studioProjectName={project?.name || ""}
            studioProject={project}
            studioSelectedVariant={selectedVariant}
            onSyncToStudio={syncPlannerLab}
          />
        </div>
      ) : null}

      {workspaceView === "reactive" ? (
        <div className="workspace-panel card workspace-workbenchCard">
          <div className="workspace-panelHeader">
            <div>
              <div className="workspace-sectionTitle">Reactive Lab + Renderer Handoff</div>
              <div className="small">
                Reactive scheduling now lives inside the current project workflow so motion, cueing, and renderer handoff stay tied to the same session.
              </div>
            </div>
            <div className="workspace-panelActions">
              <button className="secondary" onClick={() => setWorkspaceView("overview")}>
                Back to overview
              </button>
              <button className="secondary" onClick={() => onNavigate?.("reactiveLab")} disabled={!projectId}>
                Open standalone
              </button>
              <button className="secondary" onClick={() => onNavigate?.("timeline")} disabled={!analysisReady}>
                Open Timeline
              </button>
              <button onClick={() => onNavigate?.("render")} disabled={!analysisReady}>
                Go to Render
              </button>
            </div>
          </div>
          <AudioReactiveWorkbench
            compact
            studioProjectId={projectId}
            studioProjectName={project?.name || ""}
            studioProject={project}
            studioSelectedVariant={selectedVariant}
            onSyncToStudio={syncReactiveLab}
          />
        </div>
      ) : null}

      {workspaceView === "storyboard" ? (
        <div className="workspace-storyboardStack">
          <div className="card workspace-featureCard">
            <div className="workspace-panelHeader">
              <div>
                <div className="workspace-sectionTitle">Storyboard Review</div>
                <div className="small">
                  Review the saved project plan, scene timing, and prompt handoff in one place before opening Timeline or Render.
                </div>
              </div>
              <div className="workspace-panelActions">
                <button className="secondary" onClick={() => setWorkspaceView("planner")}>
                  Open AI Planner
                </button>
                <button className="secondary" onClick={() => onNavigate?.("timeline")} disabled={!storyboardReady}>
                  Open Timeline
                </button>
                <button onClick={() => onNavigate?.("render")} disabled={!storyboardReady}>
                  Go to Render
                </button>
              </div>
            </div>

            {plan?.variants?.length ? (
              <div className="workspace-storyboardMeta">
                <label className="workspace-storyboardField">
                  <span>Variant</span>
                  <select value={selectedVariant} onChange={(e) => setSelectedVariant(Number(e.target.value))}>
                    {plan.variants.map((v: any, idx: number) => (
                      <option key={idx} value={idx}>
                        {idx + 1}. {v.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="workspace-storyboardActions">
                  <button className="secondary" onClick={() => void shuffleStoryboardScenes()} disabled={variantScenes.length < 2}>
                    Shuffle scenes
                  </button>
                  <button onClick={() => void applyTimelinePlan(false)} disabled={!storyboardReady}>
                    Apply to timeline
                  </button>
                  <button className="secondary" onClick={() => void applyTimelinePlan(true)} disabled={!storyboardReady}>
                    Overwrite timeline
                  </button>
                </div>
              </div>
            ) : null}

            <TimelinePreview detailed />
          </div>

          <div className="workspace-storyboardGrid">
            {variantScenes.length ? (
              variantScenes.map((scene: any, index: number) => (
                <article key={scene.id || index} className="card workspace-storyboardCard">
                  <div className="workspace-storyboardCardHead">
                    <div>
                      <div className="workspace-storyboardIndex">Scene {index + 1}</div>
                      <h3>{scene.name || "Untitled scene"}</h3>
                    </div>
                    <div className="small">
                      {Number(scene.start_s ?? index * 5).toFixed(2)}s → {Number(scene.end_s ?? (index * 5 + 5)).toFixed(2)}s
                    </div>
                  </div>
                  <div className="workspace-storyboardCardActions">
                    <button className="secondary" onClick={() => void moveStoryboardScene(index, -1)} disabled={index === 0}>
                      Move earlier
                    </button>
                    <button className="secondary" onClick={() => void moveStoryboardScene(index, 1)} disabled={index === variantScenes.length - 1}>
                      Move later
                    </button>
                  </div>
                  <div className="workspace-storyboardPrompt">{scene.prompt || "No prompt yet."}</div>
                  {scene.negative_prompt ? (
                    <div className="workspace-storyboardNote"><strong>Negative:</strong> {scene.negative_prompt}</div>
                  ) : null}
                  {scene.transition ? (
                    <div className="workspace-storyboardNote"><strong>Transition:</strong> {scene.transition}</div>
                  ) : null}
                </article>
              ))
            ) : (
              <div className="card workspace-storyboardEmpty">
                <div className="workspace-sectionTitle">No storyboard saved yet</div>
                <div className="small">Generate a plan in Overview or sync the AI Planner to populate this review surface.</div>
              </div>
            )}
          </div>
        </div>
      ) : null}

      <div className="small workspace-footerNote">
        Use Outputs to view images/videos. The backend runs an always-on worker by default; Render Queue lets you inspect jobs/logs and retry/cancel, while the sidebar keeps standalone labs available when you want them separate.
      </div>
    </div>
  );
}
