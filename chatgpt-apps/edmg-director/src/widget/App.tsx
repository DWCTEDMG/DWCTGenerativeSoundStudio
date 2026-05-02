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

type PlannerImportResultOutput = {
  type: "planner-import-result";
  projectId: string;
  projectName: string;
  variantCount: number;
  appliedTimeline: boolean;
  timelineSummary: TimelineSummary | null;
  message: string;
};

type ReactiveApplyResultOutput = {
  type: "reactive-apply-result";
  projectId: string;
  projectName: string;
  cueEventCount: number;
  keyframeCount: number;
  sectionCount: number;
  timelineSummary: TimelineSummary | null;
  message: string;
};

type OperationResult =
  | ActionResultOutput
  | PlannerImportResultOutput
  | ReactiveApplyResultOutput;

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

function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
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

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
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

function isPlannerImportResult(value: unknown): value is PlannerImportResultOutput {
  return asRecord(value).type === "planner-import-result";
}

function isReactiveApplyResult(value: unknown): value is ReactiveApplyResultOutput {
  return asRecord(value).type === "reactive-apply-result";
}

function getActiveVariant(
  preview: PlanPreviewOutput | null,
  selectedVariantIndex: number,
): PlanVariant | null {
  if (!preview) {
    return null;
  }
  return (
    preview.variants.find((variant) => variant.index === selectedVariantIndex) ??
    preview.variants[0] ??
    null
  );
}

function inferCueType(transitionCue: string | null): "cut" | "push" | "orbit" | "hold" {
  const cue = String(transitionCue ?? "").toLowerCase();
  if (cue.includes("cut")) {
    return "cut";
  }
  if (cue.includes("push") || cue.includes("crash") || cue.includes("zoom")) {
    return "push";
  }
  if (cue.includes("orbit") || cue.includes("pivot") || cue.includes("rotate")) {
    return "orbit";
  }
  return "hold";
}

function inferRenderMode(scene: PlanScene): "smooth" | "cut-heavy" | "performance-led" | "ambient" {
  const text = `${scene.prompt} ${scene.transitionCue ?? ""} ${scene.shotType ?? ""}`.toLowerCase();
  if (text.includes("cut") || text.includes("flash")) {
    return "cut-heavy";
  }
  if (text.includes("perform") || text.includes("tracking") || text.includes("push")) {
    return "performance-led";
  }
  if (text.includes("ambient") || text.includes("drift") || text.includes("haze")) {
    return "ambient";
  }
  return "smooth";
}

function buildPlannerSyncPayload(
  preview: PlanPreviewOutput,
  selectedVariantIndex: number,
  previewInput: Record<string, unknown>,
) {
  const orderedVariants = [
    ...preview.variants.filter((variant) => variant.index === selectedVariantIndex),
    ...preview.variants.filter((variant) => variant.index !== selectedVariantIndex),
  ];

  const analysis = preview.analysisSummary
    ? {
        features: {
          bpm: preview.analysisSummary.bpm ?? undefined,
          duration_s: preview.analysisSummary.durationS ?? undefined,
        },
        hook_line: preview.analysisSummary.hookLine ?? undefined,
        narrative_structure: preview.analysisSummary.narrative ?? undefined,
      }
    : {};

  const plan = {
    title: preview.projectName,
    source: preview.planSource ?? "edmg-director",
    variants: orderedVariants.map((variant) => ({
      title: variant.label,
      summary: variant.summary ?? undefined,
      duration_s: variant.durationS ?? undefined,
      source_variant_index: variant.index,
      scenes: variant.scenes.map((scene) => ({
        title: scene.title,
        prompt: scene.prompt,
        start_s: scene.startS ?? undefined,
        end_s: scene.endS ?? undefined,
        duration_s: scene.durationS ?? undefined,
        shot_type: scene.shotType ?? undefined,
        rationale: scene.rationale ?? undefined,
        transition_cue: scene.transitionCue ?? undefined,
        continuity_note: scene.continuityNote ?? undefined,
      })),
    })),
  };

  const maxScenesFromInput = coerceNumber(previewInput.maxScenes);
  const numVariantsFromInput = coerceNumber(previewInput.numVariants);
  const maxScenes =
    maxScenesFromInput ??
    Math.max(...orderedVariants.map((variant) => variant.scenes.length), 1);

  const settings = {
    mode: preview.mode,
    selected_variant_index: selectedVariantIndex,
    requested_variant_count: numVariantsFromInput ?? preview.variants.length,
    requested_max_scenes: maxScenes,
    title: asString(previewInput.title) || preview.projectName,
    user_notes: asString(previewInput.userNotes) || undefined,
    style_prefs: asString(previewInput.stylePrefs) || undefined,
  };

  return {
    analysis,
    plan,
    settings,
  };
}

