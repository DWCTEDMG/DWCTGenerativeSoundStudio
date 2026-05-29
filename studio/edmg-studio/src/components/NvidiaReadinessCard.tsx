import React from "react";

type NvidiaReadinessCardProps = {
  diagnostics?: any;
  status?: any;
  title?: string;
  asCard?: boolean;
  busy?: boolean;
  onRefresh?: () => void;
  onOpenSettings?: () => void;
};

function readinessLabel(level: string) {
  if (level === "ready") return "Ready";
  if (level === "partial") return "Partial";
  if (level === "disabled") return "Disabled";
  return "Blocked";
}

function readinessColors(level: string) {
  if (level === "ready") return { background: "#163a1f", color: "#b7ffcb", border: "#245b32" };
  if (level === "partial") return { background: "#332c12", color: "#ffe6a3", border: "#665624" };
  if (level === "disabled") return { background: "#202535", color: "#c9d7ff", border: "#35405f" };
  return { background: "#3a1616", color: "#ffb7b7", border: "#5b2424" };
}

function Badge({ level, label }: { level: string; label: string }) {
  const colors = readinessColors(level);
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 800,
        background: colors.background,
        color: colors.color,
        border: `1px solid ${colors.border}`,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

function CheckRow({ check }: { check: any }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
        gap: 8,
        alignItems: "center",
      }}
    >
      <div className="small" style={{ fontWeight: 800 }}>{check?.label || check?.id || "check"}</div>
      <Badge level={check?.ok ? "ready" : "blocked"} label={check?.ok ? "OK" : "Needs work"} />
      <div className="small" style={{ opacity: 0.86, minWidth: 0, overflowWrap: "anywhere" }}>
        {check?.detail || check?.fix || check?.severity || ""}
      </div>
    </div>
  );
}

export default function NvidiaReadinessCard({
  diagnostics,
  status,
  title = "NVIDIA Runtime Readiness",
  asCard = true,
  busy = false,
  onRefresh,
  onOpenSettings,
}: NvidiaReadinessCardProps) {
  const nvidiaDiagnostics = diagnostics?.nvidia ?? diagnostics ?? null;
  const readiness = nvidiaDiagnostics?.readiness ?? null;
  const profile = status?.nvidia ?? nvidiaDiagnostics?.profile ?? null;
  const host = nvidiaDiagnostics?.host ?? null;
  const services = nvidiaDiagnostics?.services ?? profile?.services ?? null;
  const level = String(readiness?.level || (profile?.enabled ? "partial" : "disabled"));
  const checks = Array.isArray(readiness?.checks) ? readiness.checks : [];
  const nextActions = Array.isArray(readiness?.next_actions) ? readiness.next_actions : [];
  const body = (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 800 }}>{title}</div>
          <div className="small" style={{ marginTop: 6, opacity: 0.88 }}>
            {readiness?.summary || "Checks the NVIDIA profile, host GPU, Docker NVIDIA runtime, NGC access, and NIM endpoint."}
          </div>
        </div>
        <Badge level={level} label={readinessLabel(level)} />
      </div>

      <div className="small" style={{ marginTop: 10, opacity: 0.9 }}>
        Profile: <b>{profile?.enabled ? "enabled" : "disabled"}</b>
        {" "}• NGC key <b>{profile?.credentials?.ngc_api_key_configured ? "configured" : "not configured"}</b>
        {host?.gpu?.gpus?.[0]?.name ? <> • GPU <b>{host.gpu.gpus[0].name}</b></> : null}
      </div>
      <div className="small" style={{ marginTop: 6, opacity: 0.9 }}>
        Docker NVIDIA runtime: <b>{host?.docker?.nvidia_runtime ? "ready" : "not ready"}</b>
        {services?.nim?.model ? <> • NIM model <code>{services.nim.model}</code></> : null}
        {services?.nim?.probe?.models_url ? <> • models <code>{services.nim.probe.models_url}</code></> : null}
      </div>

      {checks.length ? (
        <div style={{ display: "grid", gap: 7, marginTop: 12 }}>
          {checks.slice(0, 7).map((check: any) => (
            <CheckRow key={check?.id || check?.label} check={check} />
          ))}
        </div>
      ) : null}

      {nextActions.length ? (
        <div style={{ marginTop: 12 }}>
          <div className="small" style={{ fontWeight: 800, marginBottom: 6 }}>Next actions</div>
          <ol className="small" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6 }}>
            {nextActions.slice(0, 4).map((action: any) => (
              <li key={action?.id || action?.title}>
                <b>{action?.title || action?.id}</b>
                {action?.fix ? <>: {action.fix}</> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
        {onRefresh ? (
          <button className="secondary" disabled={busy} onClick={onRefresh}>
            {busy ? "Checking..." : "Refresh NVIDIA checks"}
          </button>
        ) : null}
        {onOpenSettings ? (
          <button className="secondary" onClick={onOpenSettings}>Open NVIDIA Settings</button>
        ) : null}
      </div>
    </>
  );

  if (!asCard) return <div>{body}</div>;
  return <div className="card">{body}</div>;
}
