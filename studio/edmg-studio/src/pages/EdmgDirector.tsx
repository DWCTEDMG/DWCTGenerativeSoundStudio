import React from "react";
import { apiPost } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { useStudioPageLayout } from "../components/studioLayout";
import type { PageProps } from "../types/pageProps";
import AiNlpWorkbench from "../workbenches/AiNlpWorkbench";
import AudioReactiveWorkbench from "../workbenches/AudioReactiveWorkbench";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";

type DirectorLabPanelId = "bridge" | "launch" | "plannerWorkbench" | "reactiveWorkbench";
type ManagedDirectorStatus = {
  available: boolean;
  managed: boolean;
  serviceUrl: string;
  mcpUrl: string;
  advertisedBaseUrl: string;
  backendUrl: string;
  pid: number | null;
  lastError: string;
  startedAt: string | null;
  packaged: boolean;
};

const EXTERNAL_DIRECTOR_URL_KEY = "edmg_director_external_url_v1";

function readStoredDirectorUrl(): string {
  if (typeof window === "undefined") return "";
  return String(window.localStorage.getItem(EXTERNAL_DIRECTOR_URL_KEY) || "").trim();
}

function writeStoredDirectorUrl(value: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(EXTERNAL_DIRECTOR_URL_KEY, String(value || "").trim());
}