function buildReactiveDraft(preview: PlanPreviewOutput, selectedVariantIndex: number) {
  const variant = getActiveVariant(preview, selectedVariantIndex);
  if (!variant) {
    return {};
  }

  const keyframes = variant.scenes.map((scene, sceneIndex) => {
    const startTime = scene.startS ?? sceneIndex * 5;
    const frame = Math.max(0, Math.round(startTime * 24));
    return {
      frame,
      time: startTime,
      metrics: {
        energy: 0.65,
        bass: 0.5,
        mid: 0.55,
        treble: 0.45,
      },
      params: {
        shot_type: scene.shotType ?? undefined,
        continuity_hint: scene.continuityNote ?? undefined,
      },
      note: scene.title,
    };
  });

  const cueEvents = variant.scenes.map((scene, sceneIndex) => {
    const time = scene.startS ?? sceneIndex * 5;
    return {
      id: sceneIndex + 1,
      frame: Math.max(0, Math.round(time * 24)),
      time,
      cueType: inferCueType(scene.transitionCue),
      instruction:
        scene.transitionCue ||
        `Enter ${scene.title.toLowerCase()} with a ${scene.shotType ?? "steady"} move.`,
    };
  });

  const sections = variant.scenes.map((scene, sceneIndex) => ({
    id: sceneIndex + 1,
    startTime: scene.startS ?? sceneIndex * 5,
    endTime:
      scene.endS ??
      ((scene.startS ?? sceneIndex * 5) + Math.max(scene.durationS ?? 5, 1)),
    label: scene.title,
    approved: true,
    renderMode: inferRenderMode(scene),
  }));

  const repairSuggestions = variant.scenes
    .filter((scene) => Boolean(scene.continuityNote))
    .map((scene, sceneIndex) => ({
      id: sceneIndex + 1,
      sectionId: scene.index + 1,
      issue: scene.continuityNote,
      action:
        `Preserve ${String(scene.continuityNote).toLowerCase()} while keeping camera direction stable across adjacent scenes.`,
    }));

  const schedules = {
    zoom: "",
    rotation_y: "",
    rotation_z: "",
    translation_x: "",
    translation_y: "",
    translation_z: "",
    strength: "",
    cfg_scale: "",
    brightness: "",
  };

  return {
    metadata: {
      projectId: preview.projectId,
      projectName: preview.projectName,
      variantIndex: variant.index,
      variantLabel: variant.label,
      generatedBy: "edmg-director-widget",
      generatedAt: new Date().toISOString(),
    },
    keyframes,
    beatMarkers: keyframes.slice(1).map((keyframe, index) => ({
      frame: keyframe.frame,
      time: keyframe.time,
      intensity: 0.7 + (index % 2) * 0.1,
    })),
    cueEvents,
    sections,
    repairSuggestions,
    schedules,
    handoffManifest: {
      approvedSectionIds: sections.map((section) => section.id),
      renderMode: "smooth",
      scheduleStride: 1,
      cueEvents,
      repairSuggestions,
      schedules,
      modelHints: {
        executionPriority: "Preview section transitions first, then commit the approved sweep.",
        continuityPriority: "Carry shot language and continuity anchors across neighboring scenes.",
        fallbackAction: "Only rerender the flagged section and keep adjacent cue timings stable.",
      },
    },
  };
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

function ResultView(props: {
  result: OperationResult;
  onAskAssistant: () => Promise<void>;
}) {
  let eyebrow = "Timeline Update";
  let pills: string[] = [];

  if (props.result.type === "action-result") {
    pills = [
      `variant ${props.result.variantIndex + 1}`,
      props.result.overwrite ? "overwrite" : "merge",
    ];
  } else if (props.result.type === "planner-import-result") {
    eyebrow = "Planner Import";
    pills = [
      `${props.result.variantCount} variant${props.result.variantCount === 1 ? "" : "s"}`,
      props.result.appliedTimeline ? "timeline refreshed" : "plan only",
    ];
  } else if (props.result.type === "reactive-apply-result") {
    eyebrow = "Reactive Handoff";
    pills = [
      `${props.result.cueEventCount} cue${props.result.cueEventCount === 1 ? "" : "s"}`,
      `${props.result.keyframeCount} keyframe${props.result.keyframeCount === 1 ? "" : "s"}`,
      `${props.result.sectionCount} section${props.result.sectionCount === 1 ? "" : "s"}`,
    ];
  }

  if (props.result.timelineSummary) {
    pills.push(
      `${props.result.timelineSummary.trackCount} track${props.result.timelineSummary.trackCount === 1 ? "" : "s"}`,
    );
  }

  return (
    <section className="result-card">
      <div className="result-header">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2>{props.result.projectName}</h2>
        </div>
        <button className="ghost-button" onClick={() => void props.onAskAssistant()}>
          Discuss Next Steps
        </button>
      </div>
      <p>{props.result.message}</p>
      <div className="pill-row">
        {pills.map((pill) => (
          <span key={pill} className="pill">
            {pill}
          </span>
        ))}
      </div>
    </section>
  );
}

function VariantCard(props: {
  variant: PlanVariant;
  busy: boolean;
  isWorkingVariant: boolean;
  onApply: () => Promise<void>;
  onSelect: () => void;
}) {
  return (
    <article className={`variant-card ${props.isWorkingVariant ? "selected-card" : ""}`}>
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

      <div className="card-actions">
        <button className="ghost-button" onClick={props.onSelect}>
          {props.isWorkingVariant ? "Working Variant" : "Use For Handoff"}
        </button>
        <button
          className="primary-button apply-button"
          disabled={props.busy}
          onClick={() => void props.onApply()}
        >
          {props.busy ? "Applying..." : "Apply To Timeline"}
        </button>
      </div>

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

function HandoffPanel(props: {
  preview: PlanPreviewOutput;
  activeVariant: PlanVariant | null;
  plannerBusy: boolean;
  reactiveBusy: boolean;
  plannerApplyTimeline: boolean;
  plannerOverwriteTimeline: boolean;
  reactiveOverwriteMotionTrack: boolean;
  reactiveOverwriteCamera: boolean;
  reactiveDraft: string;
  reactiveDirty: boolean;
  onPlannerApplyTimelineChange: (value: boolean) => void;
  onPlannerOverwriteTimelineChange: (value: boolean) => void;
  onReactiveOverwriteMotionTrackChange: (value: boolean) => void;
  onReactiveOverwriteCameraChange: (value: boolean) => void;
  onReactiveDraftChange: (value: string) => void;
  onResetReactiveDraft: () => void;
  onImportPlanner: () => Promise<void>;
  onApplyReactive: () => Promise<void>;
}) {
  return (
    <section className="handoff-panel">
      <div className="handoff-header">
        <div>
          <div className="eyebrow">Studio Handoff</div>
          <h2>Push the working variant back into Studio</h2>
          <p>
            Planner import reorders the current review pack so the working variant becomes
            variant 1 in the imported plan. That matches the backend behavior that applies
            variant 0 when timeline sync is enabled.
          </p>
        </div>
        {props.activeVariant ? (
          <div className="pill-row">
            <span className="pill">working: {props.activeVariant.label}</span>
            <span className="pill">
              {props.activeVariant.scenes.length} scene
              {props.activeVariant.scenes.length === 1 ? "" : "s"}
            </span>
            <span className="pill">{formatSeconds(props.activeVariant.durationS)}</span>
          </div>
        ) : null}
      </div>

      <div className="handoff-grid">
        <article className="handoff-card">
          <div className="handoff-card-head">
            <div>
              <h3>Planner Sync</h3>
              <p>
                Import the review board preview as a planner payload and optionally refresh
                the Studio timeline immediately.
              </p>
            </div>
            <button
              className="primary-button"
              disabled={!props.activeVariant || props.plannerBusy}
              onClick={() => void props.onImportPlanner()}
            >
              {props.plannerBusy ? "Syncing..." : "Import Current Preview"}
            </button>
          </div>

          <div className="option-grid">
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={props.plannerApplyTimeline}
                onChange={(event) => props.onPlannerApplyTimelineChange(event.target.checked)}
              />
              <span>Apply timeline after import</span>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={props.plannerOverwriteTimeline}
                onChange={(event) => props.onPlannerOverwriteTimelineChange(event.target.checked)}
              />
              <span>Overwrite existing timeline</span>
            </label>
          </div>
        </article>

        <article className="handoff-card">
          <div className="handoff-card-head">
            <div>
              <h3>Reactive Handoff</h3>
              <p>
                Start from an auto-generated handoff JSON for the working variant, then edit
                it before sending cue events and schedules into Studio.
              </p>
            </div>
            <div className="card-actions">
              <button className="ghost-button" onClick={props.onResetReactiveDraft}>
                Reset Draft
              </button>
              <button
                className="primary-button"
                disabled={!props.activeVariant || props.reactiveBusy}
                onClick={() => void props.onApplyReactive()}
              >
                {props.reactiveBusy ? "Applying..." : "Apply Reactive Handoff"}
              </button>
            </div>
          </div>

          <div className="option-grid">
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={props.reactiveOverwriteMotionTrack}
                onChange={(event) => props.onReactiveOverwriteMotionTrackChange(event.target.checked)}
              />
              <span>Overwrite motion track</span>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={props.reactiveOverwriteCamera}
                onChange={(event) => props.onReactiveOverwriteCameraChange(event.target.checked)}
              />
              <span>Overwrite camera track</span>
            </label>
          </div>

          <label className="editor-label" htmlFor="reactive-draft">
            Reactive payload JSON{props.reactiveDirty ? " (edited)" : ""}
          </label>
          <textarea
            id="reactive-draft"
            className="json-editor"
            value={props.reactiveDraft}
            onChange={(event) => props.onReactiveDraftChange(event.target.value)}
            spellCheck={false}
          />
        </article>
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
  const initialPreview = isPlanPreview(initialOutput) ? initialOutput : null;
  const initialPreviewInput = initialPreview ? asRecord(host()?.toolInput) : null;
  const initialSelectedVariantIndex =
    initialPreview?.selectedVariantIndex ?? initialPreview?.variants[0]?.index ?? 0;

  const [output, setOutput] = useState<unknown>(initialOutput);
  const [lastPreview, setLastPreview] = useState<PlanPreviewOutput | null>(initialPreview);
  const [lastPreviewInput, setLastPreviewInput] = useState<Record<string, unknown> | null>(
    initialPreviewInput,
  );
  const [selectedVariantIndex, setSelectedVariantIndex] = useState<number>(
    initialSelectedVariantIndex,
  );
  const [busyVariantIndex, setBusyVariantIndex] = useState<number | null>(null);
  const [plannerBusy, setPlannerBusy] = useState(false);
  const [reactiveBusy, setReactiveBusy] = useState(false);
  const [plannerApplyTimeline, setPlannerApplyTimeline] = useState(true);
  const [plannerOverwriteTimeline, setPlannerOverwriteTimeline] = useState(true);
  const [reactiveOverwriteMotionTrack, setReactiveOverwriteMotionTrack] = useState(true);
  const [reactiveOverwriteCamera, setReactiveOverwriteCamera] = useState(true);
  const [reactiveDraft, setReactiveDraft] = useState<string>(
    initialPreview ? formatJson(buildReactiveDraft(initialPreview, initialSelectedVariantIndex)) : "",
  );
  const [reactiveDirty, setReactiveDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    applyTheme(host()?.theme);
    const sync = () => {
      applyTheme(host()?.theme);
      const nextOutput = readToolOutput(host()?.toolOutput);
      setOutput(nextOutput);
      if (isPlanPreview(nextOutput)) {
        setLastPreview(nextOutput);
        setLastPreviewInput(asRecord(host()?.toolInput));
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
      setLastPreviewInput(asRecord(host()?.toolInput));
    }
  }, [output]);

  const preview = useMemo(
    () => (isPlanPreview(output) ? output : lastPreview),
    [lastPreview, output],
  );
  const activeVariant = useMemo(
    () => getActiveVariant(preview, selectedVariantIndex),
    [preview, selectedVariantIndex],
  );
  const operationResult = useMemo(() => {
    if (isActionResult(output) || isPlannerImportResult(output) || isReactiveApplyResult(output)) {
      return output;
    }
    return null;
  }, [output]);

  useEffect(() => {
    if (!preview) {
      return;
    }
    const selectedStillExists = preview.variants.some(
      (variant) => variant.index === selectedVariantIndex,
    );
    if (!selectedStillExists) {
      setSelectedVariantIndex(preview.selectedVariantIndex ?? preview.variants[0]?.index ?? 0);
    }
  }, [preview, selectedVariantIndex]);

  useEffect(() => {
    if (!preview || !activeVariant || reactiveDirty) {
      return;
    }
    setReactiveDraft(formatJson(buildReactiveDraft(preview, activeVariant.index)));
  }, [activeVariant, preview, reactiveDirty]);

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

  async function handleImportPlanner(): Promise<void> {
    if (!preview || !activeVariant) {
      setError("No working variant is available for planner import.");
      return;
    }
    if (!host()?.callTool) {
      setError("The ChatGPT host bridge is unavailable.");
      return;
    }

    setPlannerBusy(true);
    setError(null);

    try {
      const payload = buildPlannerSyncPayload(
        preview,
        activeVariant.index,
        lastPreviewInput ?? {},
      );
      const result = await host()!.callTool!("import_planner_lab_payload", {
        projectId: preview.projectId,
        analysis: payload.analysis,
        plan: payload.plan,
        settings: payload.settings,
        applyTimeline: plannerApplyTimeline,
        overwriteTimeline: plannerOverwriteTimeline,
      });
      setOutput(readToolOutput(result));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Planner import failed.");
    } finally {
      setPlannerBusy(false);
    }
  }

  async function handleApplyReactive(): Promise<void> {
    if (!preview || !activeVariant) {
      setError("No working variant is available for reactive handoff.");
      return;
    }
    if (!host()?.callTool) {
      setError("The ChatGPT host bridge is unavailable.");
      return;
    }

    setReactiveBusy(true);
    setError(null);

    try {
      const parsed = asRecord(JSON.parse(reactiveDraft));
      const result = await host()!.callTool!("apply_reactive_handoff", {
        projectId: preview.projectId,
        metadata: asRecord(parsed.metadata),
        keyframes: asArray(parsed.keyframes),
        beatMarkers: asArray(parsed.beatMarkers),
        cueEvents: asArray(parsed.cueEvents),
        sections: asArray(parsed.sections),
        repairSuggestions: asArray(parsed.repairSuggestions),
        schedules: asRecord(parsed.schedules),
        handoffManifest: asRecord(parsed.handoffManifest),
        overwriteMotionTrack: reactiveOverwriteMotionTrack,
        overwriteCamera: reactiveOverwriteCamera,
      });
      setOutput(readToolOutput(result));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Reactive handoff failed. Check the JSON payload and retry.",
      );
    } finally {
      setReactiveBusy(false);
    }
  }

  function handleReactiveDraftChange(value: string): void {
    setReactiveDraft(value);
    setReactiveDirty(true);
  }

  function handleResetReactiveDraft(): void {
    if (!preview || !activeVariant) {
      return;
    }
    setReactiveDraft(formatJson(buildReactiveDraft(preview, activeVariant.index)));
    setReactiveDirty(false);
  }

  async function handleAskAssistant(): Promise<void> {
    if (!host()?.sendFollowUpMessage) {
      setError("Follow-up messaging is unavailable in this host.");
      return;
    }
    setError(null);
    try {
      const variantPrompt = activeVariant
        ? `Focus on ${activeVariant.label} while comparing it to the other variants.`
        : "Compare the current EDMG variants.";
      await host()!.sendFollowUpMessage!(
        `${variantPrompt} Recommend the strongest direction, call out continuity risks, and suggest whether I should import planner state, reactive handoff, or both before committing the timeline.`,
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

  if (!preview && !operationResult) {
    return <FallbackView raw={output} />;
  }

  return (
    <main className="shell">
      {operationResult ? (
        <ResultView result={operationResult} onAskAssistant={handleAskAssistant} />
      ) : null}
      {error ? (
        <StatusBanner tone="error" title="Action failed" detail={error} />
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
          <HandoffPanel
            preview={preview}
            activeVariant={activeVariant}
            plannerBusy={plannerBusy}
            reactiveBusy={reactiveBusy}
            plannerApplyTimeline={plannerApplyTimeline}
            plannerOverwriteTimeline={plannerOverwriteTimeline}
            reactiveOverwriteMotionTrack={reactiveOverwriteMotionTrack}
            reactiveOverwriteCamera={reactiveOverwriteCamera}
            reactiveDraft={reactiveDraft}
            reactiveDirty={reactiveDirty}
            onPlannerApplyTimelineChange={setPlannerApplyTimeline}
            onPlannerOverwriteTimelineChange={setPlannerOverwriteTimeline}
            onReactiveOverwriteMotionTrackChange={setReactiveOverwriteMotionTrack}
            onReactiveOverwriteCameraChange={setReactiveOverwriteCamera}
            onReactiveDraftChange={handleReactiveDraftChange}
            onResetReactiveDraft={handleResetReactiveDraft}
            onImportPlanner={handleImportPlanner}
            onApplyReactive={handleApplyReactive}
          />
          <section className="variant-grid">
            {preview.variants.map((variant) => (
              <VariantCard
                key={variant.index}
                variant={variant}
                busy={busyVariantIndex === variant.index}
                isWorkingVariant={activeVariant?.index === variant.index}
                onApply={() => handleApplyVariant(variant.index)}
                onSelect={() => setSelectedVariantIndex(variant.index)}
              />
            ))}
          </section>
        </>
      ) : null}
    </main>
  );
}
