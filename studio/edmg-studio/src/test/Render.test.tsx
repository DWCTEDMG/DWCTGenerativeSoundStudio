import React from "react";
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Render from "../pages/Render";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Render page", () => {
  it("renders and navigates to Outputs from the top action bar", async () => {
    const onNavigate = vi.fn();
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Demo Project" }] },
      "/v1/comfyui/capabilities": { ok: true },
      "/v1/hardware": { ok: true, device: "cpu" },
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
            assets: { overlays: [], masks: [] },
          },
        },
      },
      "/v1/projects/p1/pipeline/validate*": { ok: true, valid: true },
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

    renderWithStudio(<Render onNavigate={onNavigate} />);

    expect(await screen.findByRole("heading", { name: "Render" })).toBeTruthy();
    expect(await screen.findByText("Creative direction")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Open Outputs" }));
    expect(onNavigate).toHaveBeenCalledWith("outputs");
  }, 10000);
});
