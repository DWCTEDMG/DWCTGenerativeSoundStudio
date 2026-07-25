import React from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import EdmgDirector from "../pages/EdmgDirector";
import { installEdmgBridge, installFetchMock, renderWithStudio } from "./testUtils";

vi.mock("../workbenches/AiNlpWorkbench", () => ({
  default: () => <div>AI planner workbench</div>,
}));

vi.mock("../workbenches/AudioReactiveWorkbench", () => ({
  default: () => <div>Audio reactive workbench</div>,
}));

describe("EDMG Director page", () => {
  it("persists the managed Director public URL and restarts the sidecar flow", async () => {
    let advertisedBaseUrl = "http://127.0.0.1:3001";
    const setDirectorSettings = vi.fn(async (settings: { baseUrl: string }) => {
      advertisedBaseUrl = String(settings.baseUrl);
      return {
        ok: true,
        restartRequired: false,
        available: true,
        managed: true,
        serviceUrl: "http://127.0.0.1:3001",
        mcpUrl: `${advertisedBaseUrl.replace(/\/+$/, "")}/mcp`,
        advertisedBaseUrl,
        backendUrl: "http://127.0.0.1:7863",
        pid: 67890,
        lastError: "",
        startedAt: "2026-05-06T00:00:00.000Z",
        packaged: false,
      };
    });

    installEdmgBridge({
      getDirectorStatus: async () => ({
        ok: true,
        available: true,
        managed: true,
        serviceUrl: "http://127.0.0.1:3001",
        mcpUrl: `${advertisedBaseUrl.replace(/\/+$/, "")}/mcp`,
        advertisedBaseUrl,
        backendUrl: "http://127.0.0.1:7863",
        pid: 12345,
        lastError: "",
        startedAt: "2026-05-06T00:00:00.000Z",
        packaged: false,
      }),
      setDirectorSettings,
    });

    installFetchMock({
      "/v1/projects": {
        projects: [
          {
            id: "project-1",
            name: "Project One",
          },
        ],
      },
      "/v1/projects/project-1": {
        project: {
          id: "project-1",
          name: "Project One",
          variants: [],
        },
      },
    });

    renderWithStudio(<EdmgDirector backendUrl="http://127.0.0.1:7863" config={{}} />);

    expect(await screen.findByText("Managed and external EDMG Director access")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Managed public URL"), {
      target: { value: "https://director.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save public URL" }));

    await waitFor(() => {
      expect(setDirectorSettings).toHaveBeenCalledWith({
        baseUrl: "https://director.example.com",
      });
    });

    expect(
      await screen.findByText(
        /Saved and restarted the managed Director service\. Refresh the ChatGPT app\/connector so it reloads the new widget metadata\./,
      ),
    ).toBeTruthy();
    expect(screen.getByDisplayValue("https://director.example.com")).toBeTruthy();
    expect(screen.getAllByText("https://director.example.com/mcp").length).toBeGreaterThan(0);
  });
});
