import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../components/api";
import { StudioLayoutCustomizer } from "../components/StudioLayoutCustomizer";
import { StructuredSummary } from "../components/StructuredSummary";
import { useStudioPageLayout } from "../components/studioLayout";
import { useStudioWorkbenchProject } from "../workbenches/useStudioWorkbenchProject";
import { STUDIO_FORGE_BRIDGES } from "../studio-forge/bridges";
import {
  buildStudioForgeRecommendations,
  type StudioForgeRecommendation,
  type StudioForgeRecommendationStatus,
} from "../studio-forge/recommendations";
import { STUDIO_FORGE_RECIPES } from "../studio-forge/recipes";
import {
  deriveStudioForgeProject,
  deriveStudioForgeRuntime,
  evaluateStudioForgeRecipeStages,
  STUDIO_FORGE_CAPABILITY_LABELS,
  STUDIO_FORGE_PREREQUISITE_LABELS,
  type StudioForgeRecipeStageState,
  type StudioForgeStatusCard,
  type StudioForgeStatusLevel,
} from "../studio-forge/runtimeStatus";
import { STUDIO_FORGE_TEMPLATES } from "../studio-forge/templates";
import type {
  StudioForgeBridge,
  StudioForgeBridgeTransport,
  StudioForgeCapability,
  StudioForgeDestination,
  StudioForgePrerequisite,
  StudioForgeRecipe,
  StudioForgeTemplate,
} from "../studio-forge/types";
import type { PageProps } from "../types/pageProps";

type BadgeStatus = StudioForgeStatusLevel | "supported" | "preview";
type StudioForgeSectionId =
  | "runtime"
  | "project"
  | "recommendations"
  | "templates"
  | "recipes"
  | "bridges"
  | "validation";

type RuntimeProbeKey =
  | "health"
  | "systemReadiness"
  | "setupStatus"
  | "backendConfig"
  | "aiStatus"
  | "renderProviders"
  | "comfyCapabilities"
  | "modelCatalog"
  | "modelTasks";

type ProjectProbeKey = "project" | "outputs" | "jobs" | "unrealPreview" | "livePublishStatus";

const RUNTIME_PROBES: Array<{ key: RuntimeProbeKey; path: string; timeoutMs: number }> = [
  { key: "health", path: "/health", timeoutMs: 8_000 },
  { key: "systemReadiness", path: "/v1/system/readiness", timeoutMs: 20_000 },
  { key: "setupStatus", path: "/v1/setup/status", timeoutMs: 30_000 },
  { key: "backendConfig", path: "/v1/config", timeoutMs: 10_000 },
  { key: "aiStatus", path: "/v1/ai/status", timeoutMs: 12_000 },
  { key: "renderProviders", path: "/v1/settings/render_providers", timeoutMs: 15_000 },
  { key: "comfyCapabilities", path: "/v1/comfyui/capabilities", timeoutMs: 10_000 },
  { key: "modelCatalog", path: "/v1/models/catalog", timeoutMs: 30_000 },
  { key: "modelTasks", path: "/v1/models/tasks", timeoutMs: 10_000 },
];

const VALIDATION_COMMANDS = [
  "pnpm run typecheck",
  "pnpm run lint",
  "pnpm run test:ui",
  "pnpm run build",
  "pnpm run validate:desktop",
  "pnpm run dist:win",
  "pnpm run dist:linux",
];

const BRIDGE_TRANSPORT_LABELS: Record<StudioForgeBridgeTransport, string> = {
  fileExport: "File export",
  http: "HTTP",
  websocket: "WebSocket",
  osc: "OSC",
  remoteControl: "Remote Control",
};

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error ?? "Unknown error");
}

function statusStyle(status: BadgeStatus): React.CSSProperties {
  if (status === "supported") {
    return { background: "#15352e", border: "1px solid #286a5a", color: "#b9ffe7" };
  }
  if (status === "preview") {
    return { background: "#24163a", border: "1px solid #47305f", color: "#dcc2ff" };
  }
  if (status === "ready") {
    return { background: "#163a1f", border: "1px solid #245b32", color: "#b7ffcb" };
  }
  if (status === "running") {
    return { background: "#16283a", border: "1px solid #2c5c82", color: "#b7dcff" };
  }
  if (status === "blocked") {
    return { background: "#3a1616", border: "1px solid #5b2424", color: "#ffb7b7" };
  }
  if (status === "degraded") {
    return { background: "#3a3116", border: "1px solid #5b4d24", color: "#ffe6a0" };
  }
  return { background: "#232530", border: "1px solid #363a4a", color: "#d2d7ea" };
}

