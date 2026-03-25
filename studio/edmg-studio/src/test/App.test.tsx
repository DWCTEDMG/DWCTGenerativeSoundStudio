import React from "react";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../App";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("App boot", () => {
  it("boots into the setup page when dependencies are missing", async () => {
    installEdmgBridge();
    installFetchMock({
      "/v1/config": {},
      "/v1/setup/status": {
        ollama: { ok: false, model_present: false },
        comfyui: { ok: false },
        ffmpeg: { ok: false },
        backend_bundle: { ok: false },
        sevenzip: { ok: false },
        ai_config: { label: "Local Ollama", ollama_required: true, model_required: true },
      },
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
    });

    renderWithStudio(<App />);

    expect(await screen.findByText("Setup Wizard")).toBeTruthy();
    expect(await screen.findByText(/Active AI path:/)).toBeTruthy();
  });
});
