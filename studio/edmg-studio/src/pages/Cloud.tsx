import React, { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Box,
  Boxes,
  CloudCog,
  CloudUpload,
  Database,
  ExternalLink,
  RefreshCw,
  Server,
  Sparkles,
} from "lucide-react";
import { apiGet, apiPost, getBackendUrl, normalizeBackendUrl, setBrowserBackendUrl } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { StructuredSummary } from "../components/StructuredSummary";
import { useStudioPageLayout } from "../components/studioLayout";
import type { PageProps } from "../types/pageProps";

type CloudPanelId = "foundry" | "aws" | "azure" | "hf" | "lightning" | "result";

const FOUNDRY_PROJECT = {
  name: "jonlong-1185",
  subscription: "Azuredwct",
  endpoint: "https://jonlong-1185-resource.services.ai.azure.com/api/projects/jonlong-1185",
};

function CloudPanelHeader({
  icon,
  eyebrow,
  title,
  status,
  statusTone = "neutral",
}: {
  icon: React.ReactNode;
  eyebrow: string;
  title: string;
  status: string;
  statusTone?: "neutral" | "ready" | "attention";
}) {
  return (
    <div className="cloud-panelHeader">
      <div className="cloud-panelIdentity">
        <span className="cloud-panelIcon" aria-hidden="true">{icon}</span>
        <div>
          <div className="cloud-panelEyebrow">{eyebrow}</div>
          <h2>{title}</h2>
        </div>
      </div>
      <span className={`cloud-statusBadge is-${statusTone}`}>{status}</span>
    </div>
  );
}

