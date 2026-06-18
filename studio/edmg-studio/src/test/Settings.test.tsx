import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BACKEND_URL_CHANGED_EVENT } from "../components/api";
import Settings from "../pages/Settings";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Settings page", () => {
  it("persists desktop backend mode and target settings", async () => {
    const setBackendSettings = vi.fn(async (settings: { mode: string; host: string; port: string; url?: string }) => ({
      ok: true,
      restartRequired: true,
      ...settings,
      currentBackendUrl: String(settings.url || `http://${settings.host}:${settings.port}`),
    }));

    installEdmgBridge({
      getBackendSettings: async () => ({
        ok: true,
        mode: "managed",
        host: "127.0.0.1",
        port: "7863",
        url: "",
        source: "bootstrap",
        currentBackendUrl: "http://127.0.0.1:7863",
      }),
      setBackendSettings,
    });

    installFetchMock({
      "/v1/config": {
        ai_mode: "local",
        ai_provider: "ollama",
        ai_ollama_url: "http://127.0.0.1:11434",
        ai_ollama_model: "qwen3:8b",
      },
      "/v1/ai/status": { ok: true, provider: "ollama" },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test", has_openai_compat_api_key: false },
      "/v1/hardware": {
        hardware: {
          device_name: "Test GPU",
          backend_family: "cuda",
          recommended_tier: "balanced",
        },
      },
      "/v1/settings/render_profiles": {
        recommended_profile: "balanced_auto",
        profiles: {
          balanced_auto: {
            label: "Balanced Auto",
            description: "General desktop profile",
            render_preset: "balanced",
            internal_render_tier: "balanced",
            resume_existing_frames: true,
          },
        },
      },
      "/v1/settings/render_providers": {
        settings: {
          stability: {
            enabled: false,
            allow_auto_fallback: false,
            service: "sd3",
            model: "sd3.5-large-turbo",
            style_preset: "none",
            output_format: "png",
          },
          directml: {
            enabled: false,
            allow_auto_selection: false,
            preferred_model: "auto",
          },
        },
        stability: { has_api_key: false, visible: false, note: "disabled" },
        directml: { runtime_ready: false, available: false, active: false, device_name: "" },
        stability_services: ["sd3"],
        stability_models: ["sd3.5-large-turbo"],
        style_presets: ["none"],
      },
      "/v1/settings/transcription": {
        settings: {
          provider: "faster_whisper",
          model: "turbo",
          device: "cpu",
          compute_type: "int8",
          fallback_to_whisper: true,
        },
        active: { provider: "faster_whisper", model: "turbo", device: "cpu" },
        dependencies: { parakeet_available: false, faster_whisper_available: true },
        hardware: { device_name: "Test GPU" },
      },
      "/health": { ok: true },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByText("Desktop Backend")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Desktop backend mode"), {
      target: { value: "external" },
    });
    fireEvent.change(screen.getByLabelText("Desktop backend URL"), {
      target: { value: "https://edmg-backend.example.com" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Save backend startup settings" }));

    await waitFor(() => {
      expect(setBackendSettings).toHaveBeenCalledWith({
        mode: "external",
        host: "127.0.0.1",
        port: "7863",
        url: "https://edmg-backend.example.com",
      });
    });

    expect(await screen.findByText(/Saved\. Restart Studio so it relaunches against the selected backend target\./)).toBeTruthy();
  });

  it("connects browser mode to a Lightning backend URL immediately", async () => {
    const changedUrls: string[] = [];
    window.addEventListener(BACKEND_URL_CHANGED_EVENT, ((event: CustomEvent<{ url?: string }>) => {
      if (event.detail?.url) changedUrls.push(event.detail.url);
    }) as EventListener);

    installFetchMock({
      "/v1/config": {
        ai_mode: "local",
        ai_provider: "rule_based",
      },
      "/v1/ai/status": { ok: true, provider: "rule_based" },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test", has_openai_compat_api_key: false },
      "/v1/hardware": {
        hardware: {
          device_name: "Lightning GPU",
          backend_family: "cuda",
          recommended_tier: "quality",
        },
      },
      "/v1/settings/render_profiles": {
        recommended_profile: "balanced_auto",
        profiles: {},
      },
      "/v1/settings/render_providers": {
        settings: {},
        stability: { has_api_key: false, visible: false, note: "disabled" },
        directml: { runtime_ready: false, available: false, active: false, device_name: "" },
        stability_services: [],
        stability_models: [],
        style_presets: [],
      },
      "/v1/settings/transcription": {
        settings: {
          provider: "faster_whisper",
          model: "turbo",
          device: "cpu",
          compute_type: "int8",
          fallback_to_whisper: true,
        },
        active: { provider: "faster_whisper", model: "turbo", device: "cpu" },
        dependencies: { parakeet_available: true, faster_whisper_available: true },
        hardware: { device_name: "Lightning GPU" },
      },
      "/health": { ok: true },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByText("Desktop Backend")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Desktop backend URL"), {
      target: { value: "https://studio-demo.lightning.ai/health" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use backend now" }));

    await waitFor(() => {
      expect(window.localStorage.getItem("edmg.backendUrl")).toBe("https://studio-demo.lightning.ai");
    });
    expect(changedUrls).toContain("https://studio-demo.lightning.ai");
    expect(await screen.findByText(/Connected for this browser\./)).toBeTruthy();
  });

  it("saves NVIDIA Parakeet transcription settings on the active backend", async () => {
    const postedBodies: any[] = [];
    installEdmgBridge();
    installFetchMock({
      "/v1/config": {
        ai_mode: "local",
        ai_provider: "rule_based",
      },
      "/v1/ai/status": { ok: true, provider: "rule_based" },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test", has_openai_compat_api_key: false },
      "/v1/hardware": {
        hardware: {
          device_name: "NVIDIA RTX PRO 6000 Blackwell Server Edition",
          backend_family: "cuda",
          recommended_tier: "quality",
        },
      },
      "/v1/settings/render_profiles": {
        recommended_profile: "high_quality",
        profiles: {},
      },
      "/v1/settings/render_providers": {
        settings: {},
        stability: { has_api_key: false, visible: false, note: "disabled" },
        directml: { runtime_ready: false, available: false, active: false, device_name: "" },
        stability_services: [],
        stability_models: [],
        style_presets: [],
      },
      "/v1/settings/transcription": (path, init) => {
        if (String(init?.method || "GET").toUpperCase() === "POST") {
          postedBodies.push(JSON.parse(String(init?.body || "{}")));
          return {
            ok: true,
            settings: postedBodies[postedBodies.length - 1],
            status: {
              active: postedBodies[postedBodies.length - 1],
              settings: postedBodies[postedBodies.length - 1],
              dependencies: { parakeet_available: true, faster_whisper_available: true },
              hardware: { device_name: "NVIDIA RTX PRO 6000 Blackwell Server Edition" },
            },
          };
        }
        return {
          settings: {
            provider: "faster_whisper",
            model: "turbo",
            device: "cpu",
            compute_type: "int8",
            fallback_to_whisper: true,
          },
          active: { provider: "faster_whisper", model: "turbo", device: "cpu" },
          dependencies: { parakeet_available: true, faster_whisper_available: true },
          hardware: { device_name: "NVIDIA RTX PRO 6000 Blackwell Server Edition" },
        };
      },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByLabelText("ASR provider")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("ASR provider"), {
      target: { value: "parakeet" },
    });
    fireEvent.change(screen.getByLabelText("ASR model"), {
      target: { value: "nvidia/parakeet-tdt-0.6b-v2" },
    });
    fireEvent.change(screen.getByLabelText("ASR device"), {
      target: { value: "cuda" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save transcription settings" }));

    await waitFor(() => {
      expect(postedBodies).toContainEqual({
        provider: "parakeet",
        model: "nvidia/parakeet-tdt-0.6b-v2",
        device: "cuda",
        compute_type: "auto",
        fallback_to_whisper: true,
      });
    });
  });
});