function normalizeUrl(value: string): string {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

async function copyText(text: string): Promise<void> {
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

export default function EdmgDirector({ onNavigate }: PageProps) {
  const { projects, projectId, setProjectId, selectedVariant, project, refreshProject } =
    useStudioWorkbenchProject();
  const [directorUrl, setDirectorUrl] = React.useState(() => readStoredDirectorUrl());
  const [launchMessage, setLaunchMessage] = React.useState("");
  const [managedDirector, setManagedDirector] = React.useState<ManagedDirectorStatus | null>(null);
  const [directorStatusLoading, setDirectorStatusLoading] = React.useState(false);

  const normalizedDirectorUrl = React.useMemo(() => normalizeUrl(directorUrl), [directorUrl]);
  const derivedMcpEndpoint = React.useMemo(() => {
    if (!normalizedDirectorUrl) return "";
    return normalizedDirectorUrl.endsWith("/mcp")
      ? normalizedDirectorUrl
      : `${normalizedDirectorUrl.replace(/\/+$/, "")}/mcp`;
  }, [normalizedDirectorUrl]);

  const refreshManagedDirectorStatus = React.useCallback(async () => {
    if (!window.edmg?.getDirectorStatus) return;
    setDirectorStatusLoading(true);
    try {
      const status = await window.edmg.getDirectorStatus();
      if (status?.ok) {
        setManagedDirector({
          available: Boolean(status.available),
          managed: Boolean(status.managed),
          serviceUrl: String(status.serviceUrl || ""),
          mcpUrl: String(status.mcpUrl || ""),
          advertisedBaseUrl: String(status.advertisedBaseUrl || ""),
          backendUrl: String(status.backendUrl || ""),
          pid: typeof status.pid === "number" ? status.pid : null,
          lastError: String(status.lastError || ""),
          startedAt: typeof status.startedAt === "string" ? status.startedAt : null,
          packaged: Boolean(status.packaged),
        });
      }
    } catch (error: any) {
      setLaunchMessage(String(error?.message ?? error ?? "Failed to read managed Director status."));
    } finally {
      setDirectorStatusLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refreshManagedDirectorStatus();
  }, [refreshManagedDirectorStatus]);

  const syncPlannerLab = async (payload: any) => {
    if (!projectId)
      throw new Error("Select a Studio project before syncing the planner into the renderer.");
    await apiPost(`/v1/projects/${projectId}/planner_lab/import`, payload);
    await refreshProject(projectId);
    return `${project?.name || "Selected project"} now has the planner lab analysis, canonical plan, and renderer prompt/motion tracks applied.`;
  };

  const syncReactiveLab = async (payload: any) => {
    if (!projectId)
      throw new Error("Select a Studio project before applying reactive motion to the renderer.");
    await apiPost(`/v1/projects/${projectId}/reactive_lab/apply`, payload);
    await refreshProject(projectId);
    return `${project?.name || "Selected project"} now has the reactive motion track and camera data wired into the internal renderer timeline.`;
  };

  const updateDirectorUrl = (value: string) => {
    setDirectorUrl(value);
    writeStoredDirectorUrl(value);
    setLaunchMessage("");
  };

  const openDirectorUrl = async () => {
    if (!normalizedDirectorUrl) {
      setLaunchMessage("Enter the public EDMG Director URL or a ChatGPT thread URL first.");
      return;
    }
    try {
      if (window.edmg?.openExternal) {
        await window.edmg.openExternal(normalizedDirectorUrl);
      } else {
        window.open(normalizedDirectorUrl, "_blank", "noopener,noreferrer");
      }
      setLaunchMessage("Opened EDMG Director outside Studio.");
    } catch (error: any) {
      setLaunchMessage(String(error?.message ?? error ?? "Failed to open the external URL."));
    }
  };

  const copyMcpEndpoint = async () => {
    if (!derivedMcpEndpoint) {
      setLaunchMessage("Enter the public EDMG Director URL first so Studio can derive the MCP endpoint.");
      return;
    }
    try {
      await copyText(derivedMcpEndpoint);
      setLaunchMessage("Copied the MCP endpoint for ChatGPT connector setup.");
    } catch (error: any) {
      setLaunchMessage(String(error?.message ?? error ?? "Failed to copy the MCP endpoint."));
    }
  };

  const openManagedDirectorStatus = async () => {
    const targetUrl = managedDirector?.serviceUrl || "";
    if (!targetUrl) {
      setLaunchMessage("The Studio-managed Director service URL is not available yet.");
      return;
    }
    try {
      if (window.edmg?.openExternal) {
        await window.edmg.openExternal(targetUrl);
      } else {
        window.open(targetUrl, "_blank", "noopener,noreferrer");
      }
      setLaunchMessage("Opened the Studio-managed Director service status page.");
    } catch (error: any) {
      setLaunchMessage(String(error?.message ?? error ?? "Failed to open the managed Director service URL."));
    }
  };

  const copyManagedDirectorMcp = async () => {
    const targetUrl = managedDirector?.mcpUrl || "";
    if (!targetUrl) {
      setLaunchMessage("The Studio-managed Director MCP endpoint is not available yet.");
      return;
    }
    try {
      await copyText(targetUrl);
      setLaunchMessage("Copied the Studio-managed Director MCP endpoint.");
    } catch (error: any) {
      setLaunchMessage(String(error?.message ?? error ?? "Failed to copy the managed Director MCP endpoint."));
    }
  };

  const panelDefinitions = React.useMemo(
    () => [
      {
        id: "bridge" as const,
        label: "Studio bridge",
        description:
          "Project targeting, current handoff target, and navigation back into the main Studio flow.",
      },
      {
        id: "launch" as const,
        label: "Director access",
        description:
          "Managed service status plus optional handoff into the ChatGPT-hosted EDMG Director app.",
      },
      {
        id: "plannerWorkbench" as const,
        label: "Planner workbench",
        description:
          "Embedded planning workflow for analysis, prompts, and Studio planner sync.",
      },
      {
        id: "reactiveWorkbench" as const,
        label: "Reactive workbench",
        description:
          "Embedded scheduling workflow for motion curves, cue events, and Studio reactive sync.",
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
  } = useStudioPageLayout<DirectorLabPanelId>(
    "director_lab",
    panelDefinitions.map((panel) => panel.id),
  );

  const panelDefinitionById = React.useMemo(
    () =>
      Object.fromEntries(
        panelDefinitions.map((definition) => [definition.id, definition]),
      ) as Record<DirectorLabPanelId, (typeof panelDefinitions)[number]>,
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

  const panelContent: Record<DirectorLabPanelId, React.ReactNode> = {
    bridge: (
      <div className="card studio-workbenchBridge">
        <div>
          <div className="timeline-kicker">Studio Workbench</div>
          <h2>EDMG Director bridge</h2>
          <div className="small studio-workbenchCopy">
            EDMG Director combines planning and reactive handoff in one Studio-native page. Use this
            when you want one place to shape the plan, motion curves, and renderer sync for the same
            project session.
          </div>
        </div>
        <div className="studio-workbenchProjectRow">
          <label className="studio-workbenchField">
            <span>Studio project</span>
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {!projects.length && <option value="">No projects yet</option>}
              {projects.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="studio-workbenchMeta">
            <span>Renderer target</span>
            <strong>{project?.name || "Select a project"}</strong>
          </div>
          <div className="studio-workbenchMeta">
            <span>Working variant</span>
            <strong>Variant {selectedVariant + 1}</strong>
          </div>
        </div>
        <div className="row studio-workbenchActions">
          <button onClick={() => onNavigate?.("workspace")}>Workspace</button>
          <button className="secondary" onClick={() => onNavigate?.("timeline")}>
            Timeline
          </button>
          <button className="secondary" onClick={() => onNavigate?.("render")}>
            Render
          </button>
          <button className="secondary" onClick={() => onNavigate?.("plannerLab")} disabled={!projectId}>
            Planner Lab
          </button>
          <button className="secondary" onClick={() => onNavigate?.("reactiveLab")} disabled={!projectId}>
            Reactive Lab
          </button>
        </div>
      </div>
    ),
    launch: (
      <div className="card studio-workbenchLaunch">
        <div>
          <div className="timeline-kicker">Studio + ChatGPT Handoff</div>
          <h2>Managed and external EDMG Director access</h2>
          <div className="small studio-workbenchCopy">
            Studio can now run the EDMG Director MCP app alongside the desktop app. Use the managed
            service details below for local connector setup, or keep a public URL here when you want
            to hand off into an externally exposed ChatGPT app flow.
          </div>
        </div>
        <div className="studio-workbenchMetaGrid">
          <div className="studio-workbenchMeta">
            <span>Managed service</span>
            <strong>
              {!managedDirector && directorStatusLoading
                ? "Loading..."
                : managedDirector?.available
                ? "Running"
                : managedDirector?.managed
                  ? "Starting / unavailable"
                  : "Disabled"}
            </strong>
          </div>
          <div className="studio-workbenchMeta">
            <span>Local service URL</span>
            <strong>{managedDirector?.serviceUrl || "Not available"}</strong>
          </div>
          <div className="studio-workbenchMeta">
            <span>Local MCP endpoint</span>
            <strong>{managedDirector?.mcpUrl || "Not available"}</strong>
          </div>
          <div className="studio-workbenchMeta">
            <span>Advertised base URL</span>
            <strong>{managedDirector?.advertisedBaseUrl || "Not available"}</strong>
          </div>
          <div className="studio-workbenchMeta">
            <span>Connected backend</span>
            <strong>{managedDirector?.backendUrl || "Not available"}</strong>
          </div>
          <div className="studio-workbenchMeta">
            <span>Runtime</span>
            <strong>
              {managedDirector
                ? managedDirector.packaged
                  ? "Packaged Studio"
                  : "Dev workspace"
                : "Not available"}
              {managedDirector?.pid ? ` · PID ${managedDirector.pid}` : ""}
            </strong>
          </div>
        </div>
        <div className="row studio-workbenchActions">
          <button onClick={() => void refreshManagedDirectorStatus()} disabled={directorStatusLoading}>
            {directorStatusLoading ? "Refreshing..." : "Refresh managed service"}
          </button>
          <button className="secondary" onClick={() => void openManagedDirectorStatus()} disabled={!managedDirector?.serviceUrl}>
            Open service status
          </button>
          <button className="secondary" onClick={() => void copyManagedDirectorMcp()} disabled={!managedDirector?.mcpUrl}>
            Copy local MCP endpoint
          </button>
        </div>
        <div className="small studio-workbenchStatus">
          {managedDirector?.lastError ||
            "The managed Director service runs the ChatGPT app server next to Studio. Its browser root is a status page; the actual widget still renders inside ChatGPT after connector/tool use."}
        </div>
        <div className="studio-workbenchProjectRow">
          <label className="studio-workbenchField studio-workbenchField--wide">
            <span>External public URL</span>
            <input
              type="text"
              value={directorUrl}
              onChange={(event) => updateDirectorUrl(event.target.value)}
              placeholder="https://your-public-director-host-or-chatgpt-thread"
            />
          </label>
          <div className="studio-workbenchMeta">
            <span>Derived external MCP endpoint</span>
            <strong>{derivedMcpEndpoint || "Provide a URL above"}</strong>
          </div>
        </div>
        <div className="row studio-workbenchActions">
          <button onClick={() => void openDirectorUrl()}>Open external EDMG Director</button>
          <button className="secondary" onClick={() => void copyMcpEndpoint()}>
            Copy external MCP endpoint
          </button>
        </div>
        <div className="small studio-workbenchStatus">
          {launchMessage ||
            "Studio-native controls below do not depend on ChatGPT. The external URL is only needed when you want a tunneled/public ChatGPT connector flow."}
        </div>
      </div>
    ),
    plannerWorkbench: (
      <AiNlpWorkbench
        studioProjectId={projectId}
        studioProjectName={project?.name || ""}
        studioProject={project}
        studioSelectedVariant={selectedVariant}
        onSyncToStudio={syncPlannerLab}
      />
    ),
    reactiveWorkbench: (
      <AudioReactiveWorkbench
        studioProjectId={projectId}
        studioProjectName={project?.name || ""}
        studioProject={project}
        studioSelectedVariant={selectedVariant}
        onSyncToStudio={syncReactiveLab}
      />
    ),
  };

  return (
    <div>
      <h1>EDMG Director</h1>
      <div className="small" style={{ marginTop: 6 }}>
        Reorder or hide the bridge, launcher, planner, and reactive sections for your preferred
        directing flow. This only changes the local Labs layout and does not alter project sync,
        canonical plans, reactive apply behavior, Timeline, Render, or Outputs.
      </div>
      <StudioLayoutCustomizer
        title="EDMG Director layout"
        description="Combine planning, reactive scheduling, and optional external ChatGPT launch in one Studio-native directing surface."
        items={panelControlItems}
        profileOptions={profileOptions}
        activeProfile={activeProfile}
        onSelectProfile={setActiveProfile}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      <div className="studio-workbenchHost">
        {visibleOrder.map((panelId) => (
          <React.Fragment key={panelId}>{panelContent[panelId]}</React.Fragment>
        ))}
      </div>
    </div>
  );
}
