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

  it("shows Linux-friendly storage paths and manual setup guidance", async () => {
    installEdmgBridge({
      getStudioPaths: async () => ({
        ok: true,
        platform: "linux",
        studioHome: "/home/test/EDMG-Studio",
        dataDir: "/home/test/EDMG-Studio/data",
        modelsDir: "/home/test/EDMG-Studio/models",
        cacheRoot: "/home/test/EDMG-Studio/cache",
        logsDir: "/home/test/EDMG-Studio/logs",
        externalDir: "/home/test/EDMG-Studio/external",
        electronUserData: "/home/test/EDMG-Studio/electron",
        sessionData: "/home/test/EDMG-Studio/electron/session",
        bootstrapConfigPath: "/home/test/.config/EDMG Studio/bootstrap.json",
        source: "test",
      }),
    });
    installFetchMock({
      "/v1/setup/status": {
        ollama: { ok: false, model_present: false, launch_available: true },
        comfyui: { ok: false, url: "http://127.0.0.1:8188" },
        ffmpeg: { ok: true },
        backend_bundle: { ok: true },
        backend_bundle_directml: { ok: false, missing: ["onnxruntime-directml"] },
        sevenzip: { ok: true, hint: "optional on linux" },
        hardware: { supports_directml: false },
        ai_config: { label: "Local Ollama", ollama_required: true, model_required: true },
      },
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
    });

    renderWithStudio(<Setup />);

    expect(await screen.findByDisplayValue("/home/test/EDMG-Studio")).toBeTruthy();
    expect(await screen.findByText("0) System Setup")).toBeTruthy();
    expect(await screen.findByText(/Linux and macOS use the manual setup path/)).toBeTruthy();
    expect(await screen.findByText(/Linux support expects a system-installed/i)).toBeTruthy();
    expect(await screen.findByText(/Linux support uses a manually installed ComfyUI instance.*optional workflows/i)).toBeTruthy();
  });
});
