import React from "react";
import { jobStatusLabel, jobStatusTone, type JobStatus } from "./jobStatus";

const TONE_STYLE: Record<ReturnType<typeof jobStatusTone>, React.CSSProperties> = {
  neutral: { opacity: 0.85 },
  active: { color: "var(--accent, #3b82f6)", fontWeight: 700 },
  ok: { color: "var(--ok, #16a34a)", fontWeight: 700 },
  danger: { color: "var(--danger, #dc2626)", fontWeight: 700 },
  warn: { color: "var(--warn, #d97706)", fontWeight: 700 },
};

export function JobStatusChip({ status }: { status: JobStatus | string }) {
  const tone = jobStatusTone(status);
  return (
    <span className="badge" style={TONE_STYLE[tone]} title={String(status)}>
      {jobStatusLabel(status)}
    </span>
  );
}
