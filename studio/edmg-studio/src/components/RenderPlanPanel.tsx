import React from "react";

type RenderPlanPanelProps = {
  plan: any;
  continuityReport?: any;
  visualDnaHints?: any;
  onOpenModels?: () => void;
  onOpenSettings?: () => void;
  onNavigateReview?: () => void;
  onRefresh?: () => void;
};

function severityColor(severity: string): string {
  if (severity === "blocking") return "var(--danger)";
  if (severity === "warning") return "var(--warning, #b58900)";
  return "inherit";
}

export function RenderPlanPanel({
  plan,
  continuityReport,
  visualDnaHints,
  onOpenModels,
  onOpenSettings,
  onNavigateReview,
  onRefresh,
}: RenderPlanPanelProps) {
  if (!plan) return null;

  const sections = Array.isArray(plan.sections) ? plan.sections : [];
  const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];
  const dependencies = Array.isArray(plan.dependencies) ? plan.dependencies : [];
  const warnings = Array.isArray(plan.warnings) ? plan.warnings : [];
  const diagnostics = Array.isArray(plan.diagnostics) ? plan.diagnostics : [];
  const estimates = plan.estimates && typeof plan.estimates === "object" ? plan.estimates : null;
  const proxySections = sections.filter((section: any) => section.engine === "proxy");

  return (
    <div className="card" style={{ marginTop: 12, padding: 12 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontWeight: 800 }}>Render Plan v1</div>
        {onRefresh ? (
          <button className="secondary" onClick={onRefresh}>Refresh plan</button>
        ) : null}
      </div>
      <div className="small" style={{ marginTop: 6 }}>{plan.summary || "Advisory multi-engine plan ready."}</div>
      {plan.plan_id ? (
        <div className="small" style={{ marginTop: 4, opacity: 0.78 }}>
          Plan <b>{plan.plan_id}</b>
          {plan.created_at ? <> • {plan.created_at}</> : null}
          {plan.advisory_only ? <> • advisory</> : null}
        </div>
      ) : null}
      {estimates ? (
        <div className="small" style={{ marginTop: 8 }}>
          Estimates: <b>{Number(estimates.seconds || 0).toFixed(1)}s</b>
          {" "}• cost <b>{Number(estimates.cost || 0).toFixed(2)}</b>
          {" "}• tasks <b>{estimates.task_count ?? tasks.length}</b>
        </div>
      ) : null}
      {visualDnaHints?.core_themes?.length || visualDnaHints?.motifs?.length ? (
        <div className="small" style={{ marginTop: 6 }}>
          Visual DNA: {[...(visualDnaHints?.core_themes || []), ...(visualDnaHints?.motifs || [])].slice(0, 4).join(" • ")}
        </div>
      ) : null}
      {typeof visualDnaHints?.confidence === "number" ? (
        <div className="small" style={{ marginTop: 6, opacity: 0.82 }}>
          Project memory confidence: {Math.round(Number(visualDnaHints.confidence) * 100)}%
        </div>
      ) : null}

      {warnings.length ? (
        <div style={{ marginTop: 10 }}>
          <div className="small" style={{ fontWeight: 700, marginBottom: 4 }}>Warnings</div>
          {warnings.slice(0, 8).map((warning: any, index: number) => (
            <div key={`${warning.code}-${index}`} className="small" style={{ color: severityColor(String(warning.severity || "warning")) }}>
              {warning.scene_id ? `[${warning.scene_id}] ` : ""}{warning.message}
            </div>
          ))}
        </div>
      ) : null}

      {tasks.length ? (
        <div style={{ marginTop: 12, overflowX: "auto" }}>
          <div className="small" style={{ fontWeight: 700, marginBottom: 6 }}>Task graph</div>
          <table>
            <thead>
              <tr>
                <th>Task</th>
                <th>Scene</th>
                <th>Kind</th>
                <th>Adapter</th>
                <th>Est (s)</th>
                <th>Cache key</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task: any) => (
                <tr key={task.id}>
                  <td className="small">{task.id}</td>
                  <td className="small">{task.scene_id}</td>
                  <td className="small">{task.step_kind}</td>
                  <td className="small">{task.adapter}</td>
                  <td className="small">{Number(task.estimated_seconds || 0).toFixed(1)}</td>
                  <td className="small" style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }} title={task.cache_key}>
                    {task.cache_key}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {dependencies.length ? (
        <div className="small" style={{ marginTop: 10, opacity: 0.85 }}>
          Dependencies: {dependencies.slice(0, 12).map((edge: any) => `${edge.from} → ${edge.to}`).join(" • ")}
          {dependencies.length > 12 ? ` • +${dependencies.length - 12} more` : ""}
        </div>
      ) : null}

      {sections.length ? (
        <div className="small" style={{ marginTop: 10 }}>
          Scene routes: {sections.slice(0, 8).map((section: any) => `${section.scene_id}:${section.engine} (~${Number(section.estimated_seconds || 0).toFixed(0)}s)`).join(" • ")}
        </div>
      ) : null}

      {diagnostics.length ? (
        <div className="small" style={{ marginTop: 8, opacity: 0.75 }}>
          Diagnostics: {diagnostics.join(" • ")}
        </div>
      ) : null}

      {proxySections.length ? (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 10, border: "1px solid var(--warning, #b58900)" }}>
          <div className="small" style={{ fontWeight: 700 }}>Legacy proxy route unavailable</div>
          <div className="small" style={{ marginTop: 4 }}>
            This stored plan references {proxySections.length} retired proxy scene route{proxySections.length === 1 ? "" : "s"}.
            Refresh the plan after installing a compatible local model or configuring an authenticated hosted provider.
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            {onOpenModels ? <button className="secondary" onClick={onOpenModels}>Open Models</button> : null}
            {onOpenSettings ? <button className="secondary" onClick={onOpenSettings}>Open provider settings</button> : null}
          </div>
        </div>
      ) : null}
      {continuityReport ? (
        <div className="small" style={{ marginTop: 8, padding: 8, borderRadius: 10, border: "1px solid var(--border)" }}>
          Continuity: {continuityReport.warning_count} warning(s)
          {continuityReport.blocking_count ? ` • ${continuityReport.blocking_count} blocking` : ""}
          {!continuityReport.ok_to_render ? " — resolve before final render." : " — ok to render."}
          {onNavigateReview ? (
            <button className="secondary" style={{ marginLeft: 8 }} onClick={onNavigateReview}>
              Open Review
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
