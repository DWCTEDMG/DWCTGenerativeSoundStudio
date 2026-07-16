import { describe, expect, it } from "vitest";
import {
  canCancelJob,
  canRetryJob,
  jobRecoveryHint,
  jobStatusLabel,
  normalizeJobStatus,
} from "../shared/jobs/jobStatus";

describe("job status helpers", () => {
  it("normalizes cancelled spelling and labels", () => {
    expect(normalizeJobStatus("cancelled")).toBe("canceled");
    expect(jobStatusLabel("running")).toBe("Running");
  });

  it("gates cancel and retry consistently", () => {
    expect(canCancelJob("queued")).toBe(true);
    expect(canCancelJob("succeeded")).toBe(false);
    expect(canRetryJob("running")).toBe(false);
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
});
