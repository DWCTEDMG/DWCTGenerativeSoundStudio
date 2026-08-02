import { describe, expect, it } from "vitest";
import {
  deriveStudioForgeProject,
  deriveStudioForgeRuntime,
  evaluateStudioForgeRecipeStages,
} from "../studio-forge/runtimeStatus";
import type { StudioForgeRecipe } from "../studio-forge/types";

function healthyReadiness(status = "ok") {
  return {
    ok: true,
    ready: status === "ok",
    status,
    summary: status === "ok" ? "Ready" : "Degraded",
    checks: {
      ffmpeg: { ok: true, status: "ok", path: "ffmpeg" },
      runtime: { ok: true, status: "ok" },
      gpu: { ok: true, status: "ok", device_name: "RTX 4050", vram_gb: 6 },
      disk: { ok: true, status: "ok" },
      writable_paths: {
        ok: true,
        status: "ok",
        paths: [{ label: "models", path: "D:\\Studio\\models", writable: true }],
      },
      models: { ok: true, status: "ok", models_dir: "D:\\Studio\\models" },
    },
  };
}

describe("Studio Forge runtime status", () => {
  it("derives ready CUDA and local-model capabilities only from live API evidence", () => {
    const runtime = deriveStudioForgeRuntime({
      health: { ok: true },
      systemReadiness: healthyReadiness(),
      setupStatus: {
        tasks: [],
        ffmpeg: { ok: true },
        ollama: { ok: false },
        ai_config: { provider: "rule_based", ollama_required: false },
        edmg: { available: true },
      },
      aiStatus: { ok: true, ai: { ok: true, provider: "rule_based", model: "director_lite" } },
      renderProviders: {
        cuda: { available: true, enabled: true, active: true, device_name: "RTX 4050", vram_gb: 6 },
        directml: { available: false },
        proxy: { active: false },
      },
      modelCatalog: {
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
        model_cache: "D:\\Studio\\cache\\huggingface",
      },
      modelTasks: { tasks: [] },
    });

    expect(runtime.overall).toBe("ready");
    expect(runtime.capabilities).toEqual(expect.arrayContaining([
      "backend",
      "systemReady",
      "ffmpeg",
      "internalRenderer",
      "internalMotion",
      "cuda",
    ]));
    expect(runtime.planningProvider).toBe("rule_based");
    expect(runtime.cards.find((card) => card.id === "models")?.status).toBe("ready");
  });

  it("keeps cloud-only models and proxy fallback visibly degraded", () => {
    const runtime = deriveStudioForgeRuntime({
      health: { ok: true },
      systemReadiness: healthyReadiness("warn"),
      setupStatus: {
        tasks: [],
        ffmpeg: { ok: true },
        ai_config: { provider: "rule_based", ollama_required: false },
      },
      aiStatus: { ok: true, ai: { ok: true, provider: "rule_based" } },
      renderProviders: {
        cuda: { available: false, enabled: true },
        directml: { available: false },
        proxy: { active: true },
      },
      modelCatalog: {
        catalog: [{ id: "hf_sd15_internal", name: "Stable Diffusion 1.5" }],
        installed: {},
        cloud: { hf_sd15_internal: { size_bytes: 4_000_000_000 } },
        storage_mode: "cloud_only",
        model_cache: "team/cache",
      },
      modelTasks: { tasks: [] },
    });

    expect(runtime.overall).toBe("degraded");
    expect(runtime.capabilities).not.toContain("internalRenderer");
    expect(runtime.capabilities).not.toContain("cuda");
    expect(runtime.cards.find((card) => card.id === "models")).toMatchObject({ status: "degraded" });
    expect(runtime.cards.find((card) => card.id === "models")?.impact).toContain("restored locally");
    expect(runtime.cards.find((card) => card.id === "render-providers")?.impact).toContain(
      "not proof that CUDA model inference works",
    );
  });

  it("does not show an overall ready state when the readiness probe is missing", () => {
    const runtime = deriveStudioForgeRuntime({
      health: { ok: true },
      setupStatus: {
        tasks: [],
        ffmpeg: { ok: true },
        ai_config: { provider: "rule_based", ollama_required: false },
      },
      aiStatus: { ok: true, ai: { ok: true, provider: "rule_based" } },
      renderProviders: {
        cuda: { available: true, enabled: true },
        proxy: { active: false },
      },
      modelCatalog: {
        catalog: [{ id: "hf_sd15_internal" }],
        installed: { hf_sd15_internal: true },
      },
      modelTasks: { tasks: [] },
    });

    expect(runtime.overall).toBe("degraded");
    expect(runtime.capabilities).not.toContain("systemReady");
    expect(runtime.cards.find((card) => card.id === "system")?.status).toBe("unknown");
  });

  it("does not claim CUDA readiness when CUDA is installed but inactive", () => {
    const runtime = deriveStudioForgeRuntime({
      health: { ok: true },
      systemReadiness: healthyReadiness(),
      setupStatus: { tasks: [], ffmpeg: { ok: true }, ai_config: { provider: "rule_based" } },
      aiStatus: { ok: true, ai: { ok: true, provider: "rule_based" } },
      renderProviders: {
        cuda: { available: true, enabled: true, active: false, device_name: "RTX 4050" },
        proxy: { active: false },
      },
      modelCatalog: {
        catalog: [{ id: "hf_sd15_internal" }],
        installed: { hf_sd15_internal: true },
      },
      modelTasks: { tasks: [] },
    });

    expect(runtime.cudaReady).toBe(false);
    expect(runtime.capabilities).not.toContain("cuda");
    expect(runtime.cards.find((card) => card.id === "accelerator")?.detail).toContain("inactive");
  });

  it("reports task state as unknown when a task probe is unavailable", () => {
    const runtime = deriveStudioForgeRuntime({
      health: { ok: true },
      systemReadiness: healthyReadiness(),
      setupStatus: { tasks: [], ffmpeg: { ok: true }, ai_config: { provider: "rule_based" } },
      aiStatus: { ok: true, ai: { ok: true, provider: "rule_based" } },
      renderProviders: { proxy: { active: true } },
      modelCatalog: { catalog: [], installed: {} },
    });

    expect(runtime.cards.find((card) => card.id === "tasks")?.status).toBe("unknown");
    expect(runtime.overall).toBe("degraded");
  });

  it("requires explicit ComfyUI motion nodes for the motion capability", () => {
    const withoutMotionNodes = deriveStudioForgeRuntime({
      comfyCapabilities: {
        animatediff: { available: false },
        svd: { available: false },
      },
    });
    const withMotionNodes = deriveStudioForgeRuntime({
      comfyCapabilities: {
        animatediff: { available: true },
        svd: { available: false },
      },
    });

    expect(withoutMotionNodes.capabilities).toContain("comfyui");
    expect(withoutMotionNodes.capabilities).not.toContain("comfyMotion");
    expect(withMotionNodes.capabilities).toContain("comfyMotion");
  });

  it("ignores resolved historical failures when newer tasks succeeded", () => {
    const runtime = deriveStudioForgeRuntime({
      setupStatus: {
        tasks: [
          { id: "setup-new", name: "runtime repair", status: "done" },
          { id: "setup-old", name: "runtime repair", status: "failed" },
        ],
      },
      modelCatalog: { catalog: [{ id: "hf_sd15_internal" }], installed: {} },
      modelTasks: {
        tasks: [
          { id: "model-new", model_id: "hf_sd15_internal", status: "done" },
          { id: "model-old", model_id: "hf_sd15_internal", status: "failed" },
        ],
      },
    });

    expect(runtime.failedTaskCount).toBe(0);
    expect(runtime.cards.find((card) => card.id === "tasks")?.status).toBe("ready");
  });
});

