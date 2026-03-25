import React from "react";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Setup from "../pages/Setup";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Setup page", () => {
  it("shows the active AI path and Studio Home controls", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/setup/status": {
        ollama: { ok: true, model_present: true },
        comfyui: { ok: false },
        ffmpeg: { ok: true },
        backend_bundle: { ok: true },
        sevenzip: { ok: true },
        ai_config: { label: "Local llama.cpp server", ollama_required: false, model_required: false },
      },
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
    });

    renderWithStudio(<Setup />);

    expect(await screen.findByText("Setup Wizard")).toBeTruthy();
    expect(await screen.findByText(/Active AI path:/)).toBeTruthy();
    expect(await screen.findByDisplayValue("D:\\EDMG-Studio")).toBeTruthy();
  });
});
