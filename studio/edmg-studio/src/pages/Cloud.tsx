import React, { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, getBackendUrl, normalizeBackendUrl, setBrowserBackendUrl } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { StructuredSummary } from "../components/StructuredSummary";
import { useStudioPageLayout } from "../components/studioLayout";
import type { PageProps } from "../types/pageProps";

type CloudPanelId = "aws" | "azure" | "hf" | "lightning" | "result";

export default function Cloud(props: PageProps) {
  const [bucket, setBucket] = useState("");
  const [bundleKey, setBundleKey] = useState("edmg_project_bundle.zip");
  const [azureContainer, setAzureContainer] = useState("edmg-model-cache");
  const [azurePrefix, setAzurePrefix] = useState("models");
  const [hfBucket, setHfBucket] = useState("");
  const [hfPrefix, setHfPrefix] = useState("");
  const [hfEnabled, setHfEnabled] = useState(false);
  const [hfStatus, setHfStatus] = useState<any>(null);
  const [hfActiveProvider, setHfActiveProvider] = useState<string | null>(null);
  const [hfStatusLoading, setHfStatusLoading] = useState(false);
  const [hfSaving, setHfSaving] = useState(false);
  const [lightningOut, setLightningOut] = useState("lightning/lightning_bundle");
  const [lightningBackendUrl, setLightningBackendUrl] = useState(
    () => normalizeBackendUrl(props.backendUrl || getBackendUrl()) || "",
  );
  const [connectingLightning, setConnectingLightning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const awsTest = async () => {
    setErr(null); setResult(null);
    try { setResult(await apiPost("/v1/cloud/aws/test", { bucket: bucket || null })); }
    catch (e: any) { setErr(String(e)); }
  };

  const awsBundle = async () => {
    setErr(null); setResult(null);
    try { setResult(await apiPost("/v1/cloud/aws/bundle", { bucket: bucket || null, key: bundleKey || null })); }
    catch (e: any) { setErr(String(e)); }
  };

  const azureTest = async () => {
    setErr(null); setResult(null);
    try { setResult(await apiPost("/v1/cloud/azure/test", { container: azureContainer || null, prefix: azurePrefix || null })); }
    catch (e: any) { setErr(String(e)); }
  };

  const applyHfPayload = (payload: any) => {
    const cfg = payload?.settings ?? {};
    setHfStatus(payload?.status ?? null);
    setHfActiveProvider(payload?.active_provider ?? null);
    setHfEnabled(!!cfg.enabled);
    setHfBucket(String(cfg.bucket ?? ""));
    setHfPrefix(String(cfg.prefix ?? ""));
  };

  const loadHfStatus = async () => {
    setHfStatusLoading(true);
    try {
      applyHfPayload(await apiGet("/v1/cloud/hf/settings"));
    } catch (e: any) {
      setHfStatus({ ok: false, error: String(e) });
    } finally {
      setHfStatusLoading(false);
    }
  };

  const saveHf = async () => {
    setErr(null); setResult(null); setHfSaving(true);
    try {
      const payload = await apiPost("/v1/cloud/hf/settings", {
        enabled: hfEnabled,
        bucket: hfBucket || null,
        prefix: hfPrefix || null,
      });
      applyHfPayload(payload);
      setResult(payload);
    } catch (e: any) {
      setErr(String(e));
    } finally {
      setHfSaving(false);
    }
  };

  const hfTest = async () => {
    setErr(null); setResult(null);
    try {
      setResult(await apiPost("/v1/cloud/hf/test", { bucket: hfBucket || null, prefix: hfPrefix || null }));
    } catch (e: any) { setErr(String(e)); }
  };

  useEffect(() => {
    void loadHfStatus();
  }, []);

  const lightningBundle = async () => {
    setErr(null); setResult(null);
    try { setResult(await apiPost("/v1/cloud/lightning/bundle", { output_dir: lightningOut })); }
    catch (e: any) { setErr(String(e)); }
  };

  const connectLightningBackend = async () => {
    setConnectingLightning(true);
    setErr(null); setResult(null);
    try {
      const normalizedUrl = normalizeBackendUrl(lightningBackendUrl);
      if (!normalizedUrl) {
        throw new Error("Enter a valid Lightning backend URL starting with http:// or https://.");
      }

      if (window.edmg?.setBackendSettings) {
        const response = await window.edmg.setBackendSettings({
          mode: "external",
          host: "127.0.0.1",
          port: "7863",
          url: normalizedUrl,
        });
        if (!response?.ok) {
          throw new Error(response?.error || "Failed to save Lightning backend settings.");
        }
        setResult({
          ok: true,
          action: "connect_lightning_backend",
          backendUrl: normalizedUrl,
          restartRequired: !!response.restartRequired,
        });
      } else {
        const connectedUrl = setBrowserBackendUrl(normalizedUrl);
        setLightningBackendUrl(connectedUrl);
        setResult({
          ok: true,
          action: "connect_lightning_backend",
          backendUrl: connectedUrl,
          restartRequired: false,
          source: "browser",
        });
      }
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setConnectingLightning(false);
    }
  };

  const panelDefinitions = useMemo(
    () => [
      {
        id: "aws" as const,
        label: "AWS bundle tools",
        description: "S3 credential test and optional project bundle upload flow.",
      },
      {
        id: "azure" as const,
        label: "Azure model cache",
        description: "Blob Storage credential test for on-demand model weight caching.",
      },
      {
        id: "hf" as const,
        label: "Hugging Face bucket",
        description: "Status and credential test for HF bucket-backed model cache.",
      },
      {
        id: "lightning" as const,
        label: "Lightning.ai bundle",
        description: "Local bundle generation for Lightning.ai-style backend startup.",
      },
      {
        id: "result" as const,
        label: "Result payload",
        description: "Read-only response output from the latest cloud helper action.",
      },
    ],
    [],
  );
  const {
    profileOptions,
    activeProfile,
    setActiveProfile,
    layoutState,
    visibleOrder,
    movePanel,
    updateHidden,
    resetLayout,
  } = useStudioPageLayout<CloudPanelId>(
    "cloud",
    panelDefinitions.map((panel) => panel.id),
  );
  const panelDefinitionById = useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<CloudPanelId, (typeof panelDefinitions)[number]>,
    [panelDefinitions],
  );
  const panelControlItems = layoutState.order.map((panelId, index) => ({
    id: panelId,
    label: panelDefinitionById[panelId].label,
    description: panelDefinitionById[panelId].description,
    hidden: layoutState.hidden.includes(panelId),
    canMoveUp: index > 0,
    canMoveDown: index < layoutState.order.length - 1,
  }));

  const panelContent: Record<CloudPanelId, React.ReactNode> = {
    aws: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 10 }}>AWS</div>
        <div className="small">Optional dependency. Install backend with: pip install -e ".[aws]"</div>
        <div style={{ marginTop: 10 }}>
          <div className="small">S3 bucket</div>
          <input value={bucket} onChange={(e) => setBucket(e.target.value)} placeholder="my-bucket" />
        </div>
        <div style={{ marginTop: 10 }}>
          <div className="small">Bundle key</div>
          <input value={bundleKey} onChange={(e) => setBundleKey(e.target.value)} />
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={awsTest}>Test credentials</button>
          <button className="secondary" onClick={awsBundle}>Bundle + (optional) upload</button>
        </div>
      </div>
    ),
    azure: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Azure</div>
        <div className="small">Optional dependency. Install backend with: pip install -e ".[azure]"</div>
        <div style={{ marginTop: 10 }}>
          <div className="small">Blob container</div>
          <input value={azureContainer} onChange={(e) => setAzureContainer(e.target.value)} placeholder="edmg-model-cache" />
        </div>
        <div style={{ marginTop: 10 }}>
          <div className="small">Model prefix</div>
          <input value={azurePrefix} onChange={(e) => setAzurePrefix(e.target.value)} placeholder="models" />
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={azureTest}>Test Azure</button>
        </div>
      </div>
    ),
    hf: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Hugging Face bucket</div>
        <div className="small">
          Model cache backed by a Hugging Face bucket. When enabled it is used <b>before AWS S3 / Azure</b>
          {" "}for finding, downloading, and storing model weights. Settings are saved by Studio — no env vars required.
        </div>
        {hfStatusLoading ? (
          <div className="small" style={{ marginTop: 10 }}>Loading backend status…</div>
        ) : hfStatus ? (
          <div className="small" style={{ marginTop: 10 }}>
            {hfStatus.error ? (
              <span style={{ color: "var(--danger)" }}>{hfStatus.error}</span>
            ) : (
              <>
                Cache enabled: {hfStatus.enabled ? "yes" : "no"} · Active: {hfStatus.active ? "yes" : "no"}
                {hfStatus.has_token ? ` · Token: ${hfStatus.token_source || "available"}` : " · Token: not found"}
                {hfStatus.active_error ? ` · ${hfStatus.active_error}` : ""}
              </>
            )}
          </div>
        ) : null}
        <div className="small" style={{ marginTop: 6 }}>
          Active model cache: <b>{hfActiveProvider || "none (local + S3/Azure fallback)"}</b>
        </div>
        <label className="row" style={{ marginTop: 10, alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            checked={hfEnabled}
            onChange={(e) => setHfEnabled(e.target.checked)}
            style={{ width: "auto" }}
          />
          <span>Use Hugging Face bucket as the model cache (priority over S3)</span>
        </label>
        <div style={{ marginTop: 10 }}>
          <div className="small">Bucket id (namespace/name)</div>
          <input
            value={hfBucket}
            onChange={(e) => setHfBucket(e.target.value)}
            placeholder="namespace/bucket-name"
          />
        </div>
        <div style={{ marginTop: 10 }}>
          <div className="small">Optional prefix</div>
          <input value={hfPrefix} onChange={(e) => setHfPrefix(e.target.value)} placeholder="models" />
        </div>
        <div className="small" style={{ marginTop: 10 }}>
          Uploads need a token with write access — env token (<code>HF_TOKEN</code> / <code>EDMG_HF_TOKEN</code>)
          first, then Settings → Tokens. Public buckets can be read without a token.
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={saveHf} disabled={hfSaving}>
            {hfSaving ? "Saving…" : "Save & apply"}
          </button>
          <button className="secondary" onClick={hfTest}>Test HF bucket</button>
          <button className="secondary" onClick={() => void loadHfStatus()} disabled={hfStatusLoading}>
            Refresh status
          </button>
        </div>
      </div>
    ),
    lightning: (
      <div className="card">
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Lightning.ai</div>
        <div className="small">Generates a runnable bundle folder (backend + startup script).</div>
        <div style={{ marginTop: 10 }}>
          <div className="small">Output dir under Studio data/cloud</div>
          <input value={lightningOut} onChange={(e) => setLightningOut(e.target.value)} />
        </div>
        <div style={{ marginTop: 10 }}>
          <div className="small">Lightning backend URL</div>
          <input
            aria-label="Lightning backend URL"
            value={lightningBackendUrl}
            onChange={(e) => setLightningBackendUrl(e.target.value)}
            placeholder="https://your-lightning-backend.example.com"
          />
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={lightningBundle}>Generate bundle</button>
          <button className="secondary" disabled={connectingLightning} onClick={connectLightningBackend}>
            {connectingLightning ? "Connecting…" : window.edmg?.setBackendSettings ? "Save backend target" : "Use backend now"}
          </button>
        </div>
      </div>
    ),
    result: result ? (
      <div className="card" style={{ marginTop: 14 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Result</div>
        <StructuredSummary value={result} showJson />
      </div>
    ) : null,
  };

  return (
    <div>
      <h1>Cloud</h1>
      <div className="small" style={{ marginTop: 6 }}>
        Reorder or hide cloud helper sections for your own workflow. This only changes the local page layout and does not alter any bundle, upload, or backend behavior.
      </div>
      <StudioLayoutCustomizer
        title="Cloud layout"
        description="Reorder or hide cloud helper panels without changing AWS tests, bundle generation, or upload payloads."
        items={panelControlItems}
        profileOptions={profileOptions}
        activeProfile={activeProfile}
        onSelectProfile={setActiveProfile}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      {err && <div style={{ marginTop: 14, color: "var(--danger)" }}>{err}</div>}
      <div className="grid2" style={{ marginTop: 14 }}>
        {visibleOrder
          .filter((panelId) => panelId !== "result")
          .map((panelId) => (
            <React.Fragment key={panelId}>{panelContent[panelId]}</React.Fragment>
          ))}
      </div>
      {visibleOrder.includes("result") ? panelContent.result : null}
    </div>
  );
}
