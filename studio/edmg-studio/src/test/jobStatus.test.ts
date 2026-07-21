import { describe, expect, it } from "vitest";
import {
  canCancelJob,
  canPauseJob,
  canResumeJob,
  canRetryJob,
  jobRecoveryHint,
  jobStatusLabel,
  normalizeJobStatus,
} from "../shared/jobs/jobStatus";

describe("job status helpers", () => {
  it("normalizes cancelled spelling and labels paused work", () => {
    expect(normalizeJobStatus("cancelled")).toBe("canceled");
    expect(jobStatusLabel("running")).toBe("Running");
    expect(jobStatusLabel("paused")).toBe("Paused");
  });

  it("gates queue controls consistently", () => {
    expect(canCancelJob("queued")).toBe(true);
    expect(canCancelJob("paused")).toBe(true);
    expect(canCancelJob("succeeded")).toBe(false);
    expect(canPauseJob("queued")).toBe(true);
    expect(canPauseJob("running")).toBe(false);
    expect(canResumeJob("paused")).toBe(true);
    expect(canRetryJob("queued")).toBe(false);
    expect(canRetryJob("running")).toBe(false);
    expect(canRetryJob("paused")).toBe(false);
    expect(canRetryJob("failed")).toBe(true);
  });

  it("explains recovery for failed jobs", () => {
    expect(
      jobRecoveryHint({
        id: "1",
        project_id: "p",
        type: "internal_video",
        status: "failed",
        error: "disk full",
      }),
    ).toContain("disk full");
  });

  it("explains that paused jobs resume into the queue", () => {
    expect(
      jobRecoveryHint({
        id: "1",
        project_id: "p",
        type: "internal_video",
        status: "paused",
      }),
    ).toContain("resume");
  });
});
