import React from "react";
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Outputs from "../pages/Outputs";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Outputs page", () => {
  it("renders active internal jobs and navigates to the render queue", async () => {
    const onNavigate = vi.fn();
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Demo Project" }] },
      "/v1/projects/p1/outputs": {
        videos: [],
        images: [
          {
            path: "outputs/images/frame.png",
            metadata_path: "outputs/images/frame.png.json",
            metadata: {
              workflow_family: "outpaint",
              engine: "internal",
              model_family: "sdxl",
              prompt: "A luminous skyline with added edge detail",
              negative_prompt: "blurry",
              seed: 42,
              sampler: "euler",
              steps: 28,
              cfg: 7.5,
              source_asset: "assets/refs/source.png",
              mask_source: "generated_outpaint",
              base_model: { model_id: "hf_sdxl_internal" },
              outpaint: { top_px: 32, right_px: 64, bottom_px: 0, left_px: 16 },
              loras: [{ name: "Neon Accent", weight: 0.8 }],
              controlnet_units: [{ model: "depth", strength: 0.65 }],
              output: { image: "outputs/images/frame.png" },
            },
          },
        ],
        latest_internal_render: null,
        internal_render_history: [],
        active_internal_jobs: [
          {
            id: "job-1",
            project_id: "p1",
            status: "failed",
            type: "internal_video",
            progress: {
              stage: "rendering",
              runtime_checkpoint: {
                resume_percent: 50,
                completed_chunks: 1,
                estimated_chunks: 2,
                next_frame_index: 10,
                total_frames: 20,
                chunk_strategy: "windowed",
                checkpoint_interval_frames: 12,
                can_resume: true,
                outputs: { checkpoint_json: "data/checkpoint.json" },
              },
            },
          },
        ],
      },
    });

    renderWithStudio(<Outputs backendUrl="http://127.0.0.1:7863" config={null} onNavigate={onNavigate} />);

    expect(await screen.findByRole("heading", { name: "Outputs" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Open Render Queue" }));
    expect(onNavigate).toHaveBeenCalledWith("queue");
    expect(await screen.findByText(/Generation metadata/)).toBeTruthy();
    expect((await screen.findAllByText(/A luminous skyline with added edge detail/)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/Outpaint margins/i)).toBeTruthy();
  }, 15000);
});
