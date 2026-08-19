import React from "react";
import {
  Film,
  Gauge,
  Image as ImageIcon,
  Layers3,
  Scissors,
  Settings2,
  SlidersHorizontal,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";

export type RenderQuickGoal =
  | "auto"
  | "full_video"
  | "motion_ad"
  | "motion_svd"
  | "stills"
  | "edit";

export type RenderQuickQuality = "fast" | "balanced" | "quality" | "ultra";

export type RenderQuickModel = {
  id: string;
  name: string;
  installed: boolean;
};

const GOALS: Array<{
  id: RenderQuickGoal;
  label: string;
  detail: string;
  icon: LucideIcon;
}> = [
  {
    id: "auto",
    label: "Auto master",
    detail: "Studio chooses the best available real renderer.",
    icon: WandSparkles,
  },
  {
    id: "full_video",
    label: "Full-motion video",
    detail: "Use downloaded SVD or AnimateDiff models scene by scene.",
    icon: Film,
  },
  {
    id: "motion_ad",
    label: "AnimateDiff",
    detail: "Prompt-driven motion with context controls.",
    icon: Layers3,
  },
  {
    id: "motion_svd",
    label: "Image to video",
    detail: "Use SVD to animate planned keyframes or source images.",
    icon: ImageIcon,
  },
  {
    id: "stills",
    label: "Still scenes",
    detail: "Render editable scene frames with full image controls.",
    icon: Gauge,
  },
  {
    id: "edit",
    label: "Edit existing video",
    detail: "Open rendered clips in the DAW-style Timeline editor.",
    icon: Scissors,
  },
];

export function RenderControlCenter({
  goal,
  onGoalChange,
  quality,
  onQualityChange,
  route,
  onRouteChange,
  routeOptions,
  modelId,
  onModelChange,
  models,
  outputFps,
  onOutputFpsChange,
  width,
  height,
  onResolutionChange,
  timelineCamera,
  onTimelineCameraChange,
  onRun,
  runDisabled,
  runLabel,
  onOpenAllSettings,
  onOpenModels,
}: {
  goal: RenderQuickGoal;
  onGoalChange: (goal: RenderQuickGoal) => void;
  quality: RenderQuickQuality;
  onQualityChange: (quality: RenderQuickQuality) => void;
  route: string;
  onRouteChange: (route: string) => void;
  routeOptions: Array<{ value: string; label: string }>;
  modelId: string;
  onModelChange: (modelId: string) => void;
  models: RenderQuickModel[];
  outputFps: number;
  onOutputFpsChange: (fps: number) => void;
  width: number;
  height: number;
  onResolutionChange: (width: number, height: number) => void;
  timelineCamera: boolean;
  onTimelineCameraChange: (enabled: boolean) => void;
  onRun: () => void;
  runDisabled: boolean;
  runLabel: string;
  onOpenAllSettings: () => void;
  onOpenModels: () => void;
}) {
  const selectedGoal = GOALS.find((option) => option.id === goal) || GOALS[0];
  const selectedModel = models.find((model) => model.id === modelId);
  const selectedRoute = routeOptions.find((option) => option.value === route);
  const showQuality = goal !== "edit";
  const showRenderer = goal === "full_video";
  const showModel = goal === "full_video" || goal === "motion_ad" || goal === "motion_svd" || goal === "stills";
  const showOutputFps = goal === "full_video" || goal === "motion_ad" || goal === "motion_svd";
  const showResolution = showModel;
  const showTimelineCamera = goal === "full_video";
  const modelLabel = goal === "motion_ad"
    ? "AnimateDiff base model"
    : goal === "motion_svd"
      ? "SVD model"
      : goal === "stills"
        ? "Still model"
        : "Keyframe model";
  const statusLabel = goal === "auto"
    ? "Orchestrator · best real route"
    : goal === "motion_ad"
      ? "ComfyUI · AnimateDiff"
      : goal === "motion_svd"
        ? "ComfyUI · SVD"
        : goal === "stills"
          ? "Still-image workflow"
          : goal === "edit"
            ? "Timeline · non-destructive edit"
            : selectedRoute?.label || route;

  return (
    <section className="render-controlCenter" aria-labelledby="render-control-center-title">
      <div className="render-controlCenterHeader">
        <div>
          <div className="render-controlCenterKicker">Render Control Center</div>
          <h2 id="render-control-center-title">Choose the result first. Fine-tune only what matters.</h2>
          <p>
            Every specialist control remains available below. This surface changes the same settings in a faster,
            plain-language workflow.
          </p>
        </div>
        <div className="render-controlCenterStatus">
          <span>Current route</span>
          <strong>{statusLabel}</strong>
          <small>Proxy substitution is off. Renders use an installed model or a configured provider.</small>
        </div>
      </div>

      <div className="render-goalGrid" role="radiogroup" aria-label="Render goal">
        {GOALS.map((option) => {
          const Icon = option.icon;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={goal === option.id}
              className={`render-goalButton${goal === option.id ? " is-active" : ""}`}
              onClick={() => onGoalChange(option.id)}
            >
              <Icon size={18} aria-hidden="true" />
              <span>
                <strong>{option.label}</strong>
                <small>{option.detail}</small>
              </span>
            </button>
          );
        })}
      </div>

      {goal === "edit" ? (
        <div className="render-quickSettings" role="status">
          <div className="small">
            Open Timeline to place completed renders on video lanes, split and trim clips, change speed, audio,
            and fades, then export a new master without changing the source files.
          </div>
        </div>
      ) : (
      <div className="render-quickSettings">
        {showQuality ? <label>
          <span>Quality</span>
          <select value={quality} onChange={(event) => onQualityChange(event.target.value as RenderQuickQuality)}>
            <option value="fast">Fast draft</option>
            <option value="balanced">Balanced</option>
            <option value="quality">High quality</option>
            <option value="ultra">Ultra / final</option>
          </select>
          <small>Adjusts the main preset, internal tier, steps, and sampling pace.</small>
        </label> : null}
        {showRenderer ? <label>
          <span>Renderer</span>
          <select value={route} onChange={(event) => onRouteChange(event.target.value)}>
            {routeOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <small>Only real local or configured hosted routes appear here.</small>
        </label> : null}
        {showModel ? <label>
          <span>{modelLabel}</span>
          <select value={modelId} onChange={(event) => onModelChange(event.target.value)}>
            <option value="auto">Auto from installed models</option>
            {models.map((model) => (
              <option key={model.id} value={model.id} disabled={!model.installed}>
                {model.name}{model.installed ? "" : " (not installed)"}
              </option>
            ))}
          </select>
          <small>{selectedModel ? (selectedModel.installed ? "Installed and ready." : "Install this model before rendering.") : "Hardware-aware automatic choice."}</small>
        </label> : null}
        {showOutputFps ? <label>
          <span>Output frame rate</span>
          <input
            aria-label="Output frame rate"
            type="number"
            min={1}
            max={60}
            step={1}
            value={outputFps}
            onChange={(event) => onOutputFpsChange(Math.max(1, Math.min(60, Number(event.target.value) || 1)))}
          />
          <small>Final delivery rate; internal generation can stay lower.</small>
        </label> : null}
        {showResolution ? <label>
          <span>Still / keyframe size</span>
          <select
            value={`${width}x${height}`}
            onChange={(event) => {
              const [nextWidth, nextHeight] = event.target.value.split("x").map(Number);
              onResolutionChange(nextWidth, nextHeight);
            }}
          >
            <option value="768x432">768 × 432 · preview</option>
            <option value="1024x576">1024 × 576 · 16:9</option>
            <option value="1280x720">1280 × 720 · HD</option>
            <option value="1920x1080">1920 × 1080 · Full HD</option>
            <option value="1024x1024">1024 × 1024 · square</option>
            <option value="864x1080">864 × 1080 · portrait</option>
            <option value="576x1024">576 × 1024 · vertical</option>
            {![
              "768x432", "1024x576", "1280x720", "1920x1080", "1024x1024", "864x1080", "576x1024",
            ].includes(`${width}x${height}`) ? <option value={`${width}x${height}`}>{width} × {height} · custom</option> : null}
          </select>
          <small>Used by still workflows and generated video keyframes.</small>
        </label> : null}
        {showTimelineCamera ? <label className="render-quickToggle">
          <span>Timeline motion</span>
          <span className="render-switchRow">
            <input
              type="checkbox"
              checked={timelineCamera}
              onChange={(event) => onTimelineCameraChange(event.target.checked)}
            />
            Apply Timeline camera after model generation
          </span>
          <small>Keeps zoom, pan, depth, pitch, yaw, roll, and rotation authored in Timeline.</small>
        </label> : null}
      </div>
      )}

      <div className="render-controlCenterFooter">
        <div className="render-controlCenterSummary">
          <SlidersHorizontal size={17} aria-hidden="true" />
          <span>
            <strong>{selectedGoal.label}</strong>
            {showQuality ? ` · ${quality}` : ""}
            {showOutputFps ? ` · ${outputFps} fps` : ""}
            {showResolution ? ` · ${width}×${height}` : ""}
            {showTimelineCamera ? (timelineCamera ? " · Timeline motion on" : " · Timeline motion off") : ""}
          </span>
        </div>
        <div className="render-controlCenterActions">
          <button type="button" className="secondary" onClick={onOpenModels}>Models</button>
          <button type="button" className="secondary" onClick={onOpenAllSettings}>
            <Settings2 size={15} aria-hidden="true" />
            All renderer settings
          </button>
          <button type="button" className="primary" onClick={onRun} disabled={runDisabled}>{runLabel}</button>
        </div>
      </div>
    </section>
  );
}
