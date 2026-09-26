import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExecutionPlaneStatus } from "../components/ExecutionPlaneStatus";

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPut = vi.fn();
vi.mock("../components/api", () => ({ apiGet: (...args: any[]) => apiGet(...args), apiPost: (...args: any[]) => apiPost(...args), apiPut: (...args: any[]) => apiPut(...args) }));

describe("ExecutionPlaneStatus", () => {
  beforeEach(() => {
    apiGet.mockReset(); apiPost.mockReset(); apiPut.mockReset();
    apiGet.mockImplementation((path: string) => Promise.resolve(path.endsWith("profile")
      ? { runtime_profile: "hybrid_gpu", model_environment_preferences: {} }
      : { wsl: { configured: true, distribution: "Ubuntu", readiness: { wsl_installed: true, distribution_running: true, worker_environment_present: true, gpu_visible: true, model_installed: true, worker_launchable: true, generation_started: false, artifact_validated: false, runtime_qualified: false } }, physical_gpus: [{}], blockers: [], probe_performed: false }));
  });

  it("shows profile, launchability, distro and GPU mapping", async () => {
    render(<ExecutionPlaneStatus />);
    await waitFor(() => expect(screen.getByText(/Worker launchable/)).toBeTruthy());
    expect(screen.getByText(/Ubuntu/)).toBeTruthy();
    expect(screen.getByText(/GPU mappings/)).toBeTruthy();
  });

  it("preserves explicit no-fallback choice", () => {
    const change = vi.fn();
    render(<ExecutionPlaneStatus environment="wsl" onEnvironmentChange={() => {}} allowFallback={false} onAllowFallbackChange={change} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(change).toHaveBeenCalledWith(true);
  });
});
