import React from "react";

export const GENUINE_RENDER_ENGINES = [
  "internal",
  "comfyui_still",
  "comfyui_motion",
  "hosted_video",
  "deforum_export",
  "tensorrt_standalone",
] as const;

export type GenuineRenderEngine = (typeof GENUINE_RENDER_ENGINES)[number];
export type RenderAspectRatio = "16:9" | "9:16" | "1:1" | "21:9";
export type RenderOutputMode = "full_video" | "scene_batch" | "preview";
export type RenderQualityTier = "draft" | "balanced" | "quality" | "ultra";
export type RenderPlanningPreset = "fast" | "balanced" | "quality" | "ultra";
export type RenderFallbackPolicy = "auto" | "strict" | "manual";

export type RenderOrchestratorSectionOverride = {
  scene_id: string;
  start_s: number;
  end_s: number;
  creative_goal: string | null;
  continuity_priority: number | null;
  speed_priority: number | null;
  notes: string[];
};

/**
 * The complete editable request accepted by POST /render/conductor/plan.
 * Values that the backend permits to be omitted are kept explicit here so the
 * workbench always shows the exact intent it will send.
 */
export type RenderOrchestratorIntentValue = {
  variant_index: number;
  preset: RenderPlanningPreset;
  aspect_ratio: RenderAspectRatio;
  output_mode: RenderOutputMode;
  quality_tier: RenderQualityTier;
  continuity_priority: number;
  speed_priority: number;
  style_lock_strength: number;
  allowed_engines: GenuineRenderEngine[];
  fallback_policy: RenderFallbackPolicy;
  sections: RenderOrchestratorSectionOverride[];
};

export function createDefaultRenderOrchestratorIntent(
  variantIndex = 0,
): RenderOrchestratorIntentValue {
  return {
    variant_index: Math.max(0, Math.trunc(variantIndex)),
    preset: "balanced",
    aspect_ratio: "16:9",
    output_mode: "full_video",
    quality_tier: "balanced",
    continuity_priority: 0.75,
    speed_priority: 0.4,
    style_lock_strength: 0.8,
    allowed_engines: [...GENUINE_RENDER_ENGINES],
    fallback_policy: "auto",
    sections: [],
  };
}

const ENGINE_OPTIONS: Array<{ value: GenuineRenderEngine; label: string; hint: string }> = [
  { value: "internal", label: "Studio internal", hint: "Downloaded in-app image and video models." },
  { value: "comfyui_still", label: "ComfyUI still", hint: "ComfyUI workflows for keyframes and source art." },
  { value: "comfyui_motion", label: "ComfyUI motion", hint: "ComfyUI animation and video workflows." },
  { value: "hosted_video", label: "Hosted video", hint: "Configured remote video-generation providers." },
  { value: "deforum_export", label: "Deforum export", hint: "Export a genuine Deforum render recipe." },
  { value: "tensorrt_standalone", label: "TensorRT standalone", hint: "Local accelerated standalone renderer." },
];

const fieldGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: 12,
};

const fieldStyle: React.CSSProperties = {
  display: "grid",
  alignContent: "start",
  gap: 6,
};

const disclosureStyle: React.CSSProperties = {
  marginTop: 14,
  padding: 12,
  border: "1px solid var(--border)",
  borderRadius: 12,
  background: "rgba(5, 18, 20, 0.46)",
};

function clampUnit(value: number, fallback = 0): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(1, Math.max(0, value));
}

function clampNonNegative(value: number, fallback = 0): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(0, value);
}

function renderPriorityLabel(label: string, value: number) {
  return (
    <span style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span>{label}</span>
      <output aria-label={`${label} value`}>{Math.round(value * 100)}%</output>
    </span>
  );
}

