import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
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

  it("shows Linux-friendly storage paths and managed setup actions", async () => {
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
    expect(await screen.findByText("0) Full System Setup (One-Click)")).toBeTruthy();
    expect(await screen.findByText(/Runs the Linux setup pipeline/)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Full Setup (CPU profile)" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Full Setup (CUDA profile)" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Install/Start Ollama Sidecar" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Install ComfyUI Sidecar (CPU)" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Install ComfyUI Sidecar (NVIDIA)" })).toBeTruthy();
    expect(await screen.findByText(/Linux setup uses Studio's bundled sidecar script/i)).toBeTruthy();
    expect(await screen.findByText(/Linux setup uses Studio's bundled ComfyUI sidecar script/i)).toBeTruthy();
  });

  it("shows Start ComfyUI NVIDIA button on Windows", async () => {
    installEdmgBridge({ platform: "win32" });
    installFetchMock({
      "/v1/setup/status": {
        ollama: { ok: true, model_present: true },
        comfyui: { ok: false, portable_installed: true },
        ffmpeg: { ok: true },
        backend_bundle: { ok: true },
        sevenzip: { ok: true },
        ai_config: { label: "Local Ollama", ollama_required: true, model_required: true },
      },
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
    });

    renderWithStudio(<Setup />);

    expect(await screen.findByRole("button", { name: "Start ComfyUI (NVIDIA)" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Start ComfyUI (CPU)" })).toBeTruthy();
  });

  it("summarizes locked toolchain provenance and sends exact accelerator profiles", async () => {
    installEdmgBridge({ platform: "win32" });
    const lockSha = "a".repeat(64);
    const fetchMock = installFetchMock({
      "/v1/setup/status": {
        ollama: { ok: true, model_present: true },
        comfyui: { ok: false },
        ffmpeg: { ok: true },
        toolchain: {
          ok: true,
          immutable: false,
          python_version: "3.12.10",
          uv_version: "0.11.28",
          lock_sha256: lockSha,
          accelerator_profile: "cpu",
          torch_packages: [
            { name: "torch", version: "2.11.0+cpu" },
            { name: "torchvision", version: "0.26.0+cpu" },
            { name: "torchaudio", version: "2.11.0+cpu" },
          ],
          torch_index: "https://download.pytorch.org/whl/cpu",
          pyinstaller_version: "6.15.0",
          lock_check: "ok",
          sync_health: "ok",
        },
        sevenzip: { ok: true },
        hardware: { supports_directml: true, directml_device_name: "AMD Radeon" },
        ai_config: { label: "Local Ollama", ollama_required: true, model_required: true },
      },
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
      "POST /v1/setup/backend/install": { ok: true, task: { id: "sync123", status: "queued" } },
    });

    renderWithStudio(<Setup />);

    expect(await screen.findByText("0.25) Locked Python Toolchain")).toBeTruthy();
    expect((await screen.findByText(/Python:/)).textContent).toContain("3.12.10");
    expect(screen.getByText(/uv.lock SHA-256:/).textContent).toContain(lockSha);
    expect(screen.getByText(/Torch packages:/).textContent).toContain("torch 2.11.0+cpu");
    expect(screen.getByText(/Torch index:/).textContent).toContain("https://download.pytorch.org/whl/cpu");
    expect(screen.getByText(/PyInstaller:/).textContent).toContain("6.15.0");

    fireEvent.click(screen.getByRole("button", { name: "Sync CUDA profile" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => (
        String(url).endsWith("/v1/setup/backend/install") && String(init?.method).toUpperCase() === "POST"
      ));
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ accelerator_profile: "cuda" });
    });
  });

  it("treats packaged Python dependencies as immutable and self-contained", async () => {
    installEdmgBridge({ platform: "win32" });
    installFetchMock({
      "/v1/setup/status": {
        ollama: { ok: true, model_present: true },
        comfyui: { ok: false },
        ffmpeg: { ok: true },
        toolchain: {
          ok: true,
          immutable: true,
          python_version: "3.12.10",
          uv_version: "0.11.28",
          lock_sha256: "b".repeat(64),
          accelerator_profile: "cuda",
          torch_packages: [{ name: "torch", version: "2.11.0+cu130" }],
          torch_index: "https://download.pytorch.org/whl/cu130",
          pyinstaller_version: "6.15.0",
          lock_check: "embedded-manifest",
          sync_health: "bundled",
        },
        sevenzip: { ok: true },
        ai_config: { label: "Local Ollama", ollama_required: true, model_required: true },
      },
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
    });

    renderWithStudio(<Setup />);

    expect(await screen.findByText(/do not need to install Python or uv/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Sync CPU profile" })).toBeNull();
    expect(screen.getByRole("button", { name: "Complete External Setup (CUDA build)" })).toBeTruthy();
  });

  it("shows a cancel button for active installer tasks", async () => {
    installEdmgBridge();
    let taskStatus = "running";
    const fetchMock = installFetchMock({
      "/v1/setup/status": () => ({
        ollama: { ok: false, model_present: false },
        comfyui: { ok: false },
        ffmpeg: { ok: true },
        backend_bundle: { ok: true },
        sevenzip: { ok: false },
        ai_config: { label: "Local Ollama", ollama_required: true, model_required: true },
        tasks: [
          {
            id: "task1234",
            name: "install_7zip",
            status: taskStatus,
            progress: taskStatus === "canceled" ? 0.42 : 0.42,
            last_log: taskStatus === "canceled" ? "Cancel requested — stopping after current step." : "Downloading portable 7-Zip CLI",
            cancel_requested: taskStatus === "canceled",
          },
        ],
      }),
      "/v1/models/catalog": { packs: [], catalog: [], user: [] },
      "POST /v1/setup/tasks/task1234/cancel": () => {
        taskStatus = "canceled";
        return {
          ok: true,
          task: {
            id: "task1234",
            name: "install_7zip",
            status: "canceled",
            progress: 0.42,
            last_log: "Cancel requested — stopping after current step.",
            cancel_requested: true,
          },
        };
      },
    });

    renderWithStudio(<Setup />);

    const cancelButton = await screen.findByRole("button", { name: "Cancel" });
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://127.0.0.1:7863/v1/setup/tasks/task1234/cancel",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByText(/canceled/i)).toBeTruthy();
  });
});
