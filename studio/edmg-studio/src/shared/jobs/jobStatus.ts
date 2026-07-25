export type JobStatus =
  | "queued"
  | "paused"
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
    case "paused":
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
    case "paused":
      return "Paused";
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
    case "paused":
      return "warn";
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
  return normalized === "queued" || normalized === "paused" || normalized === "running";
}

export function canPauseJob(status: unknown): boolean {
  return normalizeJobStatus(status) === "queued";
}

export function canResumeJob(status: unknown): boolean {
  return normalizeJobStatus(status) === "paused";
}

export function isJobActive(status: unknown): boolean {
  const normalized = normalizeJobStatus(status);
  return normalized === "queued" || normalized === "paused" || normalized === "running";
}

export function canRetryJob(status: unknown): boolean {
  const normalized = normalizeJobStatus(status);
  return normalized === "succeeded" || normalized === "failed" || normalized === "canceled";
}

export function canUseCheckpointRecovery(status: unknown): boolean {
  return !isJobActive(status);
}

export function jobRecoveryHint(job: StudioJob): string | null {
  const status = normalizeJobStatus(job.status);
  if (status === "failed") {
    return job.error ? `Retry or resume after: ${job.error}` : "Failed — retry or restart clean.";
  }
  if (status === "canceled") {
    return "Canceled — retry to re-queue, or resume from checkpoint when available.";
  }
  if (status === "paused") {
    return "Paused before execution — resume to return this job to the queue.";
  }
  if (status === "running" && job.progress?.message) {
    return String(job.progress.message);
  }
  return null;
}
