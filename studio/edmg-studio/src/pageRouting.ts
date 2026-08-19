import { isStudioForgeEnabled } from "./features";

export type Page =
  | "dashboard"
  | "projects"
  | "workspace"
  | "timeline"
  | "render"
  | "queue"
  | "review"
  | "outputs"
  | "cloud"
  | "settings"
  | "setup"
  | "models"
  | "directorLab"
  | "plannerLab"
  | "reactiveLab"
  | "studioForge";

export type StudioNavigationGroupId = "flow" | "delivery" | "labs" | "system";

export type StudioNavigationItem = {
  page: Page;
  label: string;
  hint: string;
  keywords: string[];
};

export type StudioNavigationGroup = {
  id: StudioNavigationGroupId;
  label: string;
  hint: string;
  items: StudioNavigationItem[];
};

const PAGE_LABELS: Record<Page, string> = {
  dashboard: "Dashboard",
  projects: "Projects",
  workspace: "Workspace",
  timeline: "Timeline",
  render: "Render",
  queue: "Render Queue",
  review: "Review",
  outputs: "Outputs",
  cloud: "Cloud",
  settings: "Settings",
  setup: "Setup Wizard",
  models: "Models",
  directorLab: "EDMG Director",
  plannerLab: "AI Planner Lab",
  reactiveLab: "Reactive Lab",
  studioForge: "Studio Forge",
};

const PAGE_LOADING_DETAILS: Record<Page, string> = {
  dashboard: "Refreshing status cards and studio overview context.",
  projects: "Loading project cards and recent session context.",
  workspace: "Preparing ingest, planning, and creative direction controls.",
  timeline: "Preparing transport, cue, and arrangement controls.",
  render: "Loading render presets, engines, and output actions.",
  queue: "Loading queue state, progress, and retry controls.",
  review: "Loading variant compare, continuity warnings, and review actions.",
  outputs: "Loading generated media, active jobs, and review actions.",
  cloud: "Loading remote integration settings and bundle actions.",
  settings: "Loading desktop backend, storage, and preference controls.",
  setup: "Loading runtime health, installers, and dependency checks.",
  models: "Loading model packs, availability, and install actions.",
  directorLab: "Preparing combined planning, reactive, and optional ChatGPT handoff controls.",
  plannerLab: "Preparing AI planning tools and Studio handoff controls.",
  reactiveLab: "Preparing audio-reactive scheduling and handoff controls.",
  studioForge: "Checking live Studio readiness, project state, and guided handoff routes.",
};

const PAGE_LOADERS: Partial<Record<Page, () => Promise<unknown>>> = {
  workspace: () => import("./pages/Workspace"),
  timeline: () => import("./pages/Timeline"),
  render: () => import("./pages/Render"),
  queue: () => import("./pages/RenderQueue"),
  review: () => import("./pages/Review"),
  outputs: () => import("./pages/Outputs"),
  cloud: () => import("./pages/Cloud"),
  settings: () => import("./pages/Settings"),
  models: () => import("./pages/Models"),
  directorLab: () => import("./pages/EdmgDirector"),
  plannerLab: () => import("./pages/AiPlannerLab"),
  reactiveLab: () => import("./pages/ReactiveLab"),
  studioForge: () => import("./pages/StudioForge"),
};

const PRELOAD_BY_PAGE: Record<Page, Page[]> = {
  dashboard: ["projects", "workspace", "setup"],
  projects: ["workspace", "dashboard"],
  workspace: ["timeline", "render", "directorLab", "plannerLab", "reactiveLab"],
  timeline: ["render", "outputs", "workspace"],
  render: ["queue", "review", "outputs", "timeline"],
  queue: ["review", "outputs", "render"],
  review: ["render", "outputs", "queue"],
  outputs: ["review", "render", "queue"],
  cloud: ["settings", "models"],
  settings: ["setup", "cloud", "models"],
  setup: ["workspace", "models", "settings"],
  models: ["render", "setup", "workspace"],
  directorLab: ["workspace", "timeline", "render"],
  plannerLab: ["workspace", "timeline", "render"],
  reactiveLab: ["workspace", "timeline", "outputs"],
  studioForge: ["workspace", "setup", "models", "render", "review", "outputs"],
};

const BASE_PAGES: Page[] = [
  "dashboard",
  "projects",
  "workspace",
  "timeline",
  "render",
  "queue",
  "review",
  "outputs",
  "cloud",
  "settings",
  "setup",
  "models",
  "directorLab",
  "plannerLab",
  "reactiveLab",
];

