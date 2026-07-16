export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | string;

export type StudioJob = {
  id: string;
  project_id: string;
  type: string;
  status: JobStatus;
  created_at?: string;
  updated_at?: string;
  error?: string | null;
  progress?: {
    percent?: number;
    stage?: string;
    message?: string;
    current?: number;
    total?: number;
  } | null;
  result?: Record<string, unknown> | null;
  attempt?: number;
};

export function normalizeJobStatus(status: unknown): JobStatus {
  const value = String(status || "queued").trim().toLowerCase();
  switch (value) {
    case "queued":
    case "running":
    case "succeeded":
    case "failed":
    case "canceled":
      return value;
    case "cancelled":
      return "canceled";
    default:
      return value || "queued";
  }
}

export function jobStatusLabel(status: unknown): string {
  const normalized = normalizeJobStatus(status);
  switch (normalized) {
    case "queued":
      return "Queued";
    case "running":
      return "Running";
    case "succeeded":
      return "Succeeded";
    case "failed":
      return "Failed";
    case "canceled":
      return "Canceled";
    default:
      return normalized;
  }
}

export function jobStatusTone(status: unknown): "neutral" | "active" | "ok" | "danger" | "warn" {
  const normalized = normalizeJobStatus(status);
  switch (normalized) {
    case "queued":
      return "neutral";
    case "running":
      return "active";
    case "succeeded":
      return "ok";
    case "failed":
      return "danger";
    case "canceled":
      return "warn";
    default:
      return "neutral";
  }
}

export function canCancelJob(status: unknown): boolean {
  const normalized = normalizeJobStatus(status);
  return normalized === "queued" || normalized === "running";
}

export function canRetryJob(status: unknown): boolean {
  const normalized = normalizeJobStatus(status);
  return normalized !== "running";
}

export function jobRecoveryHint(job: StudioJob): string | null {
  const status = normalizeJobStatus(job.status);
  if (status === "failed") {
    return job.error ? `Retry or resume after: ${job.error}` : "Failed — retry or restart clean.";
  }
  if (status === "canceled") {
    return "Canceled — retry to re-queue, or resume from checkpoint when available.";
  }
  if (status === "running" && job.progress?.message) {
    return String(job.progress.message);
  }
  return null;
}
