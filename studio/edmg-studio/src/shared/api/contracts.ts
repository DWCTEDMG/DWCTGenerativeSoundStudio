/**
 * Typed API contracts for extracted System/Project durability domains (WP-08 / P1-06).
 * Keep these aligned with FastAPI responses from `edmg_studio_backend.api.routers`.
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
