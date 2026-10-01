import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import RuntimeAccelerationPanel from "../components/RuntimeAccelerationPanel";
import { apiGet, apiPost } from "../components/api";

vi.mock("../components/api", () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiGet).mockResolvedValue({ settings: {
    mode: "auto", enabled: true, auto_build: true, allow_fallback: true, precision: "auto",
    strict: false, cache_enabled: true, cache_limit_gb: 100, package_path: ""
  }, state: "unprobed", installed: true, available: true, healthy: false, compatible: false,
  accelerating: false, supported_component_count: 0, diagnostics: null, cache_bytes: 0,
  components: [], engines: [] });
  vi.mocked(apiPost).mockResolvedValue({ job_id: "runtime-job" });
});

test("shows unprobed installation without claiming acceleration and queues backend diagnostics", async () => {
  render(<RuntimeAccelerationPanel />);
  await screen.findByText("Not run");
  fireEvent.click(screen.getByText("Run diagnostics"));
  await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/v1/runtime/jobs", { operation: "diagnose", device: 0, precision: "fp16" }));
  expect(await screen.findByText(/runtime-job queued/)).toBeTruthy();
});

test("global disable is saved through the shared backend", async () => {
  render(<RuntimeAccelerationPanel />);
  fireEvent.click(await screen.findByLabelText("Enable TensorRT"));
  fireEvent.click(screen.getByText("Save runtime"));
  await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/v1/runtime/settings", expect.objectContaining({ enabled: false })));
});

test("shows truthful component routes, validation, and fallback independently", async () => {
  vi.mocked(apiGet).mockResolvedValueOnce({
    settings: {
      mode: "auto", enabled: true, auto_build: true, allow_fallback: true, precision: "auto",
      strict: false, cache_limit_gb: 100, package_path: "",
    },
    state: "ready", installed: true, available: true, healthy: true, compatible: true,
    accelerating: false, tensorrt_version: "10.15", supported_component_count: 2,
    diagnostics: { status: "ready" }, cache_bytes: 1024, engines: [],
    components: [
      {
        model_family: "sd15", component: "vae_decoder", fallback_runtime: "pytorch_cuda",
        validated_engine_count: 1, source_kind: "huggingface", architecture: "diffusers",
        selected_route: "huggingface_torch_tensorrt", compiler: "torch_tensorrt",
        route_supported: true, validated: true, accelerating: false,
      },
      {
        model_family: "sd15", component: "unet", fallback_runtime: "pytorch_cuda",
        validated_engine_count: 0, source_kind: "pytorch", selected_route: "existing_runtime",
        route_supported: false, route_reason: "Torch-TensorRT compiler/backend is not installed",
        validated: false, accelerating: false,
      },
    ],
  });

  render(<RuntimeAccelerationPanel />);

  expect(await screen.findByText((_, element) =>
    element?.classList.contains("small") === true
    && element.textContent?.startsWith("Hugging Face via Torch-TensorRT") === true,
  )).toBeTruthy();
  expect(screen.getByText("Validated engine available")).toBeTruthy();
  expect(screen.getByText("Fallback: pytorch cuda")).toBeTruthy();
  expect(screen.getByText("Torch-TensorRT compiler/backend is not installed")).toBeTruthy();
  expect(screen.getByText((_, element) =>
    element?.classList.contains("small") === true
    && element.textContent?.includes("saved receipt, not a live-render acceleration claim") === true,
  )).toBeTruthy();
});
