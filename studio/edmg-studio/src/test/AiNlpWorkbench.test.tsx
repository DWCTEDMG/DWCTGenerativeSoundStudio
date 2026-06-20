import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AiNlpWorkbench from "../workbenches/AiNlpWorkbench";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

const TRANSCRIPT = "A late night drive through the rain soaked city.";

function studioProject() {
  return {
    id: "p1",
    name: "Handoff Demo",
    meta: {
      audio: { filename: "track.wav", duration_s: 12 },
      analysis: {
        timestamp: 123,
        summary: TRANSCRIPT,
        transcript: { text: TRANSCRIPT },
        features: { duration_s: 12, bpm: 120 },
        sections: [
          { start_s: 0, end_s: 6, energy: 0.3, label: "intro" },
          { start_s: 6, end_s: 12, energy: 0.8, label: "drop" },
        ],
      },
      last_plan: {
        variants: [
          {
            name: "Variant 1",
            scenes: [
              { start_s: 0, end_s: 6, name: "Intro", prompt: "rain on glass, neon reflections" },
              { start_s: 6, end_s: 12, name: "Drop", prompt: "city lights rushing past" },
            ],
          },
        ],
      },
    },
  };
}

describe("AiNlpWorkbench shared-session hydration", () => {
  it("pre-fills the creative brief and subject focus from the analyzed transcript", async () => {
    installEdmgBridge();
    // Audio endpoint returns a non-blob response; the workbench handles that
    // gracefully and still hydrates the brief/prompts from the session.
    installFetchMock({ "/v1/projects/p1/audio": {} });

    renderWithStudio(
      <AiNlpWorkbench
        compact
        studioProjectId="p1"
        studioProjectName="Handoff Demo"
        studioProject={studioProject()}
        studioSelectedVariant={0}
        onSyncToStudio={vi.fn()}
      />,
    );

    // Wait for hydration to finish (it auto-opens the Prompt Pack once the
    // saved storyboard scenes are loaded from the shared session).
    await waitFor(() => expect(screen.getByText(/Executive AI plan/i)).toBeTruthy());

    // Open Setup to inspect the seeded brief/subject fields.
    fireEvent.click(screen.getByRole("tab", { name: /Setup/i }));

    // Creative brief is seeded from the transcript instead of the generic default.
    expect(screen.getByDisplayValue(TRANSCRIPT)).toBeTruthy();
    // Subject focus is derived from the transcript too.
    expect(screen.getByDisplayValue(/embodying A late night drive/i)).toBeTruthy();
    // Handoff message tells the user no re-upload is required.
    expect(screen.getByText(/no need to re-upload/i)).toBeTruthy();
    // With session analysis hydrated, planning works without a local file.
    expect(screen.getByRole("button", { name: /Plan from session analysis/i })).toBeTruthy();
  });
});
