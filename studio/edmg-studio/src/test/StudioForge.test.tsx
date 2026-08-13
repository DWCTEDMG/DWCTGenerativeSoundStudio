import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import App from "../App";
import StudioForge from "../pages/StudioForge";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

const ORIGINAL_STUDIO_FORGE_FLAG = import.meta.env.VITE_EDMG_ENABLE_STUDIO_FORGE;
const ORIGINAL_STUDIO_FORGE_DISABLE_FLAG = import.meta.env.VITE_EDMG_DISABLE_STUDIO_FORGE;

const READY_STATUS = {
  ollama: {
    ok: false,
    model_present: false,
    model: "",
    url: "http://127.0.0.1:11434",
  },
  comfyui: {
    ok: false,
    url: "http://127.0.0.1:8188",
  },
  ffmpeg: {
    ok: true,
    path: "ffmpeg",
  },
  backend_bundle: {
    ok: true,
  },
  edmg: {
    available: true,
  },
  ai_config: {
    label: "Rule-based planner",
    provider: "rule_based",
    ollama_required: false,
    model_required: false,
  },
  tasks: [],
};

const SYSTEM_READINESS = {
  ok: true,
  ready: true,
  status: "ok",
  summary: "Ready",
  checks: {
    ffmpeg: { ok: true, status: "ok", path: "ffmpeg" },
    runtime: { ok: true, status: "ok" },
    gpu: { ok: true, status: "ok", device_name: "RTX 4050", vram_gb: 6 },
    disk: { ok: true, status: "ok" },
    writable_paths: {
      ok: true,
      status: "ok",
      paths: [
        { label: "models", path: "D:\\EDMG Studio\\models", writable: true },
        { label: "cache", path: "D:\\EDMG Studio\\cache", writable: true },
      ],
    },
    models: { ok: true, status: "ok", models_dir: "D:\\EDMG Studio\\models" },
  },
};

const PROJECT = {
  id: "p1",
  name: "Forge Demo",
  meta: {
    audio: { filename: "source.wav", path: "assets/audio/source.wav", duration_s: 8 },
    analysis: { features: { duration_s: 8, bpm: 124 } },
    last_plan: {
      variants: [{ title: "Performance Cut", scenes: [{ id: "scene-1" }] }],
    },
  },
};

const FETCH_FIXTURES = {
  "/health": { ok: true },
  "/v1/projects": {
    projects: [{ id: "p1", name: "Forge Demo" }],
  },
  "/v1/projects/p1": {
    project: PROJECT,
  },
  "/v1/projects/p1/outputs": {
    videos: [{ path: "outputs/videos/forge-demo.mp4" }],
    images: [],
    deforum_exports: [{ path: "outputs/deforum/forge-demo.json" }],
    unreal_exports: [{ path: "outputs/unreal/forge-demo.zip" }],
    unreal_returns: [{ path: "outputs/unreal/returned.mov" }],
  },
  "/v1/projects/p1/jobs": { jobs: [] },
  "/v1/projects/p1/live_cues/publish/status": {
    ok: true,
    publish: { running: true, osc: true, websocket: true, midi: false },
  },
  "/v1/projects/p1/unreal/preview?variant_index=0": {
    ok: true,
    preview: {
      project_id: "p1",
      project_name: "Forge Demo",
      variant_index: 0,
      source: "studio_project",
      diagnostics: [],
      shot_metadata_export: {
        engine: "unreal",
        handoff_kind: "shot_metadata_export",
        sequence_name: "forge_demo_MainSequence",
        fps: 24,
        duration_seconds: 8,
        audio_path: "projects/forge-demo/assets/audio/source.wav",
        project_fields: ["project_id", "project_name", "fps", "audio_path"],
        shot_fields: ["shot_id", "scene_id", "start_frame", "end_frame", "prompt", "continuity_tags"],
        marker_fields: ["label", "frame", "time_seconds"],
        shots: [{ shot_id: "shot_001_scene_1", scene_id: "scene-1", start_frame: 0, end_frame: 96, approved: true }],
        markers: [{ label: "Intro", frame: 0, time_seconds: 0 }],
      },
      render_handoff: {
        engine: "unreal",
        handoff_kind: "render_handoff",
        execution_owner: "external_runtime",
        return_owner: "studio",
        render_mode: "performance-led",
        schedule_stride: 2,
        approved_section_ids: ["scene-1"],
        expected_inputs: ["shot_manifest.json", "audio_markers.json", "style_packet.json"],
        expected_outputs: ["shot_render.mov", "alpha_pass.mov", "metadata.json"],
        assembly_mode: "ffmpeg_back_in_studio",
        sections: [{ shot_id: "shot_001_scene_1", scene_id: "scene-1", start_frame: 0, end_frame: 96, approved: true, engine_hint: "comfyui_motion" }],
      },
      live_control_bridge: {
        engine: "unreal",
        handoff_kind: "live_control_bridge",
        transports: {
          osc: ["/edmg/section", "/edmg/beat", "/edmg/camera"],
          websocket: ["section_change", "beat_pulse", "lighting_envelope"],
          remote_control: ["sequence.PlayRate", "camera.FocalLength", "lights.Intensity"],
        },
        cadence_hz: 30,
        bpm: 124,
        section_payload_fields: ["section_id", "energy", "continuity_priority"],
        section_events: [{ section_id: "scene-1", label: "Intro", time_seconds: 0, energy: 0.35, continuity_priority: 1 }],
        cue_events: [],
        beat_times: [0, 0.5, 1, 1.5],
        camera_keyframes: [{ t: 0, zoom: 1 }],
      },
    },
  },
  "/v1/config": {
    ai_mode: "local",
    ai_provider: "rule_based",
    model: "director_lite",
  },
  "/v1/system/readiness": SYSTEM_READINESS,
  "/v1/setup/status": READY_STATUS,
  "/v1/ai/status": {
    ok: true,
    ai: { ok: true, provider: "rule_based", model: "director_lite" },
  },
  "/v1/settings/render_providers": {
    ok: true,
    cuda: { available: true, enabled: true, active: true, device_name: "RTX 4050", vram_gb: 6 },
    directml: { available: false, enabled: false },
  },
  "/v1/comfyui/capabilities": {
    ok: false,
    nodes: [],
  },
  "/v1/models/catalog": {
    catalog: [
      { id: "hf_sd15_internal", name: "Stable Diffusion 1.5" },
      { id: "hf_animatediff_motion_adapter_v15_2_internal", name: "AnimateDiff" },
    ],
    installed: {
      hf_sd15_internal: true,
      hf_animatediff_motion_adapter_v15_2_internal: true,
    },
    cloud: {},
    storage_mode: "local_cache",
    model_cache: "D:\\EDMG Studio\\cache\\huggingface",
  },
  "/v1/models/tasks": { tasks: [] },
};

