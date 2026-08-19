import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LayeredAnimationControls } from "../components/LayeredAnimationControls";

function renderControls(onQueue = vi.fn()) {
  render(
    <LayeredAnimationControls
      sourceOptions={[{ path: "assets/refs/cover.png" }]}
      maskOptions={["assets/masks/subject.png"]}
      modelOptions={[
        { id: "hf_sdxl_internal", name: "SDXL Internal", installed: true },
        { id: "missing_model", name: "Missing model", installed: false },
      ]}
      busy={false}
      disabled={false}
      onQueue={onQueue}
      onOpenModels={vi.fn()}
    />,
  );
  return onQueue;
}

describe("LayeredAnimationControls", () => {
  it("surfaces and submits the complete masked animation contract", () => {
    const onQueue = renderControls();

    fireEvent.change(screen.getByLabelText("Source image"), { target: { value: "assets/refs/cover.png" } });
    fireEvent.change(screen.getByLabelText("Layering mode"), { target: { value: "masked" } });
    fireEvent.change(screen.getByLabelText("Depth bands"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Subject motion"), { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText("Background motion"), { target: { value: "0.2" } });
    fireEvent.change(screen.getByLabelText("Frame rate"), { target: { value: "30" } });
    fireEvent.click(screen.getByLabelText(/assets\/masks\/subject\.png/));
    fireEvent.change(screen.getByLabelText("Regional prompt"), { target: { value: "performer jacket moving" } });
    fireEvent.change(screen.getByLabelText("Depth"), { target: { value: "0.75" } });
    fireEvent.change(screen.getByLabelText("Motion scale"), { target: { value: "1.8" } });
    fireEvent.change(screen.getByLabelText("Strength"), { target: { value: "1.2" } });

    fireEvent.click(screen.getByLabelText(/Refine every composited frame/));
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "hf_sdxl_internal" } });
    fireEvent.change(screen.getByLabelText("Device"), { target: { value: "cuda" } });
    fireEvent.change(screen.getByLabelText("Denoise"), { target: { value: "0.35" } });
    fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "28" } });
    fireEvent.change(screen.getByLabelText("CFG"), { target: { value: "7.5" } });
    fireEvent.change(screen.getByLabelText("Seed"), { target: { value: "1234" } });
    fireEvent.change(screen.getByLabelText("Refinement prompt"), { target: { value: "cinematic cloth detail" } });

    fireEvent.click(screen.getByRole("button", { name: /Queue still-image animation/i }));

    expect(onQueue).toHaveBeenCalledWith(expect.objectContaining({
      source_asset: "assets/refs/cover.png",
      mode: "masked",
      bands: 5,
      subject_motion: 1.5,
      background_motion: 0.2,
      fps: 30,
      diffusion_refine: true,
      model_id: "hf_sdxl_internal",
      device_preference: "cuda",
      refine_denoise: 0.35,
      refine_steps: 28,
      refine_cfg: 7.5,
      seed: 1234,
      refine_prompt: "cinematic cloth detail",
      masks: [{
        mask_asset: "assets/masks/subject.png",
        prompt: "performer jacket moving",
        depth: 0.75,
        motion_scale: 1.8,
        strength: 1.2,
      }],
    }));
  });

  it("blocks an incomplete masked request with a plain-language error", () => {
    const onQueue = renderControls();
    fireEvent.change(screen.getByLabelText("Layering mode"), { target: { value: "masked" } });
    fireEvent.click(screen.getByRole("button", { name: /Queue still-image animation/i }));

    expect(screen.getByRole("alert").textContent).toMatch(/Choose an uploaded source image/i);
    expect(onQueue).not.toHaveBeenCalled();
  });

  it("blocks odd output dimensions before queueing", () => {
    const onQueue = renderControls();
    fireEvent.change(screen.getByLabelText("Source image"), { target: { value: "assets/refs/cover.png" } });
    fireEvent.change(screen.getByLabelText("Width"), { target: { value: "769" } });
    fireEvent.click(screen.getByRole("button", { name: /Queue still-image animation/i }));

    expect(screen.getByRole("alert").textContent).toMatch(/even whole numbers/i);
    expect(onQueue).not.toHaveBeenCalled();
  });

  it("replaces a stale source when the project media options change", () => {
    const onQueue = vi.fn();
    const sharedProps = {
      maskOptions: [] as string[],
      modelOptions: [] as Array<{ id: string; name: string; installed: boolean }>,
      busy: false,
      disabled: false,
      onQueue,
      onOpenModels: vi.fn(),
    };
    const { rerender } = render(
      <LayeredAnimationControls
        {...sharedProps}
        sourceOptions={[{ path: "assets/refs/project-a.png" }]}
      />,
    );
    fireEvent.change(screen.getByLabelText("Source image"), {
      target: { value: "assets/refs/project-a.png" },
    });

    rerender(
      <LayeredAnimationControls
        {...sharedProps}
        sourceOptions={[{ path: "assets/refs/project-b.png" }]}
      />,
    );

    expect((screen.getByLabelText("Source image") as HTMLSelectElement).value)
      .toBe("assets/refs/project-b.png");
  });
});
