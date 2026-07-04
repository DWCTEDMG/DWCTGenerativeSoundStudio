import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Render from "../pages/Render";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

const installRenderMocks = () => {
  installEdmgBridge();
  return installFetchMock({
    "/v1/projects": { projects: [{ id: "p1", name: "Demo Project" }] },
    "/v1/comfyui/capabilities": { ok: true },
    "/v1/hardware": { ok: true, device: "cpu" },
    "/v1/models/catalog": {
      catalog: [
        {
          id: "hf_sdxl_base_1_0",
          name: "Stable Diffusion XL Base 1.0",
          kind: "checkpoint",
          engine: "comfyui",
          family: "sdxl",
          supports_txt2img: true,
          supports_img2img: true,
          supports_inpaint: true,
          supports_outpaint: true,
          supports_controlnet: true,
          render: {
            checkpoint_name: "sdxl_base_1.0.safetensors",
            render_modes: ["stills"],
            engine: "comfyui",
            family: "sdxl",
          },
        },
        {
          id: "hf_sdxl_controlnet_canny",
          name: "SDXL Canny ControlNet",
          kind: "controlnet",
          engine: "comfyui",
          family: "sdxl",
          render: {
            controlnet_name: "controlnet-canny-sdxl.safetensors",
            conditioning_mode: "edge",
            engine: "comfyui",
            family: "sdxl",
          },
        },
        {
          id: "hf_svd_xt_1_1",
          name: "Stable Video Diffusion XT 1.1",
          kind: "motion_module",
          render: { svd_checkpoint: "svd_xt_1_1.safetensors", render_modes: ["motion_svd"] },
        },
        {
          id: "hf_sdxl_internal",
          name: "Stable Diffusion XL (Internal / Diffusers)",
          kind: "diffusers",
          engine: "internal",
          family: "sdxl",
          supports_txt2img: true,
          supports_img2img: true,
          supports_inpaint: true,
          supports_outpaint: true,
          supports_controlnet: true,
          render: { render_modes: ["stills"], engine: "internal", family: "sdxl" },
        },
        {
          id: "hf_sd35_medium_internal",
          name: "Stable Diffusion 3.5 Medium (Internal / Diffusers)",
          kind: "diffusers",
          engine: "internal",
          family: "sd35",
          supports_txt2img: true,
          supports_img2img: true,
          supports_inpaint: true,
          supports_outpaint: true,
          supports_controlnet: false,
          render: { render_modes: ["stills"], engine: "internal", family: "sd35" },
        },
        {
          id: "local_sd15_tensorrt_bundle",
          name: "Local SD1.5 TensorRT Bundle",
          kind: "runtime_bundle",
          engine: "tensorrt_standalone",
          family: "sd15",
          render: {
            render_modes: ["stills"],
            engine: "tensorrt_standalone",
            family: "sd15",
            profile_width: 512,
            profile_height: 512,
            max_batch: 1,
          },
        },
        {
          id: "hf_svd_xt_1_1_tensorrt_bundle",
          name: "SVD XT 1.1 TensorRT Bundle",
          kind: "runtime_bundle",
          engine: "tensorrt_standalone",
          family: "svd",
          render: {
            render_modes: ["internal_video"],
            engine: "tensorrt_standalone",
            family: "svd",
          },
        },
      ],
      user: [
        {
          id: "local_lora_neon",
          name: "Neon Accent LoRA",
          kind: "lora",
          source: "local",
          filename: "neon-accent.safetensors",
        },
      ],
      packs: [],
      accepted: {},
      installed: {
        local_lora_neon: true,
        hf_sdxl_internal: true,
        hf_sd35_medium_internal: true,
        local_sd15_tensorrt_bundle: true,
        hf_svd_xt_1_1_tensorrt_bundle: true,
      },
    },
    "/v1/projects/p1": {
      project: {
        id: "p1",
        name: "Demo Project",
        meta: {
          analysis: {
            features: { duration_s: 32, bpm: 120, energy: 0.58, bass_energy: 0.47, brightness: 0.36 },
            transcript: { text: "The track opens wide, then the chorus pushes into a brighter skyline." },
          },
          last_plan: {
            variants: [{ name: "Variant 1", scenes: [{ start_s: 0, end_s: 8, prompt: "scene" }] }],
          },
          timeline: { layers: [], camera: { keyframes: [] } },
          assets: { overlays: [], masks: ["mask-a.png"] },
        },
      },
      visual_dna: {
        project_id: "p1",
        identity: {
          core_themes: ["future nostalgia"],
          motifs: ["neon skyline", "lead silhouette"],
        },
      },
      visual_dna_hints: {
        core_themes: ["future nostalgia"],
        motifs: ["neon skyline", "lead silhouette"],
        confidence: 0.72,
      },
    },
    "/v1/projects/p1/assets": {
      assets: {
        refs: [{ path: "assets/refs/source.png" }, { path: "assets/refs/depth.png" }],
      },
    },
    "/v1/projects/p1/pipeline/validate*": { ok: true, valid: true },
    "POST /v1/projects/p1/render/conductor/plan": {
      ok: true,
      plan: {
        summary: "Recommended engine mix: internal x1.",
        sections: [{ scene_id: "scene-1", engine: "internal" }],
      },
      environment: {
        diagnostics: ["test-environment"],
      },
      visual_dna_hints: {
        core_themes: ["future nostalgia"],
        motifs: ["neon skyline", "lead silhouette"],
        confidence: 0.72,
      },
    },
    "/v1/projects/p1/creative_direction*": {
      creative_direction: {
        preset: "cinematic",
        sensitivity: 1,
        metrics: { energy: 0.58, bass: 0.47, mid: 0.44, treble: 0.36, duration_s: 32, source: "analysis" },
        waveform: [0.15, 0.32, 0.48, 0.4],
        motifs: ["skyline", "chorus"],
        transcript_text: "The track opens wide, then the chorus pushes into a brighter skyline.",
        transcript_summary: "The track opens wide, then the chorus pushes into a brighter skyline.",
        status: "Creative direction is being derived on the backend from the saved project analysis and plan.",
        export_text: "1. Variant 1 (0.00s - 8.00s)\nscene",
        scenes: [
          {
            index: 0,
            name: "Scene 1",
            start_s: 0,
            end_s: 8,
            duration_s: 8,
            energy: 0.58,
            energy_label: "steady",
            prompt: "scene",
            transcript_cue: "The track opens wide, then the chorus pushes into a brighter skyline.",
            camera_hint: "Measured dolly or orbit, restrained motion blur, and stable framing for continuity.",
            motion_hint: "Zoom 1.10, cfg 7.6, strength 0.65, Z travel -14.0.",
            prompt_pack: "scene",
          },
        ],
      },
    },
    "POST /v1/projects/p1/render/internal/preflight": { ok: true, mode: "proxy" },
    "/v1/projects/p1/jobs": { jobs: [] },
  });
};