export function getStudioNavigationGroups(): StudioNavigationGroup[] {
  const labs: StudioNavigationItem[] = [
    {
      page: "directorLab",
      label: "EDMG Director",
      hint: "Combined planning and reactive direction",
      keywords: ["orchestrator", "director", "plan", "reactive", "creative"],
    },
    {
      page: "plannerLab",
      label: "AI Planner Lab",
      hint: "Deep prompt and storyboard authoring",
      keywords: ["prompt", "storyboard", "plan", "scene", "ai"],
    },
    {
      page: "reactiveLab",
      label: "Reactive Lab",
      hint: "Audio-reactive schedules and cues",
      keywords: ["audio", "beat", "bpm", "cue", "schedule", "motion"],
    },
  ];
  if (isStudioForgeEnabled()) {
    labs.push({
      page: "studioForge",
      label: "Studio Forge",
      hint: "Guided AI builder and readiness preview",
      keywords: ["builder", "assistant", "forge", "readiness"],
    });
  }

  return [
    {
      id: "flow",
      label: "Create",
      hint: "Project, source, plan, and arrangement",
      items: [
        {
          page: "dashboard",
          label: "Dashboard",
          hint: "Studio status and quick access",
          keywords: ["home", "status", "overview"],
        },
        {
          page: "projects",
          label: "Projects",
          hint: "Create and choose sessions",
          keywords: ["session", "project", "new", "open"],
        },
        {
          page: "workspace",
          label: "Workspace",
          hint: "Import, analyze, plan, and hand off",
          keywords: ["upload", "audio", "analyze", "plan", "ingest"],
        },
        {
          page: "timeline",
          label: "Timeline",
          hint: "DAW-style audio, video, prompts, and motion",
          keywords: ["edit", "video", "audio", "daw", "arrange", "clips", "orchestrator"],
        },
      ],
    },
    {
      id: "delivery",
      label: "Make & Deliver",
      hint: "Render, monitor, review, and export",
      items: [
        {
          page: "render",
          label: "Render",
          hint: "Configure every renderer and launch outputs",
          keywords: ["generate", "render", "settings", "model", "quality", "fps"],
        },
        {
          page: "queue",
          label: "Render Queue",
          hint: "Progress, logs, pause, retry, and recovery",
          keywords: ["jobs", "progress", "logs", "retry", "pause"],
        },
        {
          page: "review",
          label: "Review",
          hint: "Compare, approve, and preserve continuity",
          keywords: ["compare", "approve", "variant", "continuity"],
        },
        {
          page: "outputs",
          label: "Outputs",
          hint: "Browse generated media and exports",
          keywords: ["media", "video", "image", "export", "history"],
        },
      ],
    },
    {
      id: "labs",
      label: "Creative Labs",
      hint: "Specialist planning and performance tools",
      items: labs,
    },
    {
      id: "system",
      label: "Studio System",
      hint: "Models, services, paths, and preferences",
      items: [
        {
          page: "models",
          label: "Models",
          hint: "Install, restore, and inspect model packs",
          keywords: ["download", "install", "weights", "hugging face", "s3", "cache"],
        },
        {
          page: "settings",
          label: "Settings",
          hint: "Storage, runtime, providers, and interface",
          keywords: ["preferences", "paths", "provider", "runtime", "theme"],
        },
        {
          page: "setup",
          label: "Setup",
          hint: "Dependency and service health",
          keywords: ["install", "dependency", "health", "ffmpeg", "ollama"],
        },
        {
          page: "cloud",
          label: "Cloud",
          hint: "Remote engines and integrations",
          keywords: ["remote", "cloud", "aws", "azure", "api"],
        },
      ],
    },
  ];
}

export function getAllowedPages(): Page[] {
  return isStudioForgeEnabled() ? [...BASE_PAGES, "studioForge"] : BASE_PAGES;
}

export function isPage(value: string): value is Page {
  return getAllowedPages().includes(value as Page);
}

export function getPageLoadingDetails(page: Page): { label: string; detail: string } {
  return { label: PAGE_LABELS[page], detail: PAGE_LOADING_DETAILS[page] };
}

export function getPageDocumentTitle(page: Page): string {
  return `${PAGE_LABELS[page]} | EDMG Studio`;
}

export function getPagesToPreload(page: Page): Page[] {
  return PRELOAD_BY_PAGE[page];
}

function filterPreloadCandidates(pages: Page[]): Page[] {
  return [...new Set(pages)].filter(
    (candidate) => candidate !== "studioForge" || isStudioForgeEnabled(),
  );
}

export function runBestEffortPagePreload(
  loader: (() => Promise<unknown>) | undefined,
): Promise<void> {
  if (!loader) return Promise.resolve();
  return loader().then(() => undefined).catch(() => undefined);
}

function preloadPages(pages: Page[]) {
  filterPreloadCandidates(pages).forEach((candidate) => {
    void runBestEffortPagePreload(PAGE_LOADERS[candidate]);
  });
}

export function preloadLikelyNextPages(page: Page) {
  preloadPages(getPagesToPreload(page).filter((candidate) => candidate !== page));
}

export function preloadNavigationIntent(page: Page) {
  preloadPages([page, ...getPagesToPreload(page)]);
}
