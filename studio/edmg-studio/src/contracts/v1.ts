/** Frozen cross-domain contracts shared with the Studio backend.
 *
 * Persisted JSON uses snake_case deliberately so Electron, browser, Python,
 * project files, and external adapters all exchange one representation.
 */

export const CONTRACT_SCHEMA_VERSION = "1.0" as const;

export const CONTRACT_TYPES = [
  "edmg.project",
  "edmg.music_graph",
  "edmg.creative_intent",
  "edmg.render_plan",
  "edmg.artifact",
  "edmg.capability",
  "edmg.job",
  "edmg.cue",
] as const;

export type ContractType = (typeof CONTRACT_TYPES)[number];
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface VersionedDocument {
  schema_version: typeof CONTRACT_SCHEMA_VERSION;
  contract_type: ContractType;
  id: string;
  created_at: string;
  updated_at: string;
}

export interface AssetRef {
  id: string;
  relative_path: string;
  media_type?: string | null;
  content_hash?: string | null;
  size_bytes?: number | null;
}

export interface ProjectContract extends VersionedDocument {
  contract_type: "edmg.project";
  name: string;
  revision: number;
  audio?: AssetRef | null;
  timeline: Record<string, JsonValue>;
  music_graph_ref?: AssetRef | null;
  creative_intent_ref?: AssetRef | null;
  render_plan_refs: AssetRef[];
  artifact_refs: AssetRef[];
  metadata: Record<string, JsonValue>;
  extensions: Record<string, JsonValue>;
}

export interface TimedEvent {
  id: string;
  time_seconds: number;
  value: JsonValue;
  confidence?: number | null;
}

export interface TimedRange {
  id: string;
  start_seconds: number;
  end_seconds: number;
}

export interface SectionRange extends TimedRange {
  label: string;
  confidence: number;
}

export interface TimedWord extends TimedRange {
  text: string;
  confidence?: number | null;
}

export interface WeightedTag {
  tag: string;
  weight: number;
}

export interface CurveRef {
  id: string;
  asset?: AssetRef | null;
  values?: number[] | null;
  sample_hz?: number | null;
  units?: string | null;
}

export interface MusicGraphContract extends VersionedDocument {
  contract_type: "edmg.music_graph";
  source: AssetRef;
  timebase: { sample_rate: number; fps_hint?: number | null; duration_seconds: number };
  tempo: { bpm: number; confidence: number; variable_tempo: TimedEvent[] };
  meter: { numerator: number; denominator: number; confidence: number };
  beats: TimedEvent[];
  bars: TimedRange[];
  sections: SectionRange[];
  stems: Array<{ id: string; kind: string; asset?: AssetRef | null; features: Record<string, CurveRef> }>;
  lyrics?: { language?: string | null; words: TimedWord[]; lines: TimedRange[] } | null;
  harmony?: { key?: string | null; chords: TimedEvent[]; confidence: number } | null;
  features: {
    loudness: CurveRef;
    onset_strength: CurveRef;
    spectral_flux: CurveRef;
    brightness: CurveRef;
    harmonicity: CurveRef;
    energy_arc: CurveRef;
  };
  semantics?: { tags: WeightedTag[]; section_tags: Record<string, WeightedTag[]> } | null;
  analysis_runs: Array<{
    id: string;
    analyzer: string;
    analyzer_version: string;
    source_hash?: string | null;
    created_at: string;
    parameters: Record<string, JsonValue>;
  }>;
}

export type DirectorMode = "narrative" | "performance" | "abstract" | "lyric" | "product" | "ambient";

export interface CreativeIntentContract extends VersionedDocument {
  contract_type: "edmg.creative_intent";
  project_id: string;
  revision: number;
  director_mode: DirectorMode;
  concept: string;
  audience?: string | null;
  aspect_ratios: string[];
  world: { summary: string; locations: string[]; characters: string[]; rules: string[] };
  continuity: Array<{ id: string; kind: string; description: string; reference_asset_ids: string[] }>;
  visual_grammar: {
    palette: string[];
    texture: string[];
    lenses: string[];
    composition_rules: string[];
    motion_character: string[];
    forbidden_traits: string[];
  };
  budget: { priority: "speed" | "balanced" | "quality"; max_compute_minutes?: number | null; max_cost?: number | null };
  accessibility?: { avoid_flashes_above_hz?: number | null; safe_text_zones?: boolean | null } | null;
}

