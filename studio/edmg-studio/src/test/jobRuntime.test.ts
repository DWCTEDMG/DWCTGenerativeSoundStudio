import { describe, expect, it } from "vitest";
import {
  countActiveJobs,
  countPausedJobs,
  jobRuntimeSummary,
} from "../shared/jobs/jobRuntime";

describe("job runtime helpers", () => {
  it("summarizes checkpoint progress for internal jobs", () => {
    const summary = jobRuntimeSummary({
      id: "job-1",
      project_id: "p1",
      type: "internal_video",
      status: "failed",
      progress: {
        runtime_checkpoint: {
          resume_percent: 42,
          completed_chunks: 2,
          estimated_chunks: 5,
          next_frame_index: 120,
          total_frames: 300,
          chunk_strategy: "chunked",
          can_resume: true,
          outputs: { checkpoint_json: "/tmp/checkpoint.json" },
        },
      },
    });
    expect(summary?.percent).toBe(42);
    expect(summary?.chunks).toBe("2/5");
    expect(summary?.checkpointPath).toContain("checkpoint.json");
  });

  it("counts active and paused queue jobs", () => {
    const jobs = [
      { id: "1", project_id: "p1", type: "internal_video", status: "queued" },
      { id: "2", project_id: "p1", type: "internal_video", status: "running" },
      { id: "3", project_id: "p1", type: "internal_video", status: "paused" },
    ] as const;
    expect(countActiveJobs([...jobs])).toBe(2);
    expect(countPausedJobs([...jobs])).toBe(1);
  });
});
