import React, { useEffect, useState } from "react";
import { apiGet, apiPost, apiPut } from "./api";
import { executionReadinessLabel, type ExecutionEnvironment, type ExecutionInventory, type ExecutionProfile } from "../shared/executionPlane";

export function ExecutionPlaneStatus({ editableProfile = false, environment, onEnvironmentChange, allowFallback = true, onAllowFallbackChange }: { editableProfile?: boolean; environment?: ExecutionEnvironment; onEnvironmentChange?: (value: ExecutionEnvironment) => void; allowFallback?: boolean; onAllowFallbackChange?: (value: boolean) => void }) {
  const [profile, setProfile] = useState<ExecutionProfile | null>(null);
  const [inventory, setInventory] = useState<ExecutionInventory | null>(null);
  const [error, setError] = useState("");
  const refresh = async () => { try { const [p, i] = await Promise.all([apiGet("/v1/execution/profile"), apiGet("/v1/execution/inventory")]); setProfile(p); setInventory(i); setError(""); } catch (err: any) { setError(String(err?.message || err)); } };
  useEffect(() => { void refresh(); }, []);
  const saveProfile = async (runtime_profile: ExecutionProfile["runtime_profile"]) => setProfile(await apiPut("/v1/execution/profile", { runtime_profile, model_environment_preferences: profile?.model_environment_preferences || {} }));
  const probe = async () => setInventory(await apiPost("/v1/execution/wsl/probe", {}));
  return <section className="card" aria-label="Execution plane status" style={{ marginBottom: 14 }}>
    <div style={{ fontWeight: 800 }}>Execution plane</div>
    {editableProfile && <label>Runtime profile <select value={profile?.runtime_profile || "standard"} onChange={(e) => void saveProfile(e.target.value as ExecutionProfile["runtime_profile"])}><option value="standard">Standard</option><option value="hybrid_gpu">Hybrid GPU (recommended)</option><option value="external_linux">External Linux backend</option></select></label>}
    {onEnvironmentChange && <label>Requested environment <select value={environment || "auto"} onChange={(e) => onEnvironmentChange(e.target.value as ExecutionEnvironment)}><option value="auto">Automatic</option><option value="windows">Windows</option><option value="wsl">WSL2 Linux worker</option></select></label>}
    {onAllowFallbackChange && <label><input type="checkbox" checked={allowFallback} onChange={(e) => onAllowFallbackChange(e.target.checked)} /> Allow environment fallback</label>}
    <div className="small">Profile: <b>{profile?.runtime_profile || "loading"}</b> • {inventory ? executionReadinessLabel(inventory) : "Loading readiness…"} • distro <b>{inventory?.wsl.distribution || "not configured"}</b> • GPU mappings <b>{inventory?.physical_gpus.length ?? 0}</b></div>
    {inventory?.blockers?.length ? <div className="small" style={{ color: "var(--danger)" }}>{inventory.blockers[0].code}: {inventory.blockers[0].message}</div> : null}
    {error && <div style={{ color: "var(--danger)" }}>{error}</div>}
    <button className="secondary" type="button" onClick={() => void probe()}>Re-probe WSL</button>
  </section>;
}
