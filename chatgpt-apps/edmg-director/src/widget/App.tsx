import { useEffect, useMemo, useState } from "react";

type HostApi = {
  theme?: string;
  locale?: string;
  displayMode?: string;
  toolInput?: unknown;
  toolOutput?: unknown;
  toolResponseMetadata?: Record<string, unknown>;
  widgetState?: unknown;
  callTool?: (name: string, args?: Record<string, unknown>) => Promise<unknown>;
  sendFollowUpMessage?: (message: string) => Promise<unknown> | void;
  requestDisplayMode?: (args: { mode: "inline" | "pip" | "fullscreen" }) => Promise<unknown> | void;
};

type PlanScene = {
  index: number;
  title: string;
  prompt: string;
  startS: number | null;
  endS: number | null;
  durationS: number | null;
  shotType: string | null;
  rationale: string | null;
  transitionCue: string | null;
  continuityNote: string | null;
};

type PlanVariant = {
  index: number;
  label: string;
  summary: string | null;
  durationS: number | null;
  scenes: PlanScene[];
};

type AnalysisSummary = {
  bpm: number | null;
  durationS: number | null;
  hookLine: string | null;
  narrative: string | null;
};

type PlanPreviewOutput = {
  type: "plan-preview";
  projectId: string;
  projectName: string;
  mode: string;
  planSource: string | null;
  selectedVariantIndex: number;
  analysisSummary: AnalysisSummary | null;
  variants: PlanVariant[];
};

type TimelineSummary = {
  rootKeys: string[];
  trackCount: number;
};

type ActionResultOutput = {
  type: "action-result";
  projectId: string;
  projectName: string;
  variantIndex: number;
  overwrite: boolean;
  applied: boolean;
  message: string;
  timelineSummary: TimelineSummary | null;
};

declare global {
  interface Window {
    openai?: HostApi;
  }
}

