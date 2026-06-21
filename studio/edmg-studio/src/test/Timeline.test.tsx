import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Timeline from "../pages/Timeline";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Timeline page", () => {
  it("updates the transport button when audio playback events fire", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Smoothness Test" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "Smoothness Test",
          meta: {
            audio: { filename: "track.wav", duration_s: 8 },
            analysis: { features: { duration_s: 8, bpm: 120 } },
            last_plan: {
              variants: [
                {
                  name: "Variant 1",
                  scenes: [
                    { id: "scene_0", start_s: 0, end_s: 8, prompt: "A continuous guitar performance with smooth motion." },
                  ],
                },
              ],
            },
          },
        },
      },
    });

    renderWithStudio(<Timeline backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByText("Timeline")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Play" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Fit all" })).toBeTruthy();

    await waitFor(() => expect(document.querySelector("audio")).toBeTruthy());
    const audio = document.querySelector("audio");
    expect(audio).toBeTruthy();
    fireEvent.play(audio as HTMLAudioElement);
    expect(await screen.findByRole("button", { name: "Pause" })).toBeTruthy();

    fireEvent.pause(audio as HTMLAudioElement);
    expect(await screen.findByRole("button", { name: "Play" })).toBeTruthy();
  });

  it("exposes sync-to-renderer and delete editing actions", async () => {
    installEdmgBridge();
    const onNavigate = vi.fn();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Editing Test" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "Editing Test",
          meta: {
            audio: { filename: "track.wav", duration_s: 8 },
            analysis: { features: { duration_s: 8, bpm: 120 } },
            last_plan: {
              variants: [
                {
                  name: "Variant 1",
                  scenes: [{ id: "scene_0", start_s: 0, end_s: 8, prompt: "A calm cinematic scene." }],
                },
              ],
            },
          },
        },
      },
      "POST /v1/projects/p1/timeline": (_path: string, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(String(init.body)) : {};
        return { ok: true, timeline: body.timeline || {} };
      },
    });

    renderWithStudio(
      <Timeline backendUrl="http://127.0.0.1:7863" config={{}} onNavigate={onNavigate} />,
    );

    // New editing affordances are present (Sync to renderer appears in both the
    // toolbar and the handoffs dock panel).
    const syncButtons = await screen.findAllByRole("button", { name: "Sync to renderer" });
    expect(syncButtons.length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Delete" }).length).toBeGreaterThan(0);

    // Sync to renderer saves the timeline then navigates to the Render page.
    fireEvent.click(syncButtons[0]);
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("render"));
  });
});
