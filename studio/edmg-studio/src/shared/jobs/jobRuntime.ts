import type { StudioJob } from "./jobStatus";

export type JobRuntimeSummary = {
  percent: number;
  chunks: string;
  nextFrame: string;
  strategy: string;
  canResume: boolean;
  checkpointPath: string;
};

export function jobRuntimeSummary(job: StudioJob | Record<string, unknown> | null | undefined): JobRuntimeSummary | null {
  const progress = (job as StudioJob | undefined)?.progress as Record<string, unknown> | null | undefined;
  const cp = progress?.runtime_checkpoint as Record<string, unknown> | null | undefined;
  if (!cp) return null;
  const outputs = cp.outputs as Record<string, unknown> | undefined;
  return {
    percent: Number(cp.resume_percent ?? 0),
    chunks: `${Number(cp.completed_chunks ?? 0)}/${Number(cp.estimated_chunks ?? 1)}`,
    nextFrame: `${Math.min(Number(cp.next_frame_index ?? 0) + 1, Number(cp.total_frames ?? 0) || 0)}/${Number(cp.total_frames ?? 0)}`,
    strategy: String(cp.chunk_strategy || "single_pass"),
    canResume: Boolean(cp.can_resume),
    checkpointPath: String(outputs?.checkpoint_json || ""),
  };
}

export function countActiveJobs(jobs: StudioJob[]): number {
  return jobs.filter((job) => job.status === "queued" || job.status === "running").length;
}

export function countPausedJobs(jobs: StudioJob[]): number {
  return jobs.filter((job) => job.status === "paused").length;
}

export function countResumableInternalJobs(jobs: StudioJob[]): number {
  return jobs.filter(
    (job) =>
      job.type === "internal_video" &&
      (job.status === "failed" || job.status === "canceled" || job.status === "succeeded"),
  ).length;
}
