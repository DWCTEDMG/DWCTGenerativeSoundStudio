import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import App from "../App";
import StudioForge from "../pages/StudioForge";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

const ORIGINAL_STUDIO_FORGE_FLAG = import.meta.env.VITE_EDMG_ENABLE_STUDIO_FORGE;

const READY_STATUS = {
  ollama: {
    ok: true,
    model_present: true,
    model: "qwen3:8b",
    url: "http://127.0.0.1:11434",
  },
  comfyui: {
    ok: false,
    url: "http://127.0.0.1:8188",
  },
  ffmpeg: {
    ok: true,
    path: "ffmpeg",
  },
  backend_bundle: {
    ok: true,
  },
  edmg: {
    available: true,
  },
  ai_config: {
    label: "Local Ollama",
    ollama_required: true,
    model_required: true,
  },
};

const FETCH_FIXTURES = {
  "/health": { ok: true },
  "/v1/config": {
    ai_mode: "local",
    ai_provider: "ollama",
    model: "qwen3:8b",
  },
  "/v1/setup/status": READY_STATUS,
  "/v1/comfyui/capabilities": {
    ok: true,
    nodes: [],
  },
};

describe("Studio Forge", () => {
  afterEach(() => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", ORIGINAL_STUDIO_FORGE_FLAG ?? "");
    window.history.pushState({}, "", "/");
  });

  it("renders the read-only page shell and template previews", async () => {
    installEdmgBridge();
    installFetchMock(FETCH_FIXTURES);

    renderWithStudio(
      <StudioForge backendUrl="http://127.0.0.1:7863" config={FETCH_FIXTURES["/v1/config"]} />,
    );

    expect(await screen.findByRole("heading", { name: /Studio Forge/i })).toBeTruthy();
    expect(screen.getByText(/Read-only preview mode/i)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Runtime Recommendations/i })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Unreal Bridge Previews/i })).toBeTruthy();
    expect((await screen.findAllByText(/Ready now/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Render Queue Dashboard/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Unreal Shot Metadata Export/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Preview payload/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Audio -> Analysis -> AI Plan -> Render -> Assemble/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Developer validation commands only/i)).toBeTruthy();
  });

  it("surfaces setup-needed recommendations when runtime capabilities are missing", async () => {
    installEdmgBridge();
    installFetchMock({
      ...FETCH_FIXTURES,
      "/v1/setup/status": {
        ...READY_STATUS,
        ollama: {
          ok: false,
          model_present: false,
          model: "",
          url: "http://127.0.0.1:11434",
        },
        comfyui: {
          ok: false,
          url: "http://127.0.0.1:8188",
        },
        ffmpeg: {
          ok: false,
          path: "ffmpeg",
        },
        edmg: {
          available: false,
        },
      },
      "/v1/comfyui/capabilities": () => {
        throw new Error("ComfyUI offline");
      },
    });

    renderWithStudio(
      <StudioForge backendUrl="http://127.0.0.1:7863" config={FETCH_FIXTURES["/v1/config"]} />,
    );

    expect((await screen.findAllByText(/Setup needed/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Missing required capabilities/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Optional boosts not detected/i)).length).toBeGreaterThan(0);
  });

  it("falls back to dashboard when direct page access is disabled", async () => {
    installEdmgBridge();
    installFetchMock(FETCH_FIXTURES);
    window.history.pushState({}, "", "/?page=studioForge");

    renderWithStudio(<App />);

    expect(await screen.findByRole("heading", { name: /Dashboard/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Studio Forge/i })).toBeNull();
  });

  it("enables direct page access and labs navigation when the flag is on", async () => {
    vi.stubEnv("VITE_EDMG_ENABLE_STUDIO_FORGE", "1");
    installEdmgBridge();
    installFetchMock(FETCH_FIXTURES);
    window.history.pushState({}, "", "/?page=studioForge");

    renderWithStudio(<App />);

    expect(await screen.findByRole("heading", { name: /Studio Forge/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Studio Forge/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /AI Planner Lab/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Reactive Lab/i })).toBeTruthy();
  });
});
