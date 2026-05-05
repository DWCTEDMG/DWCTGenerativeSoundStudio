import type { StudioForgeBridge } from "./types";

export const STUDIO_FORGE_BRIDGES: StudioForgeBridge[] = [
  {
    id: "unreal-shot-metadata-export",
    name: "Unreal Shot Metadata Export",
    kind: "metadataExport",
    description:
      "Preview a non-destructive export that packages scene timing, prompt context, continuity notes, and shot metadata for Unreal ingest tooling.",
    transports: ["fileExport"],
    outputs: [
      "Scene + shot manifest JSON",
      "Prompt and continuity packet",
      "Sequencer-friendly timing markers",
    ],
    limitations:
      "Preview only. Studio Forge does not write Unreal project files or require an Unreal plugin in this phase.",
    requiredCapabilities: ["backend"],
    optionalCapabilities: ["edmgCore"],
    destructive: false,
    status: "preview",
  },
  {
    id: "unreal-render-handoff",
    name: "Unreal Render Handoff",
    kind: "renderHandoff",
    description:
      "Preview an external render target where Studio stays the planner and assembly owner while Unreal becomes an optional execution endpoint.",
    transports: ["fileExport", "http"],
    outputs: [
      "Render intent manifest",
      "Audio stem and marker map",
      "Assembly contract for the return path",
    ],
    limitations:
      "Preview only. No Unreal render job is launched from Studio Forge, and the internal renderer remains the default runtime.",
    requiredCapabilities: ["backend", "ffmpeg"],
    optionalCapabilities: ["internalRenderer", "edmgCore"],
    destructive: false,
    status: "preview",
  },
  {
    id: "unreal-live-control-bridge",
    name: "Unreal Live Control Bridge",
    kind: "controlBridge",
    description:
      "Preview section-aware control outputs that could drive Unreal scenes over OSC, WebSocket, or Remote Control without making Unreal part of Studio startup.",
    transports: ["websocket", "osc", "remoteControl"],
    outputs: [
      "Section and cue events",
      "Beat, onset, and envelope streams",
      "Camera and lighting control hints",
    ],
    limitations:
      "Preview only. Studio Forge does not open live control sockets or bind directly to Unreal in the current phase.",
    requiredCapabilities: ["backend"],
    optionalCapabilities: ["ollama", "ffmpeg"],
    destructive: false,
    status: "preview",
  },
];