function statusLabel(status: BadgeStatus): string {
  if (status === "supported") return "Supported path";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function StatusBadge({ status, label }: { status: BadgeStatus; label?: string }) {
  return (
    <span
      style={{
        ...statusStyle(status),
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 800,
        letterSpacing: 0.3,
        padding: "4px 10px",
        whiteSpace: "nowrap",
      }}
    >
      {label ?? statusLabel(status)}
    </span>
  );
}

function CapabilityList({
  label,
  capabilities,
}: {
  label: string;
  capabilities: StudioForgeCapability[];
}) {
  return (
    <div className="small" style={{ display: "grid", gap: 4 }}>
      <div style={{ fontWeight: 800 }}>{label}</div>
      <div>{capabilities.map((capability) => STUDIO_FORGE_CAPABILITY_LABELS[capability]).join(", ")}</div>
    </div>
  );
}

function PrerequisiteList({
  label,
  prerequisites,
}: {
  label: string;
  prerequisites: StudioForgePrerequisite[];
}) {
  return (
    <div className="small" style={{ display: "grid", gap: 4 }}>
      <div style={{ fontWeight: 800 }}>{label}</div>
      <div>{prerequisites.map((item) => STUDIO_FORGE_PREREQUISITE_LABELS[item]).join(", ")}</div>
    </div>
  );
}

function RuntimeCard({ card }: { card: StudioForgeStatusCard }) {
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div className="timeline-kicker">{card.role}</div>
          <div style={{ fontWeight: 900 }}>{card.label}</div>
        </div>
        <StatusBadge status={card.status} />
      </div>
      <div className="small" style={{ marginTop: 10 }}>{card.detail}</div>
      <div className="small" style={{ marginTop: 10, opacity: 0.84 }}>{card.impact}</div>
    </div>
  );
}

function TemplateCard({
  template,
  onNavigate,
}: {
  template: StudioForgeTemplate;
  onNavigate?: (destination: StudioForgeDestination) => void;
}) {
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div className="timeline-kicker">Studio Surface</div>
          <div style={{ fontWeight: 900 }}>{template.name}</div>
        </div>
        <StatusBadge status={template.status} />
      </div>
      <div className="small" style={{ marginTop: 8 }}>{template.description}</div>
      <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
        <div className="small">Kind: <b>{template.kind}</b></div>
        <CapabilityList label="Required capabilities" capabilities={template.requiredCapabilities} />
        {template.requiredPrerequisites?.length ? (
          <PrerequisiteList label="Project requirements" prerequisites={template.requiredPrerequisites} />
        ) : null}
        {template.optionalCapabilities?.length ? (
          <CapabilityList label="Optional boosts" capabilities={template.optionalCapabilities} />
        ) : null}
        <button className="secondary" onClick={() => onNavigate?.(template.action.destination)}>
          {template.action.label}
        </button>
      </div>
    </div>
  );
}

function stageStatus(stageState: StudioForgeRecipeStageState): StudioForgeStatusLevel {
  if (stageState.state === "complete") return "ready";
  if (stageState.state === "current") return "degraded";
  return "blocked";
}

