import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiUpload, getBackendUrl } from "../components/api";
import { CreativeDirectionPanel } from "../components/CreativeDirectionPanel";
import { useUiMode } from "../components/uiMode";
import type { PageProps } from "../types/pageProps";

function bytes(n: number) {
  if (!Number.isFinite(n)) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let u = 0, v = n;
  while (v > 1024 && u < units.length - 1) { v /= 1024; u++; }
  return `${v.toFixed(u === 0 ? 0 : 2)} ${units[u]}`;
}

export default function Workspace({ onNavigate }: PageProps) {
  const { mode: uiMode } = useUiMode();
  const backendUrl = useMemo(() => getBackendUrl(), []);
  const [projects, setProjects] = useState<any[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [project, setProject] = useState<any>(null);

  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [refFile, setRefFile] = useState<File | null>(null);
  const [assets, setAssets] = useState<any>(null);
  const [analysis, setAnalysis] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [selectedVariant, setSelectedVariant] = useState<number>(0);

  const [planMode, setPlanMode] = useState<"auto" | "ai" | "local">("auto");

  const [timelineZoom, setTimelineZoom] = useState<number>(60); // px per second

  const [info, setInfo] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

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
    await apiUpload(`/v1/projects/${projectId}/assets/audio`, audioFile);
    await refreshProject(projectId);
  };

  const uploadRef = async () => {
    if (!refFile) return;
    setErr(null); setInfo(null);
    await apiUpload(`/v1/projects/${projectId}/assets/refs`, refFile);
    setRefFile(null);
    await refreshProject(projectId);
  };

  const runAnalysis = async () => {
    setErr(null); setInfo(null);
    try {
      const d = await apiPost(`/v1/projects/${projectId}/analyze_audio`, {});
      setAnalysis(d);
      await refreshProject(projectId);
    } catch (e: any) { setErr(String(e)); }
  };

  const generatePlan = async () => {
    setErr(null); setInfo(null);
    try {
      const d = await apiPost(`/v1/projects/${projectId}/plan?mode=${planMode}`, {
        title: project?.name || "Untitled",
        style_prefs: "cinematic, coherent subject, high detail, consistent style",
        num_variants: 3,
        max_scenes: 12
      });
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

  const Timeline = () => {
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
          <div className="small">Zoom</div>
          <input
            className="workspace-timelineRange"
            type="range"
            min={20}
            max={160}
            value={timelineZoom}
            onChange={(e) => setTimelineZoom(Number(e.target.value))}
          />
          <div className="small">{timelineZoom}px/s</div>
        </div>
        <div className="workspace-timelineScroller">
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
        <div className="workspace-sceneList">
          <div className="workspace-sectionTitle">Scene list</div>
          {variantScenes.map((sc: any, i: number) => (
            <div key={i} className="workspace-sceneRow">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div style={{ fontWeight: 700 }}>{i + 1}. {sc.name || "Scene"}</div>
                <div className="small">{Number(sc.start_s ?? i * 5).toFixed(2)}s → {Number(sc.end_s ?? (i * 5 + 5)).toFixed(2)}s</div>
              </div>
              <div className="small" style={{ marginTop: 6 }}>{sc.prompt}</div>
            </div>
          ))}
        </div>
      </div>
    );
  };

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

      <div className="workspace-shell">
        <div className="card workspace-sideCard">
          <div className="workspace-section">
            <div className="workspace-sectionHead">
              <div className="workspace-sectionTitle">Project</div>
              <div className="small">Choose the active session and inspect current ingest status.</div>
            </div>
          {projects.length ? (
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          ) : (
            <div className="small">No projects yet. Create one in Projects tab.</div>
          )}
          </div>

          <div className="workspace-section">
            <div className="workspace-sectionHead">
              <div className="workspace-sectionTitle">Audio</div>
              <div className="small">Upload the track, then analyze and transcribe it.</div>
            </div>
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
          </div>

          <div className="workspace-section">
            <div className="workspace-sectionHead">
              <div className="workspace-sectionTitle">Reference Assets</div>
              <div className="small">Style and character anchors that guide image and motion prompts.</div>
            </div>
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
          </div>

          <div className="workspace-section">
            <div className="workspace-sectionHead">
              <div className="workspace-sectionTitle">Plan Variants</div>
              <div className="small">Generate multiple scene structures, then apply the best one to the timeline.</div>
            </div>
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
                onClick={async () => {
                  setErr(null);
                  try {
                    await apiPost(`/v1/projects/${projectId}/timeline/apply_plan`, { variant_index: selectedVariant, overwrite: false });
                    await refreshProject(projectId);
                  } catch (e: any) { setErr(String(e)); }
                }}
                disabled={!projectId || !plan?.variants?.length}
              >
                Apply variant to timeline
              </button>
              <button
                className="secondary"
                onClick={async () => {
                  setErr(null);
                  try {
                    await apiPost(`/v1/projects/${projectId}/timeline/apply_plan`, { variant_index: selectedVariant, overwrite: true });
                    await refreshProject(projectId);
                  } catch (e: any) { setErr(String(e)); }
                }}
                disabled={!projectId || !plan?.variants?.length}
              >
                Apply (overwrite)
              </button>
            </div>
            </>
          ) : (
            <div className="small" style={{ marginTop: 10 }}>No plan generated yet.</div>
          )}
          </div>

          <div className="workspace-section">
            <div className="workspace-sectionHead">
              <div className="workspace-sectionTitle">Handoff</div>
              <div className="small">Move from planning into rendering and output review.</div>
            </div>
          <div className="small" style={{ marginBottom: 10 }}>
            Workspace is for planning. Rendering, queue control, and exports live in the Render page.
          </div>
          <div className="row workspace-actionRow" style={{ gap: 10, flexWrap: "wrap" }}>
            <button onClick={() => onNavigate?.("render")} disabled={!plan?.variants?.length}>Go to Render</button>
            <button className="secondary" onClick={() => onNavigate?.("outputs")}>Outputs</button>
            <button className="secondary" onClick={() => onNavigate?.("queue")}>Render Queue</button>
          </div>
          </div>

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
            <Timeline />
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
      </div>

      <div className="small workspace-footerNote">
        Use Outputs to view images/videos. The backend runs an always-on worker by default; Render Queue lets you inspect jobs/logs and retry/cancel.
      </div>
    </div>
  );
}