export default function Cloud(props: PageProps) {
  const [bucket, setBucket] = useState("");
  const [bundleKey, setBundleKey] = useState("edmg_project_bundle.zip");
  const [azureContainer, setAzureContainer] = useState("edmg-model-cache");
  const [azurePrefix, setAzurePrefix] = useState("models");
  const [hfBucket, setHfBucket] = useState("");
  const [hfPrefix, setHfPrefix] = useState("");
  const [hfEnabled, setHfEnabled] = useState(false);
  const [hfStorageMode, setHfStorageMode] = useState<"local_cache" | "cloud_only">("local_cache");
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
    setHfStorageMode(cfg.storage_mode === "cloud_only" ? "cloud_only" : "local_cache");
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
        storage_mode: hfStorageMode,
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
        id: "foundry" as const,
        label: "Microsoft Foundry project",
        description: "Selected Foundry project context and inference configuration boundary.",
      },
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
    foundry: (
      <section className="cloud-panel cloud-panel--featured">
        <CloudPanelHeader
          icon={<Bot size={20} />}
          eyebrow="AI orchestration"
          title="Microsoft Foundry"
          status="Project selected"
          statusTone="ready"
        />
        <p className="cloud-panelCopy">
          Studio is scoped to the selected Foundry project. Model inference remains separate until a deployment
          and authentication method are configured in AI Provider settings.
        </p>
        <div className="cloud-projectGrid">
          <div className="cloud-projectFact">
            <span>Project</span>
            <strong>{FOUNDRY_PROJECT.name}</strong>
          </div>
          <div className="cloud-projectFact">
            <span>Subscription</span>
            <strong>{FOUNDRY_PROJECT.subscription}</strong>
          </div>
          <div className="cloud-projectFact cloud-projectFact--wide">
            <span>Project endpoint</span>
            <code>{FOUNDRY_PROJECT.endpoint}</code>
          </div>
        </div>
        <div className="cloud-callout">
          <Sparkles size={16} aria-hidden="true" />
          <span>This project endpoint identifies the workspace; it is not treated as an OpenAI inference endpoint.</span>
        </div>
        <a
          className="cloud-linkButton"
          href={FOUNDRY_PROJECT.endpoint}
          target="_blank"
          rel="noreferrer"
        >
          Open Foundry project <ExternalLink size={15} aria-hidden="true" />
        </a>
      </section>
    ),
    aws: (
      <section className="cloud-panel">
        <CloudPanelHeader
          icon={<CloudUpload size={20} />}
          eyebrow="Bundle delivery"
          title="AWS S3"
          status="Optional"
        />
        <p className="cloud-panelCopy">Test S3 credentials and optionally upload a portable Studio project bundle.</p>
        <div className="cloud-capability">Requires <code>uv sync --frozen --extra PROFILE --extra aws</code></div>
        <div className="cloud-field">
          <label htmlFor="cloud-aws-bucket">S3 bucket</label>
          <input id="cloud-aws-bucket" value={bucket} onChange={(e) => setBucket(e.target.value)} placeholder="my-bucket" />
        </div>
        <div className="cloud-field">
          <label htmlFor="cloud-aws-key">Bundle key</label>
          <input id="cloud-aws-key" value={bundleKey} onChange={(e) => setBundleKey(e.target.value)} />
        </div>
        <div className="cloud-actions">
          <button onClick={awsTest}>Test credentials</button>
          <button className="secondary" onClick={awsBundle}>Bundle + (optional) upload</button>
        </div>
      </section>
    ),
    azure: (
      <section className="cloud-panel">
        <CloudPanelHeader
          icon={<Database size={20} />}
          eyebrow="Model storage"
          title="Azure Blob cache"
          status="Optional"
        />
        <p className="cloud-panelCopy">Validate Blob Storage access for on-demand model weight caching.</p>
        <div className="cloud-capability">Requires <code>uv sync --frozen --extra PROFILE --extra azure</code></div>
        <div className="cloud-field">
          <label htmlFor="cloud-azure-container">Blob container</label>
          <input id="cloud-azure-container" value={azureContainer} onChange={(e) => setAzureContainer(e.target.value)} placeholder="edmg-model-cache" />
        </div>
        <div className="cloud-field">
          <label htmlFor="cloud-azure-prefix">Model prefix</label>
          <input id="cloud-azure-prefix" value={azurePrefix} onChange={(e) => setAzurePrefix(e.target.value)} placeholder="models" />
        </div>
        <div className="cloud-actions">
          <button onClick={azureTest}>Test Azure</button>
        </div>
      </section>
    ),
    hf: (
      <section className="cloud-panel cloud-panel--wide">
        <CloudPanelHeader
          icon={<Boxes size={20} />}
          eyebrow="Primary model cache"
          title="Hugging Face bucket"
          status={hfStatusLoading ? "Checking" : hfStatus?.active ? "Active" : hfEnabled ? "Configured" : "Disabled"}
          statusTone={hfStatus?.active ? "ready" : hfEnabled ? "attention" : "neutral"}
        />
        <p className="cloud-panelCopy">
          Model cache backed by a Hugging Face bucket. When enabled it is used <b>before AWS S3 / Azure</b>
          {" "}for finding, downloading, and storing model weights. Settings are saved by Studio — no env vars required.
        </p>
        {hfStatusLoading ? (
          <div className="cloud-inlineStatus"><RefreshCw className="cloud-spin" size={14} /> Loading backend status…</div>
        ) : hfStatus ? (
          <div className="cloud-inlineStatus">
            {hfStatus.error ? (
              <span className="cloud-errorText">{hfStatus.error}</span>
            ) : (
              <>
                Cache enabled: {hfStatus.enabled ? "yes" : "no"} · Active: {hfStatus.active ? "yes" : "no"}
                {hfStatus.has_token ? ` · Token: ${hfStatus.token_source || "available"}` : " · Token: not found"}
                {hfStatus.active_error ? ` · ${hfStatus.active_error}` : ""}
              </>
            )}
          </div>
        ) : null}
        <div className="cloud-activeProvider">
          <Box size={15} aria-hidden="true" />
          Active model cache: <b>{hfActiveProvider || "none (local + S3/Azure fallback)"}</b>
        </div>
        <div className="cloud-field">
          <label htmlFor="cloud-hf-storage">Model storage mode</label>
          <select id="cloud-hf-storage" value={hfStorageMode} onChange={(e) => setHfStorageMode(e.target.value as "local_cache" | "cloud_only")}>
            <option value="local_cache">Local models + HF/S3 secondary mirrors</option>
            <option value="cloud_only">Cloud only (no local model copy)</option>
          </select>
        </div>
        <div className="cloud-fieldHint">
          Local-first keeps installed models on this machine. When HF bucket or S3 is enabled, Studio also mirrors supported models there and restores from those caches if the local file is missing.
        </div>
        <label className="cloud-toggle">
          <input
            type="checkbox"
            checked={hfEnabled}
            onChange={(e) => setHfEnabled(e.target.checked)}
          />
          <span>Use Hugging Face bucket as the model cache (priority over S3)</span>
        </label>
        <div className="cloud-fieldGrid">
          <div className="cloud-field">
            <label htmlFor="cloud-hf-bucket">Bucket id (namespace/name)</label>
          <input
            id="cloud-hf-bucket"
            value={hfBucket}
            onChange={(e) => setHfBucket(e.target.value)}
            placeholder="namespace/bucket-name"
          />
          </div>
          <div className="cloud-field">
            <label htmlFor="cloud-hf-prefix">Optional prefix</label>
            <input id="cloud-hf-prefix" value={hfPrefix} onChange={(e) => setHfPrefix(e.target.value)} placeholder="models" />
          </div>
        </div>
        <div className="cloud-fieldHint">
          Uploads need a token with write access. Studio checks env tokens (<code>HF_TOKEN</code> / <code>EDMG_HF_TOKEN</code>),
          then the modern <code>hf auth login</code> session, then Settings → Tokens. Public buckets can be read without a token.
        </div>
        <div className="cloud-actions">
          <button onClick={saveHf} disabled={hfSaving}>
            {hfSaving ? "Saving…" : "Save & apply"}
          </button>
          <button className="secondary" onClick={hfTest}>Test HF bucket</button>
          <button className="secondary" onClick={() => void loadHfStatus()} disabled={hfStatusLoading}>
            Refresh status
          </button>
        </div>
      </section>
    ),
    lightning: (
      <section className="cloud-panel">
        <CloudPanelHeader
          icon={<Server size={20} />}
          eyebrow="Remote runtime"
          title="Lightning.ai"
          status="Bundle tools"
        />
        <p className="cloud-panelCopy">Generate a runnable backend bundle and target a hosted Studio runtime.</p>
        <div className="cloud-field">
          <label htmlFor="cloud-lightning-output">Output dir under Studio data/cloud</label>
          <input id="cloud-lightning-output" value={lightningOut} onChange={(e) => setLightningOut(e.target.value)} />
        </div>
        <div className="cloud-field">
          <label htmlFor="cloud-lightning-url">Lightning backend URL</label>
          <input
            id="cloud-lightning-url"
            aria-label="Lightning backend URL"
            value={lightningBackendUrl}
            onChange={(e) => setLightningBackendUrl(e.target.value)}
            placeholder="https://your-lightning-backend.example.com"
          />
        </div>
        <div className="cloud-actions">
          <button onClick={lightningBundle}>Generate bundle</button>
          <button className="secondary" disabled={connectingLightning} onClick={connectLightningBackend}>
            {connectingLightning ? "Connecting…" : window.edmg?.setBackendSettings ? "Save backend target" : "Use backend now"}
          </button>
        </div>
      </section>
    ),
    result: result ? (
      <section className="cloud-result">
        <CloudPanelHeader
          icon={<CloudCog size={20} />}
          eyebrow="Latest operation"
          title="Result"
          status={result?.ok === false ? "Action failed" : "Complete"}
          statusTone={result?.ok === false ? "attention" : "ready"}
        />
        <StructuredSummary value={result} showJson />
      </section>
    ) : null,
  };

  return (
    <div className="cloud-page">
      <header className="cloud-pageHeader">
        <div>
          <div className="cloud-kicker">Infrastructure workspace</div>
          <div className="cloud-titleRow">
            <CloudCog size={28} aria-hidden="true" />
            <h1>Cloud</h1>
          </div>
          <p className="cloud-headerCopy">
            Coordinate AI projects, model caches, bundle delivery, and remote Studio runtimes from one workspace.
          </p>
        </div>
        <div className="cloud-statusStrip" aria-label="Cloud workspace status">
          <div className="cloud-stat">
            <span>Foundry</span>
            <strong>{FOUNDRY_PROJECT.name}</strong>
          </div>
          <div className="cloud-stat">
            <span>Model cache</span>
            <strong>{hfStatus?.active ? "HF active" : "Local fallback"}</strong>
          </div>
          <div className="cloud-stat">
            <span>Backend</span>
            <strong>{normalizeBackendUrl(props.backendUrl || getBackendUrl()) ? "Target set" : "Local"}</strong>
          </div>
        </div>
      </header>
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
      {err && <div className="cloud-error" role="alert">{err}</div>}
      <div className="cloud-panelGrid">
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