function RecipeDetail({
  recipe,
  capabilities,
  prerequisites,
  onNavigate,
}: {
  recipe: StudioForgeRecipe;
  capabilities: StudioForgeCapability[];
  prerequisites: StudioForgePrerequisite[];
  onNavigate?: (destination: StudioForgeDestination) => void;
}) {
  const stages = evaluateStudioForgeRecipeStages(recipe, capabilities, prerequisites);
  const current = stages.find((stage) => stage.state === "current");
  const allComplete = stages.every((stage) => stage.state === "complete");
  const action = current?.stage
    ? { label: `Continue: ${current.stage.label}`, destination: current.stage.destination }
    : recipe.action;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div className="timeline-kicker">Guided Workflow</div>
          <div style={{ fontWeight: 900, fontSize: 18 }}>{recipe.name}</div>
        </div>
        <StatusBadge status={allComplete ? "ready" : recipe.status} label={allComplete ? "Complete" : undefined} />
      </div>
      <div className="small" style={{ marginTop: 8 }}>{recipe.description}</div>
      <ol style={{ display: "grid", gap: 10, margin: "16px 0 0", paddingLeft: 22 }}>
        {stages.map((stageState) => (
          <li key={stageState.stage.id} style={{ paddingLeft: 4 }}>
            <div style={{ display: "flex", gap: 10, justifyContent: "space-between", alignItems: "center" }}>
              <b>{stageState.stage.label}</b>
              <StatusBadge
                status={stageStatus(stageState)}
                label={stageState.state === "complete" ? "Complete" : stageState.state === "current" ? "Next" : "Waiting"}
              />
            </div>
            <div className="small" style={{ marginTop: 4 }}>{stageState.stage.description}</div>
            {stageState.state !== "complete" && stageState.missingCapabilities.length ? (
              <div className="small" style={{ marginTop: 4 }}>
                Needs capability: {stageState.missingCapabilities.map((item) => STUDIO_FORGE_CAPABILITY_LABELS[item]).join(" or ")}
              </div>
            ) : null}
            {stageState.state !== "complete" && stageState.missingPrerequisites.length ? (
              <div className="small" style={{ marginTop: 4 }}>
                Needs project state: {stageState.missingPrerequisites.map((item) => STUDIO_FORGE_PREREQUISITE_LABELS[item]).join(", ")}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      <button style={{ marginTop: 16 }} onClick={() => onNavigate?.(action.destination)}>
        {allComplete ? recipe.action.label : action.label}
      </button>
    </div>
  );
}

function recommendationBadgeStatus(
  status: StudioForgeRecommendationStatus,
): { badge: BadgeStatus; label: string } {
  if (status === "ready") return { badge: "ready", label: "Ready now" };
  if (status === "optionalBoost") return { badge: "degraded", label: "Optional boosts" };
  return { badge: "blocked", label: "Setup needed" };
}

function RecommendationCard({
  recommendation,
  onNavigate,
}: {
  recommendation: StudioForgeRecommendation;
  onNavigate?: (destination: StudioForgeDestination) => void;
}) {
  const badge = recommendationBadgeStatus(recommendation.status);
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div className="timeline-kicker">{recommendation.kindLabel}</div>
          <div style={{ fontWeight: 900 }}>{recommendation.name}</div>
        </div>
        <StatusBadge status={badge.badge} label={badge.label} />
      </div>
      <div className="small" style={{ marginTop: 8 }}>{recommendation.description}</div>
      <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
        {recommendation.missingRequired.length ? (
          <CapabilityList label="Missing required capabilities" capabilities={recommendation.missingRequired} />
        ) : null}
        {recommendation.missingPrerequisites.length ? (
          <PrerequisiteList label="Missing project requirements" prerequisites={recommendation.missingPrerequisites} />
        ) : null}
        {recommendation.missingOptional.length ? (
          <CapabilityList label="Optional boosts not detected" capabilities={recommendation.missingOptional} />
        ) : null}
        {!recommendation.missingRequired.length && !recommendation.missingPrerequisites.length ? (
          <div className="small">All required runtime and project conditions are currently present.</div>
        ) : null}
        <button className="secondary" onClick={() => onNavigate?.(recommendation.action.destination)}>
          {recommendation.action.label}
        </button>
      </div>
    </div>
  );
}

function BridgeCard({
  bridge,
  previewPayload,
  hasProject,
  hasPlan,
  hasAnalysis,
  onNavigate,
}: {
  bridge: StudioForgeBridge;
  previewPayload?: Record<string, unknown> | null;
  hasProject: boolean;
  hasPlan: boolean;
  hasAnalysis: boolean;
  onNavigate?: (destination: StudioForgeDestination) => void;
}) {
  const payload = previewPayload ?? bridge.previewPayload;
  const requiresPlan = bridge.requiredPrerequisites?.includes("plan");
  const requiresAnalysis = bridge.requiredPrerequisites?.includes("analysis");
  const prepareFirst = !hasProject || (requiresPlan && !hasPlan) || (requiresAnalysis && !hasAnalysis);
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div>
          <div className="timeline-kicker">Unreal / World Handoff</div>
          <div style={{ fontWeight: 900 }}>{bridge.name}</div>
        </div>
        <StatusBadge status={bridge.status} />
      </div>
      <div className="small" style={{ marginTop: 8 }}>{bridge.description}</div>
      <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
        <div className="small">
          Transport: <b>{bridge.transports.map((transport) => BRIDGE_TRANSPORT_LABELS[transport]).join(" • ")}</b>
        </div>
        <div className="small">Outputs: <b>{bridge.outputs.join(", ")}</b></div>
        <div>
          <div className="small" style={{ fontWeight: 800, marginBottom: 8 }}>Preview details</div>
          <StructuredSummary value={payload} showJson maxItems={12} />
        </div>
        <div className="small">{bridge.limitations}</div>
        <button
          className="secondary"
          onClick={() => onNavigate?.(prepareFirst ? "workspace" : bridge.action.destination)}
        >
          {prepareFirst ? "Prepare project in Workspace" : bridge.action.label}
        </button>
      </div>
    </div>
  );
}

export default function StudioForge({ backendUrl, config, onNavigate }: PageProps) {
  const {
    projects,
    projectId,
    setProjectId,
    selectedVariant,
    setSelectedVariant,
    project: workbenchProject,
  } = useStudioWorkbenchProject();
  const [runtimePayloads, setRuntimePayloads] = useState<Partial<Record<RuntimeProbeKey, unknown>>>({});
  const [runtimeErrors, setRuntimeErrors] = useState<Partial<Record<RuntimeProbeKey, string>>>({});
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [projectPayloads, setProjectPayloads] = useState<Partial<Record<ProjectProbeKey, unknown>>>({});
  const [projectErrors, setProjectErrors] = useState<Partial<Record<ProjectProbeKey, string>>>({});
  const [projectLoading, setProjectLoading] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [selectedRecipeId, setSelectedRecipeId] = useState(STUDIO_FORGE_RECIPES[0]?.id ?? "");

  useEffect(() => {
    if (!backendUrl) {
      setRuntimeLoading(false);
      setRuntimeErrors({ health: "No Studio backend URL is configured." });
      return;
    }
    const controller = new AbortController();
    let alive = true;
    setRuntimeLoading(true);

    void Promise.all(
      RUNTIME_PROBES.map(async (probe) => {
        try {
          const value = await apiGet(probe.path, { signal: controller.signal, timeoutMs: probe.timeoutMs });
          return { key: probe.key, value, error: "" };
        } catch (error) {
          return { key: probe.key, value: undefined, error: errorMessage(error) };
        }
      }),
    ).then((results) => {
      if (!alive) return;
      const values: Partial<Record<RuntimeProbeKey, unknown>> = {};
      const errors: Partial<Record<RuntimeProbeKey, string>> = {};
      for (const result of results) {
        if (result.value !== undefined) values[result.key] = result.value;
        if (result.error) errors[result.key] = result.error;
      }
      setRuntimePayloads(values);
      setRuntimeErrors(errors);
      setRuntimeLoading(false);
    });

    return () => {
      alive = false;
      controller.abort();
    };
  }, [backendUrl, refreshVersion]);

  useEffect(() => {
    if (!backendUrl || !projectId) {
      setProjectPayloads({});
      setProjectErrors({});
      setProjectLoading(false);
      return;
    }
    const controller = new AbortController();
    let alive = true;
    setProjectLoading(true);

    const probes: Array<{ key: ProjectProbeKey; path: string; timeoutMs: number; select?: (value: unknown) => unknown }> = [
      { key: "project", path: `/v1/projects/${projectId}`, timeoutMs: 15_000, select: (value) => objectValue(value).project },
      { key: "outputs", path: `/v1/projects/${projectId}/outputs`, timeoutMs: 20_000 },
      { key: "jobs", path: `/v1/projects/${projectId}/jobs`, timeoutMs: 12_000 },
      {
        key: "unrealPreview",
        path: `/v1/projects/${projectId}/unreal/preview?variant_index=${selectedVariant}`,
        timeoutMs: 15_000,
        select: (value) => objectValue(value).preview,
      },
      { key: "livePublishStatus", path: `/v1/projects/${projectId}/live_cues/publish/status`, timeoutMs: 10_000 },
    ];

    void Promise.all(
      probes.map(async (probe) => {
        try {
          const response = await apiGet(probe.path, { signal: controller.signal, timeoutMs: probe.timeoutMs });
          return { key: probe.key, value: probe.select ? probe.select(response) : response, error: "" };
        } catch (error) {
          return { key: probe.key, value: undefined, error: errorMessage(error) };
        }
      }),
    ).then((results) => {
      if (!alive) return;
      const values: Partial<Record<ProjectProbeKey, unknown>> = {};
      const errors: Partial<Record<ProjectProbeKey, string>> = {};
      for (const result of results) {
        if (result.value !== undefined) values[result.key] = result.value;
        if (result.error) errors[result.key] = result.error;
      }
      setProjectPayloads(values);
      setProjectErrors(errors);
      setProjectLoading(false);
    });

    return () => {
      alive = false;
      controller.abort();
    };
  }, [backendUrl, projectId, refreshVersion, selectedVariant]);

  const runtime = useMemo(
    () => deriveStudioForgeRuntime({
      ...runtimePayloads,
      backendConfig: runtimePayloads.backendConfig ?? config,
    }),
    [config, runtimePayloads],
  );
  const projectReadiness = useMemo(
    () => deriveStudioForgeProject({
      projectId,
      project: projectPayloads.project ?? workbenchProject,
      selectedVariant,
      outputs: projectPayloads.outputs,
      jobs: projectPayloads.jobs,
      unrealPreview: projectPayloads.unrealPreview,
      livePublishStatus: projectPayloads.livePublishStatus,
    }),
    [projectId, projectPayloads, selectedVariant, workbenchProject],
  );

  useEffect(() => {
    if (projectReadiness.variantCount > 0 && !projectReadiness.selectedVariantValid) {
      setSelectedVariant(0);
    }
  }, [projectReadiness.selectedVariantValid, projectReadiness.variantCount, setSelectedVariant]);

  useEffect(() => {
    if (!runtime.activeTaskCount && !projectReadiness.projectActiveTaskCount) return;
    const timeout = window.setTimeout(() => setRefreshVersion((value) => value + 1), 4_000);
    return () => window.clearTimeout(timeout);
  }, [projectReadiness.projectActiveTaskCount, refreshVersion, runtime.activeTaskCount]);

  const recommendations = useMemo(
    () => buildStudioForgeRecommendations({
      bridges: STUDIO_FORGE_BRIDGES,
      templates: STUDIO_FORGE_TEMPLATES,
      recipes: STUDIO_FORGE_RECIPES,
      availableCapabilities: runtime.capabilities,
      availablePrerequisites: projectReadiness.prerequisites,
    }),
    [projectReadiness.prerequisites, runtime.capabilities],
  );
  const selectedRecipe = STUDIO_FORGE_RECIPES.find((recipe) => recipe.id === selectedRecipeId)
    ?? STUDIO_FORGE_RECIPES[0];
  const unrealPreview = objectValue(projectPayloads.unrealPreview);
  const liveBridgePreviewById = useMemo<Record<string, Record<string, unknown>>>(() => ({
    "unreal-shot-metadata-export": objectValue(unrealPreview.shot_metadata_export),
    "unreal-render-handoff": objectValue(unrealPreview.render_handoff),
    "unreal-live-control-bridge": objectValue(unrealPreview.live_control_bridge),
  }), [unrealPreview]);

  const runtimeErrorEntries = Object.entries(runtimeErrors).filter(([, message]) => Boolean(message));
  const projectErrorEntries = Object.entries(projectErrors).filter(([, message]) => Boolean(message));
  const refresh = () => setRefreshVersion((value) => value + 1);
  const navigate = (destination: StudioForgeDestination) => onNavigate?.(destination);

  const sectionDefinitions = useMemo(
    () => [
      { id: "runtime" as const, label: "Runtime Status", description: "Live backend, storage, accelerator, model, provider, and task readiness." },
      { id: "project" as const, label: "Project Readiness", description: "Active project, plan variant, output, Unreal, and live-publisher state." },
      { id: "recipes" as const, label: "Guided Recipes", description: "Selectable workflows that route each next step into canonical Studio pages." },
      { id: "recommendations" as const, label: "Recommendations", description: "Capability and project-aware guidance for the current machine and session." },
      { id: "templates" as const, label: "Studio Surfaces", description: "Safe launch points for existing Studio tools and operational pages." },
      { id: "bridges" as const, label: "Unreal and World Handoffs", description: "Project-backed previews and safe routes into Outputs and Review." },
      { id: "validation" as const, label: "Developer Validation", description: "Documented release commands; Forge never executes shell commands." },
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
  } = useStudioPageLayout<StudioForgeSectionId>(
    "studio_forge",
    sectionDefinitions.map((section) => section.id),
  );
  const sectionDefinitionById = useMemo(
    () => Object.fromEntries(
      sectionDefinitions.map((definition) => [definition.id, definition]),
    ) as Record<StudioForgeSectionId, (typeof sectionDefinitions)[number]>,
    [sectionDefinitions],
  );
  const sectionControlItems = layoutState.order.map((sectionId, index) => ({
    id: sectionId,
    label: sectionDefinitionById[sectionId].label,
    description: sectionDefinitionById[sectionId].description,
    hidden: layoutState.hidden.includes(sectionId),
    canMoveUp: index > 0,
    canMoveDown: index < layoutState.order.length - 1,
  }));

  const sectionContent: Record<StudioForgeSectionId, React.ReactNode> = {
    runtime: (
      <section aria-labelledby="forge-runtime-heading">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 10 }}>
          <div>
            <h2 id="forge-runtime-heading" style={{ marginBottom: 4 }}>Runtime Status</h2>
            <div className="small">Canonical readiness, provider, model catalog, storage, CUDA, and task APIs.</div>
          </div>
          <StatusBadge status={runtimeLoading ? "running" : runtime.overall} label={runtimeLoading ? "Checking" : undefined} />
        </div>
        {runtimeLoading ? <div className="small" role="status" aria-live="polite">Checking Studio runtime readiness…</div> : null}
        {runtimeErrorEntries.length ? (
          <div className="card" role="status" aria-live="polite" style={{ marginBottom: 12 }}>
            <b>Probe notes</b>
            <div className="small" style={{ marginTop: 6 }}>
              {runtimeErrorEntries.map(([key, message]) => <div key={key}>{key}: {message}</div>)}
            </div>
          </div>
        ) : null}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 12 }}>
          {runtime.cards.map((card) => <RuntimeCard key={card.id} card={card} />)}
        </div>
      </section>
    ),
    project: (
      <section aria-labelledby="forge-project-heading">
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div>
              <div className="timeline-kicker">Canonical Studio Session</div>
              <h2 id="forge-project-heading" style={{ margin: "4px 0 0" }}>Project Readiness</h2>
            </div>
            <StatusBadge
              status={projectLoading ? "running" : projectReadiness.hasProject ? (projectReadiness.selectedVariantValid ? "ready" : "degraded") : "blocked"}
              label={projectLoading ? "Refreshing" : undefined}
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginTop: 14 }}>
            <label className="small">
              Active project
              <select
                aria-label="Forge project"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                style={{ width: "100%", marginTop: 6 }}
              >
                {!projects.length ? <option value="">No projects available</option> : null}
                {projects.map((project: Record<string, unknown>) => (
                  <option key={String(project.id)} value={String(project.id)}>
                    {String(project.name || project.id)}
                  </option>
                ))}
              </select>
            </label>
            <label className="small">
              Plan variant
              <select
                aria-label="Forge plan variant"
                value={projectReadiness.selectedVariantValid ? selectedVariant : 0}
                onChange={(event) => setSelectedVariant(Number(event.target.value) || 0)}
                disabled={!projectReadiness.variantCount}
                style={{ width: "100%", marginTop: 6 }}
              >
                {projectReadiness.variantCount
                  ? Array.from({ length: projectReadiness.variantCount }, (_, index) => (
                    <option key={index} value={index}>Variant {index + 1}</option>
                  ))
                  : <option value={0}>No plan variants</option>}
              </select>
            </label>
          </div>
          <div className="small" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
            <StatusBadge status={projectReadiness.hasAudio ? "ready" : "blocked"} label={projectReadiness.hasAudio ? "Audio ready" : "Audio missing"} />
            <StatusBadge status={projectReadiness.hasAnalysis ? "ready" : "blocked"} label={projectReadiness.hasAnalysis ? "Analysis ready" : "Analysis missing"} />
            <StatusBadge status={projectReadiness.selectedVariantValid ? "ready" : "blocked"} label={projectReadiness.selectedVariantValid ? `${projectReadiness.variantCount} plan variant${projectReadiness.variantCount === 1 ? "" : "s"}` : "Plan missing"} />
            <StatusBadge status={projectReadiness.hasRenderOutput ? "ready" : "degraded"} label={`${projectReadiness.outputCount} registered output${projectReadiness.outputCount === 1 ? "" : "s"}`} />
            <StatusBadge status={projectReadiness.livePublisherRunning ? "running" : "unknown"} label={projectReadiness.livePublisherRunning ? "Live publisher running" : "Live publisher stopped"} />
          </div>
          <div className="small" style={{ marginTop: 12 }}>
            Unreal: <b>{projectReadiness.unrealPreviewReady ? "live preview ready" : "preview unavailable"}</b>
            {" • "}{projectReadiness.unrealBundleCount} bundle{projectReadiness.unrealBundleCount === 1 ? "" : "s"}
            {" • "}{projectReadiness.unrealReturnCount} returned-media record{projectReadiness.unrealReturnCount === 1 ? "" : "s"}
            {" • "}{projectReadiness.deforumExportCount} Deforum export{projectReadiness.deforumExportCount === 1 ? "" : "s"}
          </div>
          {projectErrorEntries.length ? (
            <div className="small" role="status" aria-live="polite" style={{ marginTop: 10 }}>
              {projectErrorEntries.map(([key, message]) => <div key={key}>{key}: {message}</div>)}
            </div>
          ) : null}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
            <button onClick={refresh}>Refresh readiness</button>
            <button className="secondary" onClick={() => navigate("workspace")}>Open Workspace</button>
            <button className="secondary" onClick={() => navigate("render")} disabled={!projectReadiness.selectedVariantValid}>Open Render</button>
            <button className="secondary" onClick={() => navigate("outputs")} disabled={!projectReadiness.hasProject}>Open Outputs</button>
            <button className="secondary" onClick={() => navigate("review")} disabled={!projectReadiness.hasProject}>Open Review / Live</button>
          </div>
        </div>
      </section>
    ),
    recipes: (
      <section aria-labelledby="forge-recipes-heading">
        <h2 id="forge-recipes-heading" style={{ marginBottom: 6 }}>Guided Recipes</h2>
        <div className="small" style={{ marginBottom: 10 }}>
          Forge evaluates saved project state and routes the next step to the page that owns it. It does not silently launch renders or installs.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 0.65fr) minmax(320px, 1.35fr)", gap: 12 }}>
          <div className="card" role="list" aria-label="Studio Forge recipes">
            {STUDIO_FORGE_RECIPES.map((recipe) => (
              <button
                key={recipe.id}
                className={recipe.id === selectedRecipe?.id ? "" : "secondary"}
                onClick={() => setSelectedRecipeId(recipe.id)}
                aria-pressed={recipe.id === selectedRecipe?.id}
                style={{ width: "100%", marginBottom: 8, textAlign: "left" }}
              >
                {recipe.name}
              </button>
            ))}
          </div>
          {selectedRecipe ? (
            <RecipeDetail
              recipe={selectedRecipe}
              capabilities={runtime.capabilities}
              prerequisites={projectReadiness.prerequisites}
              onNavigate={navigate}
            />
          ) : null}
        </div>
      </section>
    ),
    recommendations: (
      <section aria-labelledby="forge-recommendations-heading">
        <h2 id="forge-recommendations-heading" style={{ marginBottom: 6 }}>Runtime and Project Recommendations</h2>
        <div className="small" style={{ marginBottom: 10 }}>
          “Ready now” requires both the runtime capabilities and active-project prerequisites declared by the workflow.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))", gap: 12 }}>
          {recommendations.map((recommendation) => (
            <RecommendationCard key={`${recommendation.source}:${recommendation.id}`} recommendation={recommendation} onNavigate={navigate} />
          ))}
        </div>
      </section>
    ),
    templates: (
      <section aria-labelledby="forge-surfaces-heading">
        <h2 id="forge-surfaces-heading" style={{ marginBottom: 6 }}>Studio Surfaces</h2>
        <div className="small" style={{ marginBottom: 10 }}>
          Supported launch points into existing Studio pages. These cards do not create code or bypass page ownership.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))", gap: 12 }}>
          {STUDIO_FORGE_TEMPLATES.map((template) => (
            <TemplateCard key={template.id} template={template} onNavigate={navigate} />
          ))}
        </div>
      </section>
    ),
    bridges: (
      <section aria-labelledby="forge-bridges-heading">
        <h2 id="forge-bridges-heading" style={{ marginBottom: 6 }}>Unreal and World Handoffs</h2>
        <div className="small" style={{ marginBottom: 10 }}>
          Forge previews active project contracts. Outputs owns Unreal bundle export/import, and Review owns existing OSC, MIDI, and WebSocket publishers.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
          {STUDIO_FORGE_BRIDGES.map((bridge) => (
            <BridgeCard
              key={bridge.id}
              bridge={bridge}
              previewPayload={Object.keys(liveBridgePreviewById[bridge.id] ?? {}).length ? liveBridgePreviewById[bridge.id] : null}
              hasProject={projectReadiness.hasProject}
              hasPlan={projectReadiness.selectedVariantValid}
              hasAnalysis={projectReadiness.hasAnalysis}
              onNavigate={navigate}
            />
          ))}
        </div>
      </section>
    ),
    validation: (
      <section className="card" aria-labelledby="forge-validation-heading">
        <h2 id="forge-validation-heading" style={{ marginBottom: 10 }}>Developer Validation</h2>
        <div className="small" style={{ marginBottom: 10 }}>
          Documentation only. Studio Forge never executes shell commands, installers, model downloads, or render jobs.
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {VALIDATION_COMMANDS.map((command) => <div key={command} className="small"><code>{command}</code></div>)}
        </div>
      </section>
    ),
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <div className="timeline-kicker">Studio-side 1.0</div>
            <h1>Studio Forge</h1>
          </div>
          <StatusBadge status={runtimeLoading ? "running" : runtime.overall} />
        </div>
        <div className="small" style={{ marginTop: 8, maxWidth: 920 }}>
          A supported, non-destructive workbench for runtime truth, project readiness, guided recipes, and external handoffs. Canonical Studio pages still own setup, models, project edits, renders, live publishing, and outputs. Packaged Unreal plugins, Unreal Editor automation, and Movie Render Queue execution remain outside Studio-side Forge 1.0.
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <button onClick={refresh}>Refresh all</button>
          <button className="secondary" onClick={() => navigate("workspace")}>Workspace</button>
          <button className="secondary" onClick={() => navigate("setup")}>Setup</button>
          <button className="secondary" onClick={() => navigate("models")}>Models</button>
          <button className="secondary" onClick={() => navigate("render")}>Render</button>
          <button className="secondary" onClick={() => navigate("review")}>Review / Live</button>
          <button className="secondary" onClick={() => navigate("outputs")}>Outputs</button>
        </div>
      </div>

      <StudioLayoutCustomizer
        title="Studio Forge layout"
        description="Reorder or hide Forge panels for this local UI profile. Project and runtime data are not changed."
        items={sectionControlItems}
        profileOptions={profileOptions}
        activeProfile={activeProfile}
        onSelectProfile={setActiveProfile}
        onMove={movePanel}
        onToggleHidden={updateHidden}
        onReset={resetLayout}
      />
      {visibleOrder.map((sectionId) => (
        <React.Fragment key={sectionId}>{sectionContent[sectionId]}</React.Fragment>
      ))}
    </div>
  );
}
