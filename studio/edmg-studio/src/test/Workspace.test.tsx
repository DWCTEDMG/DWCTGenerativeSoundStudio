import React from "react";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Workspace from "../pages/Workspace";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Workspace page", () => {
  it("integrates creative direction from the real project analysis and plan", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/projects": { projects: [{ id: "p1", name: "Demo Project" }] },
      "/v1/projects/p1": {
        project: {
          id: "p1",
          name: "Demo Project",
          meta: {
            audio: { filename: "track.wav", size_bytes: 1024 * 1024, duration_s: 48 },
            analysis: {
              features: {
                duration_s: 48,
                bpm: 122,
                energy: 0.68,
                bass_energy: 0.55,
                mid_energy: 0.49,
                brightness: 0.42,
              },
              transcript: {
                text: "Neon streets open into a dawn skyline while the chorus lifts the whole crowd forward.",
              },
            },
            last_plan: {
              variants: [
                {
                  name: "Variant 1",
                  scenes: [
                    { name: "Neon arrival", start_s: 0, end_s: 12, prompt: "Neon streets with rain reflections and kinetic camera drift." },
                    { name: "Skyline lift", start_s: 12, end_s: 24, prompt: "Dawn skyline bloom with silhouettes and stronger motion parallax." },
                  ],
                },
              ],
            },
          },
        },
      },
      "/v1/projects/p1/assets": { assets: { refs: [] } },
      "/v1/projects/p1/creative_direction*": {
        creative_direction: {
          preset: "cinematic",
          sensitivity: 1,
          metrics: { energy: 0.68, bass: 0.55, mid: 0.49, treble: 0.42, duration_s: 48, source: "analysis" },
          waveform: [0.2, 0.45, 0.8, 0.5],
          motifs: ["neon", "skyline", "dawn"],
          transcript_text: "Neon streets open into a dawn skyline while the chorus lifts the whole crowd forward.",
          transcript_summary: "Neon streets open into a dawn skyline while the chorus lifts the whole crowd forward.",
          status: "Creative direction is being derived on the backend from the saved project analysis and plan.",
          export_text: "1. Neon arrival (0.00s - 12.00s)\nNeon streets with rain reflections and kinetic camera drift.",
          scenes: [
            {
              index: 0,
              name: "Neon arrival",
              start_s: 0,
              end_s: 12,
              duration_s: 12,
              energy: 0.64,
              energy_label: "lift",
              prompt: "Neon streets with rain reflections and kinetic camera drift.",
              transcript_cue: "Neon streets open into a dawn skyline while the chorus lifts the whole crowd forward.",
              camera_hint: "Tracking medium shot with progressive push, controlled drift, and bolder edge lighting.",
              motion_hint: "Zoom 1.14, cfg 7.9, strength 0.68, Z travel -16.6.",
              prompt_pack: "Neon streets with rain reflections and kinetic camera drift.",
            },
          ],
        },
      },
    });

    renderWithStudio(<Workspace backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByRole("heading", { name: "Workspace" })).toBeTruthy();
    expect(await screen.findByText("Creative direction")).toBeTruthy();
    expect(await screen.findByText("Scene prompt pack")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Copy prompt pack" })).toBeTruthy();
    expect(await screen.findByText(/Transcript anchor/i)).toBeTruthy();
  });
});
