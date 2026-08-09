import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BACKEND_URL_CHANGED_EVENT } from "../components/api";
import Settings from "../pages/Settings";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Settings page", () => {
  it("normalizes the legacy local qwen OpenAI-compatible default pair", async () => {
    installEdmgBridge({
      getAiSettings: async () => ({
        ok: true,
        mode: "local",
        provider: "openai_compat",
        aiBaseUrl: "http://127.0.0.1:7862",
        ollamaUrl: "http://127.0.0.1:11434",
        ollamaModel: "qwen3:8b",
        openaiCompatBaseUrl: "http://127.0.0.1:8000",
        openaiCompatModel: "qwen3-8b",
        nvidiaBaseUrl: "https://integrate.api.nvidia.com/v1",
        nvidiaModel: "nvidia/llama-3.1-nemotron-ultra-253b-v1",
        source: "launcher",
      }),
    });

    installFetchMock({
      "/v1/config": {
        ai_mode: "local",
        ai_provider: "openai_compat",
        ai_openai_compat_base_url: "https://integrate.api.nvidia.com/v1",
        ai_openai_compat_model: "nvidia/llama-3.1-nemotron-ultra-253b-v1",
      },
      "/v1/ai/status": { ok: true, provider: "openai_compat" },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test", has_openai_compat_api_key: false },
      "/v1/hardware": { hardware: { device_name: "Test GPU", backend_family: "cuda", recommended_tier: "balanced" } },
      "/v1/settings/render_profiles": { recommended_profile: "balanced_auto", profiles: {} },
      "/v1/settings/render_providers": {
        settings: {},
        stability: { has_api_key: false, visible: false, note: "disabled" },
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: ["imagine-turbo"],
        imagineart_video_styles: ["kling-1.0-pro"],
        directml: { runtime_ready: false, available: false, active: false, device_name: "" },
        stability_services: [],
        stability_models: [],
        style_presets: [],
      },
      "/v1/settings/transcription": {
        settings: {
          provider: "faster_whisper",
          model: "turbo",
          device: "auto",
          compute_type: "auto",
          fallback_to_whisper: true,
        },
        active: { provider: "faster_whisper", model: "turbo", device: "auto" },
        dependencies: { parakeet_available: false, faster_whisper_available: true },
        hardware: { device_name: "Test GPU" },
      },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByDisplayValue("https://integrate.api.nvidia.com/v1")).toBeTruthy();
    expect(await screen.findByDisplayValue("nvidia/llama-3.1-nemotron-ultra-253b-v1")).toBeTruthy();
  });

  it("saves DiffusionGemma as an NVIDIA planning model preset", async () => {
    const diffusionGemmaModel = "google/diffusiongemma-26B-A4B-it";
    const setAiSettings = vi.fn(async (settings: any) => ({
      ok: true,
      restartRequired: true,
      ...settings,
    }));

    installEdmgBridge({
      getAiSettings: async () => ({
        ok: true,
        mode: "local",
        provider: "nemotron_cloud",
        aiBaseUrl: "http://127.0.0.1:7862",
        ollamaUrl: "http://127.0.0.1:11434",
        ollamaModel: "qwen3:8b",
        openaiCompatBaseUrl: "https://integrate.api.nvidia.com/v1",
        openaiCompatModel: "nvidia/llama-3.1-nemotron-ultra-253b-v1",
        nvidiaBaseUrl: "https://integrate.api.nvidia.com/v1",
        nvidiaModel: "nvidia/llama-3.1-nemotron-ultra-253b-v1",
        source: "test",
      }),
      setAiSettings,
    });

    installFetchMock({
      "/v1/config": {
        ai_mode: "local",
        ai_provider: "nemotron_cloud",
        ai_nvidia_base_url: "https://integrate.api.nvidia.com/v1",
        ai_nvidia_model: "nvidia/llama-3.1-nemotron-ultra-253b-v1",
        ai_nvidia_model_presets: [
          { label: "Nemotron Ultra 253B", model: "nvidia/llama-3.1-nemotron-ultra-253b-v1" },
          { label: "DiffusionGemma 26B A4B", model: diffusionGemmaModel },
        ],
      },
      "/v1/ai/status": {
        ok: true,
        ai_config: {
          provider: "nvidia_nim",
          label: "NVIDIA NIM / OpenAI-compatible",
          model: "nvidia/llama-3.1-nemotron-ultra-253b-v1",
          model_presets: [
            { label: "Nemotron Ultra 253B", model: "nvidia/llama-3.1-nemotron-ultra-253b-v1" },
            { label: "DiffusionGemma 26B A4B", model: diffusionGemmaModel },
          ],
        },
      },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test", has_nvidia_api_key: true, has_openai_compat_api_key: false },
      "/v1/hardware": {
        hardware: {
          device_name: "NVIDIA RTX 5080",
          backend_family: "cuda",
          recommended_tier: "quality",
        },
      },
      "/v1/settings/render_profiles": { recommended_profile: "high_quality", profiles: {} },
      "/v1/settings/render_providers": {
        settings: {},
        stability: { has_api_key: false, visible: false, note: "disabled" },
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: ["imagine-turbo"],
        imagineart_video_styles: ["kling-1.0-pro"],
        directml: { runtime_ready: false, available: false, active: false, device_name: "" },
        stability_services: [],
        stability_models: [],
        style_presets: [],
      },
      "/v1/settings/transcription": {
        settings: {
          provider: "faster_whisper",
          model: "turbo",
          device: "auto",
          compute_type: "auto",
          fallback_to_whisper: true,
        },
        active: { provider: "faster_whisper", model: "turbo", device: "auto" },
        dependencies: { parakeet_available: false, faster_whisper_available: true },
        hardware: { device_name: "NVIDIA RTX 5080" },
      },
      "/health": { ok: true },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    fireEvent.change(await screen.findByLabelText("NVIDIA prompt model preset"), {
      target: { value: diffusionGemmaModel },
    });
    expect(await screen.findByText(/DiffusionGemma is for planning and prompt text/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save AI startup settings" }));

    await waitFor(() => {
      expect(setAiSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "nemotron_cloud",
          nvidiaModel: diffusionGemmaModel,
        }),
      );
    });
  });

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
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: ["imagine-turbo"],
        imagineart_video_styles: ["kling-1.0-pro"],
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
    expect(await screen.findByText("Backend Access Security")).toBeTruthy();

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

  it("saves a backend access token through encrypted desktop storage", async () => {
    const setBackendAuthToken = vi.fn(async (token: string) => ({
      ok: true,
      configured: !!token,
      persisted: !!token,
      secureStorageAvailable: true,
      note: "Backend access token saved with Electron OS-backed encryption.",
    }));
    installEdmgBridge({ setBackendAuthToken });
    installFetchMock({
      "/health": { ok: true },
      "/v1/security/status": {
        ok: true,
        auth_required: true,
        cors_origins: ["http://127.0.0.1:5173"],
        public_media_gets: true,
      },
      "/v1/config": { ai_mode: "local", ai_provider: "rule_based" },
    });

    renderWithStudio(<Settings backendUrl="https://edmg-backend.example.com" config={{}} />);

    fireEvent.change(await screen.findByLabelText("Backend access token"), {
      target: { value: "test-remote-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save encrypted token" }));

    await waitFor(() => {
      expect(setBackendAuthToken).toHaveBeenCalledWith("test-remote-token");
    });
    expect(await screen.findByText(/saved with Electron OS-backed encryption/i)).toBeTruthy();
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
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: ["imagine-turbo"],
        imagineart_video_styles: ["kling-1.0-pro"],
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
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: ["imagine-turbo"],
        imagineart_video_styles: ["kling-1.0-pro"],
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
        separate_vocals: false,
        separation_model: "htdemucs",
      });
    });
  });

  it("saves the music transcription setup with Whisper large-v3 and vocal separation", async () => {
    const postedBodies: any[] = [];
    installEdmgBridge();
    installFetchMock({
      "/v1/config": {
        ai_mode: "local",
        ai_provider: "nemotron_cloud",
      },
      "/v1/ai/status": { ok: true, provider: "nemotron_cloud" },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test", has_openai_compat_api_key: false },
      "/v1/hardware": {
        hardware: {
          device_name: "NVIDIA RTX 4050",
          backend_family: "cuda",
          recommended_tier: "balanced",
        },
      },
      "/v1/settings/render_profiles": {
        recommended_profile: "balanced_auto",
        profiles: {},
      },
      "/v1/settings/render_providers": {
        settings: {},
        stability: { has_api_key: false, visible: false, note: "disabled" },
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: ["imagine-turbo"],
        imagineart_video_styles: ["kling-1.0-pro"],
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
              dependencies: { parakeet_available: false, faster_whisper_available: true, demucs_available: true },
              hardware: { device_name: "NVIDIA RTX 4050" },
            },
          };
        }
        return {
          settings: {
            provider: "faster_whisper",
            model: "turbo",
            device: "auto",
            compute_type: "auto",
            fallback_to_whisper: true,
            separate_vocals: false,
            separation_model: "htdemucs",
          },
          active: { provider: "faster_whisper", model: "turbo", device: "auto", separate_vocals: false },
          dependencies: { parakeet_available: false, faster_whisper_available: true, demucs_available: true },
          hardware: { device_name: "NVIDIA RTX 4050" },
        };
      },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByLabelText("ASR model")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("ASR model"), {
      target: { value: "large-v3" },
    });
    fireEvent.change(screen.getByLabelText("ASR device"), {
      target: { value: "cuda" },
    });
    fireEvent.click(screen.getByLabelText("Separate vocals before transcription"));
    fireEvent.click(screen.getByRole("button", { name: "Save transcription settings" }));

    await waitFor(() => {
      expect(postedBodies).toContainEqual({
        provider: "faster_whisper",
        model: "large-v3",
        device: "cuda",
        compute_type: "auto",
        fallback_to_whisper: true,
        separate_vocals: true,
        separation_model: "htdemucs",
      });
    });
  });

  it("shows the shared system readiness report", async () => {
    window.localStorage.clear();
    installEdmgBridge();
    installFetchMock({
      "/v1/config": {},
      "/v1/ai/status": { ok: true },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test" },
      "/v1/hardware": { hardware: { device_name: "Test GPU" } },
      "/v1/system/readiness": {
        ok: true,
        ready: false,
        summary: "Degraded",
        status: "warn",
        checked_at: "2026-07-15T12:00:00Z",
        checks: {
          ffmpeg: { ok: true, status: "ok", path: "ffmpeg", version: "ffmpeg version 7.0" },
          runtime: {
            ok: true,
            status: "ok",
            python_version: "3.12.0",
            uv_version: "0.11.28",
            accelerator_profile: "cpu",
            sync_health: "synchronized",
          },
          gpu: { ok: true, status: "warn", backend: "cpu", device_name: "CPU", available_backends: ["cpu"] },
          disk: { ok: true, status: "ok", paths: [{ free_gb: 100, total_gb: 500, volume_path: "C:\\" }] },
          writable_paths: {
            ok: true,
            status: "ok",
            paths: [{ label: "data", path: "C:\\data", writable: true }],
          },
          models: {
            ok: true,
            status: "warn",
            models_dir: "C:\\models",
            entry_count: 0,
            hint: "Models directory is empty",
          },
        },
      },
      "/v1/settings/render_profiles": { recommended_profile: "balanced_auto", profiles: {} },
      "/v1/settings/render_providers": {
        settings: {},
        stability: { has_api_key: false, visible: false, note: "disabled" },
        imagineart: { has_api_key: false, visible: false, configured: false, note: "disabled" },
        imagineart_image_styles: [],
        imagineart_video_styles: [],
        directml: { runtime_ready: false, available: false, active: false, device_name: "" },
        stability_services: [],
        stability_models: [],
        style_presets: [],
      },
      "/v1/settings/transcription": {
        settings: {
          provider: "faster_whisper",
          model: "turbo",
          device: "auto",
          compute_type: "auto",
          fallback_to_whisper: true,
        },
        active: { provider: "faster_whisper", model: "turbo", device: "auto" },
        dependencies: { parakeet_available: false, faster_whisper_available: true },
        hardware: { device_name: "Test GPU" },
      },
      "/v1/render/route": { route: "local_gpu", local_ready: true },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByText("Degraded", {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.getAllByText("System readiness").length).toBeGreaterThan(0);
    expect(screen.getByText(/Models directory is empty/i)).toBeTruthy();
  });

  it("shows packaged desktop and backend build identity for support", async () => {
    installEdmgBridge({
      getBuildIdentity: async () => ({
        ok: true,
        desktop: {
          version: "1.2.0",
          packaged: true,
          platform: "win32",
          arch: "x64",
          electronVersion: "39.2.7",
          executablePath: "E:\\EDMG Studio\\EDMG Studio.exe",
        },
        backendBundle: {
          available: true,
          binaryVerified: true,
          schemaVersion: 5,
          builder: "scripts/prepare-release-bundle.mjs",
          platform: "win32",
          backendEntryPoint: "edmg-studio-backend.exe",
          acceleratorProfile: "cuda",
          pythonVersion: "3.12.10",
          sourceHash: "a".repeat(64),
          sourceFileCount: 267,
          lockSha256: "b".repeat(64),
          binarySha256: "c".repeat(64),
        },
      }),
    });
    installFetchMock({
      "/v1/config": {},
      "/health": { ok: true, version: "1.2.0" },
      "/v1/ai/status": { ok: true },
      "/v1/edmg/deforum_template": { ok: true },
      "/v1/settings/secrets/status": { store: "test" },
      "/v1/hardware": { hardware: { device_name: "NVIDIA RTX 5080" } },
      "/v1/system/readiness": {
        ok: true,
        status: "ok",
        summary: "Ready",
        checks: { runtime: { status: "ok", accelerator_profile: "cuda" } },
      },
      "/v1/settings/render_profiles": { recommended_profile: "high_quality", profiles: {} },
      "/v1/settings/render_providers": { settings: {} },
      "/v1/settings/transcription": { settings: {} },
    });

    renderWithStudio(<Settings backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByText("Packaged desktop")).toBeTruthy();
    expect(screen.getByLabelText("Desktop build version").textContent).toContain("1.2.0");
    expect(screen.getByLabelText("Desktop executable location").textContent).toContain("E:\\EDMG Studio\\EDMG Studio.exe");
    expect(screen.getByLabelText("Backend build version").textContent).toContain("1.2.0");
    expect(screen.getByText(/verified installed backend \+ release manifest v5/i)).toBeTruthy();
    expect(screen.getByText("Show technical fingerprints")).toBeTruthy();
    expect(screen.getByText("a".repeat(64))).toBeTruthy();
    expect(screen.getByText("b".repeat(64))).toBeTruthy();
    expect(screen.getByText("c".repeat(64))).toBeTruthy();
  });
});
