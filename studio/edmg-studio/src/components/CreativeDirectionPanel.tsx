import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "./api";

type PreviewTab = "prompt-pack" | "timeline" | "deforum" | "contract";

type CreativeDirectionPanelProps = {
  projectId: string;
  analysis: any;
  plan: any;
  selectedVariant: number;
  compact?: boolean;
  onNavigate?: (page: any) => void;
};

type CreativeDirectionResponse = {
  ready: boolean;
  missing: string[];
  preset: "cinematic" | "psychedelic" | "ambient";
  sensitivity: number;
  provider_mode: string;
  scene_source: string;
  metrics: {
    energy: number;
    bass: number;
    mid: number;
    treble: number;
    duration_s: number;
    source: string;
  };
  waveform: number[];
  motifs: string[];
  transcript_text: string;
  transcript_summary: string;
  status: string;
  export_text: string;
  notes?: string[];
  narrative_analysis?: {
    ok: boolean;
    title: string;
    provider_mode: string;
    scene_source: string;
    hooks: string[];
    motifs: string[];
    transcript_line_count: number;
    emotions: Array<{ emotion: string; score: number }>;
  };
  sections?: Array<{
    index: number;
    name: string;
    start_s: number;
    end_s: number;
    energy: number;
    energy_label: string;
    band: string;
  }>;
  scenes: Array<{
    index: number;
    name: string;
    start_s: number;
    end_s: number;
    duration_s: number;
    energy: number;
    energy_label: string;
    prompt: string;
    transcript_cue: string;
    camera_hint: string;
    motion_hint: string;
    prompt_pack: string;
  }>;
  timeline_patch?: any;
  deforum_preview?: any;
  llm_contract?: any;
};

const PREVIEW_LABELS: Record<PreviewTab, string> = {
  "prompt-pack": "Prompt pack",
  timeline: "Timeline patch",
  deforum: "Deforum preview",
  contract: "LLM contract",
};

