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
            analysis: { duration_s: 32, bpm: 120 },
            last_plan: {
              variants: [{ name: "Variant 1", scenes: [{ start_s: 0, end_s: 8, prompt: "scene" }] }],
            },
            timeline: { layers: [], camera: { keyframes: [] } },
            assets: { overlays: [], masks: [] },
          },
        },
      },
      "/v1/projects/p1/pipeline/validate*": { ok: true, valid: true },
      "POST /v1/projects/p1/render/internal/preflight": { ok: true, mode: "proxy" },
      "/v1/projects/p1/jobs": { jobs: [] },
    });

    renderWithStudio(<Render onNavigate={onNavigate} />);

    expect(await screen.findByRole("heading", { name: "Render" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: "Open Outputs" }));
    expect(onNavigate).toHaveBeenCalledWith("outputs");
  });
});
