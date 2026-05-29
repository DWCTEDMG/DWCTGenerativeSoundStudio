import React from "react";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Dashboard from "../pages/Dashboard";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

describe("Dashboard page", () => {
  it("supports local panel customization without changing backend reads", async () => {
    installEdmgBridge();
    const fetchMock = installFetchMock({
      "/health": { ok: true, version: "test" },
      "/v1/edmg/status": { ok: true, core: "ready" },
      "/v1/nvidia/status": {
        ok: true,
        nvidia: { enabled: true, profile: "omniverse", credentials: { ngc_api_key_configured: true }, services: {} },
      },
      "/v1/nvidia/diagnostics": {
        ok: true,
        nvidia: {
          profile: { enabled: true, profile: "omniverse", credentials: { ngc_api_key_configured: true } },
          host: {
            gpu: { ok: true, gpus: [{ name: "Test RTX" }] },
            docker: { ok: true, nvidia_runtime: true },
          },
          services: { nim: { model: "nvidia/model", probe: { reachable: true, models_url: "http://127.0.0.1:8000/v1/models" } } },
          readiness: {
            level: "ready",
            summary: "NVIDIA profile, local GPU runtime, NGC access, and NIM planner endpoint are ready.",
            checks: [],
            next_actions: [],
          },
        },
      },
    });

    renderWithStudio(
      <Dashboard
        backendUrl="http://127.0.0.1:7863"
        config={{ profile: "test", renderer: "internal" }}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeTruthy();
    expect(await screen.findByText("Create a project")).toBeTruthy();
    expect(await screen.findByText("NVIDIA Runtime Readiness")).toBeTruthy();

    const layoutDetails = screen.getByText("Dashboard layout").closest("details");
    expect(layoutDetails).toBeTruthy();
    layoutDetails?.setAttribute("open", "");
    const profileSelect = screen.getByRole("combobox", { name: "Dashboard layout profile" });
    expect(profileSelect).toBeTruthy();

    const workflowControl = screen
      .getByText("Current production flow from project creation through export.")
      .closest(".studio-layoutToolsItem");
    expect(workflowControl).toBeTruthy();

    fireEvent.click(
      within(workflowControl as HTMLElement).getByRole("button", { name: "Hide" }),
    );

    expect(screen.queryByText("Create a project")).toBeNull();
    expect(localStorage.getItem("edmg_layout_dashboard_v1")).toContain("workflow");

    fireEvent.change(profileSelect, { target: { value: "focus" } });
    expect(localStorage.getItem("edmg_layout_dashboard_active_profile_v1")).toBe("focus");
    expect(await screen.findByText("Create a project")).toBeTruthy();

    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/health")),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/v1/edmg/status")),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/v1/nvidia/diagnostics")),
    ).toBe(true);
  });
});
