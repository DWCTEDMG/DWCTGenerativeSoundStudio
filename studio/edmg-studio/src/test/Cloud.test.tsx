import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Cloud from "../pages/Cloud";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Cloud page", () => {
  it("shows the selected Foundry project without claiming inference connectivity", async () => {
    installEdmgBridge();
    installFetchMock({
      "GET /v1/cloud/hf/settings": { ok: true, settings: { enabled: false, bucket: "", prefix: "", storage_mode: "local_cache" }, status: { ok: true, provider: "huggingface_bucket", enabled: false }, active_provider: null },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    expect(await screen.findAllByText("jonlong-1185")).toHaveLength(2);
    expect(screen.getByText("Azuredwct")).toBeTruthy();
    expect(screen.getByText("Project selected")).toBeTruthy();
    expect(screen.getByText(/not treated as an OpenAI inference endpoint/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Open Foundry project/i }).getAttribute("href")).toBe(
      "https://jonlong-1185-resource.services.ai.azure.com/api/projects/jonlong-1185",
    );
  });

  it("keeps AWS test actions working while exposing layout profiles", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "GET /v1/cloud/hf/settings": { ok: true, settings: { enabled: false, bucket: "", prefix: "", storage_mode: "local_cache" }, status: { ok: true, provider: "huggingface_bucket", enabled: false }, active_provider: null },
      "POST /v1/cloud/aws/test": { ok: true, provider: "aws", bucket: "demo-bucket" },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    expect(await screen.findByRole("combobox", { name: "Cloud layout profile" })).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("my-bucket"), {
      target: { value: "demo-bucket" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test credentials" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/aws/test")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes("demo-bucket")),
      ).toBe(true);
    });
  });

  it("posts Azure model cache credential tests with the selected container", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "GET /v1/cloud/hf/settings": { ok: true, settings: { enabled: false, bucket: "", prefix: "", storage_mode: "local_cache" }, status: { ok: true, provider: "huggingface_bucket", enabled: false }, active_provider: null },
      "POST /v1/cloud/azure/test": { ok: true, provider: "azure", container: "edmg-model-cache" },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    fireEvent.change(await screen.findByPlaceholderText("edmg-model-cache"), {
      target: { value: "team-model-cache" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test Azure" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/azure/test")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes("team-model-cache")),
      ).toBe(true);
    });
  });

  it("loads HF bucket status and posts credential tests with the selected bucket", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "GET /v1/cloud/hf/settings": {
        ok: true,
        settings: { enabled: true, bucket: "team/edmg-models", prefix: "weights", storage_mode: "local_cache" },
        status: {
          ok: true,
          provider: "huggingface_bucket",
          enabled: true,
          active: false,
          bucket: "team/edmg-models",
          prefix: "weights",
          has_token: true,
          token_source: "settings",
        },
        active_provider: "Hugging Face bucket",
      },
      "POST /v1/cloud/hf/test": {
        ok: true,
        provider: "huggingface_bucket",
        bucket: "team/custom-bucket",
        sample_paths: ["checkpoints/demo.safetensors"],
      },
      "POST /v1/cloud/hf/settings": {
        ok: true,
        settings: { enabled: true, bucket: "team/custom-bucket", prefix: "weights", storage_mode: "cloud_only" },
        status: { ok: true, provider: "huggingface_bucket", enabled: true, active: true },
        active_provider: "Hugging Face bucket",
      },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/hf/settings")
          && String(init?.method || "GET").toUpperCase() === "GET"),
      ).toBe(true);
    });

    fireEvent.change(await screen.findByPlaceholderText("namespace/bucket-name"), {
      target: { value: "team/custom-bucket" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Test HF bucket" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/hf/test")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes("team/custom-bucket")),
      ).toBe(true);
    });

    fireEvent.change(screen.getByDisplayValue("Local models + HF/S3 secondary mirrors"), {
      target: { value: "cloud_only" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & apply" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/hf/settings")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes('"storage_mode":"cloud_only"')),
      ).toBe(true);
    });
  });

  it("persists a Lightning backend target from the Cloud page", async () => {
    const setBackendSettings = vi.fn(async (settings: { mode: string; host: string; port: string; url?: string }) => ({
      ok: true,
      restartRequired: true,
      ...settings,
      currentBackendUrl: String(settings.url || ""),
    }));
    installEdmgBridge({ setBackendSettings });
    installFetchMock({
      "GET /v1/cloud/hf/settings": { ok: true, settings: { enabled: false, bucket: "", prefix: "", storage_mode: "local_cache" }, status: { ok: true, provider: "huggingface_bucket", enabled: false }, active_provider: null },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    fireEvent.change(await screen.findByLabelText("Lightning backend URL"), {
      target: { value: "https://studio-demo.lightning.ai/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save backend target" }));

    await waitFor(() => {
      expect(setBackendSettings).toHaveBeenCalledWith({
        mode: "external",
        host: "127.0.0.1",
        port: "7863",
        url: "https://studio-demo.lightning.ai",
      });
    });
    expect(await screen.findByText(/connect_lightning_backend/)).toBeTruthy();
  });

  it("generates Lightning bundles under the organized Studio data cloud path by default", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "GET /v1/cloud/hf/settings": { ok: true, settings: { enabled: false, bucket: "", prefix: "", storage_mode: "local_cache" }, status: { ok: true, provider: "huggingface_bucket", enabled: false }, active_provider: null },
      "POST /v1/cloud/lightning/bundle": { ok: true, output_dir: "data/cloud/lightning/lightning_bundle" },
    });

    renderWithStudio(<Cloud backendUrl="http://127.0.0.1:7863" config={null} />);

    fireEvent.click(await screen.findByRole("button", { name: "Generate bundle" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).includes("/v1/cloud/lightning/bundle")
          && String(init?.method || "GET").toUpperCase() === "POST"
          && String(init?.body || "").includes("lightning/lightning_bundle")),
      ).toBe(true);
    });
  });
});