describe("Render page", () => {
  it("renders and navigates to Outputs from the top action bar", async () => {
    const onNavigate = vi.fn();
    installRenderMocks();

    renderWithStudio(<Render onNavigate={onNavigate} />);

    expect(await screen.findByRole("heading", { name: "Render" })).toBeTruthy();
    expect(await screen.findByText("Creative direction")).toBeTruthy();
    expect(await screen.findByText("Generation settings")).toBeTruthy();
    expect((await screen.findAllByRole("option", { name: /Internal/ })).length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByRole("button", { name: "Add LoRA" }));
    expect((await screen.findAllByText("Neon Accent LoRA")).length).toBeGreaterThan(1);
    fireEvent.click(await screen.findByRole("button", { name: "Open Outputs" }));
    expect(onNavigate).toHaveBeenCalledWith("outputs");
  }, 10000);

  it("switches still workflows and edits controlnet units", async () => {
    installRenderMocks();

    renderWithStudio(<Render />);

    const workflowSelect = await screen.findByDisplayValue("Text-to-image");
    fireEvent.change(workflowSelect, { target: { value: "outpaint" } });
    expect(await screen.findByText("Expand top")).toBeTruthy();
    expect(await screen.findByText("Optional mask override")).toBeTruthy();
    expect(await screen.findByText("Use source as stage background")).toBeTruthy();
    expect(await screen.findByText("Enhancement passes")).toBeTruthy();

    fireEvent.change(screen.getByDisplayValue("Outpaint"), { target: { value: "controlnet" } });
    const addUnitButton = await screen.findByRole("button", { name: "Add ControlNet unit" });
    fireEvent.click(addUnitButton);

    expect(await screen.findByText("Unit 1")).toBeTruthy();
    expect(await screen.findByRole("option", { name: /SDXL Canny ControlNet/ })).toBeTruthy();
    expect(await screen.findByText("assets/refs/source.png")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Duplicate" })).toBeTruthy();
  }, 10000);

  it("defaults internal video temporal mode to frame img2img motion", async () => {
    installRenderMocks();

    renderWithStudio(<Render />);

    expect(await screen.findByDisplayValue("Internal motion (frame img2img)")).toBeTruthy();
  }, 10000);

  it("sends video-model motion score and anchor controls in the internal renderer payload", async () => {
    const fetchMock = installRenderMocks();

    renderWithStudio(<Render />);

    const temporalOption = await screen.findByRole("option", { name: "Internal video model (SVD / AnimateDiff)" });
    const temporalSelect = temporalOption.closest("select");
    expect(temporalSelect).toBeTruthy();
    fireEvent.change(temporalSelect!, { target: { value: "video_model" } });

    expect(await screen.findByText("Motion score")).toBeTruthy();
    fireEvent.change(await screen.findByDisplayValue("Start anchor"), { target: { value: "loop" } });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) => {
          if (!String(url).includes("/v1/projects/p1/render/internal/preflight")) return false;
          const body = String(init?.body || "");
          return body.includes('"temporal_mode":"video_model"')
            && body.includes('"video_model_motion_score_mode":"auto"')
            && body.includes('"video_model_manual_motion_score":4')
            && body.includes('"video_model_anchor_mode":"loop"')
            && body.includes('"video_model_scene_motion":"subject"')
            && body.includes('"video_model_prompt_refine":true');
        }),
      ).toBe(true);
    });
  }, 10000);

  it("sends storyboard full motion strategy with generated-anchor video mode", async () => {
    const fetchMock = installRenderMocks();

    renderWithStudio(<Render />);

    const strategyOption = await screen.findByRole("option", { name: "Storyboard full motion" });
    const strategySelect = strategyOption.closest("select");
    expect(strategySelect).toBeTruthy();
    fireEvent.change(strategySelect!, { target: { value: "storyboard_full_motion" } });

    expect(await screen.findByText(/generate scene keyframe anchors/i)).toBeTruthy();
    expect(await screen.findByDisplayValue("Internal video model (SVD / AnimateDiff)")).toBeTruthy();

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) => {
          if (!String(url).includes("/v1/projects/p1/render/internal/preflight")) return false;
          const body = String(init?.body || "");
          return body.includes('"motion_strategy":"storyboard_full_motion"')
            && body.includes('"storyboard_shot_max_s":4')
            && body.includes('"temporal_mode":"video_model"')
            && body.includes('"video_model_motion_score_mode":"auto"')
            && body.includes('"video_model_scene_motion":"scene"')
            && body.includes('"video_model_prompt_refine":true');
        }),
      ).toBe(true);
    });
  }, 10000);

  it("sends TensorRT SD1.5 as the video-model storyboard anchor renderer", async () => {
    const fetchMock = installRenderMocks();

    renderWithStudio(<Render />);

    const temporalOption = await screen.findByRole("option", { name: "Internal video model (SVD / AnimateDiff)" });
    const temporalSelect = temporalOption.closest("select");
    expect(temporalSelect).toBeTruthy();
    fireEvent.change(temporalSelect!, { target: { value: "video_model" } });

    expect(await screen.findByText("Storyboard anchors")).toBeTruthy();
    fireEvent.change(await screen.findByDisplayValue("Internal diffusion keyframes"), { target: { value: "tensorrt_sd15" } });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) => {
          if (!String(url).includes("/v1/projects/p1/render/internal/preflight")) return false;
          const body = String(init?.body || "");
          return body.includes('"temporal_mode":"video_model"')
            && body.includes('"video_model_keyframe_renderer":"tensorrt_sd15"')
            && body.includes('"video_model_keyframe_model_id":"local_sd15_tensorrt_bundle"');
        }),
      ).toBe(true);
    });
  }, 10000);

  it("sends TensorRT video mode through the internal renderer payload", async () => {
    const fetchMock = installRenderMocks();

    renderWithStudio(<Render />);

    const tensorRtOption = await screen.findByRole("option", { name: "TensorRT SD1.5 keyframes" });
    const renderModeSelect = tensorRtOption.closest("select");
    expect(renderModeSelect).toBeTruthy();

    fireEvent.change(renderModeSelect!, { target: { value: "tensorrt" } });

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) => {
          if (!String(url).includes("/v1/projects/p1/render/internal/preflight")) return false;
          const body = String(init?.body || "");
          return body.includes('"render_mode":"tensorrt"')
            && body.includes('"model_id":"local_sd15_tensorrt_bundle"')
            && body.includes('"device_preference":"cuda"')
            && body.includes('"temporal_mode":"keyframes"')
            && body.includes('"resume_existing_frames":false');
        }),
      ).toBe(true);
    });
  }, 10000);

  it("hides unsupported TensorRT runtime bundles from internal video model selection", async () => {
    installRenderMocks();

    renderWithStudio(<Render />);

    expect(await screen.findByRole("option", { name: "TensorRT SD1.5 keyframes" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Local SD1.5 TensorRT Bundle" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "SVD XT 1.1 TensorRT Bundle" })).toBeNull();
  }, 10000);

  it("disables controlnet workflows for internal sd3.5 still models", async () => {
    installRenderMocks();

    renderWithStudio(<Render />);

    const stillModelSelect = await screen.findByDisplayValue(/Stable Diffusion XL Base 1\.0/);
    fireEvent.change(stillModelSelect, { target: { value: "hf_sd35_medium_internal" } });

    expect(await screen.findByText(/internal diffusers adapter/i)).toBeTruthy();
    expect(screen.queryByRole("option", { name: "ControlNet" })).toBeNull();
    expect(await screen.findByText(/ComfyUI workflow export is disabled/)).toBeTruthy();
  }, 10000);
});
