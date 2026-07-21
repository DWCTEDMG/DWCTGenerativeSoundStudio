import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RenderPlanPanel } from "../components/RenderPlanPanel";

describe("RenderPlanPanel", () => {
  it("shows task graph, estimates, and cache keys", () => {
    render(
      <RenderPlanPanel
        plan={{
          plan_id: "plan-test",
          summary: "Advisory render plan for 1 scenes.",
          estimates: { seconds: 42.5, cost: 1.2, task_count: 3 },
          tasks: [
            {
              id: "scene-1-motion",
              scene_id: "scene-1",
              step_kind: "render_motion",
              adapter: "internal",
              cache_key: "rp1:demo:v0:scene-1:render_motion:abc123",
              estimated_seconds: 12,
            },
          ],
          dependencies: [{ from: "scene-1-prepare", to: "scene-1-motion" }],
          warnings: [{ code: "advisory_only", message: "Plan is advisory.", severity: "info" }],
          sections: [{ scene_id: "scene-1", engine: "internal", estimated_seconds: 12 }],
          diagnostics: ["advisory_only=true"],
        }}
        onPromoteAll={vi.fn()}
        onPromoteScene={vi.fn()}
      />,
    );

    expect(screen.getByText("Render Plan v1")).toBeTruthy();
    expect(screen.getByText(/42\.5s/)).toBeTruthy();
    expect(screen.getByText("Task graph")).toBeTruthy();
    expect(screen.getByText("scene-1-motion")).toBeTruthy();
    expect(screen.getByText(/rp1:demo:v0:scene-1:render_motion:abc123/)).toBeTruthy();
    expect(screen.getByText(/Plan is advisory/)).toBeTruthy();
  });
});
