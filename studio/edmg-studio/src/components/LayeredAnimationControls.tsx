import React, { useEffect, useMemo, useState } from "react";
import { Boxes, ChevronRight, Layers3, WandSparkles } from "lucide-react";

export type LayeredAnimationMode = "parallax" | "masked" | "segment" | "background";

export type LayerMaskSetting = {
  mask_asset: string;
  prompt: string | null;
  depth: number;
  motion_scale: number;
  strength: number;
};

export type LayeredAnimationPayload = {
  source_asset: string;
  mode: LayeredAnimationMode;
  motion: string;
  bands: number;
  masks: LayerMaskSetting[];
  subject_motion: number;
  background_motion: number;
  fps: number;
  duration_s: number;
  width: number;
  height: number;
  include_audio: boolean;
  diffusion_refine: boolean;
  model_id: string;
  device_preference: "auto" | "cpu" | "cuda" | "mps" | "directml";
  refine_prompt: string | null;
  refine_negative: string;
  refine_denoise: number;
  refine_steps: number;
  refine_cfg: number;
  seed: number | null;
};

type MediaOption = { path: string };
type ModelOption = { id: string; name: string; installed: boolean };

const MODE_OPTIONS: Array<{ value: LayeredAnimationMode; label: string; hint: string }> = [
  { value: "parallax", label: "Depth-band parallax", hint: "Split the image into near/far bands and move them at different depths." },
  { value: "segment", label: "Animate subject", hint: "Automatically separate the main subject from the background." },
  { value: "background", label: "Animate background", hint: "Keep the subject steadier while the background receives parallax motion." },
  { value: "masked", label: "Masked objects", hint: "Animate one or more hand-authored mask regions independently." },
];

const MOTION_OPTIONS = [
  { value: "none", label: "Still / no camera motion" },
  { value: "subtle", label: "Subtle" },
  { value: "moderate", label: "Moderate" },
  { value: "full", label: "Full 2D" },
  { value: "full_3d", label: "Full 3D" },
];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));
}

