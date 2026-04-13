import React from "react";

export type ProgressTone = "accent" | "success" | "warning" | "danger";

export function ProgressBar({
  value,
  label,
  detail,
  tone = "accent",
  compact = false,
}: {
  value: number;
  label?: string;
  detail?: string;
  tone?: ProgressTone;
  compact?: boolean;
}) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));

  return (
    <div className={`progressBar${compact ? " progressBar--compact" : ""}`} data-tone={tone}>
      {(label || detail) && (
        <div className="progressBar-head">
          {label ? <span className="progressBar-label">{label}</span> : <span />}
          <span className="progressBar-value">{Math.round(clamped)}%</span>
        </div>
      )}
      <div
        className="progressBar-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped)}
      >
        <div className="progressBar-fill" style={{ width: `${clamped}%` }} />
      </div>
      {detail ? <div className="progressBar-detail">{detail}</div> : null}
    </div>
  );
}