export function RenderOrchestratorIntentControls({
  value,
  onChange,
  disabled = false,
}: {
  value: RenderOrchestratorIntentValue;
  onChange: (next: RenderOrchestratorIntentValue) => void;
  disabled?: boolean;
}) {
  const update = <K extends keyof RenderOrchestratorIntentValue>(
    key: K,
    next: RenderOrchestratorIntentValue[K],
  ) => onChange({ ...value, [key]: next });

  const toggleEngine = (engine: GenuineRenderEngine, checked: boolean) => {
    const current = value.allowed_engines.filter((candidate) =>
      GENUINE_RENDER_ENGINES.includes(candidate),
    );
    if (checked) {
      update("allowed_engines", GENUINE_RENDER_ENGINES.filter(
        (candidate) => candidate === engine || current.includes(candidate),
      ));
      return;
    }
    if (current.length <= 1) return;
    update("allowed_engines", current.filter((candidate) => candidate !== engine));
  };

  const addSection = () => {
    const nextIndex = value.sections.length + 1;
    update("sections", [
      ...value.sections,
      {
        scene_id: `scene-${nextIndex}`,
        start_s: 0,
        end_s: 0,
        creative_goal: null,
        continuity_priority: null,
        speed_priority: null,
        notes: [],
      },
    ]);
  };

  const updateSection = (
    index: number,
    patch: Partial<RenderOrchestratorSectionOverride>,
  ) => update("sections", value.sections.map((section, sectionIndex) =>
    sectionIndex === index ? { ...section, ...patch } : section,
  ));

  const removeSection = (index: number) => update(
    "sections",
    value.sections.filter((_, sectionIndex) => sectionIndex !== index),
  );

  return (
    <section className="card" aria-labelledby="render-orchestrator-intent-title">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ maxWidth: 760 }}>
          <span className="badge">Render Orchestrator</span>
          <h3 id="render-orchestrator-intent-title" style={{ marginTop: 8 }}>Tell the Studio what matters for this render</h3>
          <p className="small" style={{ margin: 0 }}>
            Set the creative target first. The Orchestrator then chooses only from the genuine render engines you allow.
          </p>
        </div>
        <span className="small">{value.allowed_engines.length} engines allowed</span>
      </div>

      <div style={{ ...fieldGridStyle, marginTop: 14 }}>
        <label style={fieldStyle}>
          <span>Storyboard variant</span>
          <input
            aria-label="Storyboard variant"
            type="number"
            min={0}
            step={1}
            value={value.variant_index}
            disabled={disabled}
            onChange={(event) => update("variant_index", Math.max(0, Math.trunc(Number(event.target.value) || 0)))}
          />
          <small className="small">Zero is the first planned variant.</small>
        </label>

        <label style={fieldStyle}>
          <span>Planning preset</span>
          <select
            aria-label="Planning preset"
            value={value.preset}
            disabled={disabled}
            onChange={(event) => update("preset", event.target.value as RenderPlanningPreset)}
          >
            <option value="fast">Fast</option>
            <option value="balanced">Balanced</option>
            <option value="quality">Quality</option>
            <option value="ultra">Ultra</option>
          </select>
          <small className="small">Sets the broad time-versus-fidelity planning bias.</small>
        </label>

        <label style={fieldStyle}>
          <span>Frame shape</span>
          <select
            aria-label="Frame shape"
            value={value.aspect_ratio}
            disabled={disabled}
            onChange={(event) => update("aspect_ratio", event.target.value as RenderAspectRatio)}
          >
            <option value="16:9">16:9 — Widescreen</option>
            <option value="9:16">9:16 — Vertical</option>
            <option value="1:1">1:1 — Square</option>
            <option value="21:9">21:9 — Ultrawide</option>
          </select>
          <small className="small">The target composition for generated scenes.</small>
        </label>

        <label style={fieldStyle}>
          <span>Deliverable</span>
          <select
            aria-label="Deliverable"
            value={value.output_mode}
            disabled={disabled}
            onChange={(event) => update("output_mode", event.target.value as RenderOutputMode)}
          >
            <option value="full_video">Full video</option>
            <option value="scene_batch">Separate scene batch</option>
            <option value="preview">Preview</option>
          </select>
          <small className="small">Choose a finished master, editable scene files, or a quick look.</small>
        </label>

        <label style={fieldStyle}>
          <span>Quality tier</span>
          <select
            aria-label="Quality tier"
            value={value.quality_tier}
            disabled={disabled}
            onChange={(event) => update("quality_tier", event.target.value as RenderQualityTier)}
          >
            <option value="draft">Draft</option>
            <option value="balanced">Balanced</option>
            <option value="quality">Quality</option>
            <option value="ultra">Ultra</option>
          </select>
          <small className="small">Controls the Orchestrator's target render fidelity.</small>
        </label>
      </div>

      <div style={{ ...fieldGridStyle, marginTop: 14 }}>
        <label style={fieldStyle}>
          {renderPriorityLabel("Continuity", value.continuity_priority)}
          <input
            aria-label="Continuity priority"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={value.continuity_priority}
            disabled={disabled}
            onChange={(event) => update("continuity_priority", clampUnit(Number(event.target.value), 0.75))}
          />
          <small className="small">Higher values favor visual consistency across cuts.</small>
        </label>

        <label style={fieldStyle}>
          {renderPriorityLabel("Speed", value.speed_priority)}
          <input
            aria-label="Speed priority"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={value.speed_priority}
            disabled={disabled}
            onChange={(event) => update("speed_priority", clampUnit(Number(event.target.value), 0.4))}
          />
          <small className="small">Higher values prefer faster genuine render routes.</small>
        </label>

        <label style={fieldStyle}>
          {renderPriorityLabel("Style lock", value.style_lock_strength)}
          <input
            aria-label="Style lock strength"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={value.style_lock_strength}
            disabled={disabled}
            onChange={(event) => update("style_lock_strength", clampUnit(Number(event.target.value), 0.8))}
          />
          <small className="small">Higher values keep the approved visual identity more rigid.</small>
        </label>
      </div>

      <details style={disclosureStyle}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>
          Engine routing and fallback <span className="small">— {value.allowed_engines.length} allowed</span>
        </summary>
        <p className="small">
          Allow the real render paths available to this project. At least one engine must remain selected.
        </p>
        <fieldset disabled={disabled} style={{ border: 0, margin: 0, padding: 0 }}>
          <legend className="small" style={{ marginBottom: 8 }}>Allowed render engines</legend>
          <div style={fieldGridStyle}>
            {ENGINE_OPTIONS.map((option) => {
              const checked = value.allowed_engines.includes(option.value);
              const lastSelected = checked && value.allowed_engines.length === 1;
              return (
                <label
                  key={option.value}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr",
                    gap: "3px 9px",
                    alignItems: "start",
                    padding: 10,
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    background: checked ? "rgba(53, 216, 223, 0.08)" : "var(--panel2)",
                  }}
                >
                  <input
                    aria-label={`Allow ${option.label}`}
                    type="checkbox"
                    checked={checked}
                    disabled={disabled || lastSelected}
                    onChange={(event) => toggleEngine(option.value, event.target.checked)}
                    style={{ width: "auto", marginTop: 3 }}
                  />
                  <span>{option.label}</span>
                  <small className="small" style={{ gridColumn: 2 }}>{option.hint}</small>
                </label>
              );
            })}
          </div>
        </fieldset>

        <label style={{ ...fieldStyle, maxWidth: 430, marginTop: 14 }}>
          <span>Fallback policy</span>
          <select
            aria-label="Fallback policy"
            value={value.fallback_policy}
            disabled={disabled}
            onChange={(event) => update("fallback_policy", event.target.value as RenderFallbackPolicy)}
          >
            <option value="auto">Automatic genuine reroute</option>
            <option value="strict">Strict — fail if the preferred route cannot run</option>
            <option value="manual">Manual — stop for a routing decision</option>
          </select>
          <small className="small">Controls what happens when a selected real engine is unavailable.</small>
        </label>
      </details>

      <details style={disclosureStyle}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>
          Section overrides <span className="small">— {value.sections.length} configured</span>
        </summary>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", marginTop: 10 }}>
          <p className="small" style={{ margin: 0, maxWidth: 680 }}>
            Give an individual scene a different creative goal or priority without changing the project-wide intent.
          </p>
          <button type="button" onClick={addSection} disabled={disabled}>Add section override</button>
        </div>

        {value.sections.length === 0 ? (
          <p className="small">No section overrides. Every scene inherits the project-wide settings above.</p>
        ) : value.sections.map((section, index) => (
          <fieldset
            key={`${index}-${section.scene_id}`}
            disabled={disabled}
            style={{ ...disclosureStyle, marginTop: 12 }}
          >
            <legend style={{ padding: "0 6px" }}>Section {index + 1}</legend>
            <div style={fieldGridStyle}>
              <label style={fieldStyle}>
                <span>Scene ID</span>
                <input
                  aria-label={`Section ${index + 1} scene ID`}
                  value={section.scene_id}
                  maxLength={120}
                  onChange={(event) => updateSection(index, { scene_id: event.target.value })}
                />
              </label>
              <label style={fieldStyle}>
                <span>Start time</span>
                <input
                  aria-label={`Section ${index + 1} start time`}
                  type="number"
                  min={0}
                  step={0.01}
                  value={section.start_s}
                  onChange={(event) => updateSection(index, { start_s: clampNonNegative(Number(event.target.value)) })}
                />
              </label>
              <label style={fieldStyle}>
                <span>End time</span>
                <input
                  aria-label={`Section ${index + 1} end time`}
                  type="number"
                  min={0}
                  step={0.01}
                  value={section.end_s}
                  onChange={(event) => updateSection(index, { end_s: clampNonNegative(Number(event.target.value)) })}
                />
              </label>
              <label style={{ ...fieldStyle, gridColumn: "1 / -1" }}>
                <span>Creative goal</span>
                <input
                  aria-label={`Section ${index + 1} creative goal`}
                  value={section.creative_goal || ""}
                  maxLength={260}
                  placeholder="Example: calm wide establishing shot"
                  onChange={(event) => updateSection(index, { creative_goal: event.target.value.trimStart() || null })}
                />
              </label>
              <label style={fieldStyle}>
                <span>Continuity override</span>
                <input
                  aria-label={`Section ${index + 1} continuity override`}
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={section.continuity_priority ?? ""}
                  placeholder="Inherit"
                  onChange={(event) => updateSection(index, {
                    continuity_priority: event.target.value === "" ? null : clampUnit(Number(event.target.value)),
                  })}
                />
                <small className="small">Leave empty to inherit {Math.round(value.continuity_priority * 100)}%.</small>
              </label>
              <label style={fieldStyle}>
                <span>Speed override</span>
                <input
                  aria-label={`Section ${index + 1} speed override`}
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={section.speed_priority ?? ""}
                  placeholder="Inherit"
                  onChange={(event) => updateSection(index, {
                    speed_priority: event.target.value === "" ? null : clampUnit(Number(event.target.value)),
                  })}
                />
                <small className="small">Leave empty to inherit {Math.round(value.speed_priority * 100)}%.</small>
              </label>
              <label style={{ ...fieldStyle, gridColumn: "1 / -1" }}>
                <span>Notes</span>
                <textarea
                  aria-label={`Section ${index + 1} notes`}
                  value={section.notes.join("\n")}
                  rows={2}
                  placeholder="One production note per line"
                  onChange={(event) => updateSection(index, {
                    notes: event.target.value.split(/\r?\n/).map((note) => note.trim()).filter(Boolean),
                  })}
                />
              </label>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
              <button type="button" className="danger" onClick={() => removeSection(index)}>
                Remove section override
              </button>
            </div>
          </fieldset>
        ))}
      </details>
    </section>
  );
}
