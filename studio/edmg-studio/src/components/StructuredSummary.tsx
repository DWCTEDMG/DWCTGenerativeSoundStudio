import React from "react";

type StructuredSummaryProps = {
  value: unknown;
  emptyLabel?: string;
  maxDepth?: number;
  maxItems?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function formatKey(key: string): string {
  return key
    .replace(/^_+/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatScalar(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not set";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "Not set";
  if (typeof value === "string") return value;
  return String(value);
}

function compactSummary(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (isRecord(value)) {
    const count = Object.keys(value).length;
    return `${count} field${count === 1 ? "" : "s"}`;
  }
  return formatScalar(value);
}

function SummaryValue({
  value,
  depth,
  maxDepth,
  maxItems,
}: {
  value: unknown;
  depth: number;
  maxDepth: number;
  maxItems: number;
}) {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="structuredSummary-empty">None</span>;
    if (depth >= maxDepth) return <span>{compactSummary(value)}</span>;
    const shown = value.slice(0, maxItems);
    return (
      <div className="structuredSummary-list">
        {shown.map((item, index) => (
          <div key={index} className="structuredSummary-listItem">
            {isRecord(item) || Array.isArray(item) ? (
              <details>
                <summary>{compactSummary(item)}</summary>
                <SummaryValue value={item} depth={depth + 1} maxDepth={maxDepth} maxItems={maxItems} />
              </details>
            ) : (
              <span>{formatScalar(item)}</span>
            )}
          </div>
        ))}
        {value.length > shown.length ? (
          <div className="structuredSummary-more">{value.length - shown.length} more</div>
        ) : null}
      </div>
    );
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (!entries.length) return <span className="structuredSummary-empty">None</span>;
    if (depth >= maxDepth) return <span>{compactSummary(value)}</span>;
    const shown = entries.slice(0, maxItems);
    return (
      <div className="structuredSummary-grid">
        {shown.map(([key, item]) => (
          <React.Fragment key={key}>
            <div className="structuredSummary-key">{formatKey(key)}</div>
            <div className="structuredSummary-value">
              {isRecord(item) || Array.isArray(item) ? (
                <details>
                  <summary>{compactSummary(item)}</summary>
                  <SummaryValue value={item} depth={depth + 1} maxDepth={maxDepth} maxItems={maxItems} />
                </details>
              ) : (
                <span>{formatScalar(item)}</span>
              )}
            </div>
          </React.Fragment>
        ))}
        {entries.length > shown.length ? (
          <>
            <div className="structuredSummary-key">More</div>
            <div className="structuredSummary-more">{entries.length - shown.length} additional fields</div>
          </>
        ) : null}
      </div>
    );
  }

  return <span>{formatScalar(value)}</span>;
}

export function StructuredSummary({
  value,
  emptyLabel = "No details.",
  maxDepth = 3,
  maxItems = 24,
}: StructuredSummaryProps) {
  if (value === null || value === undefined) {
    return <div className="small structuredSummary-empty">{emptyLabel}</div>;
  }
  return (
    <div className="structuredSummary">
      <SummaryValue value={value} depth={0} maxDepth={maxDepth} maxItems={maxItems} />
    </div>
  );
}