function clamp01(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function formatSeconds(seconds: number) {
  return `${Number(seconds || 0).toFixed(2)}s`;
}

function prettyJson(value: any) {
  return JSON.stringify(value ?? {}, null, 2);
}

function Meter({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="insight-meter">
      <div className="small" style={{ fontWeight: 800 }}>{label}</div>
      <div className="insight-meter-track">
        <div className="insight-meter-fill" style={{ height: `${Math.round(clamp01(value) * 100)}%`, background: tone }} />
      </div>
      <div className="small">{Math.round(clamp01(value) * 100)}%</div>
    </div>
  );
}

export function CreativeDirectionPanel(props: CreativeDirectionPanelProps) {
  const { projectId, analysis, plan, selectedVariant, compact = false, onNavigate } = props;
  const [preset, setPreset] = useState<"cinematic" | "psychedelic" | "ambient">("cinematic");
  const [sensitivity, setSensitivity] = useState<number>(1.0);
  const [copyStatus, setCopyStatus] = useState<string>("");
  const [applyStatus, setApplyStatus] = useState<string>("");
  const [payload, setPayload] = useState<CreativeDirectionResponse | null>(null);
  const [status, setStatus] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [preview, setPreview] = useState<PreviewTab>("prompt-pack");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!projectId) {
        setPayload(null);
        setCopyStatus("");
        setApplyStatus("");
        setStatus("Select a project to load creative direction guidance.");
        setLoading(false);
        return;
      }

      setPayload(null);
      setCopyStatus("");
      setApplyStatus("");
      setLoading(true);
      setStatus("Loading backend creative direction...");
      try {
        const result = await apiGet(
          `/v1/projects/${projectId}/creative_direction?variant_index=${selectedVariant}&preset=${preset}&sensitivity=${encodeURIComponent(String(sensitivity))}`,
        );
        if (!cancelled) {
          const nextPayload = result?.creative_direction || null;
          setPayload(nextPayload);
          setStatus(String(nextPayload?.status || ""));
        }
      } catch (error: any) {
        if (!cancelled) {
          setPayload(null);
          setStatus(`Creative direction unavailable: ${String(error)}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load().catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [preset, projectId, selectedVariant, sensitivity]);

  const hasPlan = Boolean(plan?.variants?.length);
  const hasAnalysis = Boolean(analysis);
  const metrics = payload?.metrics || {
    energy: 0,
    bass: 0,
    mid: 0,
    treble: 0,
    duration_s: 0,
    source: "analysis",
  };
  const hooks = payload?.narrative_analysis?.hooks || [];
  const emotions = payload?.narrative_analysis?.emotions || [];
  const missing = payload?.missing || [];

  const previewText = useMemo(() => {
    if (!payload) {
      return loading
        ? "Loading creative direction from the Studio backend..."
        : "Creative direction is unavailable until analysis or planning data exists.";
    }
    if (preview === "timeline") return prettyJson(payload.timeline_patch);
    if (preview === "deforum") return prettyJson(payload.deforum_preview);
    if (preview === "contract") return prettyJson(payload.llm_contract);
    return String(payload.export_text || "");
  }, [loading, payload, preview]);

  const copyPack = async () => {
    const value = String(payload?.export_text || "");
    if (!value) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        setCopyStatus("Prompt pack copied.");
      } else {
        setCopyStatus("Clipboard is unavailable in this environment. Use the export textarea below.");
      }
    } catch (error: any) {
      setCopyStatus(`Copy failed: ${String(error)}`);
    }
  };

  const applyTimelinePatch = async () => {
    if (!projectId || !payload?.timeline_patch?.timeline) return;
    setApplyStatus("");
    try {
      await apiPost(`/v1/projects/${projectId}/creative_direction/apply_timeline_patch`, {
        variant_index: selectedVariant,
        preset,
        sensitivity,
        overwrite_tracks: true,
        overwrite_camera: false,
      });
      setApplyStatus("Direction patch applied to timeline.");
      if (!compact) onNavigate?.("timeline");
    } catch (error: any) {
      setApplyStatus(`Apply failed: ${String(error)}`);
    }
  };

  return (
    <div className="creative-direction-panel">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 900, fontSize: compact ? 18 : 20 }}>Creative direction</div>
          <div className="small">
            Archive-prototype logic is now folded into the canonical Studio flow: audio-reactive sections, narrative hooks, timeline patching, and Deforum-aligned preview output.
          </div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {!compact && onNavigate ? (
            <button className="secondary" onClick={() => onNavigate("timeline")} disabled={!projectId}>
              Refine in Timeline
            </button>
          ) : null}
          {!compact ? (
            <button className="secondary" onClick={applyTimelinePatch} disabled={!payload?.timeline_patch?.timeline || loading}>
              Apply direction to timeline
            </button>
          ) : null}
          <button className="secondary" onClick={copyPack} disabled={!payload?.export_text || loading}>
            Copy prompt pack
          </button>
        </div>
      </div>

      <div className="row" style={{ gap: 10, flexWrap: "wrap", marginTop: 10, alignItems: "center" }}>
        <label className="small row" style={{ gap: 6, alignItems: "center" }}>
          Preset
          <select value={preset} onChange={(event) => setPreset(event.target.value as any)} style={{ width: 180 }}>
            <option value="cinematic">Cinematic</option>
            <option value="psychedelic">Psychedelic</option>
            <option value="ambient">Ambient</option>
          </select>
        </label>
        <label className="small row" style={{ gap: 6, alignItems: "center" }}>
          Sensitivity
          <input
            type="range"
            min={0.2}
            max={2.4}
            step={0.1}
            value={sensitivity}
            onChange={(event) => setSensitivity(Number(event.target.value))}
            style={{ width: 140 }}
          />
          <span>{sensitivity.toFixed(1)}</span>
        </label>
        <div className="badge">{hasAnalysis ? "Analysis ready" : "Needs analysis"}</div>
        <div className="badge">{hasPlan ? "Plan ready" : "Plan fallback"}</div>
        {payload?.provider_mode ? <div className="badge">{payload.provider_mode}</div> : null}
        {payload?.scene_source ? <div className="badge">Scenes: {payload.scene_source}</div> : null}
      </div>

      <div className="small" style={{ marginTop: 8 }}>
        {status || "Creative direction is unavailable until analysis and planning exist."}
      </div>
      {missing.length ? (
        <div className="small" style={{ marginTop: 6 }}>
          Missing inputs: {missing.join(", ")}.
        </div>
      ) : null}
      {applyStatus ? <div className="small" style={{ marginTop: 6 }}>{applyStatus}</div> : null}

      <div className="insight-grid" style={{ marginTop: 12 }}>
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ fontWeight: 900 }}>Audio-reactive direction</div>
            <div className="badge">{payload?.ready ? "Studio-ready" : "Waiting"}</div>
          </div>

          <div className="small" style={{ marginTop: 8 }}>
            Duration {formatSeconds(metrics.duration_s)} • Source {payload?.metrics?.source || "analysis"} • Sections {payload?.sections?.length || 0}
          </div>

          {payload?.waveform?.length ? (
            <div className="insight-waveform" aria-label="Audio waveform" style={{ marginTop: 12 }}>
              {payload.waveform.map((value, index) => (
                <div key={`${index}-${value.toFixed(3)}`} className="insight-waveform-bar" style={{ height: `${Math.max(8, value * 100)}%` }} />
              ))}
            </div>
          ) : (
            <div className="insight-waveform-placeholder" style={{ marginTop: 12 }}>
              <div className="small">Waveform bars appear when the saved project analysis includes an energy curve.</div>
            </div>
          )}

          <div className="insight-meter-grid" style={{ marginTop: 12 }}>
            <Meter label="Energy" value={metrics.energy} tone="linear-gradient(180deg, rgba(53,216,223,0.18), rgba(53,216,223,0.95))" />
            <Meter label="Bass" value={metrics.bass} tone="linear-gradient(180deg, rgba(255,122,102,0.18), rgba(255,122,102,0.95))" />
            <Meter label="Mid" value={metrics.mid} tone="linear-gradient(180deg, rgba(243,183,70,0.18), rgba(243,183,70,0.92))" />
            <Meter label="Treble" value={metrics.treble} tone="linear-gradient(180deg, rgba(143,112,255,0.18), rgba(143,112,255,0.92))" />
          </div>

          {emotions.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="small" style={{ fontWeight: 900, marginBottom: 6 }}>Emotional read</div>
              <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                {emotions.map((emotion) => (
                  <span key={emotion.emotion} className="badge">
                    {emotion.emotion} {Math.round(clamp01(emotion.score) * 100)}%
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {hooks.length ? (
            <div className="insight-callout" style={{ marginTop: 12 }}>
              <div className="small" style={{ fontWeight: 900 }}>Narrative hooks</div>
              <div style={{ marginTop: 6 }}>{hooks.join(" / ")}</div>
            </div>
          ) : null}
        </div>

        <div className="card">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ fontWeight: 900 }}>Scene prompt pack</div>
            <div className="badge">{payload?.scenes?.length || 0} scenes</div>
          </div>

          {payload?.motifs?.length ? (
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 10 }}>
              {payload.motifs.map((motif) => (
                <span key={motif} className="badge">{motif}</span>
              ))}
            </div>
          ) : null}

          {payload?.transcript_summary ? (
            <div className="insight-callout" style={{ marginTop: 10 }}>
              <div className="small" style={{ fontWeight: 900 }}>Transcript anchor</div>
              <div style={{ marginTop: 6 }}>{payload.transcript_summary}</div>
            </div>
          ) : null}

          <div style={{ marginTop: 12 }}>
            {payload?.scenes?.length ? payload.scenes.map((scene) => (
              <div key={`${scene.index}-${scene.name}`} className="insight-scene-card">
                <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                  <div>
                    <div style={{ fontWeight: 800 }}>{scene.index + 1}. {scene.name}</div>
                    <div className="small">{formatSeconds(scene.start_s)} - {formatSeconds(scene.end_s)} • {scene.energy_label}</div>
                  </div>
                  <div className="badge">{Math.round(scene.energy * 100)}% energy</div>
                </div>
                <div style={{ marginTop: 8 }}><strong>Base prompt:</strong> {scene.prompt}</div>
                <div className="small" style={{ marginTop: 6 }}><strong>Transcript cue:</strong> {scene.transcript_cue}</div>
                <div className="small" style={{ marginTop: 6 }}><strong>Camera:</strong> {scene.camera_hint}</div>
                <div className="small" style={{ marginTop: 6 }}><strong>Motion:</strong> {scene.motion_hint}</div>
              </div>
            )) : (
              <div className="small" style={{ marginTop: 10 }}>
                Generate a plan or run audio analysis to build a real scene direction pack.
              </div>
            )}
          </div>

          <details style={{ marginTop: 12 }} open={!compact}>
            <summary style={{ cursor: "pointer", fontWeight: 800 }}>Exports and previews</summary>
            <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 10 }}>
              {(Object.keys(PREVIEW_LABELS) as PreviewTab[]).map((key) => (
                <button
                  key={key}
                  className={preview === key ? "primary" : "secondary"}
                  onClick={() => setPreview(key)}
                  disabled={loading}
                >
                  {PREVIEW_LABELS[key]}
                </button>
              ))}
            </div>
            <textarea
              readOnly
              value={previewText}
              style={{ marginTop: 10, minHeight: compact ? 160 : 240 }}
            />
            {payload?.notes?.length ? (
              <div style={{ marginTop: 10 }}>
                {payload.notes.map((note, index) => (
                  <div key={index} className="small">{note}</div>
                ))}
              </div>
            ) : null}
            {copyStatus ? <div className="small" style={{ marginTop: 8 }}>{copyStatus}</div> : null}
          </details>
        </div>
      </div>
    </div>
  );
}
