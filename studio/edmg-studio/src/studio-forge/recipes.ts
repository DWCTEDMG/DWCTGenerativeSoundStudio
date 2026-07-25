import type { StudioForgeRecipe } from "./types";

export const STUDIO_FORGE_RECIPES: StudioForgeRecipe[] = [
  {
    id: "audio-analysis-plan-render-assemble",
    name: "Audio -> Analysis -> AI Plan -> Render -> Assemble",
    description: "Tracks the default Studio path from source audio to finished video assembly while preserving the internal renderer as the default engine.",
    stages: ["Audio ingest", "Analysis", "Planner pass", "Render variants", "FFmpeg assembly"],
    requiredCapabilities: ["backend", "internalRenderer", "ffmpeg"],
    optionalCapabilities: ["ollama", "edmgCore"],
    destructive: false,
    status: "preview",
  },
  {
    id: "still-image-workflow",
    name: "Still Image Workflow",
    description: "Preview a still-oriented recipe that can stay fully internal or branch to optional ComfyUI-backed workflows.",
    stages: ["Project context", "Prompt design", "Still render", "Review outputs"],
    requiredCapabilities: ["backend", "internalRenderer"],
    optionalCapabilities: ["comfyui", "ollama"],
    destructive: false,
    status: "preview",
  },
  {
    id: "motion-workflow",
    name: "Motion Workflow",
    description: "Preview the steps for scene motion rendering while keeping ComfyUI motion as an additive sidecar rather than a required dependency.",
    stages: ["Plan scenes", "Pick motion engine", "Queue clips", "Review queue", "Assemble video"],
    requiredCapabilities: ["backend", "ffmpeg"],
    optionalCapabilities: ["comfyui", "internalRenderer"],
    destructive: false,
    status: "preview",
  },
  {
    id: "deforum-export-workflow",
    name: "Deforum Export Workflow",
    description: "Preview how canonical Studio plans can end in an optional Deforum export without changing runtime defaults.",
    stages: ["Plan variants", "Creative direction", "Deforum settings preview", "Export JSON"],
    requiredCapabilities: ["backend"],
    optionalCapabilities: ["edmgCore", "ffmpeg"],
    destructive: false,
    status: "preview",
  },
];