function host(): HostApi | undefined {
  return window.openai;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function readToolOutput(value: unknown): unknown {
  const record = asRecord(value);
  if ("structuredContent" in record) {
    return record.structuredContent;
  }
  return value;
}

function formatSeconds(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "TBD";
  }
  const total = Math.max(0, Math.round(value));
  const minutes = Math.floor(total / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (total % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function applyTheme(theme?: string): void {
  const normalized = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = normalized;
  document.documentElement.style.colorScheme = normalized;
}

function isPlanPreview(value: unknown): value is PlanPreviewOutput {
  const record = asRecord(value);
  return record.type === "plan-preview" && Array.isArray(record.variants);
}

function isActionResult(value: unknown): value is ActionResultOutput {
  return asRecord(value).type === "action-result";
}

function StatusBanner(props: {
  tone: "success" | "error";
  title: string;
  detail: string;
}) {
  return (
    <section className={`status-banner ${props.tone}`}>
      <div className="status-title">{props.title}</div>
      <p>{props.detail}</p>
    </section>
  );
}

function Hero(props: {
  projectName: string;
  mode: string;
  source: string | null;
  variantCount: number;
  onFullscreen: () => Promise<void>;
  onAskAssistant: () => Promise<void>;
}) {
  return (
    <header className="hero">
      <div>
        <div className="eyebrow">EDMG Director</div>
        <h1>{props.projectName}</h1>
        <p>
          Interactive storyboard review for {props.variantCount} variant
          {props.variantCount === 1 ? "" : "s"}.
        </p>
      </div>
      <div className="hero-meta">
        <div className="pill-row">
          <span className="pill">mode: {props.mode}</span>
          {props.source ? <span className="pill">source: {props.source}</span> : null}
        </div>
        <div className="hero-actions">
          <button className="ghost-button" onClick={() => void props.onAskAssistant()}>
            Ask ChatGPT
          </button>
          <button className="primary-button" onClick={() => void props.onFullscreen()}>
            Fullscreen
          </button>
        </div>
      </div>
    </header>
  );
}

function AnalysisPanel(props: { summary: AnalysisSummary | null }) {
  if (!props.summary) {
    return (
      <section className="analysis-panel muted">
        <h2>Analysis Snapshot</h2>
        <p>No audio analysis summary was attached to this plan.</p>
      </section>
    );
  }

  return (
    <section className="analysis-panel">
      <h2>Analysis Snapshot</h2>
      <div className="metric-grid">
        <div className="metric-card">
          <span className="metric-label">Tempo</span>
          <strong>{props.summary.bpm ?? "?"} BPM</strong>
        </div>
        <div className="metric-card">
          <span className="metric-label">Duration</span>
          <strong>{formatSeconds(props.summary.durationS)}</strong>
        </div>
        <div className="metric-card">
          <span className="metric-label">Narrative</span>
          <strong>{props.summary.narrative ?? "Unspecified"}</strong>
        </div>
      </div>
      {props.summary.hookLine ? (
        <div className="hook-line">
          <span className="metric-label">Hook line</span>
          <p>{props.summary.hookLine}</p>
        </div>
      ) : null}
    </section>
  );
}

function VariantCard(props: {
  variant: PlanVariant;
  busy: boolean;
  onApply: () => Promise<void>;
}) {
  return (
    <article className="variant-card">
      <div className="variant-head">
        <div>
          <div className="variant-kicker">Variant {props.variant.index + 1}</div>
          <h3>{props.variant.label}</h3>
          {props.variant.summary ? <p>{props.variant.summary}</p> : null}
        </div>
        <div className="variant-side">
          <span className="scene-count">
            {props.variant.scenes.length} scene{props.variant.scenes.length === 1 ? "" : "s"}
          </span>
          <span className="scene-count">{formatSeconds(props.variant.durationS)}</span>
        </div>
      </div>

      <button
        className="primary-button apply-button"
        disabled={props.busy}
        onClick={() => void props.onApply()}
      >
        {props.busy ? "Applying..." : "Apply To Timeline"}
      </button>

      <div className="scene-list">
        {props.variant.scenes.map((scene) => (
          <section key={`${props.variant.index}-${scene.index}`} className="scene-card">
            <div className="scene-head">
              <div>
                <span className="scene-chip">Scene {scene.index + 1}</span>
                <h4>{scene.title}</h4>
              </div>
              <span className="scene-time">
                {formatSeconds(scene.startS)} - {formatSeconds(scene.endS)}
              </span>
            </div>
            {scene.shotType ? <div className="micro-note">shot: {scene.shotType}</div> : null}
            <p className="scene-prompt">{scene.prompt || "No prompt provided."}</p>
            <div className="scene-notes">
              {scene.rationale ? (
                <div>
                  <span>Rationale</span>
                  <p>{scene.rationale}</p>
                </div>
              ) : null}
              {scene.transitionCue ? (
                <div>
                  <span>Transition</span>
                  <p>{scene.transitionCue}</p>
                </div>
              ) : null}
              {scene.continuityNote ? (
                <div>
                  <span>Continuity</span>
                  <p>{scene.continuityNote}</p>
                </div>
              ) : null}
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}

function ActionResultView(props: {
  result: ActionResultOutput;
  onAskAssistant: () => Promise<void>;
}) {
  return (
    <section className="result-card">
      <div className="result-header">
        <div>
          <div className="eyebrow">Timeline Update</div>
          <h2>{props.result.projectName}</h2>
        </div>
        <button className="ghost-button" onClick={() => void props.onAskAssistant()}>
          Discuss Next Steps
        </button>
      </div>
      <p>{props.result.message}</p>
      <div className="pill-row">
        <span className="pill">variant {props.result.variantIndex + 1}</span>
        <span className="pill">{props.result.overwrite ? "overwrite" : "merge"}</span>
        {props.result.timelineSummary ? (
          <span className="pill">
            {props.result.timelineSummary.trackCount} track
            {props.result.timelineSummary.trackCount === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>
    </section>
  );
}

function FallbackView(props: { raw: unknown }) {
  return (
    <section className="fallback-card">
      <div className="eyebrow">Widget Output</div>
      <h1>Awaiting plan preview</h1>
      <p>
        Run <code>generate_plan_preview</code> to load storyboard variants into the review
        board.
      </p>
      {props.raw ? <pre>{JSON.stringify(props.raw, null, 2)}</pre> : null}
    </section>
  );
}

export default function App() {
  const initialOutput = readToolOutput(host()?.toolOutput);
  const [output, setOutput] = useState<unknown>(initialOutput);
  const [lastPreview, setLastPreview] = useState<PlanPreviewOutput | null>(
    isPlanPreview(initialOutput) ? initialOutput : null,
  );
  const [busyVariantIndex, setBusyVariantIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    applyTheme(host()?.theme);
    const sync = () => {
      applyTheme(host()?.theme);
      const nextOutput = readToolOutput(host()?.toolOutput);
      setOutput(nextOutput);
      if (isPlanPreview(nextOutput)) {
        setLastPreview(nextOutput);
      }
    };

    window.addEventListener("openai:set_globals", sync as EventListener);
    return () => {
      window.removeEventListener("openai:set_globals", sync as EventListener);
    };
  }, []);

  useEffect(() => {
    if (isPlanPreview(output)) {
      setLastPreview(output);
    }
  }, [output]);

  const preview = useMemo(
    () => (isPlanPreview(output) ? output : lastPreview),
    [lastPreview, output],
  );
  const actionResult = isActionResult(output) ? output : null;

  async function handleApplyVariant(variantIndex: number): Promise<void> {
    if (!preview) {
      setError("No plan preview is loaded.");
      return;
    }
    if (!host()?.callTool) {
      setError("The ChatGPT host bridge is unavailable.");
      return;
    }

    setBusyVariantIndex(variantIndex);
    setError(null);

    try {
      const result = await host()!.callTool!("apply_plan_variant", {
        projectId: preview.projectId,
        variantIndex,
        overwrite: true,
      });
      setOutput(readToolOutput(result));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to apply the selected variant.");
    } finally {
      setBusyVariantIndex(null);
    }
  }

  async function handleAskAssistant(): Promise<void> {
    if (!host()?.sendFollowUpMessage) {
      setError("Follow-up messaging is unavailable in this host.");
      return;
    }
    setError(null);
    try {
      await host()!.sendFollowUpMessage!(
        "Compare the current EDMG variants, recommend the strongest direction, and call out any continuity risks before I commit the timeline.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send the follow-up prompt.");
    }
  }

  async function handleFullscreen(): Promise<void> {
    try {
      await host()?.requestDisplayMode?.({ mode: "fullscreen" });
    } catch {
      // Layout requests are best-effort only.
    }
  }

  if (!preview && !actionResult) {
    return <FallbackView raw={output} />;
  }

  return (
    <main className="shell">
      {actionResult ? (
        <ActionResultView result={actionResult} onAskAssistant={handleAskAssistant} />
      ) : null}
      {error ? (
        <StatusBanner
          tone="error"
          title="Action failed"
          detail={error}
        />
      ) : null}
      {preview ? (
        <>
          <Hero
            projectName={preview.projectName}
            mode={preview.mode}
            source={preview.planSource}
            variantCount={preview.variants.length}
            onAskAssistant={handleAskAssistant}
            onFullscreen={handleFullscreen}
          />
          <AnalysisPanel summary={preview.analysisSummary} />
          <section className="variant-grid">
            {preview.variants.map((variant) => (
              <VariantCard
                key={variant.index}
                variant={variant}
                busy={busyVariantIndex === variant.index}
                onApply={() => handleApplyVariant(variant.index)}
              />
            ))}
          </section>
        </>
      ) : null}
    </main>
  );
}
