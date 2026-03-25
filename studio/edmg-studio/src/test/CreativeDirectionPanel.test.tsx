import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CreativeDirectionPanel } from "../components/CreativeDirectionPanel";
import { UiModeProvider } from "../components/uiMode";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

function payloadFor(name: string) {
  return {
    ready: true,
    missing: [],
    preset: "cinematic",
    sensitivity: 1,
    provider_mode: "local-heuristic",
    scene_source: "plan",
    metrics: { energy: 0.58, bass: 0.47, mid: 0.44, treble: 0.36, duration_s: 32, source: "analysis" },
    waveform: [0.15, 0.32, 0.48, 0.4],
    motifs: ["skyline", "chorus"],
    transcript_text: "The track opens wide, then the chorus pushes into a brighter skyline.",
    transcript_summary: "The track opens wide, then the chorus pushes into a brighter skyline.",
    status: "Creative direction is being derived on the backend from the saved project analysis and plan.",
    export_text: `1. ${name} (0.00s - 8.00s)\nscene`,
    narrative_analysis: {
      ok: true,
      title: "Demo Project",
      provider_mode: "local-heuristic",
      scene_source: "plan",
      hooks: ["The track opens wide, then the chorus pushes into a brighter skyline."],
      motifs: ["skyline", "chorus"],
      transcript_line_count: 1,
      emotions: [{ emotion: "wonder", score: 1 }],
    },
    sections: [{ index: 0, name: "Arrival", start_s: 0, end_s: 8, energy: 0.52, energy_label: "steady", band: "mid" }],
    scenes: [
      {
        index: 0,
        name,
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
    timeline_patch: {
      ok: true,
      timeline: {
        tracks: [{ id: "track_prompt", name: "Prompts", type: "prompt", clips: [] }],
        layers: [],
        camera: { keyframes: [] },
      },
    },
    deforum_preview: { ok: true, settings: { prompts: { 0: "scene" } } },
    llm_contract: { ok: true, endpoint: "/v1/projects/:project_id/narrative_direction" },
    notes: ["Prompt and motion tracks match the canonical Studio timeline schema."],
  };
}

describe("CreativeDirectionPanel", () => {
  it("clears stale payload while loading a different variant", async () => {
    installEdmgBridge();
    let resolveSecond: null | (() => void) = null;

    installFetchMock({
      "/v1/projects/p1/creative_direction*": (path) => {
        if (path.includes("variant_index=0")) {
          return { creative_direction: payloadFor("Variant zero scene") };
        }
        if (path.includes("variant_index=1")) {
          return new Promise((resolve) => {
            resolveSecond = () => resolve({ creative_direction: payloadFor("Variant one scene") });
          });
        }
        throw new Error(`Unexpected route: ${path}`);
      },
    });

    const view = renderWithStudio(
      <CreativeDirectionPanel
        projectId="p1"
        analysis={{ features: { duration_s: 32 } }}
        plan={{ variants: [{}, {}] }}
        selectedVariant={0}
      />,
    );

    expect((await screen.findAllByText(/Variant zero scene/)).length).toBeGreaterThan(0);

    view.rerender(
      <UiModeProvider>
        <CreativeDirectionPanel
          projectId="p1"
          analysis={{ features: { duration_s: 32 } }}
          plan={{ variants: [{}, {}] }}
          selectedVariant={1}
        />
      </UiModeProvider>,
    );

    await waitFor(() => expect(screen.getByText(/Loading backend creative direction/i)).toBeTruthy());
    expect(screen.queryAllByText(/Variant zero scene/).length).toBe(0);
    expect((screen.getByRole("button", { name: "Copy prompt pack" }) as HTMLButtonElement).disabled).toBe(true);

    resolveSecond?.();
    await waitFor(() => expect(screen.queryAllByText(/Variant one scene/).length).toBeGreaterThan(0));
  });

  it("applies the generated timeline patch through the backend route", async () => {
    const onNavigate = vi.fn();
    let applyCalls = 0;
    installEdmgBridge();

    installFetchMock({
      "/v1/projects/p1/creative_direction*": { creative_direction: payloadFor("Variant one scene") },
      "POST /v1/projects/p1/creative_direction/apply_timeline_patch": (_path, init) => {
        applyCalls += 1;
        const body = JSON.parse(String(init?.body || "{}"));
        expect(body.variant_index).toBe(0);
        expect(body.overwrite_tracks).toBe(true);
        return { ok: true, timeline: { tracks: [], layers: [], camera: { keyframes: [] } } };
      },
    });

    renderWithStudio(
      <CreativeDirectionPanel
        projectId="p1"
        analysis={{ features: { duration_s: 32 } }}
        plan={{ variants: [{}] }}
        selectedVariant={0}
        onNavigate={onNavigate}
      />,
    );

    expect((await screen.findAllByText(/Variant one scene/)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Apply direction to timeline" }));

    await waitFor(() => expect(applyCalls).toBe(1));
    expect(await screen.findByText("Direction patch applied to timeline.")).toBeTruthy();
    expect(onNavigate).toHaveBeenCalledWith("timeline");
  });
});
