/**
 * Typed API contracts for extracted System/Project durability domains (WP-08 / P1-06).
 * Keep these aligned with FastAPI responses from `edmg_studio_backend.api.routers` and `app.py`.
 */

export type SystemReadinessStatus = "ready" | "degraded" | "blocked" | string;

export type SystemReadinessReport = {
  ok: boolean;
  status: SystemReadinessStatus;
  checked_at?: string;
  checks?: Record<string, unknown>;
  blockers?: Array<{ code?: string; message?: string }>;
  warnings?: Array<{ code?: string; message?: string }>;
};

export type ProjectHealthIssue = {
  code: string;
  severity: "error" | "warning" | "info" | string;
  message: string;
};

export type ProjectAssetIndex = {
  schema_version: number;
  generated_at: string;
  asset_count: number;
  missing_count: number;
  total_bytes: number;
  disk_estimate_gb: number;
  missing: Array<{ path: string; reason?: string }>;
  assets: Array<{
    path: string;
    role: string;
    exists: boolean;
    bytes: number | null;
    sha256: string | null;
    referenced: boolean;
  }>;
};

export type ProjectHealthReport = {
  ok: boolean;
  status: "ok" | "warning" | "error" | string;
  issues: ProjectHealthIssue[];
  asset_index: ProjectAssetIndex;
  actions: string[];
};

export type RecoveryCandidate = {
  kind: "journal" | "snapshot" | string;
  saved_at: string;
  reason: string;
  path: string;
};

export type ProjectRecoveryStatus = {
  ok: boolean;
  needs_recovery: boolean;
  candidates: RecoveryCandidate[];
};

export type AutosaveResponse = {
  ok: boolean;
  autosave: {
    saved_at?: string;
    reason?: string;
    dirty?: boolean;
  };
};

export type WeightedTag = {
  tag: string;
  confidence: number;
  source?: string;
};

export type MusicGraphStem = {
  kind: string;
  asset?: string;
  features?: Record<string, unknown>;
};

export type MusicGraphSection = {
  start: number;
  end: number;
  label: string;
  confidence?: number;
  energy?: number;
};

export type MusicGraphV1 = {
  schemaVersion: "1.0" | string;
  source?: { filename?: string | null; kind?: string };
  timebase?: { sampleRate?: number; durationSeconds?: number; fpsHint?: number };
  tempo?: { bpm?: number; confidence?: number };
  meter?: { numerator?: number; denominator?: number; confidence?: number };
  beats?: Array<{ t: number; confidence?: number }>;
  bars?: Array<{ start: number; end: number }>;
  sections?: MusicGraphSection[];
  stems?: MusicGraphStem[];
  lyrics?: {
    language?: string | null;
    words?: Array<{ t: number; text: string; confidence?: number }>;
    lines?: Array<{ start: number; end: number; text: string }>;
    error?: string;
    note?: string;
    source?: string;
  };
  semantics?: { tags?: WeightedTag[] };
  features?: Record<string, unknown>;
  energy?: unknown;
  analysisRuns?: Array<Record<string, unknown>>;
  confidenceNotes?: string[];
};

export type MusicGraphResponse = {
  ok: boolean;
  music_graph: MusicGraphV1;
};

export type RenderPlanEstimates = {
  seconds?: number;
  cost_units?: number;
  scene_count?: number;
};

export type RenderPlanSection = {
  scene_id: string;
  engine: string;
  rationale?: string;
  estimated_cost?: number;
  estimated_seconds?: number;
  continuity_risk?: number;
  notes?: string[];
};

export type RenderPlanV1 = {
  plan_id?: string;
  project_id?: string;
  variant_index?: number;
  created_at?: string;
  advisory_only?: boolean;
  summary?: string;
  sections?: RenderPlanSection[];
  tasks?: Array<Record<string, unknown>>;
  dependencies?: Array<Record<string, unknown>>;
  estimates?: RenderPlanEstimates;
  warnings?: Array<{ code?: string; message?: string; severity?: string; scene_id?: string }>;
  diagnostics?: string[];
};

export type RenderConductorPlanResponse = {
  ok: boolean;
  plan?: RenderPlanV1 | null;
  intent?: Record<string, unknown>;
  environment?: Record<string, unknown>;
  stored?: boolean;
};

export type VariantReviewArtifact = {
  path?: string;
  scene_id?: string;
  review_state?: string;
  traits?: string[];
};

export type VariantReviewReport = {
  schema_version?: number;
  artifacts?: VariantReviewArtifact[];
  approved_count?: number;
  pending_count?: number;
};

export type VariantReviewResponse = {
  ok: boolean;
  variant_review: VariantReviewReport;
};

export type LiveAssetPack = {
  pack_id?: string;
  channels?: Array<Record<string, unknown>>;
};

export type LiveAssetsReport = {
  schema_version?: number;
  pack_count?: number;
  channel_count?: number;
  packs?: LiveAssetPack[];
};

export type LiveAssetsResponse = {
  ok: boolean;
  live_assets: LiveAssetsReport;
};

export type TemplatePackageManifest = {
  schema_version?: number | string;
  package_id?: string;
  models?: Array<Record<string, unknown>>;
  assets?: Array<Record<string, unknown>>;
  permissions?: Record<string, unknown>;
};

export type TemplatePackageExportResponse = {
  ok: boolean;
  package: TemplatePackageManifest;
};

export type PerformerWorkflowTask = {
  scene_id: string;
  engine: string;
  model?: Record<string, unknown>;
  audio_window?: { start_s: number; end_s: number; duration_s: number };
  energy?: number;
  provenance?: Record<string, unknown>;
  notes?: string[];
};

export type PerformerWorkflowPlan = {
  schema_version?: number;
  plan_id?: string;
  project_id?: string;
  variant_index?: number;
  created_at?: string;
  advisory_only?: boolean;
  model?: Record<string, unknown>;
  tasks?: PerformerWorkflowTask[];
  warnings?: Array<{ code?: string; message?: string; severity?: string }>;
  summary?: string;
};

export type PerformerWorkflowPlanResponse = {
  ok: boolean;
  performer_plan?: PerformerWorkflowPlan | null;
  music_graph?: MusicGraphV1;
  environment?: Record<string, unknown>;
  stored?: boolean;
};
