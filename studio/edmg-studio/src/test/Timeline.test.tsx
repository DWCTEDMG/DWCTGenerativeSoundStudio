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

  it("provides DAW-style grid jumps and loop locator controls", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Locator Test" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "Locator Test",
          meta: {
            audio: { filename: "track.wav", duration_s: 8 },
            analysis: { features: { duration_s: 8, bpm: 120, beat_times_s: [0, 0.5, 1, 1.5, 2, 2.5, 3] } },
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
    });

    renderWithStudio(<Timeline backendUrl="http://127.0.0.1:7863" config={{}} />);

    const playhead = await screen.findByLabelText("Playhead time") as HTMLInputElement;
    const loopIn = await screen.findByLabelText("Loop in") as HTMLInputElement;
    const loopOut = await screen.findByLabelText("Loop out") as HTMLInputElement;

    fireEvent.click(screen.getByRole("button", { name: "Next grid" }));
    expect(playhead.value).toBe("0.5");

    fireEvent.change(screen.getByLabelText("Quantize grid"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Go to start" }));
    fireEvent.click(screen.getByRole("button", { name: "Next grid" }));
    expect(playhead.value).toBe("0.25");

    fireEvent.click(screen.getByRole("button", { name: "Disable snap" }));
    expect(screen.getByRole("button", { name: "Enable snap" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show time ruler" }));
    expect(screen.getByRole("button", { name: "Show bars and beats ruler" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Set in" }));
    expect(loopIn.value).toBe("0.25");

    fireEvent.change(playhead, { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Set out" }));
    expect(loopOut.value).toBe("2.5");

    fireEvent.click(screen.getByRole("button", { name: "Enable loop" }));
    expect(screen.getByRole("button", { name: "Disable loop" })).toBeTruthy();

    fireEvent.pointerDown(await screen.findByTitle(/A calm cinematic scene/));
    fireEvent.click(screen.getByRole("button", { name: "Use selection" }));
    expect(loopIn.value).toBe("0");
    expect(loopOut.value).toBe("8");
  });

  it("snaps clip moves, exposes timing fields, and honors track edit locks", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "DAW Edit Test" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "DAW Edit Test",
          meta: {
            audio: { filename: "track.wav", duration_s: 8 },
            analysis: {
              features: { duration_s: 8, bpm: 120, beat_times_s: [0, 0.5, 1, 1.5, 2, 2.5, 3] },
            },
            last_plan: {
              variants: [
                {
                  name: "Variant 1",
                  scenes: [{ id: "scene_0", start_s: 0, end_s: 2, prompt: "Move me on the beat." }],
                },
              ],
            },
          },
        },
      },
    });

    renderWithStudio(<Timeline backendUrl="http://127.0.0.1:7863" config={{}} />);

    const clip = await screen.findByTitle("Move me on the beat.");
    fireEvent.change(screen.getByLabelText("Timeline zoom"), { target: { value: "100" } });
    fireEvent.pointerDown(clip, { clientX: 0, pointerId: 1 });

    const arrangement = document.querySelector(".timeline-arrangementCard");
    expect(arrangement).toBeTruthy();
    fireEvent.pointerMove(arrangement as Element, { clientX: 60, pointerId: 1 });
    fireEvent.pointerUp(arrangement as Element, { pointerId: 1 });
    fireEvent.click(screen.getByRole("tab", { name: /Inspector/ }));

    const snappedStart = Number((await screen.findByLabelText("Clip start") as HTMLInputElement).value);
    const snappedEnd = Number((screen.getByLabelText("Clip end") as HTMLInputElement).value);
    expect(Number.isInteger(snappedStart * 2)).toBe(true);
    expect(snappedEnd - snappedStart).toBe(2);
    expect((screen.getByLabelText("Clip length") as HTMLInputElement).value).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: "Lock Prompts track" }));
    expect(screen.getByRole("button", { name: "Unlock Prompts track" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Clip length"), { target: { value: "1" } });
    expect((screen.getByLabelText("Clip length") as HTMLInputElement).value).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: "Unlock Prompts track" }));
    fireEvent.change(screen.getByLabelText("Clip length"), { target: { value: "1" } });
    expect(Number((screen.getByLabelText("Clip end") as HTMLInputElement).value)).toBe(snappedStart + 1);
  });
});