describe("Studio Forge project and recipe readiness", () => {
  it("derives active project, variant, output, Unreal, and publisher state", () => {
    const readiness = deriveStudioForgeProject({
      projectId: "p1",
      selectedVariant: 1,
      project: {
        id: "p1",
        name: "Forge Demo",
        meta: {
          audio: { filename: "track.wav" },
          analysis: { features: { bpm: 124 } },
          last_plan: { variants: [{ title: "A" }, { title: "B" }] },
        },
      },
      outputs: {
        videos: [{ path: "output.mp4" }],
        images: [],
        deforum_exports: [{ path: "deforum.json" }],
        unreal_exports: [{ path: "unreal.zip" }],
        unreal_returns: [{ path: "returned.mov" }],
      },
      jobs: { jobs: [{ status: "running" }] },
      unrealPreview: { shot_metadata_export: { sequence_name: "Demo_MainSequence" } },
      livePublishStatus: { publish: { running: true } },
    });

    expect(readiness.prerequisites).toEqual(expect.arrayContaining([
      "project",
      "audio",
      "analysis",
      "plan",
      "renderOutput",
      "deforumExport",
      "unrealBundle",
    ]));
    expect(readiness.variantCount).toBe(2);
    expect(readiness.selectedVariantValid).toBe(true);
    expect(readiness.livePublisherRunning).toBe(true);
    expect(readiness.projectActiveTaskCount).toBe(1);
  });

  it("keeps later guided stages waiting behind the first unmet stage", () => {
    const recipe: StudioForgeRecipe = {
      id: "sequential",
      name: "Sequential",
      description: "test",
      stages: [
        {
          id: "audio",
          label: "Add audio",
          description: "Upload audio",
          destination: "workspace",
          requiredPrerequisites: ["audio"],
        },
        {
          id: "setup",
          label: "Open setup",
          description: "No direct requirement",
          destination: "setup",
        },
      ],
      requiredCapabilities: [],
      action: { label: "Open", destination: "workspace" },
      destructive: false,
      status: "supported",
    };

    const stages = evaluateStudioForgeRecipeStages(recipe, [], ["project"]);
    expect(stages.map((stage) => stage.state)).toEqual(["current", "blocked"]);
  });
});
