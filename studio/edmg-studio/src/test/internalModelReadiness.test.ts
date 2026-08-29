import { describe, expect, it } from "vitest";
import { buildInternalModelReadiness } from "../shared/internalModelReadiness";

const CATALOG = [
  { id: "hf_sd15_internal", name: "Stable Diffusion 1.5" },
  { id: "hf_sdxl_internal", name: "Stable Diffusion XL" },
  { id: "hf_flux1_schnell_internal", name: "FLUX.1 Schnell" },
  { id: "hf_animatediff_motion_adapter_v15_2_internal", name: "AnimateDiff" },
];

describe("internal model readiness", () => {
  it("reports genuinely local still and motion models separately", () => {
    const readiness = buildInternalModelReadiness({
      catalog: CATALOG,
      installed: {
        hf_sd15_internal: true,
        hf_animatediff_motion_adapter_v15_2_internal: true,
      },
    });

    expect(readiness.hasLocalStillModel).toBe(true);
    expect(readiness.hasLocalMotionModel).toBe(true);
    expect(readiness.preferredLocalKey).toBe("sd15");
    expect(readiness.status("sd15")).toBe("installed locally");
  });

  it("does not treat a cloud-only model as installed", () => {
    const readiness = buildInternalModelReadiness({
      catalog: CATALOG,
      installed: {},
      cloud: { hf_sdxl_internal: { size_bytes: 4_000_000_000 } },
      modelCache: "team/cache",
    });

    expect(readiness.hasLocalStillModel).toBe(false);
    expect(readiness.hasRestorableStillModel).toBe(true);
    expect(readiness.preferred).toBe("SDXL (restore needed)");
    expect(readiness.status("sdxl")).toContain("restore needed");
  });

  it("surfaces active progress and failed installs without claiming availability", () => {
    const readiness = buildInternalModelReadiness({
      catalog: CATALOG,
      tasks: [
        { model_id: "hf_sd15_internal", status: "running", progress: 0.42 },
        { modelId: "hf_sdxl_internal", status: "failed", error: "disk full" },
      ],
    });

    expect(readiness.state("sd15")).toBe("installing");
    expect(readiness.status("sd15")).toBe("installing 42%");
    expect(readiness.state("sdxl")).toBe("failed");
    expect(readiness.status("sdxl")).toContain("disk full");
    expect(readiness.activeTasks).toHaveLength(1);
    expect(readiness.failedTasks).toHaveLength(1);
    expect(readiness.hasLocalStillModel).toBe(false);
  });

  it("keeps the newest task when older history exists for the same model", () => {
    const readiness = buildInternalModelReadiness({
      catalog: CATALOG,
      tasks: [
        { id: "new", model_id: "hf_sd15_internal", status: "running", progress: 0.75 },
        { id: "old", model_id: "hf_sd15_internal", status: "failed", error: "old failure" },
      ],
    });

    expect(readiness.state("sd15")).toBe("installing");
    expect(readiness.status("sd15")).toBe("installing 75%");
    expect(readiness.failedTasks).toHaveLength(0);
  });

  it("requires the SD 1.5 base before an AnimateDiff adapter is motion-ready", () => {
    const adapterOnly = buildInternalModelReadiness({
      catalog: CATALOG,
      installed: { hf_animatediff_motion_adapter_v15_2_internal: true },
    });
    const compatiblePair = buildInternalModelReadiness({
      catalog: CATALOG,
      installed: {
        hf_sd15_internal: true,
        hf_animatediff_motion_adapter_v15_2_internal: true,
      },
    });

    expect(adapterOnly.hasLocalMotionModel).toBe(false);
    expect(compatiblePair.hasLocalMotionModel).toBe(true);
  });

  it("tracks FLUX as a still/keyframe model without making it a motion adapter", () => {
    const readiness = buildInternalModelReadiness({
      catalog: CATALOG,
      installed: { hf_flux1_schnell_internal: true },
    });

    expect(readiness.status("flux")).toBe("installed locally");
    expect(readiness.preferredLocalKey).toBe("flux");
    expect(readiness.hasLocalStillModel).toBe(true);
    expect(readiness.hasLocalMotionModel).toBe(false);
  });
});
