import React, { useEffect, useState } from "react";
import { apiGet } from "./api";

type CreativeDirectionPanelProps = {
  projectId: string;
  analysis: any;
  plan: any;
  selectedVariant: number;
  compact?: boolean;
  onNavigate?: (page: any) => void;
};

type CreativeDirectionResponse = {
  preset: "cinematic" | "psychedelic" | "ambient";
  sensitivity: number;
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
};

function clamp01(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function formatSeconds(seconds: number) {
  return `${Number(seconds || 0).toFixed(2)}s`;
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
  const [payload, setPayload] = useState<CreativeDirectionResponse | null>(null);
  const [status, setStatus] = useState<string>("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!projectId) {
        setPayload(null);
        setStatus("Select a project to load creative direction guidance.");
        return;
      }
      setStatus("Loading backend creative direction...");
      try {
        const result = await apiGet(
          `/v1/projects/${projectId}/creative_direction?variant_index=${selectedVariant}&preset=${preset}&sensitivity=${encodeURIComponent(String(sensitivity))}`,
        );
        if (!cancelled) {
          setPayload(result?.creative_direction || null);
          setStatus(String(result?.creative_direction?.status || ""));
        }
      } catch (error: any) {
        if (!cancelled) {
          setPayload(null);
          setStatus(`Creative direction unavailable: ${String(error)}`);
        }
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

  return (
    <div className="creative-direction-panel">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 900, fontSize: compact ? 18 : 20 }}>Creative direction</div>
          <div className="small">
            Backend-authored reactivity, scene energy, and prompt-pack guidance folded into the Studio workflow.
          </div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {!compact && onNavigate ? (
            <button className="secondary" onClick={() => onNavigate("timeline")} disabled={!projectId}>
              Refine in Timeline
            </button>
          ) : null}
          <button className="secondary" onClick={copyPack} disabled={!payload?.export_text}>
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
        <div className="badge">{hasPlan ? "Plan ready" : "Needs plan"}</div>
      </div>

      <div className="small" style={{ marginTop: 8 }}>{status || "Creative direction is unavailable until analysis and planning exist."}</div>

      <div className="insight-grid" style={{ marginTop: 12 }}>
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ fontWeight: 900 }}>Audio-reactive direction</div>
            <div className="badge">Server-side</div>
          </div>

          <div className="small" style={{ marginTop: 8 }}>
            Duration {formatSeconds(metrics.duration_s)} • Source {payload?.metrics?.source || "analysis"}
          </div>

          {payload?.waveform?.length ? (
            <div className="insight-waveform" aria-label="Audio waveform" style={{ marginTop: 12 }}>
              {payload.waveform.map((value, index) => (
                <div key={`${index}-${value.toFixed(3)}`} className="insight-waveform-bar" style={{ height: `${Math.max(8, value * 100)}%` }} />
              ))}
            </div>
          ) : (
            <div className="insight-waveform-placeholder" style={{ marginTop: 12 }}>
              <div className="small">Waveform bars are derived on the backend when an energy curve is available from project analysis.</div>
            </div>
          )}

          <div className="insight-meter-grid" style={{ marginTop: 12 }}>
            <Meter label="Energy" value={metrics.energy} tone="linear-gradient(180deg, rgba(53,216,223,0.18), rgba(53,216,223,0.95))" />
            <Meter label="Bass" value={metrics.bass} tone="linear-gradient(180deg, rgba(255,122,102,0.18), rgba(255,122,102,0.95))" />
            <Meter label="Mid" value={metrics.mid} tone="linear-gradient(180deg, rgba(243,183,70,0.18), rgba(243,183,70,0.92))" />
            <Meter label="Treble" value={metrics.treble} tone="linear-gradient(180deg, rgba(143,112,255,0.18), rgba(143,112,255,0.92))" />
          </div>
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
                Generate a plan variant to build a real scene direction pack.
              </div>
            )}
          </div>

          <details style={{ marginTop: 12 }} open={!compact}>
            <summary style={{ cursor: "pointer", fontWeight: 800 }}>Prompt pack export</summary>
            <textarea
              readOnly
              value={String(payload?.export_text || "")}
              style={{ marginTop: 10, minHeight: compact ? 140 : 220 }}
            />
            {copyStatus ? <div className="small" style={{ marginTop: 8 }}>{copyStatus}</div> : null}
          </details>
        </div>
      </div>
    </div>
  );
}
