import React, { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "./api";

type Policy = {
  mode: string; enabled: boolean; auto_build: boolean; allow_fallback: boolean;
  precision: string; strict: boolean; cache_enabled: boolean; cache_limit_gb: number; package_path: string;
};
type Status = { settings: Policy; state: string; package: { installed: boolean };
  diagnostics: { status: string; version?: string; tested_at?: number } | null;
  cache_bytes: number; engines: { engine_id: string; state: string }[] };

export default function RuntimeAccelerationPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [device, setDevice] = useState(0);
  async function refresh() {
    const value = await apiGet("/v1/runtime/status") as Status;
    setStatus(value); setPolicy(value.settings);
  }
  useEffect(() => { void refresh().catch(error => setMessage(String(error))); }, []);
  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    try { await action(); setMessage(message); await refresh(); }
    catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  }
  async function start(operation: string) {
    const job = await apiPost("/v1/runtime/jobs", { operation, device, precision: policy?.precision === "fp32" ? "fp32" : "fp16" });
    setMessage(`Job ${job.job_id} queued. Follow progress or cancel in the Studio job queue.`);
  }
  return <details>
    <summary>AI runtime / NVIDIA acceleration</summary>
    <p>Automatic reuses validated engines when beneficial. Performance can compile on first use. SD1.5 VAE decoding is the first supported component.</p>
    {policy && <fieldset disabled={busy} style={{ display: "grid", gap: 10 }}>
      <label>Runtime mode <select value={policy.mode} onChange={e => setPolicy({ ...policy, mode: e.target.value })}>
        {["auto", "compatibility", "performance", "pytorch_cuda", "tensorrt"].map(v => <option key={v}>{v}</option>)}
      </select></label>
      {(["enabled", "auto_build", "allow_fallback"] as const).map((key, i) => <label key={key}>
        <input type="checkbox" checked={policy[key]} onChange={e => setPolicy({ ...policy, [key]: e.target.checked })} />
        {["Enable TensorRT", "Allow engine builds in Performance mode", "Allow PyTorch CUDA fallback"][i]}
      </label>)}
      <label><input type="checkbox" checked={policy.strict} onChange={e => setPolicy({ ...policy, strict: e.target.checked })} />Strict TensorRT diagnostics (fail instead of fallback)</label>
      <label>Precision <select value={policy.precision} onChange={e => setPolicy({ ...policy, precision: e.target.value })}>
        {["auto", "fp16", "fp32"].map(v => <option key={v}>{v}</option>)}
      </select></label>
      <label>Maximum cache (GB) <input type="number" min={1} max={1000} value={policy.cache_limit_gb} onChange={e => setPolicy({ ...policy, cache_limit_gb: Number(e.target.value) })} /></label>
      <label>Optional SDK folder <input value={policy.package_path} placeholder="Empty uses installed runtime" onChange={e => setPolicy({ ...policy, package_path: e.target.value })} /></label>
      <label>GPU index <input type="number" min={0} max={63} value={device} onChange={e => setDevice(Number(e.target.value))} /></label>
      <div className="row">
        <button onClick={() => void perform(() => apiPost("/v1/runtime/settings", policy), "Runtime settings saved.")}>Save runtime</button>
        <button onClick={() => void start("diagnose").catch(e => setMessage(String(e)))}>Run diagnostics</button>
        <button onClick={() => void start("optimize").catch(e => setMessage(String(e)))}>Optimize SD1.5 (512 × 512)</button>
        <button onClick={() => void perform(refresh, "Runtime status refreshed.")}>Refresh runtime</button>
      </div>
    </fieldset>}
    {status && <>
      <p>Installed: {status.package.installed ? "Yes" : "No"}. Last diagnostic: {status.diagnostics?.status ?? "Not run"}
        {status.diagnostics?.version ? ` (TensorRT ${status.diagnostics.version})` : ""}. Cache: {(status.cache_bytes / 1024 ** 3).toFixed(2)} GB.</p>
      <p>Diagnostics record a previous test. Actual acceleration is recorded per render. Optimization requires the installed SD1.5 model.</p>
      {status.engines.map(engine => <div key={engine.engine_id} style={{ overflowWrap: "anywhere" }}>
        {engine.engine_id} — {engine.state} <button disabled={busy} onClick={() => void perform(() => apiDelete(`/v1/runtime/tensorrt/cache/${engine.engine_id}`), "Engine cache cleared.")}>Clear engine</button>
      </div>)}
    </>}
    <p role="status">{message}</p>
  </details>;
}