describe("Studio Forge", () => {
  afterEach(() => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", ORIGINAL_STUDIO_FORGE_FLAG ?? "");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", ORIGINAL_STUDIO_FORGE_DISABLE_FLAG ?? "");
    window.localStorage.clear();
    window.history.pushState({}, "", "/");
  });

  it("renders truthful runtime, project, recipe, and handoff state", async () => {
    const onNavigate = vi.fn();
    installEdmgBridge();
    installFetchMock(FETCH_FIXTURES);

    renderWithStudio(
      <StudioForge
        backendUrl="http://127.0.0.1:7863"
        config={FETCH_FIXTURES["/v1/config"]}
        onNavigate={onNavigate}
      />,
    );

    expect(await screen.findByRole("heading", { name: /Studio Forge/i })).toBeTruthy();
    expect(screen.getByText(/Studio-side 1.0/i)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Runtime Status/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Project Readiness/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Guided Recipes/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Unreal and World Handoffs/i })).toBeTruthy();
    expect(await screen.findByText(/forge_demo_MainSequence/i)).toBeTruthy();
    expect((await screen.findAllByText(/Audio ready/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Live publisher running/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Preview details/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Ready now/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/never executes shell commands, installers, model downloads, or render jobs/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Open Review / Live" }));
    expect(onNavigate).toHaveBeenCalledWith("review");
  });

  it("surfaces cloud-only models, disabled CUDA, and partial probe failures", async () => {
    installEdmgBridge();
    installFetchMock({
      ...FETCH_FIXTURES,
      "/v1/settings/render_providers": {
        ok: true,
        cuda: { available: true, enabled: false, active: false, device_name: "RTX 4050", vram_gb: 6 },
        directml: { available: false, enabled: false },
      },
      "/v1/models/catalog": {
        catalog: [{ id: "hf_sd15_internal", name: "Stable Diffusion 1.5" }],
        installed: {},
        cloud: { hf_sd15_internal: { size_bytes: 4_000_000_000 } },
        storage_mode: "cloud_only",
        model_cache: "team/cache",
      },
      "/v1/comfyui/capabilities": () => {
        throw new Error("ComfyUI offline");
      },
    });

    renderWithStudio(
      <StudioForge backendUrl="http://127.0.0.1:7863" config={FETCH_FIXTURES["/v1/config"]} />,
    );

    expect(await screen.findByText(/stored in team\/cache; restore needed/i)).toBeTruthy();
    expect((await screen.findAllByText(/Setup needed/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/CUDA is detected but disabled in Settings/i)).toBeTruthy();
    expect(screen.getByText(/A genuine local model or authenticated hosted provider is required for rendering/i)).toBeTruthy();
    expect(screen.getByText(/comfyCapabilities: ComfyUI offline/i)).toBeTruthy();
  });

  it("falls back to Dashboard only when the explicit opt-out is set", async () => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", "1");
    installEdmgBridge();
    installFetchMock(FETCH_FIXTURES);
    window.history.pushState({}, "", "/?page=studioForge");

    renderWithStudio(<App />);

    expect(await screen.findByRole("heading", { name: /Dashboard/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Studio Forge/i })).toBeNull();
  });

  it("enables direct page access and navigation by default", async () => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "");
    vi.stubEnv("VITE_EDMG_DISABLE_STUDIO_FORGE", "");
    installEdmgBridge();
    installFetchMock(FETCH_FIXTURES);
    window.history.pushState({}, "", "/?page=studioForge");

    renderWithStudio(<App />);

    expect(
      await screen.findByRole("heading", { name: /Studio Forge/i }, { timeout: 10_000 }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /Studio Forge/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /AI Planner Lab/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Reactive Lab/i })).toBeTruthy();
  });
});
