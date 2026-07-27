import React from "react";
import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Models from "../pages/Models";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

vi.mock("@huggingface/hub", () => ({
  listModels: async function* () {
    // Model discovery is deliberately empty in these polling tests.
  },
}));

const catalog = {
  catalog: [],
  user: [],
  packs: [],
  accepted: {},
  installed: {},
  cloud: {},
  storage_mode: "local_cache",
};

describe("Models page polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.localStorage.clear();
    installEdmgBridge();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("loads catalog and providers once, then stops task polling while idle", async () => {
    const fetchMock = installFetchMock({
      "/v1/models/catalog": catalog,
      "/v1/models/tasks": { tasks: [] },
      "/v1/settings/render_providers": {},
    });

    renderWithStudio(<Models backendUrl="http://127.0.0.1:7863" config={{}} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("Model Manager")).toBeTruthy();
    expect(screen.getByText("No model install tasks yet.")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    const paths = fetchMock.mock.calls.map(([url]) => new URL(String(url)).pathname);
    expect(paths.filter((path) => path === "/v1/models/catalog")).toHaveLength(1);
    expect(paths.filter((path) => path === "/v1/settings/render_providers")).toHaveLength(1);
    expect(paths.filter((path) => path === "/v1/models/tasks")).toHaveLength(1);
  });

  it("shows stage and progress in the default basic UI mode", async () => {
    installFetchMock({
      "/v1/models/catalog": catalog,
      "/v1/models/tasks": {
        tasks: [{
          id: "model-1",
          name: "Install SDXL",
          status: "running",
          progress: 0.42,
          stage: "Downloading inference weights",
          bytes_completed: 1_610_612_736,
          bytes_total: 4_294_967_296,
          files_completed: 3,
          files_total: 8,
        }],
      },
      "/v1/settings/render_providers": {},
    });

    renderWithStudio(<Models backendUrl="http://127.0.0.1:7863" config={{}} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText("Model install progress")).toBeTruthy();
    expect(screen.getByText("Stage: Downloading inference weights")).toBeTruthy();
    expect(screen.getByText("running • 42%")).toBeTruthy();
    expect(screen.getByText(/Downloaded/).textContent).toContain("1.50 GB");
    expect(screen.getByText(/Downloaded/).textContent).toContain("4.00 GB");
    expect(screen.getByText(/Downloaded/).textContent).toContain("Files 3 of 8");
    expect(screen.getByRole("progressbar", { name: "Install SDXL progress" })).toBeTruthy();
  });
});
