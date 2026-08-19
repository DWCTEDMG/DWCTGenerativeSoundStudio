import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  createDefaultRenderOrchestratorIntent,
  GENUINE_RENDER_ENGINES,
  RenderOrchestratorIntentControls,
  type RenderOrchestratorIntentValue,
} from "../components/RenderOrchestratorIntentControls";

function renderControlled(onChange = vi.fn()) {
  let current = createDefaultRenderOrchestratorIntent();

  function Harness() {
    const [value, setValue] = useState(current);
    const handleChange = (next: RenderOrchestratorIntentValue) => {
      current = next;
      onChange(next);
      setValue(next);
    };
    return <RenderOrchestratorIntentControls value={value} onChange={handleChange} />;
  }

  render(<Harness />);
  return { onChange, getCurrent: () => current };
}

describe("RenderOrchestratorIntentControls", () => {
  it("exposes every project-wide intent field and only genuine render engines", () => {
    const { getCurrent } = renderControlled();

    fireEvent.change(screen.getByLabelText("Storyboard variant"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Planning preset"), { target: { value: "ultra" } });
    fireEvent.change(screen.getByLabelText("Frame shape"), { target: { value: "9:16" } });
    fireEvent.change(screen.getByLabelText("Deliverable"), { target: { value: "scene_batch" } });
    fireEvent.change(screen.getByLabelText("Quality tier"), { target: { value: "quality" } });
    fireEvent.change(screen.getByLabelText("Continuity priority"), { target: { value: "0.9" } });
    fireEvent.change(screen.getByLabelText("Speed priority"), { target: { value: "0.25" } });
    fireEvent.change(screen.getByLabelText("Style lock strength"), { target: { value: "0.95" } });

    fireEvent.click(screen.getByText(/Engine routing and fallback/));
    fireEvent.click(screen.getByLabelText("Allow Hosted video"));
    fireEvent.click(screen.getByLabelText("Allow Deforum export"));
    fireEvent.change(screen.getByLabelText("Fallback policy"), { target: { value: "manual" } });

    expect(getCurrent()).toMatchObject({
      variant_index: 2,
      preset: "ultra",
      aspect_ratio: "9:16",
      output_mode: "scene_batch",
      quality_tier: "quality",
      continuity_priority: 0.9,
      speed_priority: 0.25,
      style_lock_strength: 0.95,
      fallback_policy: "manual",
    });
    expect(getCurrent().allowed_engines).toEqual([
      "internal",
      "comfyui_still",
      "comfyui_motion",
      "tensorrt_standalone",
    ]);
    expect(GENUINE_RENDER_ENGINES).toEqual([
      "internal",
      "comfyui_still",
      "comfyui_motion",
      "hosted_video",
      "deforum_export",
      "tensorrt_standalone",
    ]);
    expect(screen.queryByRole("checkbox", { name: /proxy/i })).toBeNull();
  });

  it("adds and edits complete section overrides without changing the global intent", () => {
    const { getCurrent } = renderControlled();

    fireEvent.click(screen.getByText(/Section overrides/));
    fireEvent.click(screen.getByRole("button", { name: "Add section override" }));
    fireEvent.change(screen.getByLabelText("Section 1 scene ID"), { target: { value: "chorus-1" } });
    fireEvent.change(screen.getByLabelText("Section 1 start time"), { target: { value: "42.5" } });
    fireEvent.change(screen.getByLabelText("Section 1 end time"), { target: { value: "71.25" } });
    fireEvent.change(screen.getByLabelText("Section 1 creative goal"), { target: { value: "Explosive performance close-up" } });
    fireEvent.change(screen.getByLabelText("Section 1 continuity override"), { target: { value: "0.6" } });
    fireEvent.change(screen.getByLabelText("Section 1 speed override"), { target: { value: "0.2" } });
    fireEvent.change(screen.getByLabelText("Section 1 notes"), { target: { value: "Keep the jacket color\nCut on the snare" } });

    expect(getCurrent().sections).toEqual([{
      scene_id: "chorus-1",
      start_s: 42.5,
      end_s: 71.25,
      creative_goal: "Explosive performance close-up",
      continuity_priority: 0.6,
      speed_priority: 0.2,
      notes: ["Keep the jacket color", "Cut on the snare"],
    }]);
    expect(getCurrent().continuity_priority).toBe(0.75);
    expect(getCurrent().speed_priority).toBe(0.4);

    fireEvent.click(screen.getByRole("button", { name: "Remove section override" }));
    expect(getCurrent().sections).toEqual([]);
  });

  it("keeps at least one genuine engine selected", () => {
    const initial = createDefaultRenderOrchestratorIntent();
    initial.allowed_engines = ["internal"];
    const onChange = vi.fn();
    render(<RenderOrchestratorIntentControls value={initial} onChange={onChange} />);

    fireEvent.click(screen.getByText(/Engine routing and fallback/));
    const lastEngine = screen.getByLabelText("Allow Studio internal") as HTMLInputElement;
    expect(lastEngine.checked).toBe(true);
    expect(lastEngine.disabled).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });
});
