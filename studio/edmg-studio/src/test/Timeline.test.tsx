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

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(Number((screen.getByLabelText("Clip start") as HTMLInputElement).value)).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect(Number((screen.getByLabelText("Clip start") as HTMLInputElement).value)).toBe(snappedStart);

    fireEvent.click(screen.getByRole("button", { name: "Lock Prompts track" }));
    expect(screen.getByRole("button", { name: "Unlock Prompts track" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Clip length"), { target: { value: "1" } });
    expect((screen.getByLabelText("Clip length") as HTMLInputElement).value).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: "Unlock Prompts track" }));
    fireEvent.change(screen.getByLabelText("Clip length"), { target: { value: "1" } });
    expect(Number((screen.getByLabelText("Clip end") as HTMLInputElement).value)).toBe(snappedStart + 1);
  });

  it("labels scheduled motion axes and applies multi-axis camera presets", async () => {
    installEdmgBridge();
    let savedTimeline: any = null;
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Motion Test" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "Motion Test",
          meta: {
            audio: { filename: "track.wav", duration_s: 8 },
            analysis: { features: { duration_s: 8, bpm: 120 } },
            last_plan: {
              variants: [
                {
                  name: "Variant 1",
                  scenes: [{ id: "scene_0", start_s: 0, end_s: 8, prompt: "Move through the frame." }],
                },
              ],
            },
            timeline: {
              duration_s: 8,
              tracks: [
                {
                  id: "track_prompt",
                  name: "Prompts",
                  type: "prompt",
                  clips: [{ id: "prompt_0", start_s: 0, end_s: 8, data: { prompt: "Move through the frame." } }],
                },
                {
                  id: "track_motion",
                  name: "Motion",
                  type: "motion",
                  clips: [
                    {
                      id: "reactive_0",
                      start_s: 0,
                      end_s: 2,
                      data: { zoom: "0:(1.0), 48:(1.08)", angle: "0:(0), 48:(2.0)" },
                    },
                    {
                      id: "simple_0",
                      start_s: 2,
                      end_s: 8,
                      data: {
                        zoom_start: 1,
                        zoom_end: 1.06,
                        pan_x_start: 0,
                        pan_x_end: 0,
                        pan_y_start: 0,
                        pan_y_end: 0,
                        rotation_start: 0,
                        rotation_end: 0,
                      },
                    },
                  ],
                },
              ],
              camera: {
                keyframes: [{ t: 4, zoom: 1, pan_x: 0, pan_y: 0, rotation_deg: 0 }],
              },
            },
          },
        },
      },
      "POST /v1/projects/p1/timeline": (_path: string, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(String(init.body)) : {};
        savedTimeline = body.timeline;
        return { ok: true, timeline: body.timeline || {} };
      },
    });

    renderWithStudio(<Timeline backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByTitle("Audio reactive · zoom + rotate")).toBeTruthy();
    fireEvent.pointerDown(await screen.findByTitle("Push in · zoom"));
    fireEvent.click(screen.getByRole("tab", { name: /Inspector/ }));

    const preset = await screen.findByLabelText("Motion preset") as HTMLSelectElement;
    expect(preset.value).toBe("custom");
    expect(screen.getByLabelText("Motion pan X end")).toBeTruthy();
    expect(screen.getByText("3D orbit + render controls")).toBeTruthy();

    fireEvent.change(preset, { target: { value: "orbit_right" } });
    expect(await screen.findByTitle("Orbit right · zoom + pan + rotate + depth + 3D orbit")).toBeTruthy();
    expect((screen.getByLabelText("Motion pan X end") as HTMLInputElement).value).toBe("8");

    fireEvent.click(screen.getByRole("button", { name: "Save timeline *" }));
    await waitFor(() => expect(savedTimeline).toBeTruthy());
    const start = savedTimeline.camera.keyframes.find((point: any) => point.t === 2);
    const middle = savedTimeline.camera.keyframes.find((point: any) => point.t === 4);
    const end = savedTimeline.camera.keyframes.find((point: any) => point.t === 8);
    expect(start.pan_x).toBe(-8);
    expect(start.rotation_3d_y).toBe(5);
    expect(middle.pan_x).toBeCloseTo(-2.67, 1);
    expect(middle.rotation_3d_y).toBeCloseTo(1.67, 1);
    expect(end.pan_x).toBe(8);
    expect(end.rotation_3d_y).toBe(-5);
  });

  it("records move, trim, split, property, camera, and curve edits in history", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Command History Test" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "Command History Test",
          meta: {
            audio: { filename: "track.wav", duration_s: 8 },
            analysis: { features: { duration_s: 8, bpm: 120, beat_times_s: [0, 0.5, 1, 1.5, 2] } },
            last_plan: {
              variants: [
                {
                  name: "Variant 1",
                  scenes: [{ id: "scene_0", start_s: 0, end_s: 4, prompt: "Command history prompt" }],
                },
              ],
            },
            timeline: {
              duration_s: 8,
              tracks: [
                {
                  id: "track_prompt",
                  name: "Prompts",
                  type: "prompt",
                  clips: [{ id: "prompt_0", start_s: 0, end_s: 4, data: { prompt: "Command history prompt" } }],
                },
                {
                  id: "track_motion",
                  name: "Motion",
                  type: "motion",
                  clips: [{ id: "motion_0", start_s: 0, end_s: 4, data: {} }],
                },
              ],
              camera: {
                keyframes: [{ t: 2, zoom: 1, pan_x: 0, pan_y: 0, rotation_deg: 0 }],
              },
            },
          },
        },
      },
    });

    renderWithStudio(<Timeline backendUrl="http://127.0.0.1:7863" config={{}} />);

    const clip = await screen.findByTitle("Command history prompt");
    fireEvent.pointerDown(clip);
    fireEvent.click(screen.getByRole("tab", { name: /Inspector/ }));

    const playhead = await screen.findByLabelText("Playhead time") as HTMLInputElement;
    fireEvent.change(playhead, { target: { value: "1" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Nudge to playhead" })[0]);
    expect((screen.getByLabelText("Clip start") as HTMLInputElement).value).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect((screen.getByLabelText("Clip start") as HTMLInputElement).value).toBe("0");

    fireEvent.change(screen.getByLabelText("Clip length"), { target: { value: "2" } });
    expect((screen.getByLabelText("Clip length") as HTMLInputElement).value).toBe("2");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect((screen.getByLabelText("Clip length") as HTMLInputElement).value).toBe("4");
    fireEvent.click(screen.getByRole("button", { name: "Redo" }));
    expect((screen.getByLabelText("Clip length") as HTMLInputElement).value).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: "Split" }));
    expect(screen.getAllByTitle("Command history prompt")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getAllByTitle("Command history prompt")).toHaveLength(1);

    const prompt = screen.getByLabelText("Prompt text") as HTMLTextAreaElement;
    fireEvent.change(prompt, { target: { value: "Updated command history prompt" } });
    expect(prompt.value).toBe("Updated command history prompt");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect((screen.getByLabelText("Prompt text") as HTMLTextAreaElement).value).toBe("Command history prompt");

    fireEvent.pointerDown(screen.getByLabelText(/Camera keyframe at/));
    const zoom = await screen.findByLabelText("Camera zoom") as HTMLInputElement;
    fireEvent.change(zoom, { target: { value: "1.5" } });
    expect(zoom.value).toBe("1.5");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect((screen.getByLabelText("Camera zoom") as HTMLInputElement).value).toBe("1");

    fireEvent.click(screen.getByRole("tab", { name: /Curves/ }));
    const strengthSchedule = await screen.findByLabelText("Strength schedule") as HTMLTextAreaElement;
    fireEvent.change(strengthSchedule, { target: { value: "0:(0.45)" } });
    expect(strengthSchedule.value).toBe("0:(0.45)");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect((screen.getByLabelText("Strength schedule") as HTMLTextAreaElement).value).toBe("");
  });
});
