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
    previewPayload: {
      engine: "unreal",
      handoff_kind: "shot_metadata_export",
      sequence_name: "EDMG_MainSequence",
      project_fields: ["project_id", "project_name", "fps", "audio_path"],
      shot_fields: ["shot_id", "scene_id", "start_frame", "end_frame", "prompt", "continuity_tags"],
      marker_fields: ["label", "frame", "time_seconds"],
    },
    limitations:
      "Studio builds the supported handoff in Outputs. Forge remains a non-destructive preview and routing surface; it does not write Unreal project files.",
    requiredCapabilities: ["backend"],
    optionalCapabilities: ["edmgCore"],
    requiredPrerequisites: ["project", "plan"],
    action: { label: "Export in Outputs", destination: "outputs" },
    destructive: false,
    status: "supported",
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
    previewPayload: {
      engine: "unreal",
      handoff_kind: "render_handoff",
      execution_owner: "external_runtime",
      return_owner: "studio",
      expected_inputs: ["shot_manifest.json", "audio_markers.json", "style_packet.json"],
      expected_outputs: ["shot_render.mov", "alpha_pass.mov", "metadata.json"],
      assembly_mode: "ffmpeg_back_in_studio",
    },
    limitations:
      "Outputs owns export, import-plan, and returned-media actions. Studio Forge never launches an Unreal render job, and the internal renderer remains the default runtime.",
    requiredCapabilities: ["backend", "ffmpeg"],
    optionalCapabilities: ["internalRenderer", "edmgCore"],
    requiredPrerequisites: ["project", "plan"],
    action: { label: "Open Unreal handoff", destination: "outputs" },
    destructive: false,
    status: "supported",
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
    previewPayload: {
      engine: "unreal",
      handoff_kind: "live_control_bridge",
      transports: {
        osc: ["/edmg/section", "/edmg/beat", "/edmg/camera"],
        websocket: ["section_change", "beat_pulse", "lighting_envelope"],
        remote_control: ["sequence.PlayRate", "camera.FocalLength", "lights.Intensity"],
      },
      cadence_hz: 30,
      section_payload_fields: ["section_id", "energy", "continuity_priority"],
    },
    limitations:
      "Review owns the existing OSC, MIDI, and WebSocket publisher controls. Direct Unreal Remote Control binding and packaged Unreal integration remain outside Studio-side Forge 1.0.",
    requiredCapabilities: ["backend"],
    optionalCapabilities: ["ollama", "ffmpeg"],
    requiredPrerequisites: ["project", "analysis"],
    action: { label: "Open Live Publishers", destination: "review" },
    destructive: false,
    status: "preview",
  },
];