export function LayeredAnimationControls({
  sourceOptions,
  maskOptions,
  modelOptions,
  defaultSource = "",
  defaultMotion = "full_3d",
  busy,
  disabled,
  onQueue,
  onOpenModels,
}: {
  sourceOptions: MediaOption[];
  maskOptions: string[];
  modelOptions: ModelOption[];
  defaultSource?: string;
  defaultMotion?: string;
  busy: boolean;
  disabled: boolean;
  onQueue: (payload: LayeredAnimationPayload) => void;
  onOpenModels: () => void;
}) {
  const [sourceAsset, setSourceAsset] = useState(defaultSource);
  const [mode, setMode] = useState<LayeredAnimationMode>("parallax");
  const [motion, setMotion] = useState(defaultMotion);
  const [bands, setBands] = useState(3);
  const [masks, setMasks] = useState<LayerMaskSetting[]>([]);
  const [subjectMotion, setSubjectMotion] = useState(1);
  const [backgroundMotion, setBackgroundMotion] = useState(0.12);
  const [fps, setFps] = useState(24);
  const [duration, setDuration] = useState(5);
  const [width, setWidth] = useState(768);
  const [height, setHeight] = useState(432);
  const [includeAudio, setIncludeAudio] = useState(false);
  const [diffusionRefine, setDiffusionRefine] = useState(false);
  const [modelId, setModelId] = useState("auto");
  const [device, setDevice] = useState<LayeredAnimationPayload["device_preference"]>("auto");
  const [refinePrompt, setRefinePrompt] = useState("");
  const [refineNegative, setRefineNegative] = useState("blurry, low quality, watermark, text, logo");
  const [refineDenoise, setRefineDenoise] = useState(0.3);
  const [refineSteps, setRefineSteps] = useState(20);
  const [refineCfg, setRefineCfg] = useState(7);
  const [seed, setSeed] = useState("");
  const [validationMessage, setValidationMessage] = useState("");

  useEffect(() => {
    setSourceAsset((current) => {
      const defaultIsAvailable = Boolean(defaultSource)
        && sourceOptions.some((entry) => entry.path === defaultSource);
      if (!current) return defaultIsAvailable ? defaultSource : current;
      if (sourceOptions.some((entry) => entry.path === current)) return current;
      if (defaultIsAvailable) return defaultSource;
      return sourceOptions[0]?.path || "";
    });
  }, [defaultSource, sourceOptions]);

  useEffect(() => {
    setMasks((current) => current.filter((entry) => maskOptions.includes(entry.mask_asset)));
  }, [maskOptions]);

  const selectedMode = MODE_OPTIONS.find((option) => option.value === mode) || MODE_OPTIONS[0];
  const selectedModel = useMemo(
    () => modelOptions.find((model) => model.id === modelId),
    [modelId, modelOptions],
  );

  const toggleMask = (maskAsset: string, checked: boolean) => {
    setMasks((current) => {
      if (!checked) return current.filter((entry) => entry.mask_asset !== maskAsset);
      if (current.some((entry) => entry.mask_asset === maskAsset)) return current;
      return [
        ...current,
        { mask_asset: maskAsset, prompt: null, depth: 1, motion_scale: 1, strength: 1 },
      ];
    });
  };

  const updateMask = (maskAsset: string, patch: Partial<LayerMaskSetting>) => {
    setMasks((current) =>
      current.map((entry) => entry.mask_asset === maskAsset ? { ...entry, ...patch } : entry),
    );
  };

  const submit = () => {
    if (!sourceAsset) {
      setValidationMessage("Choose an uploaded source image before queueing the animation.");
      return;
    }
    if (mode === "masked" && !masks.length) {
      setValidationMessage("Masked-object mode needs at least one mask region.");
      return;
    }
    if (!Number.isInteger(width) || !Number.isInteger(height) || width % 2 !== 0 || height % 2 !== 0) {
      setValidationMessage("Width and height must be even whole numbers before queueing the animation.");
      return;
    }
    setValidationMessage("");
    const parsedSeed = seed.trim() === "" ? null : Number(seed);
    onQueue({
      source_asset: sourceAsset,
      mode,
      motion,
      bands: Math.round(clamp(bands, 1, 8)),
      masks: mode === "masked" ? masks : [],
      subject_motion: clamp(subjectMotion, 0, 4),
      background_motion: clamp(backgroundMotion, 0, 4),
      fps: Math.round(clamp(fps, 1, 60)),
      duration_s: clamp(duration, 0.5, 120),
      width: Math.round(clamp(width, 256, 1920)),
      height: Math.round(clamp(height, 256, 1080)),
      include_audio: includeAudio,
      diffusion_refine: diffusionRefine,
      model_id: modelId,
      device_preference: device,
      refine_prompt: refinePrompt.trim() || null,
      refine_negative: refineNegative,
      refine_denoise: clamp(refineDenoise, 0.05, 0.95),
      refine_steps: Math.round(clamp(refineSteps, 1, 80)),
      refine_cfg: clamp(refineCfg, 1, 20),
      seed: parsedSeed == null || !Number.isFinite(parsedSeed) ? null : Math.trunc(parsedSeed),
    });
  };

  return (
    <section className="render-layeredSettings" aria-labelledby="render-layered-title">
      <div className="render-layeredHeader">
        <div>
          <div className="render-layeredKicker"><Layers3 size={15} aria-hidden="true" /> Still-image animation</div>
          <h3 id="render-layered-title">Animate objects, depth layers, or the background</h3>
          <p>
            This is the complete object-animation contract: every decision stays editable, and optional diffusion
            refinement uses a downloaded model instead of a synthetic proxy.
          </p>
        </div>
        <span className="badge">Non-destructive</span>
      </div>

      <div className="render-layeredGrid">
        <label>
          <span>Source image</span>
          <select aria-label="Source image" value={sourceAsset} onChange={(event) => setSourceAsset(event.target.value)}>
            <option value="">Select an uploaded reference</option>
            {sourceOptions.map((entry) => (
              <option key={entry.path} value={entry.path}>{entry.path.replace(/^assets\/refs\//, "")}</option>
            ))}
          </select>
          <small>Original media is read-only; the animation becomes a new output.</small>
        </label>
        <label>
          <span>Layering mode</span>
          <select aria-label="Layering mode" value={mode} onChange={(event) => setMode(event.target.value as LayeredAnimationMode)}>
            {MODE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <small>{selectedMode.hint}</small>
        </label>
        <label>
          <span>Motion profile</span>
          <select aria-label="Motion profile" value={motion} onChange={(event) => setMotion(event.target.value)}>
            {MOTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <small>Sets the base 2D/3D schedule before per-layer scaling.</small>
        </label>
        <label>
          <span>Depth bands</span>
          <input aria-label="Depth bands" type="number" min={1} max={8} step={1} value={bands} onChange={(event) => setBands(Number(event.target.value))} />
          <small>Used by parallax modes; 3–5 bands is a practical starting range.</small>
        </label>
        <label>
          <span>Subject motion</span>
          <input aria-label="Subject motion" type="number" min={0} max={4} step={0.05} value={subjectMotion} onChange={(event) => setSubjectMotion(Number(event.target.value))} />
          <small>Multiplier for the foreground subject or selected masks.</small>
        </label>
        <label>
          <span>Background motion</span>
          <input aria-label="Background motion" type="number" min={0} max={4} step={0.01} value={backgroundMotion} onChange={(event) => setBackgroundMotion(Number(event.target.value))} />
          <small>Keep this lower than the subject for believable depth.</small>
        </label>
        <label>
          <span>Duration</span>
          <input aria-label="Duration" type="number" min={0.5} max={120} step={0.1} value={duration} onChange={(event) => setDuration(Number(event.target.value))} />
          <small>Seconds, from 0.5 to 120.</small>
        </label>
        <label>
          <span>Frame rate</span>
          <input
            aria-label="Frame rate"
            type="number"
            min={1}
            max={60}
            step={1}
            value={fps}
            onChange={(event) => setFps(Number(event.target.value))}
          />
          <small>Any whole-number generation/output rate from 1–60 FPS.</small>
        </label>
        <label>
          <span>Width</span>
          <input aria-label="Width" type="number" min={256} max={1920} step={2} value={width} onChange={(event) => setWidth(Number(event.target.value))} />
          <small>256–1920 pixels.</small>
        </label>
        <label>
          <span>Height</span>
          <input aria-label="Height" type="number" min={256} max={1080} step={2} value={height} onChange={(event) => setHeight(Number(event.target.value))} />
          <small>256–1080 pixels.</small>
        </label>
        <label className="render-layeredToggle">
          <span>Project audio</span>
          <span><input aria-label="Include project audio" type="checkbox" checked={includeAudio} onChange={(event) => setIncludeAudio(event.target.checked)} /> Include uploaded audio in the result</span>
          <small>Audio is copied/muxed into the new animation when available.</small>
        </label>
      </div>

      {mode === "masked" ? (
        <details className="render-layeredDisclosure" open>
          <summary><Boxes size={15} aria-hidden="true" /> Mask regions <span>{masks.length} selected</span></summary>
          {maskOptions.length ? (
            <div className="render-maskEditor">
              {maskOptions.map((maskAsset) => {
                const setting = masks.find((entry) => entry.mask_asset === maskAsset);
                return (
                  <div key={maskAsset} className={`render-maskRow${setting ? " is-active" : ""}`}>
                    <label className="render-maskSelect">
                      <input type="checkbox" checked={Boolean(setting)} onChange={(event) => toggleMask(maskAsset, event.target.checked)} />
                      <span>{maskAsset}</span>
                    </label>
                    {setting ? (
                      <div className="render-maskFields">
                        <label><span>Regional prompt</span><input aria-label="Regional prompt" value={setting.prompt || ""} onChange={(event) => updateMask(maskAsset, { prompt: event.target.value || null })} /></label>
                        <label><span>Depth</span><input aria-label="Depth" type="number" min={0} max={1} step={0.05} value={setting.depth} onChange={(event) => updateMask(maskAsset, { depth: clamp(Number(event.target.value), 0, 1) })} /></label>
                        <label><span>Motion scale</span><input aria-label="Motion scale" type="number" min={0} max={4} step={0.05} value={setting.motion_scale} onChange={(event) => updateMask(maskAsset, { motion_scale: clamp(Number(event.target.value), 0, 4) })} /></label>
                        <label><span>Strength</span><input aria-label="Strength" type="number" min={0} max={2} step={0.05} value={setting.strength} onChange={(event) => updateMask(maskAsset, { strength: clamp(Number(event.target.value), 0, 2) })} /></label>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : <div className="small">Upload masks in Render → Workflow inputs to use masked-object animation.</div>}
        </details>
      ) : null}

      <details className="render-layeredDisclosure">
        <summary><WandSparkles size={15} aria-hidden="true" /> Diffusion refinement <span>{diffusionRefine ? "enabled" : "optional"}</span></summary>
        <label className="render-refineToggle">
          <input aria-label="Refine every composited frame with a downloaded internal image model" type="checkbox" checked={diffusionRefine} onChange={(event) => setDiffusionRefine(event.target.checked)} />
          Refine every composited frame with a downloaded internal image model
        </label>
        <div className="render-layeredGrid" aria-disabled={!diffusionRefine}>
          <label>
            <span>Model</span>
            <select aria-label="Model" disabled={!diffusionRefine} value={modelId} onChange={(event) => setModelId(event.target.value)}>
              <option value="auto">Auto-select downloaded model</option>
              {modelOptions.map((model) => (
                <option key={model.id} value={model.id} disabled={!model.installed}>{model.name}{model.installed ? "" : " (not installed)"}</option>
              ))}
            </select>
            <small>{selectedModel ? (selectedModel.installed ? "Downloaded and ready." : "Install this model before refining.") : "Hardware-aware downloaded model selection."}</small>
          </label>
          <label>
            <span>Device</span>
            <select aria-label="Device" disabled={!diffusionRefine} value={device} onChange={(event) => setDevice(event.target.value as LayeredAnimationPayload["device_preference"])}>
              <option value="auto">Auto</option><option value="cpu">CPU</option><option value="cuda">CUDA</option><option value="mps">Apple MPS</option><option value="directml">DirectML</option>
            </select>
            <small>Preflight will explain when the selected runtime is unavailable.</small>
          </label>
          <label><span>Denoise</span><input aria-label="Denoise" disabled={!diffusionRefine} type="number" min={0.05} max={0.95} step={0.01} value={refineDenoise} onChange={(event) => setRefineDenoise(Number(event.target.value))} /><small>Lower values preserve the source composition.</small></label>
          <label><span>Steps</span><input aria-label="Steps" disabled={!diffusionRefine} type="number" min={1} max={80} step={1} value={refineSteps} onChange={(event) => setRefineSteps(Number(event.target.value))} /><small>More steps improve convergence but increase render time.</small></label>
          <label><span>CFG</span><input aria-label="CFG" disabled={!diffusionRefine} type="number" min={1} max={20} step={0.1} value={refineCfg} onChange={(event) => setRefineCfg(Number(event.target.value))} /><small>Prompt-guidance strength.</small></label>
          <label><span>Seed</span><input aria-label="Seed" disabled={!diffusionRefine} type="number" value={seed} placeholder="Random" onChange={(event) => setSeed(event.target.value)} /><small>Leave blank for a random seed.</small></label>
          <label className="render-layeredWide"><span>Refinement prompt</span><textarea aria-label="Refinement prompt" disabled={!diffusionRefine} value={refinePrompt} onChange={(event) => setRefinePrompt(event.target.value)} placeholder="Optional prompt; uses project direction when blank" /></label>
          <label className="render-layeredWide"><span>Negative prompt</span><textarea aria-label="Negative prompt" disabled={!diffusionRefine} value={refineNegative} onChange={(event) => setRefineNegative(event.target.value)} /></label>
        </div>
        <button type="button" className="secondary" onClick={onOpenModels}>Manage downloaded models</button>
      </details>

      {validationMessage ? <div className="render-layeredError" role="alert">{validationMessage}</div> : null}
      <div className="render-layeredFooter">
        <div className="small">{mode} · {motion} · {duration.toFixed(1)}s · {fps} fps · {width}×{height}{diffusionRefine ? " · model refined" : " · compositor only"}</div>
        <button type="button" className="primary" disabled={disabled || busy} onClick={submit}>
          {busy ? "Queueing animation…" : "Queue still-image animation"} <ChevronRight size={15} aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}
