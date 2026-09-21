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
  }, state: "unprobed", package: { installed: true }, diagnostics: null, cache_bytes: 0, engines: [] });
  vi.mocked(apiPost).mockResolvedValue({ job_id: "runtime-job" });
});

test("shows unprobed installation without claiming acceleration and queues backend diagnostics", async () => {
  render(<RuntimeAccelerationPanel />);
  await screen.findByText(/Last diagnostic: Not run/);
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
