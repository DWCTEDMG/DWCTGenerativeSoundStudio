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
          <strong>{selectedRoute?.label || route}</strong>
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

      <div className="render-quickSettings">
        <label>
          <span>Quality</span>
          <select value={quality} onChange={(event) => onQualityChange(event.target.value as RenderQuickQuality)}>
            <option value="fast">Fast draft</option>
            <option value="balanced">Balanced</option>
            <option value="quality">High quality</option>
            <option value="ultra">Ultra / final</option>
          </select>
          <small>Adjusts the main preset, internal tier, steps, and sampling pace.</small>
        </label>
        <label>
          <span>Renderer</span>
          <select value={route} onChange={(event) => onRouteChange(event.target.value)}>
            {routeOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <small>Only real local or configured hosted routes appear here.</small>
        </label>
        <label>
          <span>Keyframe model</span>
          <select value={modelId} onChange={(event) => onModelChange(event.target.value)}>
            <option value="auto">Auto from installed models</option>
            {models.map((model) => (
              <option key={model.id} value={model.id} disabled={!model.installed}>
                {model.name}{model.installed ? "" : " (not installed)"}
              </option>
            ))}
          </select>
          <small>{selectedModel ? (selectedModel.installed ? "Installed and ready." : "Install this model before rendering.") : "Hardware-aware automatic choice."}</small>
        </label>
        <label>
          <span>Output frame rate</span>
          <select value={outputFps} onChange={(event) => onOutputFpsChange(Number(event.target.value))}>
            {[12, 15, 24, 25, 30, 48, 50, 60].map((fps) => <option key={fps} value={fps}>{fps} fps</option>)}
          </select>
          <small>Final delivery rate; internal generation can stay lower.</small>
        </label>
        <label>
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
            <option value="1080x1350">1080 × 1350 · portrait</option>
            <option value="1080x1920">1080 × 1920 · vertical</option>
            {![
              "768x432", "1024x576", "1280x720", "1920x1080", "1024x1024", "1080x1350", "1080x1920",
            ].includes(`${width}x${height}`) ? <option value={`${width}x${height}`}>{width} × {height} · custom</option> : null}
          </select>
          <small>Used by still workflows and generated video keyframes.</small>
        </label>
        <label className="render-quickToggle">
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
        </label>
      </div>

      <div className="render-controlCenterFooter">
        <div className="render-controlCenterSummary">
          <SlidersHorizontal size={17} aria-hidden="true" />
          <span>
            <strong>{selectedGoal.label}</strong> · {quality} · {outputFps} fps · {width}×{height}
            {timelineCamera ? " · Timeline motion on" : " · Timeline motion off"}
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