export type MediaKind = "image" | "video" | "audio" | "mask" | "depth" | "scene";
export type CapabilityOperation = "generate" | "transform" | "extend" | "upscale" | "interpolate" | "assemble";
export type CapabilityControl = "text" | "image" | "first_frame" | "last_frame" | "audio" | "pose" | "depth" | "mask";
export type CapabilityLocality = "in_process" | "local_service" | "remote";

export interface CapabilityRequirement {
  media: MediaKind;
  operation: CapabilityOperation;
  controls: CapabilityControl[];
  locality?: CapabilityLocality | null;
}

export interface RenderTaskContract {
  id: string;
  kind: string;
  inputs: Record<string, JsonValue>;
  outputs: Record<string, JsonValue>;
  cache_key?: string | null;
}

export interface RenderPlanContract extends VersionedDocument {
  contract_type: "edmg.render_plan";
  project_id: string;
  revision: number;
  intent_revision: string;
  project_revision: string;
  tasks: RenderTaskContract[];
  dependencies: Array<{ from_task: string; to_task: string }>;
  allocations: Array<{
    task_id: string;
    capability: CapabilityRequirement;
    preferred_provider?: string | null;
    fallbacks: string[];
  }>;
  estimates: { seconds: number; vram_gb?: number | null; disk_gb: number; cost?: number | null };
  warnings: Array<{ code: string; message: string; severity: "info" | "warning" | "error"; task_id?: string | null }>;
  extensions: Record<string, JsonValue>;
}

export interface ArtifactManifestContract extends VersionedDocument {
  contract_type: "edmg.artifact";
  project_id: string;
  relative_path: string;
  content_hash: string;
  source_asset_hashes: string[];
  scene_id?: string | null;
  plan_revision: string;
  project_revision: string;
  engine: string;
  provider?: string | null;
  model: { repository?: string | null; revision?: string | null };
  runtime_versions: Record<string, string>;
  inputs: Record<string, JsonValue>;
  seed?: number | null;
  hardware: Record<string, JsonValue>;
  elapsed_seconds: number;
  safety: Record<string, JsonValue>;
  license: Record<string, JsonValue>;
  parent_artifact_ids: string[];
  child_artifact_ids: string[];
  review_state: "unreviewed" | "approved" | "rejected" | "repair";
  approved_visual_dna_updates: string[];
}

export interface CapabilityContract extends VersionedDocument {
  contract_type: "edmg.capability";
  provider_id: string;
  media: MediaKind;
  operation: CapabilityOperation;
  controls: CapabilityControl[];
  max_duration_seconds?: number | null;
  resolutions: string[];
  deterministic: boolean;
  supports_cancel: boolean;
  locality: CapabilityLocality;
  metadata: Record<string, JsonValue>;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "canceled" | "paused" | "blocked";

export interface JobContract extends VersionedDocument {
  contract_type: "edmg.job";
  project_id: string;
  job_type: string;
  status: JobStatus;
  priority: number;
  plan_id?: string | null;
  task_id?: string | null;
  idempotency_key?: string | null;
  attempt: number;
  payload: Record<string, JsonValue>;
  result?: Record<string, JsonValue> | null;
  error?: string | null;
  progress?: Record<string, JsonValue> | null;
}

export type CueTransport = "internal" | "osc" | "midi" | "websocket" | "unreal" | "touchdesigner";

export interface CueContract extends VersionedDocument {
  contract_type: "edmg.cue";
  project_id: string;
  cue_type: string;
  time_seconds: number;
  frame?: number | null;
  transport: CueTransport;
  target?: string | null;
  payload: Record<string, JsonValue>;
}

export type V1Contract =
  | ProjectContract
  | MusicGraphContract
  | CreativeIntentContract
  | RenderPlanContract
  | ArtifactManifestContract
  | CapabilityContract
  | JobContract
  | CueContract;

export function isV1Contract(value: unknown): value is V1Contract {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<VersionedDocument>;
  return (
    candidate.schema_version === CONTRACT_SCHEMA_VERSION &&
    typeof candidate.id === "string" &&
    CONTRACT_TYPES.includes(candidate.contract_type as ContractType)
  );
}
