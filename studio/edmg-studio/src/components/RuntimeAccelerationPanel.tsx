import React, { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "./api";

type Policy = {
  mode: string; enabled: boolean; auto_build: boolean; allow_fallback: boolean;
  precision: string; strict: boolean; cache_enabled?: boolean; cache_limit_gb: number; package_path: string;
};
type RuntimeComponent = {
  model_family: string; component: string; fallback_runtime: string;
  optimization_reason?: string | null; validated_engine_count: number;
  last_failure?: string | null; source_kind?: string | null; architecture?: string | null;
  selected_route: string; compiler?: string | null; route_supported: boolean;
  route_reason?: string | null; validated: boolean; accelerating: boolean;
};
type Engine = { engine_id: string; state: string };
type Status = {
  settings: Policy; state: string; installed: boolean; available: boolean; healthy: boolean;
  compatible: boolean; accelerating: boolean; tensorrt_version?: string | null;
  diagnostics: { status?: string; version?: string } | null; cache_bytes: number;
  supported_component_count: number; components: RuntimeComponent[]; engines: Engine[];
};

const ROUTE_LABELS: Record<string, string> = {
  onnx_parser: "ONNX via TensorRT parser",
  torch_tensorrt: "PyTorch via Torch-TensorRT",
  torch_compile_tensorrt: "PyTorch via torch.compile TensorRT",
  huggingface_torch_tensorrt: "Hugging Face via Torch-TensorRT",
  huggingface_onnx_tensorrt: "Hugging Face via ONNX/TensorRT",
  prebuilt_engine: "Prebuilt TensorRT engine",
  llama_cpp: "GGUF via llama.cpp (non-TensorRT)",
  existing_runtime: "Existing runtime",
};
const words = (value: string | null | undefined) => String(value || "unknown").replaceAll("_", " ");
const routeLabel = (component: RuntimeComponent) => ROUTE_LABELS[component.selected_route] || words(component.selected_route);
function componentState(component: RuntimeComponent) {
  if (component.accelerating) return "Accelerating this operation";
  if (component.validated) return "Validated engine available";
  if (component.route_supported) return "Supported; not yet validated";
  return `Fallback: ${words(component.fallback_runtime)}`;
}

export default function RuntimeAccelerationPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [device, setDevice] = useState(0);

  async function refresh() {
    const value = await apiGet("/v1/runtime/status") as Status;
    setStatus({ ...value, components: value.components || [], engines: value.engines || [] });
    setPolicy(value.settings);
  }
  useEffect(() => { void refresh().catch(error => setMessage(String(error))); }, []);
  async function perform(action: () => Promise<unknown>, successMessage: string) {
    setBusy(true);
    try { await action(); setMessage(successMessage); await refresh(); }
    catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  }
  async function start(operation: string) {
    const job = await apiPost("/v1/runtime/jobs", { operation, device, precision: policy?.precision === "fp32" ? "fp32" : "fp16" });
    setMessage(`Job ${job.job_id} queued. Follow progress or cancel in the Studio job queue.`);
  }

  return <details>
    <summary>AI runtime / NVIDIA acceleration</summary>
    <p>Automatic mode reuses validated engines when beneficial. Performance mode can compile on first use; actual acceleration is recorded per render.</p>
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
      <div className="card" style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 900 }}>Runtime readiness</div>
        <div className="small">Installed: <b>{status.installed ? "Yes" : "No"}</b> · Healthy: <b>{status.healthy ? "Yes" : "No"}</b> · Compatible: <b>{status.compatible ? "Yes" : "No"}</b>{status.tensorrt_version ? ` · TensorRT ${status.tensorrt_version}` : ""} · Cache: <b>{(status.cache_bytes / 1024 ** 3).toFixed(2)} GB</b></div>
        <div className="small">Last diagnostic: <b>{status.diagnostics?.status ?? "Not run"}</b>. This is a saved receipt, not a live-render acceleration claim.</div>
      </div>
      {status.components.length > 0 && <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
        <div style={{ fontWeight: 900 }}>Component routes</div>
        {status.components.map(component => <div className="card" key={`${component.model_family}:${component.component}`}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
            <b>{words(component.model_family)} · {words(component.component)}</b><span className="badge">{componentState(component)}</span>
          </div>
          <div className="small">{routeLabel(component)}{component.compiler ? ` · compiler ${component.compiler}` : ""}</div>
          <div className="small">Source: {words(component.source_kind)}{component.architecture ? ` · ${component.architecture}` : ""} · Engines: {component.validated_engine_count}</div>
          {!component.route_supported && component.route_reason ? <div className="small warn">{component.route_reason}</div> : null}
          {component.optimization_reason ? <div className="small">{component.optimization_reason}</div> : null}
          {component.last_failure ? <div className="small error">Last failure: {component.last_failure}</div> : null}
        </div>)}
      </div>}
      {status.engines.length > 0 && <details style={{ marginTop: 12 }}>
        <summary>Validated engine cache ({status.engines.length})</summary>
        {status.engines.map(engine => <div key={engine.engine_id} style={{ overflowWrap: "anywhere" }}>{engine.engine_id} — {engine.state} <button disabled={busy} onClick={() => void perform(() => apiDelete(`/v1/runtime/tensorrt/cache/${engine.engine_id}`), "Engine cache cleared.")}>Clear engine</button></div>)}
      </details>}
    </>}
    <p role="status">{message}</p>
  </details>;
}
